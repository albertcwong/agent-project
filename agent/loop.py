"""ReAct-style agent loop: LLM + MCP tools."""

import base64
import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager

import httpx

from openai import AsyncOpenAI

STREAM_READ_TIMEOUT = float(os.environ.get("LLM_STREAM_READ_TIMEOUT", "300"))

from agent.flag_log_write import parse_flags_json
from agent.intent import classify as classify_intent
from agent.mcp_client import mcp_session_pool
from agent.python_exec import execute_python as run_execute_python
from agent.tools import DOWNLOAD_TOOLS, WRITE_TOOLS, get_tools_for_servers
from agent.trace import LoopTrace


@asynccontextmanager
async def _pool_context(server_configs: list[dict], override: dict | None):
    """Yield pool from override (for testing) or from mcp_session_pool."""
    if override:
        yield override
    else:
        async with mcp_session_pool(server_configs) as pool:
            yield pool


logger = logging.getLogger(__name__)

MAX_AGENT_ITERATIONS = int(os.environ.get("MAX_AGENT_ITERATIONS", "20"))
MAX_RESULT_CHARS = int(os.environ.get("MAX_RESULT_CHARS", "50000"))
TRUNCATE_MARKER = '\n\n... [truncated for display — full data is available via execute_python using data["rows"]]'

# Tools that return chartable data; metadata-only tools (e.g. get-datasource-metadata) excluded
_CHART_TOOLS = {"query-datasource", "get-view-data"}

# Tools exempt from redundancy check (agent may re-read after errors)
_REDUNDANCY_EXEMPT = {"get-datasource-metadata", "list-datasources", "search-content", "list-projects", "list-workbooks"}

# Patterns indicating the LLM is asking the user for text confirmation instead of calling a tool
_CONFIRMATION_PATTERNS = (
    "is this correct", "shall i proceed", "should i proceed", "do you confirm",
    "would you like me to proceed", "do you want me to", "ready to publish",
    "can i proceed", "want me to go ahead",
)


def _is_text_confirmation(content: str, workflow: str) -> bool:
    """Detect if the LLM is asking for text confirmation in a publish workflow."""
    if workflow not in ("publish",):
        return False
    lower = content.lower()
    return any(p in lower for p in _CONFIRMATION_PATTERNS)


def _parse_publish_intent(content: str) -> dict | None:
    """Extract publish tool name and arguments from an LLM text confirmation message.

    Returns {"toolName": ..., "arguments": {...}} or None if parsing fails.
    The LLM typically says something like:
      'I will publish "albert test" to the "My Project" project using ATTACHMENT_0.'
    """
    lower = content.lower()
    # Determine which publish tool
    if "update" in lower and "datasource" in lower:
        tool_name = "update-datasource-data"
    elif "datasource" in lower:
        tool_name = "publish-datasource"
    elif "workbook" in lower:
        tool_name = "publish-workbook"
    elif "flow" in lower:
        tool_name = "publish-flow"
    else:
        tool_name = "publish-datasource"  # default for publish workflow

    args: dict = {}
    # Extract name: look for quoted strings near "name" or after "publish"
    name_patterns = [
        re.compile(r"""(?:name\s+(?:is|as|:)\s*['"]?)([^'".\n]{1,80})['"]?""", re.IGNORECASE),
        re.compile(r"""(?:publish|datasource|workbook)\s+['"]([^'"]{1,80})['"]""", re.IGNORECASE),
        re.compile(r"""['"]([^'"]{1,80})['"]\s+(?:to|as|datasource|workbook)""", re.IGNORECASE),
    ]
    for pat in name_patterns:
        m = pat.search(content)
        if m:
            args["name"] = m.group(1).strip()
            break
    # Extract project name (we'll auto-resolve the ID later)
    proj_patterns = [
        re.compile(r"""(?:project|to the)\s+['"]([^'"]{1,80})['"]""", re.IGNORECASE),
        re.compile(r"""['"]([^'"]{1,80})['"]\s+project""", re.IGNORECASE),
    ]
    for pat in proj_patterns:
        m = pat.search(content)
        if m:
            args["projectId"] = m.group(1).strip()  # name, will be auto-resolved
            break
    # contentBase64 placeholder
    if "attachment" in lower:
        args["contentBase64"] = "ATTACHMENT_0"

    if not args.get("name") and tool_name != "update-datasource-data":
        return None
    return {"toolName": tool_name, "arguments": args}



# Keywords indicating user wants a chart/visualization (MCP app)
_CHART_KEYWORDS = (
    "chart", "charts", "visualization", "visualize", "graph", "graphs",
    "bar chart", "pie chart", "line chart", "plot", "visual", "show as chart",
    "show as graph", "display as chart", "display as graph",
)


def _user_wants_chart(question: str) -> bool:
    """True if the user's message indicates they want a chart or visualization."""
    q = (question or "").lower()
    return any(kw in q for kw in _CHART_KEYWORDS)


def _result_has_chart_data(result: str, tool_name: str) -> bool:
    """True if the tool result contains data suitable for charting. Skip empty, errors, metadata-only, or JSON with no rows."""
    s = (result or "").strip()
    if not s:
        return False
    if s.startswith("Error:"):
        return False
    if tool_name not in _CHART_TOOLS:
        return False
    try:
        p = json.loads(s)
        if not isinstance(p, dict):
            return False
        arr = p.get("rows") or p.get("data") or p.get("items") or p.get("datasources") or p.get("workbooks") or []
        if isinstance(arr, list) and len(arr) > 0:
            return True
        return False
    except (json.JSONDecodeError, TypeError):
        return False


def _format_python_result(s: str) -> str:
    """Format execute_python JSON output for the agent."""
    if not s or s.startswith("Error:"):
        return s or ""
    try:
        d = json.loads(s)
        err = d.get("error")
        if err:
            return f"Error: {err}"
        parts = []
        if d.get("stdout"):
            parts.append(d["stdout"].rstrip())
        if "result" in d and d["result"] is not None:
            parts.append(json.dumps(d["result"]) if not isinstance(d["result"], str) else d["result"])
        return "\n".join(parts) if parts else s
    except (json.JSONDecodeError, TypeError):
        return s


def _extract_json_object(s: str) -> dict | None:
    """Extract outermost JSON object from string (handles multi-line pretty-printed)."""
    idx = s.find("{")
    if idx < 0:
        return None
    sub = s[idx:]
    depth, i, n = 0, 0, len(sub)
    in_str, escape, q = False, False, None
    while i < n:
        c = sub[i]
        if escape:
            escape = False
            i += 1
            continue
        if in_str:
            if c == "\\":
                escape = True
            elif c == q:
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str, q = True, c
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(sub[: i + 1])
                except json.JSONDecodeError:
                    return None
        i += 1
    return None


def _parse_query_result(result: str) -> dict | None:
    """Parse query-datasource/get-view-data result. Handles multi-line (text + JSON)."""
    if not result or not isinstance(result, str):
        return None
    s = result.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    for part in reversed(s.split("\n")):
        part = part.strip()
        if part.startswith("{") and part.endswith("}"):
            try:
                parsed = json.loads(part)
                logger.debug("_parse_query_result used line fallback for %d-char result", len(s))
                return parsed
            except json.JSONDecodeError:
                continue
    parsed = _extract_json_object(s)
    if parsed is not None:
        logger.debug("_parse_query_result used multi-line fallback for %d-char result", len(s))
    return parsed


def _truncate_for_llm(s: str, max_chars: int = MAX_RESULT_CHARS) -> str:
    """Truncate tool result for LLM context to avoid overflow."""
    if not s or len(s) <= max_chars:
        return s
    return s[:max_chars] + TRUNCATE_MARKER


async def _get_endor_headers(base_url: str, api_key: str, provider: str) -> dict[str, str]:
    """Return headers for LLM proxy. Adds x-endor-token when provider is endor."""
    headers = {"x-provider": provider}
    if provider != "endor":
        return headers
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                f"{base_url}/auth/endor/token",
                headers={"x-api-key": api_key} if api_key != "dummy" else {},
            )
            r.raise_for_status()
            data = r.json()
            if token := data.get("token"):
                headers["x-endor-token"] = token
    except Exception as e:
        logger.warning("Failed to fetch Endor token: %s", e)
    return headers


def _classify_error(result: str) -> str | None:
    """Classify tool error for agent hint. Returns error_type or None."""
    if not result or not result.strip().startswith("Error:"):
        return None
    r = result.lower()
    if "empty code" in r:
        return "empty_code"
    if "401" in r or "unauthorized" in r:
        return "auth"
    if "403" in r or "forbidden" in r:
        return "auth"
    if "field" in r and ("not found" in r or "unknown" in r):
        return "validation_field"
    if "404" in r or "not found" in r:
        return "not_found"
    if "rate limit" in r or "429" in r:
        return "rate_limit"
    if "connection" in r or "timeout" in r or "refused" in r:
        return "connection"
    return "unknown"


def _error_hint(error_type: str) -> str:
    """Return a hint for the agent based on error type."""
    hints = {
        "empty_code": " (Provide Python code in the code parameter. Use df = pd.DataFrame(data[\"rows\"]) for the injected query result.)",
        "auth": " (Check authentication; user may need to reconnect in Settings.)",
        "not_found": " (Verify the resource ID or name exists.)",
        "validation_field": " (Re-check get-datasource-metadata for correct fieldCaption.)",
        "rate_limit": " (Wait and retry, or simplify the request.)",
        "connection": " (MCP server may be down; check Settings.)",
        "unknown": " (Do not retry with the same arguments. Adjust your approach.)",
    }
    return hints.get(error_type, "")


# Strip MCP SDK noise that can leak into tool results
def _sanitize_tool_result(s: str) -> str:
    if not s:
        return s
    for pattern in ("unhandled errors in a TaskGroup", "BaseExceptionGroup:"):
        idx = s.find(pattern)
        if idx > 0:  # Only strip if pattern is not at the start
            s = s[:idx].rstrip()
    return s


def _to_preview_str(val, max_len: int = 2000) -> str:
    """Coerce value to string for preview. Handles dict (e.g. structured query)."""
    if isinstance(val, str):
        s = val.strip()
    elif isinstance(val, dict):
        s = json.dumps(val, indent=2)
    else:
        s = str(val)
    return s[:max_len] + ("..." if len(s) > max_len else "")


def _tool_input_preview(name: str, args: dict) -> str | None:
    """Extract key input for thought stream. Returns None if nothing to show."""
    if name == "execute_python":
        code = args.get("code") or ""
        if code and isinstance(code, str):
            return _to_preview_str(code)
    if name == "query-datasource":
        q = args.get("query") or args.get("queryText") or ""
        if q:
            return _to_preview_str(q)
    if name == "get-view-data":
        vid = args.get("viewId") or args.get("view_id")
        if vid:
            return f"viewId: {vid}"
    if name in ("publish-workbook", "publish-datasource", "publish-flow", "update-datasource-data"):
        parts = []
        if args.get("projectId"):
            parts.append(f"projectId: {args['projectId']}")
        if args.get("name"):
            parts.append(f"name: {args['name']}")
        if args.get("datasourceId"):
            parts.append(f"datasourceId: {args['datasourceId']}")
        if args.get("contentBase64"):
            b64 = args["contentBase64"]
            parts.append(f"contentBase64: ({len(b64)} chars)")
        if parts:
            return "\n".join(parts)
    return None


def _tool_result_summary(name: str, result: str, max_len: int = 800) -> str:
    """Summary for thought stream. Shows fuller detail; truncates only very long output."""
    if not result or result.strip().startswith("Error:"):
        return "error"
    try:
        data = json.loads(result) if result.strip().startswith("{") else None
        if not isinstance(data, dict):
            return result[:max_len] + "..." if len(result) > max_len else result
        if name in ("query-datasource", "get-view-data"):
            arr = data.get("rows") or data.get("data") or []
            n = len(arr) if isinstance(arr, list) else 0
            return f"{n} rows"
        if name == "get-datasource-metadata":
            cols = data.get("columns") or []
            n = len(cols) if isinstance(cols, list) else 0
            return f"{n} columns"
        if name == "execute_python":
            if data.get("error"):
                return f"error: {data['error'][:500]}"
            parts = []
            if data.get("stdout"):
                parts.append(data["stdout"].rstrip()[:500])
            if "result" in data and data["result"] is not None:
                r = data["result"]
                s = json.dumps(r) if not isinstance(r, str) else r
                parts.append(s[:500] + ("..." if len(s) > 500 else ""))
            return "\n".join(parts) if parts else "complete"
        if name in ("search-content", "list-datasources", "list-workbooks", "list-views", "list-projects", "list-flows"):
            items = data.get("datasources") or data.get("workbooks") or data.get("views") or data.get("projects") or data.get("flows") or []
            n = len(items) if isinstance(items, list) else 0
            return f"{n} found"
    except (json.JSONDecodeError, TypeError):
        pass
    return result[:max_len] + "..." if len(result) > max_len else result


DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "gpt-4")


async def _retry_empty_after_tools(client, messages: list, model: str, tools: list) -> str | None:
    """If last message is tool, retry once with nudge. Returns content or None."""
    if not messages or messages[-1].get("role") != "tool":
        return None
    messages.append({"role": "user", "content": "Please respond to the user based on the tool results above."})
    try:
        # Omit tools on retry—some providers (e.g. Gemini) return empty when tools are present
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            stream=False,
        )
        c = resp.choices[0] if resp.choices else None
        if c and getattr(c.message, "content", None):
            return (c.message.content or "").strip()
    except Exception:
        logger.exception("Retry after empty content failed")
    return None


def _get_project_from_result(result: str) -> dict | None:
    """Parse MCP tool result into a project dict. Returns None on failure."""
    if not result or result.strip().startswith("Error:"):
        return None
    try:
        data = json.loads(result) if result.strip().startswith("{") else None
        if isinstance(data, dict) and (data.get("name") or data.get("projectName")):
            return data
        if isinstance(data, dict) and "projects" in data:
            projs = data.get("projects") or []
            if projs and isinstance(projs[0], dict):
                return projs[0]
    except Exception:
        pass
    return None


async def _resolve_project_name(pool: dict, sid: str, project_id: str) -> str | None:
    """Try to resolve projectId to project name via MCP. Returns None on failure."""
    for tool_name, tool_args in [
        ("get-project", {"projectId": project_id}),
        ("list-projects", {"filter": f"id:eq:{project_id}", "limit": 1}),
    ]:
        try:
            result = await pool["call_tool"](sid, tool_name, tool_args)
            proj = _get_project_from_result(result)
            if proj:
                return proj.get("name") or proj.get("projectName")
        except Exception:
            continue
    return None


async def _resolve_project_path(pool: dict, sid: str, project_id: str, seen: set | None = None) -> str | None:
    """Resolve projectId to full hierarchical path (e.g. 'Sales / Finance') via MCP. Returns None on failure."""
    seen = seen or set()
    if project_id in seen:
        return None
    seen.add(project_id)
    for tool_name, tool_args in [
        ("get-project", {"projectId": project_id}),
        ("list-projects", {"filter": f"id:eq:{project_id}", "limit": 1}),
    ]:
        try:
            result = await pool["call_tool"](sid, tool_name, tool_args)
            proj = _get_project_from_result(result)
            if not proj:
                continue
            name = proj.get("name") or proj.get("projectName") or ""
            parent_id = proj.get("parentProjectId") or proj.get("parentId")
            if parent_id:
                parent_path = await _resolve_project_path(pool, sid, str(parent_id), seen)
                return f"{parent_path} / {name}" if parent_path else name
            return name or None
        except Exception:
            continue
    return None


def _user_specifies_datasource(question: str) -> bool:
    """True if the user message indicates they are specifying a datasource by name."""
    q = (question or "").lower()
    signals = [
        "datasource", "data source", "use datasource", "from datasource",
        "query datasource", "use data source", "from data source",
    ]
    return any(s in q for s in signals)


def _format_context_block(state: dict | None, user_question: str = "") -> str:
    """Format conversation state as a specific context block for the prompt."""
    if not state:
        return ""
    parts = []
    if state.get("currentDatasourceId") and not _user_specifies_datasource(user_question):
        parts.append(f"Active datasource: {state['currentDatasourceId']}")
    if state.get("lastQuery"):
        q = state["lastQuery"]
        if isinstance(q, dict) and q:
            parts.append(f"Last query: {json.dumps(q)[:200]}...")
        elif isinstance(q, str):
            parts.append(f"Last query: {q[:200]}...")
    if state.get("establishedFilters"):
        f = state["establishedFilters"]
        if isinstance(f, dict) and f:
            parts.append(f"Established filters: {json.dumps(f)[:150]}...")
    if state.get("targetProjectId"):
        name = state.get("targetProjectName") or state["targetProjectId"]
        parts.append(f"Target project: {name}")
    if state.get("lastInspectedObjectId"):
        parts.append(f"Last inspected: {state.get('lastInspectedObjectType', 'object')} {state['lastInspectedObjectId']}")
    if state.get("lastDownloadedObjects"):
        objs = state["lastDownloadedObjects"]
        if isinstance(objs, list) and objs:
            names = [o.get("name") or o.get("id", "")[:20] for o in objs[:3] if isinstance(o, dict)]
            parts.append(f"Recently downloaded: {', '.join(names)}")
    if not parts:
        return ""
    return "[Context: " + "; ".join(parts) + "]\n\n"


def _update_conversation_state(
    state: dict | None, tool_name: str, args: dict, result: str
) -> dict | None:
    """Update conversation state from successful tool call."""
    out = dict(state) if state else {}
    if tool_name == "get-datasource-metadata":
        ds_id = args.get("datasourceLuid") or args.get("datasourceId") or args.get("datasource_id")
        if ds_id:
            out["currentDatasourceId"] = str(ds_id)
    elif tool_name == "query-datasource" and not (result or "").strip().startswith("Error:"):
        ds_id = args.get("datasourceLuid") or args.get("datasourceId") or args.get("datasource_id")
        if ds_id:
            out["currentDatasourceId"] = str(ds_id)
        q = args.get("query") or args.get("queryText")
        if q is not None:
            out["lastQuery"] = q if isinstance(q, dict) else {"query": str(q)[:500]}
        flt = args.get("filters")
        if flt is not None:
            out["establishedFilters"] = flt if isinstance(flt, dict) else {"filters": str(flt)[:200]}
    elif tool_name in ("download-workbook", "download-datasource", "download-flow") and not (result or "").strip().startswith("Error:"):
        try:
            data = json.loads(result) if (result or "").strip().startswith("{") else {}
            if isinstance(data, dict) and data.get("filename"):
                objs = list(out.get("lastDownloadedObjects") or [])[-4:]
                objs.append({"id": data.get("id", ""), "name": data.get("filename"), "type": tool_name.replace("download-", "")})
                out["lastDownloadedObjects"] = objs[-5:]
        except (json.JSONDecodeError, TypeError):
            pass
    elif tool_name in ("inspect-workbook-file", "inspect-datasource-file", "inspect-flow-file") and not (result or "").strip().startswith("Error:"):
        obj_id = args.get("workbookId") or args.get("datasourceId") or args.get("flowId") or ""
        if obj_id:
            out["lastInspectedObjectId"] = str(obj_id)
            out["lastInspectedObjectType"] = tool_name.split("-")[0]
    elif tool_name == "list-datasources":
        out.pop("currentDatasourceId", None)
        out.pop("lastQuery", None)
        out.pop("establishedFilters", None)
    elif tool_name in ("publish-workbook", "publish-datasource", "publish-flow") and not (result or "").strip().startswith("Error:"):
        proj_id = args.get("projectId")
        if proj_id:
            out["targetProjectId"] = str(proj_id)
            out["targetProjectName"] = args.get("projectName") or args.get("projectPath")
    return out if out else None


# Text file extensions: decode and inject content into user message
_TEXT_EXT = (".csv", ".txt", ".json", ".md", ".log")
_MAX_TEXT_ATTACHMENT_CHARS = 50_000


def _decode_text_attachment(att: dict) -> str | None:
    """Decode base64 text attachment. Returns None on failure."""
    try:
        b64 = att.get("contentBase64")
        if not isinstance(b64, str):
            return None
        raw = base64.b64decode(b64).decode("utf-8", errors="replace")
        if len(raw) > _MAX_TEXT_ATTACHMENT_CHARS:
            return raw[:_MAX_TEXT_ATTACHMENT_CHARS] + "\n\n... [truncated — file too large]"
        return raw
    except Exception:
        return None


# Tableau LUIDs are UUIDs (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
_LUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


def _is_valid_luid(val: str) -> bool:
    """Check if a string looks like a valid Tableau LUID (UUID format)."""
    return bool(_LUID_RE.match(val.strip()))


async def _auto_resolve_project(
    pool: dict, sid: str, search_name: str,
    tool_calls_log: list[dict], log: logging.Logger,
    trace_id: str | None = None, iteration: int = 0,
) -> str | None:
    """Call list-projects and return a resolved LUID, or None on failure.

    Tries with a name filter first; falls back to listing all projects if
    the filtered call returns nothing (some MCP servers don't support filters).
    """
    for attempt, lp_args in enumerate([
        {"filter": f"name:eq:{search_name}"} if search_name else {},
        {},  # fallback: list all
    ]):
        if attempt == 1 and not search_name:
            break  # already tried unfiltered
        try:
            lp_result = await pool["call_tool"](sid, "list-projects", lp_args)
            tool_calls_log.append({"name": "list-projects", "arguments": lp_args})
        except Exception:
            log.exception("traceId=%s iter=%d auto list-projects failed (attempt %d)", trace_id or "(none)", iteration, attempt)
            continue
        log.info(
            "traceId=%s iter=%d list-projects attempt=%d result_preview=%.300s",
            trace_id or "(none)", iteration, attempt, str(lp_result)[:300],
        )
        if not lp_result or str(lp_result).startswith("Error:"):
            continue
        try:
            lp_data = json.loads(lp_result) if isinstance(lp_result, str) else lp_result
            # Handle multiple response shapes: {"projects": [...]}, [...], or {"project": {...}}
            projects = (
                lp_data.get("projects")
                or lp_data.get("project") and [lp_data["project"]]
                or (lp_data if isinstance(lp_data, list) else [])
            )
            if not isinstance(projects, list):
                projects = [projects] if projects else []
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue
        resolved_id = None
        # Prefer exact name match
        if search_name:
            for p in projects:
                if (p.get("name") or "").lower() == search_name.lower():
                    resolved_id = p.get("id") or p.get("luid")
                    break
        # Fall back to first result
        if not resolved_id and projects:
            resolved_id = projects[0].get("id") or projects[0].get("luid")
        if resolved_id and _is_valid_luid(str(resolved_id)):
            return str(resolved_id)
    return None


# Args added for the UI confirmation dialog but not part of MCP tool schemas
_UI_ONLY_ARGS = {"projectPath", "projectName"}


def _strip_ui_args(args: dict) -> dict:
    """Remove UI-only keys (projectPath, projectName) before sending to MCP server."""
    return {k: v for k, v in args.items() if k not in _UI_ONLY_ARGS}


def _inject_attachments_in_args(args: dict, attachments: list[dict]) -> dict:
    """Replace ATTACHMENT_N placeholders in contentBase64 with actual content."""
    if not attachments:
        return args
    content = args.get("contentBase64")
    if not isinstance(content, str) and "uploadSessionId" not in args:
        args = {**args, "contentBase64": "ATTACHMENT_0"}
        content = "ATTACHMENT_0"
    if not isinstance(content, str):
        return args
    for i, att in enumerate(attachments):
        if content.strip() == f"ATTACHMENT_{i}":
            return {**args, "contentBase64": att["contentBase64"]}
    return args


async def run_agent_loop_stream(
    question: str,
    system_prompt: str,
    server_configs: list[dict],
    provider: str = "openai",
    model: str | None = None,
    history: list[dict] | None = None,
    write_confirmation: dict | None = None,
    confirmed_action: dict | None = None,
    attachments: list[dict] | None = None,
    conversation_state: dict | None = None,
    trace_id: str | None = None,
    _pool_override: dict | None = None,
    _trace: bool = False,
):
    """Async generator yielding (chunk_type, data). chunk_type: "thought" | "text" | "done". data: str for thought/text, dict for done."""
    trace = LoopTrace() if _trace else None
    if not server_configs:
        if trace:
            trace.termination_reason = "no_config"
        yield "text", "Please connect at least one Tableau MCP server in Settings & Help before asking Tableau questions."
        yield "done", {"sources": [], "tool_calls": [], **({"trace": trace.to_dict()} if trace else {})}
        return

    async with _pool_context(server_configs, _pool_override) as pool:
        tools, tool_ui_map, tool_server_map = await get_tools_for_servers(server_configs, pool=pool)
        if not tools:
            if trace:
                trace.termination_reason = "no_tools"
            yield "text", "No Tableau tools available. Your session may have expired — sign in again in Settings & Help."
            yield "done", {"sources": [], "tool_calls": [], **({"trace": trace.to_dict()} if trace else {})}
            return

        base_url = os.environ.get("LLM_PROXY_URL", "http://localhost:8000").rstrip("/")
        api_key = os.environ.get("LLM_PROXY_API_KEY", "dummy")
        headers = await _get_endor_headers(base_url, api_key, provider)
        client = AsyncOpenAI(
            base_url=f"{base_url}/v1",
            api_key=api_key,
            default_headers=headers,
            timeout=httpx.Timeout(60.0, read=STREAM_READ_TIMEOUT),
        )
        model = model or DEFAULT_MODEL

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for m in (history or []):
            if m.get("role") in ("user", "assistant") and m.get("content"):
                messages.append({"role": m["role"], "content": m["content"]})
        ctx_block = _format_context_block(conversation_state, question)
        user_content = ctx_block + (f"[Tableau is connected.] {question}" if server_configs and tools else question)
        if attachments:
            names = ", ".join(a.get("filename", "file") for a in attachments)
            user_content += f"\n\n[Attached file(s): {names}. When calling publish-workbook, publish-datasource, publish-flow, or update-datasource-data, use contentBase64: 'ATTACHMENT_0' for the first file, 'ATTACHMENT_1' for the second, etc.]"
            for a in attachments:
                fn = (a.get("filename") or "").lower()
                if any(fn.endswith(ext) for ext in _TEXT_EXT):
                    decoded = _decode_text_attachment(a)
                    if decoded:
                        user_content += f"\n\n[File: {a.get('filename', 'file')}]\n{decoded}"
        messages.append({"role": "user", "content": user_content})

        tool_calls_log: list[dict] = []
        sources: list[dict] = []
        conv_state = dict(conversation_state) if conversation_state else {}
        query_data_cache: dict[str, dict] = {}  # Full (untruncated) results keyed by datasource/view id
        seen_calls: set[str] = set()
        workflow = classify_intent(question)
        if trace:
            trace.intent = workflow
            trace.system_prompt_length = len(system_prompt)
        logger.info("traceId=%s workflow=%s question_len=%d", trace_id or "(none)", workflow, len(question))

        if confirmed_action and write_confirmation:
            name = confirmed_action.get("toolName") or ""
            args = dict(confirmed_action.get("arguments") or {})
            logger.info("traceId=%s confirmed_action: tool=%s attachments=%d contentBase64_len=%d",
                        trace_id or "(none)", name, len(attachments or []),
                        len(str(args.get("contentBase64", ""))))
            if name in WRITE_TOOLS:
                # Auto-resolve projectId for publish tools if missing or not a LUID
                if name in ("publish-workbook", "publish-datasource", "publish-flow"):
                    pid = args.get("projectId") or ""
                    if not pid or not _is_valid_luid(str(pid)):
                        search_name = str(pid) if pid and not _is_valid_luid(str(pid)) else ""
                        if not search_name:
                            for kw in ("to the ", "to '", 'to "', "project "):
                                idx = question.lower().find(kw)
                                if idx >= 0:
                                    candidate = question[idx + len(kw):].strip().strip("'\"").split(" project")[0].split(" on ")[0].strip()
                                    if candidate and len(candidate) < 80:
                                        search_name = candidate
                                        break
                        yield "thought", f"  Auto-resolving project: {search_name or '(listing all)'}"
                        cfg = tool_server_map.get("list-projects") or server_configs[0]
                        sid = cfg.get("id", cfg.get("url", ""))
                        resolved_id = await _auto_resolve_project(pool, sid, search_name, tool_calls_log, logger, trace_id)
                        if resolved_id:
                            yield "thought", f"  Resolved projectId: {resolved_id}"
                            args["projectId"] = str(resolved_id)
                        else:
                            yield "text", f'Publish failed: could not resolve project "{search_name or pid}" to a valid ID.'
                            if trace:
                                trace.termination_reason = "invalid_project_id"
                            yield "done", {"sources": [], "tool_calls": tool_calls_log, **({"trace": trace.to_dict()} if trace else {})}
                            return
                args = _inject_attachments_in_args(args, attachments or [])
                # User confirmed via dialog — set overwrite=true for publish tools
                if name in ("publish-workbook", "publish-datasource", "publish-flow"):
                    args.setdefault("overwrite", True)
                mcp_args = _strip_ui_args(args)
                cfg = tool_server_map.get(name) or server_configs[0]
                sid = cfg.get("id", cfg.get("url", ""))
                tool_calls_log.append({"name": name, "arguments": args})
                try:
                    yield "thought", f"Using tool: {name}"
                    if (preview := _tool_input_preview(name, args)):
                        for line in preview.split("\n"):
                            yield "thought", f"    {line}"
                    result = await pool["call_tool"](sid, name, mcp_args)
                except Exception:
                    logger.exception("Tool %s failed", name)
                    result = "Error: MCP server connection failed. Please try again."
                clean = _sanitize_tool_result(result)
                yield "thought", f"  → {name}: {_tool_result_summary(name, result)}"
                updated = _update_conversation_state(conv_state, name, args, clean)
                if updated is not None:
                    conv_state = updated
                if name in DOWNLOAD_TOOLS:
                    try:
                        parsed = json.loads(clean)
                        if isinstance(parsed, dict) and "filename" in parsed and "contentBase64" in parsed:
                            yield "download", {"filename": parsed["filename"], "contentBase64": parsed["contentBase64"]}
                            clean = f'Downloaded: {parsed["filename"]}'
                    except (json.JSONDecodeError, TypeError):
                        pass
                tc_id = f"call_{uuid.uuid4().hex[:12]}"
                messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": tc_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]})
                tool_content = _truncate_for_llm(clean)
                if err_type := _classify_error(clean):
                    tool_content += _error_hint(err_type)
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": tool_content})
                ui_meta = tool_ui_map.get(name)
                if ui_meta and ui_meta.get("resourceUri") and _user_wants_chart(question) and _result_has_chart_data(clean, name):
                    yield "app", {"resourceUri": ui_meta["resourceUri"], "toolName": name, "toolCallId": tc_id, "result": clean, "serverId": ui_meta.get("serverId", "")}
                if clean.startswith("Error:"):
                    msg = clean
                    if "403" in clean:
                        msg = "Publish failed: Access forbidden (403). Check your Tableau permissions and that you have publish rights to the project."
                    elif ("contentBase64" in clean or "uploadSessionId" in clean) and "required" in clean.lower():
                        msg = "Publish failed: A file is required. Attach a .twbx workbook (or .tdsx/.tflx) before publishing."
                    yield "text", msg
                else:
                    try:
                        meta = json.loads(clean)
                        if isinstance(meta, dict) and (meta.get("id") or meta.get("name") or meta.get("contentUrl")):
                            yield "text", f"Published successfully. {meta.get('name', '')} → project {meta.get('projectId', '')}"
                        else:
                            if name in WRITE_TOOLS and (not meta or (isinstance(meta, dict) and not meta)):
                                yield "text", "Publish returned no confirmation. Check Tableau Server to verify."
                            else:
                                yield "text", clean
                    except (json.JSONDecodeError, TypeError):
                        if name in WRITE_TOOLS and clean.strip() in ("{}", ""):
                            yield "text", "Publish returned no confirmation. Check Tableau Server to verify."
                        else:
                            yield "text", clean
                if trace:
                    trace.termination_reason = "confirmed_write"
                yield "done", {"sources": sources, "tool_calls": tool_calls_log, **({"conversationState": conv_state} if conv_state else {}), **({"trace": trace.to_dict()} if trace else {})}
                return

        first_turn_no_history = not (history or []) and not (confirmed_action and write_confirmation)
        for iteration in range(MAX_AGENT_ITERATIONS):
            if trace:
                trace.add_iteration(iteration + 1)
            yield "thought", f"Step {iteration + 1}:"
            tool_choice_val = "required" if (iteration == 0 and first_turn_no_history) else "auto"
            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice_val,
                stream=True,
            )
            content_parts = []
            tool_calls_buf = []
            finish_reason = None

            async for chunk in stream:
                c = chunk.choices[0] if chunk.choices else None
                if not c:
                    continue
                finish_reason = getattr(c, "finish_reason", None) or finish_reason
                delta = getattr(c, "delta", None) or {}
                reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "thought", None)
                if reasoning:
                    yield "thought", (reasoning if isinstance(reasoning, str) else str(reasoning))
                if getattr(delta, "content", None):
                    content_parts.append(delta.content)
                if getattr(delta, "tool_calls", None):
                    tool_calls_buf.extend(delta.tool_calls)

            logger.debug(
                "Stream chunk: finish_reason=%s content_len=%d tool_calls=%d",
                finish_reason, len(content_parts), len(tool_calls_buf),
            )

            content = "".join(content_parts).strip()
            # Only yield text when not running tool calls this turn—avoids duplicate intro (model emits it before + after tools)
            will_run_tools = bool(tool_calls_buf)
            synthetic_tool_calls = None  # set when we intercept a text confirmation

            # When we have tool_calls, execute them even if finish_reason is stop (some providers return stop with tool_calls)
            if finish_reason in ("stop", "length") and will_run_tools:
                logger.info(
                    "traceId=%s provider returned finish_reason=%s with tool_calls (provider=%s)",
                    trace_id or "(none)", finish_reason, provider,
                )

            if not will_run_tools:
                # Intercept: if the LLM is asking "Is this correct?" instead of calling the publish tool,
                # parse the intent and inject a synthetic tool call instead of re-prompting the LLM
                if content and _is_text_confirmation(content, workflow):
                    parsed = _parse_publish_intent(content)
                    if parsed:
                        logger.info("traceId=%s intercepted text confirmation, injecting synthetic %s call", trace_id or "(none)", parsed["toolName"])
                        yield "thought", f"  (intercepted text confirmation — calling {parsed['toolName']} directly)"
                        synthetic_id = f"call_{uuid.uuid4().hex[:12]}"
                        synthetic_tool_calls = [{
                            "id": synthetic_id, "type": "function",
                            "function": {"name": parsed["toolName"], "arguments": json.dumps(parsed["arguments"])},
                        }]
                        messages.append({"role": "assistant", "content": content, "tool_calls": synthetic_tool_calls})
                        msg_tool_calls = synthetic_tool_calls
                        # Fall through to tool execution below
                    else:
                        logger.info("traceId=%s intercepted text confirmation but could not parse intent, re-prompting", trace_id or "(none)")
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": "Yes, proceed. Call the publish tool now with the arguments you described. Do not ask for confirmation — the system will prompt me automatically."})
                        continue
                else:
                    # Normal stop: no tool calls, not a text confirmation — return final answer
                    if trace:
                        trace.set_llm_response(content, finish_reason, [])
                        trace.termination_reason = "stop" if finish_reason == "stop" else ("length" if finish_reason == "length" else "no_tool_calls")
                    if not content:
                        content = await _retry_empty_after_tools(client, messages, model, tools)
                    if not content:
                        logger.warning("LLM returned no content (provider=%s model=%s finish=%s)", provider, model, finish_reason)
                        hint = "The model returned no response. Try switching to OpenAI—some providers do not support tool calling."
                        last_err = next((m for m in reversed(messages) if m.get("role") == "tool" and (m.get("content") or "").strip().lower().startswith("error")), None)
                        if last_err:
                            hint += " If a tool call failed, check your Tableau connection."
                        yield "text", hint
                    else:
                        if finish_reason == "length":
                            content = f"{content}\n\n(Response was truncated due to length. The answer may be incomplete.)"
                        yield "text", content
                    logger.info("traceId=%s completed iterations=%d tools=%s", trace_id or "(none)", iteration + 1, [t.get("name") for t in tool_calls_log])
                    yield "done", {"sources": sources, "tool_calls": tool_calls_log, **({"conversationState": conv_state} if conv_state else {}), **({"trace": trace.to_dict()} if trace else {})}
                    return

            if not synthetic_tool_calls:
                # Normal path: assemble tool calls from streaming chunks
                tc_by_idx: dict[int, dict] = {}
                for t in tool_calls_buf:
                    idx = getattr(t, "index", 0)
                    if idx not in tc_by_idx:
                        tc_by_idx[idx] = {"id": "", "name": "", "arguments": "", "thought_signature": None}
                    if getattr(t, "id", None):
                        tc_by_idx[idx]["id"] = (tc_by_idx[idx]["id"] or "") + (t.id or "")
                    fn = getattr(t, "function", None) or {}
                    if getattr(fn, "name", None):
                        existing = tc_by_idx[idx]["name"] or ""
                        new_part = fn.name or ""
                        if new_part:
                            if new_part == existing or existing.endswith(new_part):
                                pass  # already have it (avoids list-datasourceslist-datasources)
                            elif new_part.startswith(existing):
                                tc_by_idx[idx]["name"] = new_part
                            else:
                                tc_by_idx[idx]["name"] = existing + new_part
                    if getattr(fn, "arguments", None):
                        tc_by_idx[idx]["arguments"] = (tc_by_idx[idx]["arguments"] or "") + (fn.arguments or "")
                    if (ts := getattr(t, "thought_signature", None)) is not None:
                        existing = tc_by_idx[idx].get("thought_signature") or ""
                        tc_by_idx[idx]["thought_signature"] = existing + (ts if isinstance(ts, str) else str(ts))

                msg_tool_calls = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"] or "{}"},
                        **({"thought_signature": tc["thought_signature"]} if tc.get("thought_signature") else {}),
                    }
                    for tc in [tc_by_idx[i] for i in sorted(tc_by_idx)]
                ]
                content_str = "".join(content_parts) or ""
                if trace:
                    trace.set_llm_response(content_str, finish_reason, [tc["function"]["name"] for tc in msg_tool_calls])

                messages.append({"role": "assistant", "content": content_str, "tool_calls": msg_tool_calls})

            tool_results = []
            for tc in msg_tool_calls:
                name = tc["function"]["name"]
                yield "thought", f"Using tool: {name}"
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                if (preview := _tool_input_preview(name, args)):
                    for line in preview.split("\n"):
                        yield "thought", f"    {line}"
                call_key = f"{name}:{json.dumps(args, sort_keys=True)}"
                if call_key in seen_calls and name not in _REDUNDANCY_EXEMPT:
                    result = "You already called this tool with these exact arguments. Use the data you already have or adjust your approach."
                    tool_results.append((name, result))
                    if trace:
                        trace.add_tool_call(name, args, result, was_redundant=True)
                    logger.info(
                        "traceId=%s iter=%d tool=%s args_keys=%s redundant=True",
                        trace_id or "(none)", iteration + 1, name, list(args.keys()),
                    )
                    continue
                tool_calls_log.append({"name": name, "arguments": args})

                # Validate and auto-resolve projectId for publish tools
                if name in ("publish-workbook", "publish-datasource", "publish-flow"):
                    pid = args.get("projectId") or ""
                    project_name_hint = ""
                    needs_resolve = False
                    if not pid:
                        needs_resolve = True
                    elif not _is_valid_luid(str(pid)):
                        # LLM passed a project name instead of LUID — use it as the search hint
                        project_name_hint = str(pid)
                        needs_resolve = True
                    if needs_resolve:
                        # Auto-resolve: call list-projects to find the projectId
                        cfg = tool_server_map.get("list-projects") or tool_server_map.get(name) or server_configs[0]
                        sid = cfg.get("id", cfg.get("url", ""))
                        search_name = project_name_hint or ""
                        # Also check the user question for project name hints
                        if not search_name:
                            for kw in ("to the ", "to '", 'to "', "project "):
                                idx = question.lower().find(kw)
                                if idx >= 0:
                                    candidate = question[idx + len(kw):].strip().strip("'\"").split(" project")[0].split(" on ")[0].strip()
                                    if candidate and len(candidate) < 80:
                                        search_name = candidate
                                        break
                        yield "thought", f"  Auto-resolving project: {search_name or '(listing all)'}"
                        resolved_id = await _auto_resolve_project(pool, sid, search_name, tool_calls_log, logger, trace_id, iteration)
                        if resolved_id:
                            yield "thought", f"  Resolved projectId: {resolved_id}"
                            args["projectId"] = str(resolved_id)
                        else:
                            result = f'Error: Could not resolve project "{search_name or pid}" to a valid ID.'
                            tool_results.append((name, result))
                            if trace:
                                trace.add_tool_call(name, args, result, was_redundant=False)
                            continue

                if name in WRITE_TOOLS and not write_confirmation:
                    confirm_args = dict(args)
                    if project_id := confirm_args.get("projectId"):
                        cfg = tool_server_map.get(name) or server_configs[0]
                        sid = cfg.get("id", cfg.get("url", ""))
                        if path := await _resolve_project_path(pool, sid, str(project_id)):
                            confirm_args["projectPath"] = path
                            if not confirm_args.get("projectName"):
                                confirm_args["projectName"] = path.split(" / ")[-1] if " / " in path else path
                        elif not confirm_args.get("projectName") and (name_res := await _resolve_project_name(pool, sid, str(project_id))):
                            confirm_args["projectName"] = name_res
                    if trace:
                        trace.termination_reason = "confirmation"
                    yield "confirm", {
                        "action": {"toolName": name, "arguments": confirm_args},
                        "correlationId": str(uuid.uuid4()),
                    }
                    yield "done", {"sources": sources, "tool_calls": tool_calls_log, "awaitingConfirmation": True, **({"conversationState": conv_state} if conv_state else {}), **({"trace": trace.to_dict()} if trace else {})}
                    return

                args = _inject_attachments_in_args(args, attachments or [])
                if name == "execute_python":
                    py_data = args.get("data") or {}
                    if isinstance(py_data, dict):
                        has_real_data = any(isinstance(v, list) and len(v) > 0 for v in py_data.values())
                        if not has_real_data and query_data_cache:
                            combined = {}
                            for ds_id, cached in query_data_cache.items():
                                if ds_id == "last":
                                    continue
                                rows = cached.get("rows") or cached.get("data") or cached.get("results") or []
                                if isinstance(rows, list) and rows:
                                    combined[ds_id] = rows
                            if combined:
                                py_data = combined
                            else:
                                last_data = query_data_cache.get("last") or next(iter(query_data_cache.values()), None)
                                if last_data:
                                    rows = last_data.get("rows") or last_data.get("data") or last_data.get("results") or []
                                    if isinstance(rows, list) and rows:
                                        py_data = {"rows": rows}
                    result = run_execute_python(args.get("code", ""), py_data)
                    # Flag Log deterministic write: auto-call update-datasource-data
                    formatted = _format_python_result(result)
                    flags_data = parse_flags_json(formatted)
                    if flags_data and flags_data.get("datasourceId"):
                        fl_ds_id = flags_data["datasourceId"]
                        fl_args = {"datasourceId": fl_ds_id, "records": flags_data.get("flag_records", [])}
                        if flags_data.get("resolved_flag_ids"):
                            fl_args["resolved_flag_ids"] = flags_data["resolved_flag_ids"]
                        fl_cfg = tool_server_map.get("update-datasource-data") or server_configs[0]
                        fl_sid = fl_cfg.get("id", fl_cfg.get("url", ""))
                        yield "thought", "Using tool: update-datasource-data (Flag Log auto-write)"
                        try:
                            fl_result = await pool["call_tool"](fl_sid, "update-datasource-data", fl_args)
                        except Exception:
                            logger.exception("Flag Log auto-write failed")
                            fl_result = "Error: Flag Log update-datasource-data failed."
                        yield "thought", f"  → update-datasource-data: {_tool_result_summary('update-datasource-data', fl_result)}"
                        tool_calls_log.append({"name": "update-datasource-data", "arguments": fl_args})
                else:
                    cfg = tool_server_map.get(name) or server_configs[0]
                    sid = cfg.get("id", cfg.get("url", ""))
                    try:
                        result = await pool["call_tool"](sid, name, args)
                    except Exception:
                        logger.exception("Tool %s failed", name)
                        result = "Error: MCP server connection failed. Please try again."
                tool_results.append((name, result))
                if not (str(result) or "").strip().startswith("Error:"):
                    seen_calls.add(call_key)
                if trace:
                    trace.add_tool_call(name, args, str(result), was_redundant=False)
                logger.info(
                    "traceId=%s iter=%d tool=%s args_keys=%s result_len=%d redundant=False",
                    trace_id or "(none)", iteration + 1, name, list(args.keys()), len(str(result)),
                )
                if name in ("query-datasource", "get-view-data") and not (str(result) or "").strip().startswith("Error:"):
                    parsed = _parse_query_result(result)
                    if isinstance(parsed, dict):
                        ds_id = str(args.get("datasourceLuid") or args.get("datasourceId") or args.get("viewId") or "last")
                        query_data_cache[ds_id] = parsed
                        query_data_cache["last"] = parsed

            for tc, (name, result) in zip(msg_tool_calls, tool_results):
                clean = _format_python_result(result) if name == "execute_python" else _sanitize_tool_result(result)
                yield "thought", f"  → {name}: {_tool_result_summary(name, result)}"
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                updated = _update_conversation_state(conv_state, name, args, clean)
                if updated is not None:
                    conv_state = updated
                if name in ("query-datasource", "get-view-data"):
                    ds_id = args.get("datasourceLuid") or args.get("datasourceId") or args.get("viewId")
                    if ds_id and not any(s.get("id") == str(ds_id) for s in sources):
                        sources.append({"id": str(ds_id), "type": name, "tool": name})
                if name in DOWNLOAD_TOOLS:
                    try:
                        parsed = json.loads(clean)
                        if isinstance(parsed, dict) and "filename" in parsed and "contentBase64" in parsed:
                            yield "download", {"filename": parsed["filename"], "contentBase64": parsed["contentBase64"]}
                            clean = f'Downloaded: {parsed["filename"]}'
                    except (json.JSONDecodeError, TypeError):
                        pass
                tool_content = _truncate_for_llm(clean)
                if err_type := _classify_error(clean):
                    tool_content += _error_hint(err_type)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_content})
                ui_meta = tool_ui_map.get(name)
                if ui_meta and ui_meta.get("resourceUri") and _user_wants_chart(question) and _result_has_chart_data(clean, name):
                    yield "app", {
                        "resourceUri": ui_meta["resourceUri"],
                        "toolName": name,
                        "toolCallId": tc["id"],
                        "result": clean,
                        "serverId": ui_meta.get("serverId", ""),
                    }

        summary = f"Tools used: {', '.join(t.get('name', '') for t in tool_calls_log)}." if tool_calls_log else ""
        if trace:
            trace.termination_reason = "max_iterations"
        logger.info("traceId=%s max_iterations_reached tools=%s", trace_id or "(none)", [t.get("name") for t in tool_calls_log])
        try:
            summary_prompt = """You have reached the maximum number of steps. Summarize in 3-4 sentences:
1. What the user asked for
2. What you were able to accomplish
3. What remained incomplete and why
4. What the user could try next
Do not attempt any more tool calls. Be concise."""
            summary_messages = messages + [{"role": "user", "content": summary_prompt}]
            resp = await client.chat.completions.create(
                model=model,
                messages=summary_messages,
                max_tokens=300,
            )
            content = (resp.choices[0].message.content or "").strip()
            if content:
                yield "text", f"{content}\n\n{summary}"
            else:
                yield "text", f"I've reached the limit of steps. {summary} You can ask a follow-up to continue."
        except Exception:
            yield "text", f"I've reached the limit of steps. {summary} You can ask a follow-up to continue."
        yield "done", {"sources": sources, "tool_calls": tool_calls_log, **({"conversationState": conv_state} if conv_state else {}), **({"trace": trace.to_dict()} if trace else {})}


async def run_agent_loop(
    question: str,
    system_prompt: str,
    server_configs: list[dict],
    provider: str = "openai",
    model: str | None = None,
    history: list[dict] | None = None,
    write_confirmation: dict | None = None,
    confirmed_action: dict | None = None,
    attachments: list[dict] | None = None,
    conversation_state: dict | None = None,
    _pool_override: dict | None = None,
    _trace: bool = False,
) -> tuple[str, list[dict], list[dict], bool, dict | None, "LoopTrace | None"]:
    """Convenience wrapper: runs the streaming loop and collects the result."""
    text_parts = []
    sources = []
    tool_calls = []
    awaiting = False
    conv_state = conversation_state
    trace = None

    async for chunk_type, data in run_agent_loop_stream(
        question=question,
        system_prompt=system_prompt,
        server_configs=server_configs,
        provider=provider,
        model=model,
        history=history,
        write_confirmation=write_confirmation,
        confirmed_action=confirmed_action,
        attachments=attachments,
        conversation_state=conversation_state,
        trace_id=None,
        _pool_override=_pool_override,
        _trace=_trace,
    ):
        if chunk_type == "text":
            text_parts.append(data)
        elif chunk_type == "done":
            sources = data.get("sources", [])
            tool_calls = data.get("tool_calls", [])
            awaiting = data.get("awaitingConfirmation", False)
            conv_state = data.get("conversationState", conversation_state)
            t = data.get("trace")
            if t and isinstance(t, dict):
                trace = LoopTrace.from_dict(t)

    if awaiting and not text_parts:
        answer = "Please confirm the publish action to proceed."
    else:
        answer = "\n".join(text_parts) if text_parts else "No answer generated."
    return (answer, sources, tool_calls, awaiting, conv_state, trace)

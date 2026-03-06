"""ReAct-style agent loop: LLM + MCP tools."""

import json
import logging
import os
import uuid

import httpx

from openai import AsyncOpenAI

STREAM_READ_TIMEOUT = float(os.environ.get("LLM_STREAM_READ_TIMEOUT", "300"))

from agent.mcp_client import mcp_session_pool
from agent.python_exec import execute_python as run_execute_python
from agent.tools import DOWNLOAD_TOOLS, WRITE_TOOLS, get_tools_for_servers

logger = logging.getLogger(__name__)

DEBUG_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug-45b476.log")
MAX_AGENT_ITERATIONS = int(os.environ.get("MAX_AGENT_ITERATIONS", "10"))

# Tools that return chartable data; metadata-only tools (e.g. get-datasource-metadata) excluded
_CHART_TOOLS = {"query-datasource", "get-view-data"}

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
            return len(s) > 50
        arr = p.get("rows") or p.get("data") or p.get("items") or p.get("datasources") or p.get("workbooks") or []
        if isinstance(arr, list) and len(arr) > 0:
            return True
        return False
    except (json.JSONDecodeError, TypeError):
        return len(s) > 50


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


# Strip MCP SDK noise that can leak into tool results
def _sanitize_tool_result(s: str) -> str:
    for pattern in ("unhandled errors in a TaskGroup", "BaseExceptionGroup:"):
        if pattern in s:
            s = s.split(pattern)[0].rstrip()
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
):
    """Async generator yielding (chunk_type, data). chunk_type: "thought" | "text" | "done". data: str for thought/text, dict for done."""
    if not server_configs:
        yield "text", "Please connect at least one Tableau MCP server in Settings & Help before asking Tableau questions."
        yield "done", {"sources": [], "tool_calls": []}
        return

    async with mcp_session_pool(server_configs) as pool:
        tools, tool_ui_map, tool_server_map = await get_tools_for_servers(server_configs, pool=pool)
        if not tools:
            yield "text", "No Tableau tools available. Your session may have expired — sign in again in Settings & Help."
            yield "done", {"sources": [], "tool_calls": []}
            return

        base_url = os.environ.get("LLM_PROXY_URL", "http://localhost:8000").rstrip("/")
        api_key = os.environ.get("LLM_PROXY_API_KEY", "dummy")
        client = AsyncOpenAI(
            base_url=f"{base_url}/v1",
            api_key=api_key,
            default_headers={"x-provider": provider},
            timeout=httpx.Timeout(60.0, read=STREAM_READ_TIMEOUT),
        )
        model = model or DEFAULT_MODEL

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for m in (history or []):
            if m.get("role") in ("user", "assistant") and m.get("content"):
                messages.append({"role": m["role"], "content": m["content"]})
        user_content = f"[Tableau is connected.] {question}" if server_configs and tools else question
        if attachments:
            names = ", ".join(a.get("filename", "file") for a in attachments)
            user_content += f"\n\n[Attached file(s) for publishing: {names}. When calling publish-workbook, publish-datasource, or publish-flow, use contentBase64: 'ATTACHMENT_0' for the first file, 'ATTACHMENT_1' for the second, etc.]"
        messages.append({"role": "user", "content": user_content})

        tool_calls_log: list[dict] = []
        sources: list[dict] = []

        if confirmed_action and write_confirmation:
            # #region agent log
            try:
                open(DEBUG_LOG, "a").write(json.dumps({"sessionId":"45b476","hypothesisId":"H1,H5","location":"loop.py:confirmed_entry","message":"confirmed_action path","data":{"toolName":confirmed_action.get("toolName"),"hasWriteConf":bool(write_confirmation)},"timestamp":__import__("time").time()*1000}) + "\n")
            except Exception: pass
            # #endregion
            name = confirmed_action.get("toolName") or ""
            args = dict(confirmed_action.get("arguments") or {})
            if name in WRITE_TOOLS:
                args = _inject_attachments_in_args(args, attachments or [])
                cfg = tool_server_map.get(name) or server_configs[0]
                sid = cfg.get("id", cfg.get("url", ""))
                tool_calls_log.append({"name": name, "arguments": args})
                try:
                    yield "thought", f"Using tool: {name}"
                    if (preview := _tool_input_preview(name, args)):
                        for line in preview.split("\n"):
                            yield "thought", f"    {line}"
                    result = await pool["call_tool"](sid, name, args)
                except Exception:
                    logger.exception("Tool %s failed", name)
                    result = "Error: MCP server connection failed. Please try again."
                # #region agent log
                try:
                    open(DEBUG_LOG, "a").write(json.dumps({"sessionId":"45b476","hypothesisId":"H1,H2,H4","location":"loop.py:tool_result","message":"raw result","data":{"result_len":len(str(result)),"result_preview":str(result)[:200]},"timestamp":__import__("time").time()*1000}) + "\n")
                except Exception: pass
                # #endregion
                clean = _sanitize_tool_result(result)
                yield "thought", f"  → {name}: {_tool_result_summary(name, result)}"
                # #region agent log
                try:
                    open(DEBUG_LOG, "a").write(json.dumps({"sessionId":"45b476","hypothesisId":"H1,H2","location":"loop.py:clean_result","message":"after sanitize","data":{"clean":clean},"timestamp":__import__("time").time()*1000}) + "\n")
                except Exception: pass
                # #endregion
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
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": clean})
                ui_meta = tool_ui_map.get(name)
                if ui_meta and ui_meta.get("resourceUri") and _user_wants_chart(question) and _result_has_chart_data(clean, name):
                    yield "app", {"resourceUri": ui_meta["resourceUri"], "toolName": name, "toolCallId": tc_id, "result": clean, "serverId": ui_meta.get("serverId", "")}
                if clean.startswith("Error:"):
                    # #region agent log
                    try:
                        open(DEBUG_LOG, "a").write(json.dumps({"sessionId":"45b476","hypothesisId":"H4","location":"loop.py:yield_branch","message":"error branch","data":{"yielding":"error"},"timestamp":__import__("time").time()*1000}) + "\n")
                    except Exception: pass
                    # #endregion
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
                            # No explicit success evidence; don't assume success
                            # #region agent log
                            try:
                                open(DEBUG_LOG, "a").write(json.dumps({"sessionId":"45b476","hypothesisId":"H1","location":"loop.py:yield_branch","message":"empty/meta branch","data":{"meta_keys":list(meta.keys()) if isinstance(meta,dict) else None,"yielding":clean},"timestamp":__import__("time").time()*1000}) + "\n")
                            except Exception: pass
                            # #endregion
                            if name in WRITE_TOOLS and (not meta or (isinstance(meta, dict) and not meta)):
                                yield "text", "Publish returned no confirmation. Check Tableau Server to verify."
                            else:
                                yield "text", clean
                    except (json.JSONDecodeError, TypeError):
                        # #region agent log
                        try:
                            open(DEBUG_LOG, "a").write(json.dumps({"sessionId":"45b476","hypothesisId":"H2","location":"loop.py:yield_branch","message":"json parse fail","data":{"yielding":clean[:100]},"timestamp":__import__("time").time()*1000}) + "\n")
                        except Exception: pass
                        # #endregion
                        if name in WRITE_TOOLS and clean.strip() in ("{}", ""):
                            yield "text", "Publish returned no confirmation. Check Tableau Server to verify."
                        else:
                            yield "text", clean
                yield "done", {"sources": sources, "tool_calls": tool_calls_log}
                return

        for iteration in range(MAX_AGENT_ITERATIONS):
            yield "thought", f"Step {iteration + 1}:"
            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
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
            if finish_reason in ("stop", "length"):
                if not content:
                    logger.warning("LLM returned stop/length with empty content (provider=%s model=%s)", provider, model)
                    yield "text", "The model returned no response. Try switching to OpenAI—some providers do not support tool calling."
                elif not will_run_tools:
                    yield "text", content
                yield "done", {"sources": sources, "tool_calls": tool_calls_log}
                return

            if not tool_calls_buf:
                if not content:
                    logger.warning("LLM returned no tool_calls and empty content (provider=%s model=%s)", provider, model)
                    yield "text", "The model returned no response. Try switching to OpenAI—some providers do not support tool calling."
                else:
                    yield "text", content
                yield "done", {"sources": sources, "tool_calls": tool_calls_log}
                return

            tc_by_idx: dict[int, dict] = {}
            for t in tool_calls_buf:
                idx = getattr(t, "index", 0)
                if idx not in tc_by_idx:
                    tc_by_idx[idx] = {"id": "", "name": "", "arguments": "", "thought_signature": None}
                if getattr(t, "id", None):
                    tc_by_idx[idx]["id"] = (tc_by_idx[idx]["id"] or "") + (t.id or "")
                fn = getattr(t, "function", None) or {}
                if getattr(fn, "name", None):
                    tc_by_idx[idx]["name"] = (tc_by_idx[idx]["name"] or "") + (fn.name or "")
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
                tool_calls_log.append({"name": name, "arguments": args})

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
                    yield "confirm", {
                        "action": {"toolName": name, "arguments": confirm_args},
                        "correlationId": str(uuid.uuid4()),
                    }
                    yield "done", {"sources": sources, "tool_calls": tool_calls_log, "awaitingConfirmation": True}
                    return

                args = _inject_attachments_in_args(args, attachments or [])
                if name == "execute_python":
                    result = run_execute_python(args.get("code", ""), args.get("data"))
                else:
                    cfg = tool_server_map.get(name) or server_configs[0]
                    sid = cfg.get("id", cfg.get("url", ""))
                    try:
                        result = await pool["call_tool"](sid, name, args)
                    except Exception:
                        logger.exception("Tool %s failed", name)
                        result = "Error: MCP server connection failed. Please try again."
                tool_results.append((name, result))

            for tc, (name, result) in zip(msg_tool_calls, tool_results):
                clean = _format_python_result(result) if name == "execute_python" else _sanitize_tool_result(result)
                yield "thought", f"  → {name}: {_tool_result_summary(name, result)}"
                if name in DOWNLOAD_TOOLS:
                    try:
                        parsed = json.loads(clean)
                        if isinstance(parsed, dict) and "filename" in parsed and "contentBase64" in parsed:
                            yield "download", {"filename": parsed["filename"], "contentBase64": parsed["contentBase64"]}
                            clean = f'Downloaded: {parsed["filename"]}'
                    except (json.JSONDecodeError, TypeError):
                        pass
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": clean})
                ui_meta = tool_ui_map.get(name)
                if ui_meta and ui_meta.get("resourceUri") and _user_wants_chart(question) and _result_has_chart_data(clean, name):
                    yield "app", {
                        "resourceUri": ui_meta["resourceUri"],
                        "toolName": name,
                        "toolCallId": tc["id"],
                        "result": clean,
                        "serverId": ui_meta.get("serverId", ""),
                    }

        yield "text", "Maximum iterations reached. The question may be too complex or the tools did not return enough information."
        yield "done", {"sources": sources, "tool_calls": tool_calls_log}


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
) -> tuple[str, list[dict], list[dict], bool]:
    """
    Run the agent loop. Returns (answer, sources, tool_calls).
    If server_configs is empty, returns a prompt to connect a server.
    """
    if not server_configs:
        return (
            "Please connect at least one Tableau MCP server in Settings & Help before asking Tableau questions.",
            [],
            [],
            False,
        )

    async with mcp_session_pool(server_configs) as pool:
        tools, _, tool_server_map = await get_tools_for_servers(server_configs, pool=pool)
        if not tools:
            return (
                "No Tableau tools available. Your session may have expired — sign in again in Settings & Help.",
                [],
                [],
                False,
            )

        base_url = os.environ.get("LLM_PROXY_URL", "http://localhost:8000").rstrip("/")
        api_key = os.environ.get("LLM_PROXY_API_KEY", "dummy")
        client = AsyncOpenAI(
            base_url=f"{base_url}/v1",
            api_key=api_key,
            default_headers={"x-provider": provider},
            timeout=httpx.Timeout(60.0, read=STREAM_READ_TIMEOUT),
        )
        model = model or DEFAULT_MODEL

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for m in (history or []):
            if m.get("role") in ("user", "assistant") and m.get("content"):
                messages.append({"role": m["role"], "content": m["content"]})
        user_content = f"[Tableau is connected.] {question}" if server_configs and tools else question
        if attachments:
            names = ", ".join(a.get("filename", "file") for a in attachments)
            user_content += f"\n\n[Attached file(s) for publishing: {names}. When calling publish-workbook, publish-datasource, or publish-flow, use contentBase64: 'ATTACHMENT_0' for the first file, 'ATTACHMENT_1' for the second, etc.]"
        messages.append({"role": "user", "content": user_content})

        tool_calls_log: list[dict] = []
        sources: list[dict] = []

        if confirmed_action and write_confirmation:
            name = confirmed_action.get("toolName") or ""
            args = dict(confirmed_action.get("arguments") or {})
            if name in WRITE_TOOLS:
                args = _inject_attachments_in_args(args, attachments or [])
                cfg = tool_server_map.get(name) or server_configs[0]
                sid = cfg.get("id", cfg.get("url", ""))
                tool_calls_log.append({"name": name, "arguments": args})
                try:
                    result = await pool["call_tool"](sid, name, args)
                except Exception:
                    logger.exception("Tool %s failed", name)
                    result = "Error: MCP server connection failed. Please try again."
                tc_id = f"call_{uuid.uuid4().hex[:12]}"
                messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": tc_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]})
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": result})

        for i in range(MAX_AGENT_ITERATIONS):
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            choice = resp.choices[0] if resp.choices else None
            if not choice:
                return ("No response from model.", sources, tool_calls_log, False)

            msg = choice.message
            finish_reason = getattr(choice, "finish_reason", None) or "stop"

            if finish_reason in ("stop", "length"):
                content = (msg.content or "").strip()
                return (content or "No answer generated.", sources, tool_calls_log, False)

            if not msg.tool_calls:
                content = (msg.content or "").strip()
                return (content or "No answer generated.", sources, tool_calls_log, False)

            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
                            **({"thought_signature": ts} if (ts := getattr(tc, "thought_signature", None)) is not None else {}),
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )

            tool_results = []
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_calls_log.append({"name": name, "arguments": args})

                if name in WRITE_TOOLS and not write_confirmation:
                    return (
                        "Please confirm the publish action to proceed.",
                        sources,
                        tool_calls_log,
                        True,
                    )

                args = _inject_attachments_in_args(args, attachments or [])
                if name == "execute_python":
                    result = run_execute_python(args.get("code", ""), args.get("data"))
                else:
                    cfg = tool_server_map.get(name) or server_configs[0]
                    sid = cfg.get("id", cfg.get("url", ""))
                    try:
                        result = await pool["call_tool"](sid, name, args)
                    except Exception:
                        logger.exception("Tool %s failed", name)
                        result = "Error: MCP server connection failed. Please try again."
                tool_results.append((name, result))

            for tc, (name, result) in zip(msg.tool_calls, tool_results):
                content = _format_python_result(result) if name == "execute_python" else _sanitize_tool_result(result)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})

    return (
        "Maximum iterations reached. The question may be too complex or the tools did not return enough information.",
        sources,
        tool_calls_log,
        False,
    )

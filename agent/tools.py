"""Convert MCP tool schemas to OpenAI FunctionTool format for llm-proxy."""

import json
import logging
import os

from agent.mcp_client import list_tools

logger = logging.getLogger(__name__)

# Required Tableau tools (subset we expose to the agent)
REQUIRED_TOOLS = {
    "search-content",
    "list-datasources",
    "list-workbooks",
    "list-views",
    "get-workbook",
    "get-datasource-metadata",
    "query-datasource",
    "get-view-data",
    "download-workbook",
    "download-datasource",
    "download-flow",
    "inspect-workbook-file",
    "inspect-datasource-file",
    "inspect-flow-file",
    "publish-workbook",
    "publish-datasource",
    "publish-flow",
    "list-projects",
    "list-flows",
}

# Tools that return file content; agent streams as download chunk
DOWNLOAD_TOOLS = {"download-workbook", "download-datasource", "download-flow"}

# Tools that modify server state; require user confirmation before execution
WRITE_TOOLS = {
    "publish-workbook",
    "publish-datasource",
    "publish-flow",
}

# Built-in Python execution (not from MCP)
EXECUTE_PYTHON_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_python",
        "description": "Run Python code against provided datasets in a sandbox. Use after query-datasource or get-view-data to analyze, forecast, or transform data.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code. Use the `data` dict for input datasets."},
                "data": {
                    "type": "object",
                    "description": "Named datasets from query results. E.g. {\"sales\": [{\"Month\":\"2023-01\",\"Sales\":10000}]}",
                },
            },
            "required": ["code"],
        },
    },
}


def _mcp_to_openai_tool(mcp_tool: dict) -> dict:
    """Convert a single MCP Tool to OpenAI function tool format."""
    name = mcp_tool.get("name", "")
    description = mcp_tool.get("description") or ""
    schema = mcp_tool.get("inputSchema", {})
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description.strip(),
            "parameters": schema,
        },
    }


def _get_ui_resource_uri(mcp_tool: dict) -> str | None:
    """Extract ui:// resourceUri from tool meta. Supports meta.ui.resourceUri and meta['ui/resourceUri']."""
    meta = mcp_tool.get("meta") or mcp_tool.get("_meta") or {}
    ui = meta.get("ui") if isinstance(meta.get("ui"), dict) else None
    if ui and isinstance(ui.get("resourceUri"), str):
        return ui["resourceUri"]
    uri = meta.get("ui/resourceUri")
    return uri if isinstance(uri, str) and uri.startswith("ui://") else None


def mcp_tools_to_openai(mcp_tools: list[dict], filter_names: set[str] | None = None) -> tuple[list[dict], dict[str, str]]:
    """Convert MCP tool list to OpenAI format. Returns (tools, tool_ui_map) where tool_ui_map is {name: resourceUri}."""
    filter_names = filter_names or set()
    out, ui_map = [], {}
    for t in mcp_tools:
        name = t.get("name", "")
        if filter_names and name not in filter_names:
            continue
        out.append(_mcp_to_openai_tool(t))
        if uri := _get_ui_resource_uri(t):
            ui_map[name] = uri
    return out, ui_map


def get_servers_config() -> list[dict]:
    """Parse TABLEAU_MCP_SERVERS env (JSON array of {id, name, url, token?})."""
    raw = os.environ.get("TABLEAU_MCP_SERVERS", "[]")
    try:
        servers = json.loads(raw)
        return [s for s in servers if isinstance(s, dict) and s.get("url")]
    except json.JSONDecodeError:
        return []


def get_servers_for_api() -> list[dict]:
    """Servers config for API response (excludes token). Adds oauthBaseUrl only when OAuth is enabled."""
    out = []
    for s in get_servers_config():
        cfg = {k: v for k, v in s.items() if k != "token"}
        url = cfg.get("url")
        # Skip oauthBaseUrl for PAT-only servers (oauthEnabled: false or authType: "pat")
        if url and cfg.get("oauthEnabled", True) and cfg.get("authType") != "pat":
            try:
                from urllib.parse import urlparse
                cfg["oauthBaseUrl"] = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            except Exception:
                pass
        out.append(cfg)
    return out


async def get_tools_for_servers(
    server_configs: list[dict],
    pool: dict | None = None,
) -> tuple[list[dict], dict[str, dict], dict[str, dict]]:
    """Fetch tools from multiple MCP servers. Returns (tools, tool_ui_map, tool_server_map).
    If pool is provided (from mcp_session_pool), use it to avoid new connections."""
    seen = set()
    tools = []
    tool_ui_map: dict[str, dict] = {}
    tool_server_map: dict[str, dict] = {}
    # Built-in execute_python (no MCP server)
    tools.append(EXECUTE_PYTHON_TOOL)
    seen.add("execute_python")
    tool_server_map["execute_python"] = {"id": "__builtin__", "url": ""}
    for cfg in server_configs:
        url = cfg.get("url")
        server_id = cfg.get("id", url or "")
        if not url:
            continue
        try:
            if pool:
                mcp_tools = await pool["list_tools"](server_id)
            else:
                mcp_tools = await list_tools(url=url, token=cfg.get("token"))
            filter_names = None if cfg.get("includeAllTools") else REQUIRED_TOOLS
            oai_tools, ui_map = mcp_tools_to_openai(mcp_tools, filter_names=filter_names)
            for t in oai_tools:
                name = t["function"]["name"]
                if name not in seen:
                    seen.add(name)
                    tools.append(t)
                    tool_server_map[name] = cfg
                    if name in ui_map:
                        tool_ui_map[name] = {"resourceUri": ui_map[name], "serverId": server_id}
        except Exception as e:
            err_str = str(e).lower()
            if "401" in err_str or "unauthorized" in err_str:
                logger.warning("MCP auth failed for %s (token missing or expired): %s", url, e)
            else:
                logger.warning("Failed to list tools from %s: %s", url, e)
    if tool_ui_map:
        logger.info("MCP Apps enabled for tools: %s", list(tool_ui_map))
    else:
        logger.info("No MCP Apps (resourceUri) in tool definitions; charts will not render")
    return tools, tool_ui_map, tool_server_map

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
    "get-datasource-metadata",
    "query-datasource",
    "get-view-data",
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


def mcp_tools_to_openai(mcp_tools: list[dict], filter_names: set[str] | None = None) -> list[dict]:
    """Convert MCP tool list to OpenAI FunctionTool format. Optionally filter by name."""
    filter_names = filter_names or set()
    out = []
    for t in mcp_tools:
        name = t.get("name", "")
        if filter_names and name not in filter_names:
            continue
        out.append(_mcp_to_openai_tool(t))
    return out


def get_servers_config() -> list[dict]:
    """Parse TABLEAU_MCP_SERVERS env (JSON array of {id, name, url, token?})."""
    raw = os.environ.get("TABLEAU_MCP_SERVERS", "[]")
    try:
        servers = json.loads(raw)
        return [s for s in servers if isinstance(s, dict) and s.get("url")]
    except json.JSONDecodeError:
        return []


def get_servers_for_api() -> list[dict]:
    """Servers config for API response (excludes token). Adds oauthBaseUrl from url origin."""
    out = []
    for s in get_servers_config():
        cfg = {k: v for k, v in s.items() if k != "token"}
        url = cfg.get("url")
        if url:
            try:
                from urllib.parse import urlparse
                cfg["oauthBaseUrl"] = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            except Exception:
                pass
        out.append(cfg)
    return out


async def get_tools_for_servers(server_configs: list[dict]) -> list[dict]:
    """Fetch tools from multiple MCP servers and merge into OpenAI format. Dedupes by name."""
    seen = set()
    tools = []
    for cfg in server_configs:
        url = cfg.get("url")
        token = cfg.get("token")
        if not url:
            continue
        try:
            mcp_tools = await list_tools(url=url, token=token)
            for t in mcp_tools_to_openai(mcp_tools, filter_names=REQUIRED_TOOLS):
                name = t["function"]["name"]
                if name not in seen:
                    seen.add(name)
                    tools.append(t)
        except Exception as e:
            err_str = str(e).lower()
            if "401" in err_str or "unauthorized" in err_str:
                logger.warning("MCP auth failed for %s (token missing or expired): %s", url, e)
            else:
                logger.warning("Failed to list tools from %s: %s", url, e)
    return tools

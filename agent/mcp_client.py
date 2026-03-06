"""MCP client for Tableau MCP servers. Supports Streamable HTTP, SSE, and stdio transports."""

import json
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.types import TextContent

logger = logging.getLogger(__name__)

# Longer timeouts for MCP over Docker/host.docker.internal; Tableau MCP can be slow
MCP_TIMEOUT = httpx.Timeout(60.0, read=300.0)


def _use_sse_transport(url: str, cfg: dict) -> bool:
    """Use SSE when url path contains /sse or transport is explicitly sse."""
    if cfg.get("transport") == "sse":
        return True
    return "/sse" in (urlparse(url).path or "")


@asynccontextmanager
async def mcp_session_pool(server_configs: list[dict]):
    """Hold one MCP session per server for the duration. Reuse like Cursor instead of connect-per-call."""
    stack = []
    sessions: dict[str, ClientSession] = {}
    try:
        for cfg in server_configs:
            url = cfg.get("url")
            token = cfg.get("token")
            sid = cfg.get("id", url or "")
            if not url or urlparse(url).scheme not in ("http", "https"):
                continue
            headers = {"Authorization": f"Bearer {token}"} if token else None
            if _use_sse_transport(url, cfg):
                stream_ctx = sse_client(url=url, headers=headers, timeout=MCP_TIMEOUT)
            else:
                http_client = create_mcp_http_client(headers=headers, timeout=MCP_TIMEOUT)
                stream_ctx = streamable_http_client(url, http_client=http_client)
                await http_client.__aenter__()
                stack.append((http_client, None))
            streams = await stream_ctx.__aenter__()
            stack.append((stream_ctx, None))
            read_stream, write_stream = streams[0], streams[1]
            session = ClientSession(read_stream, write_stream)
            await session.__aenter__()
            stack.append((session, None))
            await session.initialize()
            sessions[sid] = session
        if not sessions:
            yield {}
            return
        cfg_by_id = {c.get("id", c.get("url", "")): c for c in server_configs if c.get("url")}

        async def list_tools_for(sid: str) -> list[dict]:
            s = sessions.get(sid)
            if not s:
                return []
            result = await s.list_tools()
            return [t.model_dump() for t in result.tools]

        async def call_tool_for(sid: str, name: str, arguments: dict) -> str:
            s = sessions.get(sid)
            if not s:
                return f"Error: No session for {sid}"
            result = await s.call_tool(name, arguments or {})
            if result.isError:
                return f"Error: {_content_to_str(result.content)}"
            text = _content_to_str(result.content)
            if result.structuredContent:
                text = json.dumps(result.structuredContent) if not text else f"{text}\n{json.dumps(result.structuredContent)}"
            return text

        yield {"list_tools": list_tools_for, "call_tool": call_tool_for, "configs": cfg_by_id}
    finally:
        for obj, _ in reversed(stack):
            try:
                await obj.__aexit__(None, None, None)
            except Exception:
                pass


def _content_to_str(content: list) -> str:
    """Convert MCP CallToolResult content blocks to a single string."""
    parts = []
    for block in content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        elif isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(json.dumps(block))
        else:
            parts.append(str(block))
    return "\n".join(parts) if parts else ""


@asynccontextmanager
async def _with_session(
    url: str,
    use_stdio: bool,
    stdio_cmd: str | None,
    stdio_args: list[str],
    headers: dict[str, str] | None = None,
):
    """Yield (read_stream, write_stream) for the given server config."""
    if use_stdio and stdio_cmd:
        params = StdioServerParameters(command=stdio_cmd, args=stdio_args or [])
        async with stdio_client(params) as (read_stream, write_stream):
            yield read_stream, write_stream
    elif url and urlparse(url).scheme in ("http", "https"):
        if "/sse" in (urlparse(url).path or ""):
            async with sse_client(url=url, headers=headers, timeout=MCP_TIMEOUT) as streams:
                yield streams[0], streams[1]
        else:
            http_client = create_mcp_http_client(headers=headers, timeout=MCP_TIMEOUT)
            async with http_client:
                async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream, _):
                    yield read_stream, write_stream
    else:
        raise ValueError("Need url (http/https) or stdio command")


async def list_tools(
    url: str | None = None,
    *,
    use_stdio: bool = False,
    stdio_cmd: str | None = None,
    stdio_args: list[str] | None = None,
    token: str | None = None,
) -> list[dict]:
    """List tools from an MCP server. Returns raw MCP Tool definitions."""
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with _with_session(url or "", use_stdio, stdio_cmd, stdio_args or [], headers) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            return [t.model_dump() for t in result.tools]


async def read_resource(
    url: str | None = None,
    uri: str = "",
    *,
    token: str | None = None,
) -> tuple[str, str]:
    """Read a resource by URI from the MCP server. Returns (content, mime_type)."""
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with _with_session(url or "", False, None, [], headers) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.read_resource(uri)
    if not result.contents:
        return "", "text/html"
    c = result.contents[0]
    mime = getattr(c, "mimeType", None) or "text/html"
    if hasattr(c, "text") and c.text:
        return c.text, mime
    if hasattr(c, "blob") and c.blob:
        import base64
        return base64.b64decode(c.blob).decode("utf-8", errors="replace"), mime
    return "", mime


async def call_tool(
    url: str | None = None,
    name: str = "",
    arguments: dict | None = None,
    *,
    use_stdio: bool = False,
    stdio_cmd: str | None = None,
    stdio_args: list[str] | None = None,
    token: str | None = None,
) -> str:
    """Execute an MCP tool and return the result as a string."""
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with _with_session(url or "", use_stdio, stdio_cmd, stdio_args or [], headers) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments or {})
            if result.isError:
                return f"Error: {_content_to_str(result.content)}"
            text = _content_to_str(result.content)
            if result.structuredContent:
                text = json.dumps(result.structuredContent) if not text else f"{text}\n{json.dumps(result.structuredContent)}"
            return text

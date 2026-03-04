"""MCP client for Tableau MCP servers. Supports Streamable HTTP and stdio transports."""

import json
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.types import TextContent

logger = logging.getLogger(__name__)


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
        http_client = create_mcp_http_client(headers=headers) if headers else None
        if http_client:
            async with http_client:
                async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream, _):
                    yield read_stream, write_stream
        else:
            async with streamable_http_client(url) as (read_stream, write_stream, _):
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

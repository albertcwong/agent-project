"""FastAPI routes for the Agent API."""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

MCP_CONNECT_TIMEOUT = 15.0
from pydantic import BaseModel

from agent.loop import run_agent_loop, run_agent_loop_stream
from agent.mcp_client import list_tools
from agent.prompts import TABLEAU_AGENT_SYSTEM_PROMPT
from agent.tools import get_servers_config, get_servers_for_api

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])
mcp_router = APIRouter(prefix="/mcp", tags=["mcp"])


class HistoryMessage(BaseModel):
    role: str
    content: str


class AskRequest(BaseModel):
    question: str
    provider: str = "openai"
    connectedServers: list[str] = []
    tokens: dict[str, str] = {}
    model: str | None = None
    history: list[HistoryMessage] = []


class AskResponse(BaseModel):
    answer: str
    sources: list[dict] = []
    tool_calls: list[dict] = []


def _resolve_server_configs(connected_ids: list[str], client_tokens: dict[str, str] | None = None) -> list[dict]:
    """Map connected server IDs to full config (url, token). Client tokens override env."""
    servers = get_servers_config()
    client_tokens = client_tokens or {}
    out = []
    for sid in connected_ids:
        cfg = next((s for s in servers if s.get("id") == sid), None)
        if cfg and cfg.get("url"):
            c = dict(cfg)
            if sid in client_tokens:
                c["token"] = client_tokens[sid]
            out.append(c)
    return out


def _chunk_line(typ: str, content: str) -> str:
    return json.dumps({"type": typ, "content": content}) + "\n"


async def _stream_agent(req: AskRequest):
    try:
        server_configs = _resolve_server_configs(req.connectedServers, req.tokens)
        history = [{"role": m.role, "content": m.content} for m in req.history]
        async for kind, data in run_agent_loop_stream(
            question=req.question,
            system_prompt=TABLEAU_AGENT_SYSTEM_PROMPT,
            server_configs=server_configs,
            provider=req.provider,
            model=req.model,
            history=history,
        ):
            if kind == "thought":
                yield _chunk_line("thought", data)
            elif kind == "text":
                yield _chunk_line("text", data)
            elif kind == "done":
                yield json.dumps({"type": "done", "meta": data}) + "\n"
    except Exception as e:
        logger.exception("Agent stream failed")
        yield _chunk_line("text", f"Error: {e}")


@router.post("/ask")
async def ask(req: AskRequest):
    """Run the Tableau Q&A agent (streaming)."""
    logger.info("Agent ask: model=%s provider=%s", req.model, req.provider)
    return StreamingResponse(
        _stream_agent(req),
        media_type="text/plain; charset=utf-8",
    )


@router.post("/ask/sync", response_model=AskResponse)
async def ask_sync(req: AskRequest):
    """Run the Tableau Q&A agent (non-streaming, for compatibility)."""
    logger.info("Agent ask sync: model=%s provider=%s", req.model, req.provider)
    server_configs = _resolve_server_configs(req.connectedServers, req.tokens)
    history = [{"role": m.role, "content": m.content} for m in req.history]
    try:
        answer, sources, tool_calls = await run_agent_loop(
            question=req.question,
            system_prompt=TABLEAU_AGENT_SYSTEM_PROMPT,
            server_configs=server_configs,
            provider=req.provider,
            model=req.model,
            history=history,
        )
        return AskResponse(answer=answer, sources=sources, tool_calls=tool_calls)
    except Exception as e:
        logger.exception("Agent ask failed")
        raise HTTPException(status_code=500, detail=str(e))


@mcp_router.get("/servers")
def get_servers():
    """Return admin-configured MCP servers from env (token excluded)."""
    return {"servers": get_servers_for_api()}


class ConnectRequest(BaseModel):
    serverId: str
    token: str | None = None


@mcp_router.post("/connect")
async def connect(req: ConnectRequest):
    """Verify connection to an MCP server. Returns status."""
    servers = get_servers_config()
    cfg = next((s for s in servers if s.get("id") == req.serverId), None)
    if cfg and req.token:
        cfg = {**cfg, "token": req.token}
    if not cfg:
        raise HTTPException(status_code=404, detail="Server not found")
    try:
        tools = await asyncio.wait_for(
            list_tools(url=cfg["url"], token=cfg.get("token")),
            timeout=MCP_CONNECT_TIMEOUT,
        )
        return {"status": "connected", "toolCount": len(tools)}
    except asyncio.TimeoutError:
        logger.warning("MCP connect timed out for %s", req.serverId)
        raise HTTPException(status_code=504, detail="MCP server timed out. Is it running?")
    except Exception as e:
        logger.warning("MCP connect failed for %s: %s", req.serverId, e)
        raise HTTPException(status_code=502, detail=str(e))

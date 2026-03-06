"""FastAPI routes for the Agent API."""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

MCP_CONNECT_TIMEOUT = 15.0
from pydantic import BaseModel

from agent.loop import run_agent_loop, run_agent_loop_stream
from agent.mcp_client import call_tool, list_tools, read_resource
from agent.prompts import TABLEAU_AGENT_SYSTEM_PROMPT
from agent.tools import get_servers_config, get_servers_for_api

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])
mcp_router = APIRouter(prefix="/mcp", tags=["mcp"])


class HistoryMessage(BaseModel):
    role: str
    content: str


class Attachment(BaseModel):
    filename: str
    contentBase64: str


class WriteConfirmation(BaseModel):
    scope: str  # "once" | "session" | "forever"


class ConfirmedAction(BaseModel):
    toolName: str
    arguments: dict = {}


class AskRequest(BaseModel):
    question: str
    provider: str = "openai"
    connectedServers: list[str] = []
    tokens: dict[str, str] = {}
    model: str | None = None
    history: list[HistoryMessage] = []
    writeConfirmation: WriteConfirmation | None = None
    confirmedAction: ConfirmedAction | None = None
    attachments: list[Attachment] = []


class AskResponse(BaseModel):
    answer: str
    sources: list[dict] = []
    tool_calls: list[dict] = []
    awaitingConfirmation: bool = False


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
    sent_done = False

    try:
        server_configs = _resolve_server_configs(req.connectedServers, req.tokens)
        history = [{"role": m.role, "content": m.content} for m in req.history]
        write_conf = req.writeConfirmation.model_dump() if req.writeConfirmation else None
        confirmed = req.confirmedAction.model_dump() if req.confirmedAction else None
        attachments = [{"filename": a.filename, "contentBase64": a.contentBase64} for a in req.attachments]
        async for kind, data in run_agent_loop_stream(
            question=req.question,
            system_prompt=TABLEAU_AGENT_SYSTEM_PROMPT,
            server_configs=server_configs,
            provider=req.provider,
            model=req.model,
            history=history,
            write_confirmation=write_conf,
            confirmed_action=confirmed,
            attachments=attachments,
        ):
            if kind == "thought":
                yield _chunk_line("thought", data)
            elif kind == "text":
                yield _chunk_line("text", data)
            elif kind == "app":
                yield json.dumps({"type": "app", "app": data}) + "\n"
            elif kind == "confirm":
                yield json.dumps({"type": "confirm", **data}) + "\n"
            elif kind == "download":
                yield json.dumps({"type": "download", "download": data}) + "\n"
            elif kind == "done":
                sent_done = True
                yield json.dumps({"type": "done", "meta": data}) + "\n"
    except GeneratorExit:
        raise
    except Exception:
        logger.exception("Agent stream failed")
        if not sent_done:
            yield _chunk_line("text", "Error: Something went wrong. Please try again.")
            yield json.dumps({"type": "done", "meta": {"sources": [], "tool_calls": []}}) + "\n"


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
    write_conf = req.writeConfirmation.model_dump() if req.writeConfirmation else None
    confirmed = req.confirmedAction.model_dump() if req.confirmedAction else None
    attachments = [{"filename": a.filename, "contentBase64": a.contentBase64} for a in req.attachments]
    try:
        answer, sources, tool_calls, awaiting = await run_agent_loop(
            question=req.question,
            system_prompt=TABLEAU_AGENT_SYSTEM_PROMPT,
            server_configs=server_configs,
            provider=req.provider,
            model=req.model,
            history=history,
            write_confirmation=write_conf,
            confirmed_action=confirmed,
            attachments=attachments,
        )
        return AskResponse(answer=answer, sources=sources, tool_calls=tool_calls, awaitingConfirmation=awaiting)
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


class ToolCallRequest(BaseModel):
    serverId: str
    token: str | None = None
    toolName: str
    arguments: dict = {}


@mcp_router.post("/tools/call")
async def mcp_tools_call(req: ToolCallRequest):
    """Proxy tool calls from MCP Apps (e.g. iframe) to the MCP server."""
    servers = get_servers_config()
    cfg = next((s for s in servers if s.get("id") == req.serverId), None)
    if not cfg or not cfg.get("url"):
        raise HTTPException(status_code=404, detail="Server not found")
    auth = req.token or cfg.get("token")
    try:
        result = await call_tool(
            url=cfg["url"], name=req.toolName, arguments=req.arguments, token=auth
        )
        return {"content": [{"type": "text", "text": result}]}
    except Exception as e:
        logger.warning("MCP tools/call failed for %s: %s", req.toolName, e)
        raise HTTPException(status_code=502, detail=str(e))


@mcp_router.get("/ui")
async def get_ui_resource(uri: str = "", serverId: str = "", token: str | None = None):
    """Fetch a ui:// resource from an MCP server. Proxies resources/read."""
    if not uri or not uri.startswith("ui://"):
        raise HTTPException(status_code=400, detail="Invalid or missing uri (must be ui://...)")
    servers = get_servers_config()
    cfg = next((s for s in servers if s.get("id") == serverId), None)
    if not cfg or not cfg.get("url"):
        raise HTTPException(status_code=404, detail="Server not found")
    auth = token or cfg.get("token")
    try:
        content, mime = await read_resource(
            url=cfg["url"], uri=uri, token=auth
        )
        from fastapi.responses import Response
        return Response(content=content, media_type=mime)
    except Exception as e:
        logger.warning("MCP read_resource failed for %s: %s", uri, e)
        def _root(ex):
            sub = getattr(ex, "exceptions", ())
            return _root(sub[0]) if sub else ex
        detail = str(_root(e))
        raise HTTPException(status_code=502, detail=detail)


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

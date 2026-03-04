"""ReAct-style agent loop: LLM + MCP tools."""

import json
import logging
import os

import httpx
from openai import AsyncOpenAI

STREAM_READ_TIMEOUT = float(os.environ.get("LLM_STREAM_READ_TIMEOUT", "300"))

from agent.mcp_client import mcp_session_pool
from agent.tools import get_tools_for_servers

logger = logging.getLogger(__name__)

MAX_AGENT_ITERATIONS = int(os.environ.get("MAX_AGENT_ITERATIONS", "10"))
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "gpt-4")


async def run_agent_loop_stream(
    question: str,
    system_prompt: str,
    server_configs: list[dict],
    provider: str = "openai",
    model: str | None = None,
    history: list[dict] | None = None,
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
        messages.append({"role": "user", "content": user_content})

        tool_calls_log: list[dict] = []
        sources: list[dict] = []

        for _ in range(MAX_AGENT_ITERATIONS):
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
                    yield "text", delta.content
                if getattr(delta, "tool_calls", None):
                    tool_calls_buf.extend(delta.tool_calls)

            if finish_reason in ("stop", "length"):
                content = "".join(content_parts).strip()
                yield "done", {"sources": sources, "tool_calls": tool_calls_log}
                return

            if not tool_calls_buf:
                content = "".join(content_parts).strip()
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
                tool_calls_log.append({"name": name, "arguments": args})
                cfg = tool_server_map.get(name) or server_configs[0]
                sid = cfg.get("id", cfg.get("url", ""))
                try:
                    result = await pool["call_tool"](sid, name, args)
                except Exception as e:
                    result = f"Error: {e}"
                    logger.exception("Tool %s failed", name)
                tool_results.append((name, result))

            for tc, (name, result) in zip(msg_tool_calls, tool_results):
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                ui_meta = tool_ui_map.get(name)
                if ui_meta and ui_meta.get("resourceUri"):
                    yield "app", {
                        "resourceUri": ui_meta["resourceUri"],
                        "toolName": name,
                        "toolCallId": tc["id"],
                        "result": result,
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
) -> tuple[str, list[dict], list[dict]]:
    """
    Run the agent loop. Returns (answer, sources, tool_calls).
    If server_configs is empty, returns a prompt to connect a server.
    """
    if not server_configs:
        return (
            "Please connect at least one Tableau MCP server in Settings & Help before asking Tableau questions.",
            [],
            [],
        )

    async with mcp_session_pool(server_configs) as pool:
        tools, _, tool_server_map = await get_tools_for_servers(server_configs, pool=pool)
        if not tools:
            return (
                "No Tableau tools available. Your session may have expired — sign in again in Settings & Help.",
                [],
                [],
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
        messages.append({"role": "user", "content": user_content})

        tool_calls_log: list[dict] = []
        sources: list[dict] = []

        for i in range(MAX_AGENT_ITERATIONS):
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            choice = resp.choices[0] if resp.choices else None
            if not choice:
                return ("No response from model.", sources, tool_calls_log)

            msg = choice.message
            finish_reason = getattr(choice, "finish_reason", None) or "stop"

            if finish_reason in ("stop", "length"):
                content = (msg.content or "").strip()
                return (content or "No answer generated.", sources, tool_calls_log)

            if not msg.tool_calls:
                content = (msg.content or "").strip()
                return (content or "No answer generated.", sources, tool_calls_log)

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
                cfg = tool_server_map.get(name) or server_configs[0]
                sid = cfg.get("id", cfg.get("url", ""))
                try:
                    result = await pool["call_tool"](sid, name, args)
                except Exception as e:
                    result = f"Error: {e}"
                    logger.exception("Tool %s failed", name)
                tool_results.append((name, result))

            for tc, (name, result) in zip(msg.tool_calls, tool_results):
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    return (
        "Maximum iterations reached. The question may be too complex or the tools did not return enough information.",
        sources,
        tool_calls_log,
    )

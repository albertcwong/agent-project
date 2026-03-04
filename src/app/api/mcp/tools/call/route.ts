import { NextResponse } from "next/server";

const AGENT_API_URL = process.env.AGENT_API_URL || "http://localhost:8001";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { serverId, token, toolName, arguments: args } = body;
    if (!serverId || !toolName) {
      return NextResponse.json({ error: "Missing serverId or toolName" }, { status: 400 });
    }
    const res = await fetch(`${AGENT_API_URL}/mcp/tools/call`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ serverId, token: token || undefined, toolName, arguments: args ?? {} }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return NextResponse.json(
        { error: data.detail || data.error || res.statusText },
        { status: res.status }
      );
    }
    return NextResponse.json(data);
  } catch (err) {
    console.error("MCP tools/call proxy error:", err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Tool call failed" },
      { status: 500 }
    );
  }
}

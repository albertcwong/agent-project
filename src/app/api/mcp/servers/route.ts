import { NextResponse } from "next/server";

const AGENT_API_URL = process.env.AGENT_API_URL || "http://localhost:8001";

export async function GET() {
  try {
    const res = await fetch(`${AGENT_API_URL}/mcp/servers`);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return NextResponse.json(data, { status: res.status });
    }
    return NextResponse.json(data);
  } catch (err) {
    console.error("MCP servers proxy error:", err);
    return NextResponse.json(
      { servers: [], error: "Agent server unavailable" },
      { status: 200 }
    );
  }
}

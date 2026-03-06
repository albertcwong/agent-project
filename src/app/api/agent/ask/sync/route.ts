import { NextResponse } from "next/server";

const AGENT_API_URL = process.env.AGENT_API_URL || "http://localhost:8001";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const res = await fetch(`${AGENT_API_URL}/agent/ask/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return NextResponse.json(
        { error: data.detail || res.statusText },
        { status: res.status }
      );
    }
    return NextResponse.json(data);
  } catch (err) {
    console.error("Agent API sync proxy error:", err);
    const msg =
      err instanceof Error && (err.message === "Failed to fetch" || err.message === "fetch failed")
        ? "Could not reach the agent. Is it running on port 8001? In Docker, set AGENT_API_URL=http://agent:8001."
        : err instanceof Error
          ? err.message
          : "Agent request failed. Is the agent server running on port 8001?";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

import { NextResponse } from "next/server";

const AGENT_API_URL = process.env.AGENT_API_URL || "http://localhost:8001";
const CONNECT_TIMEOUT_MS = 15_000;

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { serverId, token } = body;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), CONNECT_TIMEOUT_MS);
    const res = await fetch(`${AGENT_API_URL}/mcp/connect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ serverId, token: token || undefined }),
      signal: controller.signal,
    });
    clearTimeout(timeout);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail ?? data.error ?? res.statusText;
      const hint =
        res.status === 502 && typeof detail === "string" && /401|unauthorized/i.test(detail)
          ? " Use Sign in with Tableau first."
          : "";
      return NextResponse.json(
        { error: `${detail}${hint}` },
        { status: res.status }
      );
    }
    return NextResponse.json(data);
  } catch (err) {
    console.error("MCP connect proxy error:", err);
    const msg =
      err instanceof Error
        ? err.name === "AbortError"
          ? "Connection timed out. Is the Agent API running? (npm run agent)"
          : err.message
        : "Connection check failed";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

import { NextResponse } from "next/server";

const AGENT_API_URL = process.env.AGENT_API_URL || "http://localhost:8001";

export async function GET(req: Request) {
  try {
    const { searchParams } = new URL(req.url);
    const uri = searchParams.get("uri");
    const serverId = searchParams.get("serverId");
    const token = searchParams.get("token");
    if (!uri || !uri.startsWith("ui://")) {
      return NextResponse.json({ error: "Invalid or missing uri (must be ui://...)" }, { status: 400 });
    }
    if (!serverId) {
      return NextResponse.json({ error: "Missing serverId" }, { status: 400 });
    }
    const url = new URL(`${AGENT_API_URL}/mcp/ui`);
    url.searchParams.set("uri", uri);
    url.searchParams.set("serverId", serverId);
    if (token) url.searchParams.set("token", token);
    const res = await fetch(url.toString());
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      return NextResponse.json(
        { error: data.detail || data.error || res.statusText },
        { status: res.status }
      );
    }
    const contentType = res.headers.get("Content-Type") || "text/html";
    const body = await res.text();
    return new Response(body, {
      headers: { "Content-Type": contentType },
    });
  } catch (err) {
    console.error("MCP UI proxy error:", err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "UI fetch failed" },
      { status: 500 }
    );
  }
}

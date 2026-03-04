import { NextRequest, NextResponse } from "next/server";
import { createHash, randomBytes } from "crypto";

const MCP_CLIENT_ID = "mcp-public-client";

function base64UrlEncode(buf: Buffer): string {
  return buf.toString("base64url");
}

function sha256(data: string): Buffer {
  return createHash("sha256").update(data).digest();
}

export async function GET(req: NextRequest) {
  const serverId = req.nextUrl.searchParams.get("serverId");
  if (!serverId) {
    return NextResponse.redirect(new URL("/", req.url));
  }

  const serversRes = await fetch(
    `${process.env.AGENT_API_URL || "http://localhost:8001"}/mcp/servers`
  );
  const { servers } = await serversRes.json().catch(() => ({ servers: [] }));
  const server = servers.find((s: { id: string }) => s.id === serverId);
  if (!server?.oauthBaseUrl) {
    return NextResponse.redirect(new URL("/", req.url));
  }

  const baseUrl =
    process.env.APP_BASE_URL ||
    (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : req.nextUrl.origin);
  const redirectUri = `${baseUrl}/api/mcp/oauth/callback`;

  const codeVerifier = base64UrlEncode(randomBytes(32));
  const codeChallenge = base64UrlEncode(sha256(codeVerifier));
  const state = base64UrlEncode(randomBytes(16));

  const params = new URLSearchParams({
    client_id: MCP_CLIENT_ID,
    redirect_uri: redirectUri,
    response_type: "code",
    code_challenge: codeChallenge,
    code_challenge_method: "S256",
    state: `${state}:${serverId}`,
  });

  const authUrl = `${server.oauthBaseUrl}/oauth/authorize?${params}`;

  const res = NextResponse.redirect(authUrl);
  res.cookies.set("mcp_oauth_state", `${state}:${serverId}`, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    maxAge: 600,
    path: "/",
  });
  res.cookies.set("mcp_oauth_verifier", codeVerifier, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    maxAge: 600,
    path: "/",
  });
  return res;
}

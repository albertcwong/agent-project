import { NextRequest, NextResponse } from "next/server";

export async function GET(req: NextRequest) {
  const code = req.nextUrl.searchParams.get("code");
  const state = req.nextUrl.searchParams.get("state");
  const error = req.nextUrl.searchParams.get("error");

  const stateCookie = req.cookies.get("mcp_oauth_state")?.value;
  const codeVerifier = req.cookies.get("mcp_oauth_verifier")?.value;

  const baseUrl =
    process.env.APP_BASE_URL ||
    (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : req.nextUrl.origin);
  const redirectUrl = new URL("/", baseUrl);

  const doRedirect = (url: URL) => {
    const res = NextResponse.redirect(url);
    res.cookies.delete("mcp_oauth_state");
    res.cookies.delete("mcp_oauth_verifier");
    return res;
  };

  if (error || !code || !state || !stateCookie || !codeVerifier) {
    if (error) redirectUrl.searchParams.set("oauth_error", error);
    return doRedirect(redirectUrl);
  }

  const parts = stateCookie.split(":");
  const serverId = parts.slice(1).join(":");
  if (state !== stateCookie || !serverId) {
    return doRedirect(redirectUrl);
  }

  try {
    const agentUrl = process.env.AGENT_API_URL || "http://localhost:8001";
    const serversRes = await fetch(`${agentUrl}/mcp/servers`, {
      signal: AbortSignal.timeout(10000),
    });
    if (!serversRes.ok) {
      redirectUrl.searchParams.set("oauth_error", "agent_unreachable");
      return doRedirect(redirectUrl);
    }
    const { servers } = await serversRes.json().catch(() => ({ servers: [] }));
    const server = servers.find((s: { id: string }) => s.id === serverId);
    if (!server?.oauthBaseUrl) {
      redirectUrl.searchParams.set("oauth_error", "server_not_found");
      return doRedirect(redirectUrl);
    }

    const redirectUri = `${baseUrl}/api/mcp/oauth/callback`;
    let tokenRes: Response;
    try {
      tokenRes = await fetch(`${server.oauthBaseUrl}/oauth/token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          grant_type: "authorization_code",
          code,
          redirect_uri: redirectUri,
          client_id: "mcp-public-client",
          code_verifier: codeVerifier,
        }),
        signal: AbortSignal.timeout(15000),
      });
    } catch (tokenErr) {
      console.error("MCP OAuth token exchange failed (MCP server unreachable):", tokenErr);
      redirectUrl.searchParams.set("oauth_error", "mcp_unreachable");
      return doRedirect(redirectUrl);
    }

    const tokenData = await tokenRes.json().catch(() => ({}));
    const accessToken = tokenData.access_token;

    if (!accessToken) {
      redirectUrl.searchParams.set("oauth_error", "no_token");
      return doRedirect(redirectUrl);
    }

    const serverIdEsc = JSON.stringify(serverId);
    const html = `<!DOCTYPE html><html><head><script>
    var tokens = JSON.parse(localStorage.getItem("mcp-server-tokens") || "{}");
    tokens[${serverIdEsc}] = ${JSON.stringify(accessToken)};
    localStorage.setItem("mcp-server-tokens", JSON.stringify(tokens));
    var connected = JSON.parse(localStorage.getItem("mcp-connected-servers") || "[]");
    if (connected.indexOf(${serverIdEsc}) === -1) {
      connected.push(${serverIdEsc});
      localStorage.setItem("mcp-connected-servers", JSON.stringify(connected));
    }
    sessionStorage.setItem("mcp_oauth_return", "1");
    window.location.href = "/";
  </script></head><body>Connecting...</body></html>`;

    return new NextResponse(html, {
      headers: { "Content-Type": "text/html" },
    });
  } catch (e) {
    console.error("MCP OAuth callback failed:", e);
    redirectUrl.searchParams.set("oauth_error", "callback_failed");
    return doRedirect(redirectUrl);
  }
}

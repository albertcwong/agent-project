import { NextRequest, NextResponse } from "next/server";

export async function GET(req: NextRequest) {
  const code = req.nextUrl.searchParams.get("code");
  const state = req.nextUrl.searchParams.get("state");
  const error = req.nextUrl.searchParams.get("error");

  const stateCookie = req.cookies.get("mcp_oauth_state")?.value;
  const codeVerifier = req.cookies.get("mcp_oauth_verifier")?.value;

  const redirect = NextResponse.redirect(new URL("/", req.url));

  redirect.cookies.delete("mcp_oauth_state");
  redirect.cookies.delete("mcp_oauth_verifier");

  if (error || !code || !state || !stateCookie || !codeVerifier) {
    return redirect;
  }

  const parts = stateCookie.split(":");
  const serverId = parts.slice(1).join(":");
  if (state !== stateCookie || !serverId) {
    return redirect;
  }

  const serversRes = await fetch(
    `${process.env.AGENT_API_URL || "http://localhost:8001"}/mcp/servers`
  );
  const { servers } = await serversRes.json().catch(() => ({ servers: [] }));
  const server = servers.find((s: { id: string }) => s.id === serverId);
  if (!server?.oauthBaseUrl) {
    return redirect;
  }

  const baseUrl =
    process.env.APP_BASE_URL ||
    (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : req.nextUrl.origin);
  const redirectUri = `${baseUrl}/api/mcp/oauth/callback`;

  const tokenRes = await fetch(`${server.oauthBaseUrl}/oauth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri,
      client_id: "mcp-public-client",
      code_verifier: codeVerifier,
    }),
  });

  const tokenData = await tokenRes.json().catch(() => ({}));
  const accessToken = tokenData.access_token;

  if (!accessToken) {
    return redirect;
  }

  const tokensJson = JSON.stringify({ [serverId]: accessToken });
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
}

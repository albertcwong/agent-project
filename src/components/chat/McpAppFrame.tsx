"use client";

import { useEffect, useRef, useState } from "react";
import { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge";
import { getMcpServerToken } from "@/lib/threads";

interface McpAppFrameProps {
  resourceUri: string;
  toolName: string;
  result: string;
  serverId: string;
}

export function McpAppFrame({ resourceUri, toolName, result, serverId }: McpAppFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = getMcpServerToken(serverId);
    const params = new URLSearchParams({ uri: resourceUri, serverId });
    if (token) params.set("token", token);
    fetch(`/api/mcp/ui?${params}`)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(r.statusText))))
      .then(setHtml)
      .catch((e) => setError(e.message));
  }, [resourceUri, serverId]);

  useEffect(() => {
    if (!html || !iframeRef.current) return;
    const iframe = iframeRef.current;
    const win = iframe.contentWindow;
    if (!win) return;
    const bridge = new AppBridge(
      null,
      { name: "AgentChat", version: "1.0.0" },
      { openLinks: {}, serverTools: {}, logging: {} }
    );
    bridge.oncalltool = async (params) => {
      const token = getMcpServerToken(serverId);
      const res = await fetch("/api/mcp/tools/call", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ serverId, token, toolName: params.name, arguments: params.arguments ?? {} }),
      });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    };
    bridge.onreadresource = async (params) => {
      const uri = typeof params.uri === "string" ? params.uri : String(params.uri);
      const token = getMcpServerToken(serverId);
      const q = new URLSearchParams({ uri, serverId });
      if (token) q.set("token", token);
      const r = await fetch(`/api/mcp/ui?${q}`);
      if (!r.ok) throw new Error(r.statusText);
      const text = await r.text();
      const mime = r.headers.get("Content-Type") || "text/html";
      return { contents: [{ type: "text" as const, uri, mimeType: mime, text }] };
    };
    bridge.oninitialized = () => {
      bridge.sendToolResult({ content: [{ type: "text", text: result }] });
    };
    const transport = new PostMessageTransport(win, win);
    bridge.connect(transport);
    iframe.srcdoc = html;
    return () => {
      bridge.teardownResource({}).catch(() => {});
    };
  }, [html, result, serverId]);

  if (error) return <div className="rounded border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">{error}</div>;
  if (!html) return <div className="h-[400px] animate-pulse rounded border bg-muted/50" />;
  return (
    <iframe
      ref={iframeRef}
      sandbox="allow-scripts"
      title={`MCP App: ${toolName}`}
      className="h-[400px] w-full rounded border bg-background"
    />
  );
}

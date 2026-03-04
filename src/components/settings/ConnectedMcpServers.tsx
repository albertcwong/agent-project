"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  getConnectedMcpServers,
  setConnectedMcpServers,
  getMcpServerToken,
  removeMcpServerToken,
} from "@/lib/threads";

interface Server {
  id: string;
  name: string;
  url: string;
  oauthBaseUrl?: string;
}

export function ConnectedMcpServers() {
  const [servers, setServers] = useState<Server[]>([]);
  const [connected, setConnected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<Record<string, string>>({});

  useEffect(() => {
    fetch("/api/mcp/servers")
      .then((r) => r.json())
      .then((d) => {
        setServers(d.servers || []);
      })
      .catch(() => setServers([]));
    setConnected(new Set(getConnectedMcpServers()));
  }, []);

  // Verify connected servers when panel opens – clear stale/expired tokens
  useEffect(() => {
    if (servers.length === 0) return;
    const ids = getConnectedMcpServers();
    ids.forEach(async (id) => {
      const token = getMcpServerToken(id);
      try {
        const res = await fetch("/api/mcp/connect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ serverId: id, token: token || undefined }),
        });
        if (!res.ok) {
          setConnected((c) => {
            const next = new Set(c);
            next.delete(id);
            setConnectedMcpServers([...next]);
            removeMcpServerToken(id);
            return next;
          });
        }
      } catch {
        // ignore network errors
      }
    });
  }, [servers]);

  const handleConnect = async (id: string, server: Server) => {
    if (server.oauthBaseUrl) {
      window.location.href = `/api/mcp/oauth/connect?serverId=${encodeURIComponent(id)}`;
      return;
    }
    setLoading((l) => ({ ...l, [id]: true }));
    setError((e) => ({ ...e, [id]: "" }));
    try {
      const token = getMcpServerToken(id);
      const res = await fetch("/api/mcp/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ serverId: id, token: token || undefined }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Connection failed");
      setConnected((c) => {
        const next = new Set([...c, id]);
        setConnectedMcpServers([...next]);
        return next;
      });
    } catch (err) {
      setError((e) => ({
        ...e,
        [id]: err instanceof Error ? err.message : "Failed",
      }));
    } finally {
      setLoading((l) => ({ ...l, [id]: false }));
    }
  };

  const handleDisconnect = (id: string) => {
    setConnected((c) => {
      const next = new Set(c);
      next.delete(id);
      setConnectedMcpServers([...next]);
      removeMcpServerToken(id);
      return next;
    });
  };

  if (servers.length === 0) {
    return (
      <div className="rounded-lg border p-4 text-sm text-muted-foreground">
        No MCP servers configured. Set TABLEAU_MCP_SERVERS in your environment.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="font-medium">Connected MCP Servers</h3>
      <ul className="space-y-2">
        {servers.map((s) => (
          <li
            key={s.id}
            className="flex flex-col gap-2 rounded-lg border border-border bg-background p-3"
          >
            <div className="min-w-0">
              <span className="font-medium">{s.name}</span>
              <span className="ml-2 truncate text-xs text-muted-foreground">
                {s.url}
              </span>
              {error[s.id] && (
                <p className="mt-1 text-xs text-destructive">{error[s.id]}</p>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {connected.has(s.id) ? (
                <>
                  <span className="text-xs text-green-600">Connected</span>
                  <Button
                    variant="outline"
                    size="sm"
                    className="min-w-[11rem]"
                    onClick={() => handleDisconnect(s.id)}
                  >
                    Disconnect
                  </Button>
                </>
              ) : (
                <Button
                  size="sm"
                  className="min-w-[11rem]"
                  onClick={() => handleConnect(s.id, s)}
                  disabled={loading[s.id]}
                >
                  {loading[s.id]
                    ? "Connecting…"
                    : s.oauthBaseUrl
                      ? "Sign in with Tableau"
                      : "Connect"}
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

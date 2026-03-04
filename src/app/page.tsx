"use client";

import { useState, useCallback, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useThreads } from "@/hooks/useThreads";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { ChatContainer } from "@/components/chat/ChatContainer";
import { getConnectedMcpServers, getMcpTokens, getAgentStreaming } from "@/lib/threads";

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  salesforce: "Salesforce",
  endor: "Endor",
};

const OAUTH_ERROR_MSG: Record<string, string> = {
  callback_failed: "MCP sign-in failed. Ensure the agent is running and reachable.",
  agent_unreachable: "Could not reach agent. In Docker, ensure AGENT_API_URL=http://agent:8001.",
  mcp_unreachable:
    "Could not reach MCP server. In Docker, use host.docker.internal in TABLEAU_MCP_SERVERS (e.g. http://host.docker.internal:3927/tableau-mcp).",
  server_not_found: "MCP server not found.",
  no_token: "MCP did not return a token.",
};

function ChatPageContent() {
  const searchParams = useSearchParams();
  const [oauthError, setOauthError] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [agentMode, setAgentMode] = useState(false);

  useEffect(() => {
    const err = searchParams.get("oauth_error");
    if (err) {
      setOauthError(OAUTH_ERROR_MSG[err] || err);
      window.history.replaceState({}, "", "/");
    }
  }, [searchParams]);
  const {
    threads,
    activeId,
    activeThread,
    setActive,
    create,
    updateTitle,
    remove,
    appendMessages,
  } = useThreads();

  const handleNewChat = () => {
    create();
  };

  const handleRenameThread = (id: string, currentTitle: string) => {
    const name = window.prompt("Rename chat", currentTitle);
    if (name != null && name.trim()) updateTitle(id, name.trim());
  };

  const handleDeleteThread = (id: string) => {
    if (window.confirm("Delete this chat?")) remove(id);
  };

  const [sending, setSending] = useState(false);

  const [streamingContent, setStreamingContent] = useState<string | null>(null);
  const [streamingThought, setStreamingThought] = useState<string | null>(null);

  const handleSend = useCallback(async (
    content: string,
    model: string,
    provider: string
  ) => {
    let thread = activeThread;
    if (!thread) {
      thread = create();
    }
    appendMessages(thread.id, [{ role: "user", content }]);
    setSending(true);
    setStreamingContent("");
    let rafId: number | null = null;

    try {
      if (agentMode) {
        const useStream = getAgentStreaming();
        const history = thread.messages
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({ role: m.role, content: m.content }));
        const body = {
          question: content,
          model,
          provider,
          connectedServers: getConnectedMcpServers(),
          tokens: getMcpTokens(),
          history,
        };
        const res = await fetch(useStream ? "/api/agent/ask" : "/api/agent/ask/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.error || res.statusText);
        }
        if (useStream) {
          const reader = res.body?.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          let thoughtAcc = "";
          let textAcc = "";
          const appAcc: Array<{ resourceUri: string; toolName: string; result: string; serverId: string }> = [];
          const flush = () => {
            rafId = null;
            setStreamingThought(thoughtAcc || null);
            setStreamingContent(textAcc || null);
          };
          try {
            if (reader) {
              while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop() ?? "";
                for (const line of lines) {
                  if (!line.trim()) continue;
                  try {
                    const obj = JSON.parse(line);
                    if (obj.type === "thought") thoughtAcc += (thoughtAcc ? "\n\n" : "") + (obj.content ?? "");
                    else if (obj.type === "text") textAcc += obj.content ?? "";
                    else if (obj.type === "app" && obj.app) appAcc.push(obj.app);
                    else if (obj.type === "done") { /* meta available if needed */ }
                  } catch {
                    // skip malformed lines
                  }
                }
                if (rafId === null) rafId = requestAnimationFrame(flush);
              }
              for (const line of buffer.split("\n").filter(Boolean)) {
                try {
                  const obj = JSON.parse(line);
                  if (obj.type === "thought") thoughtAcc += obj.content ?? "";
                  else if (obj.type === "text") textAcc += obj.content ?? "";
                  else if (obj.type === "app" && obj.app) appAcc.push(obj.app);
                } catch { /* skip */ }
              }
            }
          } catch (streamErr) {
            throw new Error(streamErr instanceof Error ? streamErr.message : "Stream failed");
          }
          if (!textAcc.trim()) {
            throw new Error("No response from agent. The provider may not support tool calling (try OpenAI).");
          }
          appendMessages(thread.id, [{
            role: "assistant",
            content: textAcc.trim(),
            ...(thoughtAcc.trim() ? { thought: thoughtAcc.trim() } : {}),
            ...(appAcc.length ? { apps: appAcc } : {}),
          }]);
        } else {
          const data = await res.json().catch(() => ({}));
          const answer = data.answer ?? "";
          if (!answer) {
            throw new Error(data.error || "No response from agent.");
          }
          appendMessages(thread.id, [{ role: "assistant", content: answer }]);
        }
      } else {
        const messages = [
          ...thread.messages,
          { role: "user" as const, content },
        ];
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages, model, provider }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error || res.statusText);
        }
        const reader = res.body?.getReader();
        const decoder = new TextDecoder();
        let full = "";
        const flush = () => {
          rafId = null;
          setStreamingContent(full);
        };
        if (reader) {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            full += decoder.decode(value, { stream: true });
            if (rafId === null) rafId = requestAnimationFrame(flush);
          }
        }
        if (!full.trim()) {
          throw new Error("No response received. Try again or check your connection.");
        }
        appendMessages(thread.id, [{ role: "assistant", content: full }]);
      }
    } catch (err) {
      appendMessages(thread.id, [
        {
          role: "assistant",
          content: `Error: ${err instanceof Error ? err.message : "Request failed"}`,
        },
      ]);
    } finally {
      setSending(false);
      setStreamingContent(null);
      setStreamingThought(null);
      if (typeof rafId === "number") cancelAnimationFrame(rafId);
    }
  }, [activeThread, create, appendMessages, agentMode]);

  const sidebarThreads = threads.map((t) => ({
    id: t.id,
    title: t.title,
    messages: t.messages,
    createdAt: t.createdAt,
  }));

  return (
    <div className="flex h-screen flex-col">
      {oauthError && (
        <div className="flex items-center justify-between gap-4 border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive">
          <span>{oauthError}</span>
          <button onClick={() => setOauthError(null)} className="shrink-0 hover:underline">
            Dismiss
          </button>
        </div>
      )}
      <div className="flex min-h-0 flex-1">
      <Sidebar
        threads={sidebarThreads}
        activeId={activeId}
        onNewChat={handleNewChat}
        onSelectThread={setActive}
        onRenameThread={handleRenameThread}
        onDeleteThread={handleDeleteThread}
      />
      <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {activeThread ? (
          <ChatContainer
            title={activeThread.title}
            modelName={selectedModel || "Select model"}
            messages={activeThread.messages}
            streamingContent={streamingContent}
            streamingThought={streamingThought}
            onSend={handleSend}
            onModelChange={(id, provider) =>
              setSelectedModel(`${id} (${PROVIDER_LABELS[provider] || provider})`)
            }
            disabled={sending}
            agentMode={agentMode}
            onAgentModeChange={setAgentMode}
          />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 text-muted-foreground">
            <p>Start a new chat to begin</p>
            <button
              onClick={handleNewChat}
              className="text-primary hover:underline"
            >
              New chat
            </button>
          </div>
        )}
      </main>
      </div>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={null}>
      <ChatPageContent />
    </Suspense>
  );
}

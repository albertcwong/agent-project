"use client";

import { useState, useCallback, useEffect, useRef, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useThreads } from "@/hooks/useThreads";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { ChatContainer } from "@/components/chat/ChatContainer";
import { getConnectedMcpServers, getMcpTokens, getAgentStreaming, getWriteConfirmationScope, setWriteConfirmationScope } from "@/lib/threads";

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
  const abortControllerRef = useRef<AbortController | null>(null);

  const [streamingContent, setStreamingContent] = useState<string | null>(null);
  const [streamingThought, setStreamingThought] = useState<string | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<{
    action: { toolName: string; arguments: Record<string, unknown> };
    correlationId: string;
    question: string;
    model: string;
    provider: string;
  } | null>(null);

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
        const writeConf = getWriteConfirmationScope();
        const body = {
          question: content,
          model,
          provider,
          connectedServers: getConnectedMcpServers(),
          tokens: getMcpTokens(),
          history,
          ...(writeConf && { writeConfirmation: writeConf }),
        };
        const controller = new AbortController();
        abortControllerRef.current = controller;
        const res = await fetch(useStream ? "/api/agent/ask" : "/api/agent/ask/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
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
          const downloadAcc: Array<{ filename: string; contentBase64: string }> = [];
          let confirmData: { action: { toolName: string; arguments: Record<string, unknown> }; correlationId: string; question: string; model: string; provider: string } | null = null;
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
                    else if (obj.type === "download" && obj.download) downloadAcc.push(obj.download);
                    else if (obj.type === "confirm" && obj.action) confirmData = { action: obj.action, correlationId: obj.correlationId ?? "", question: content, model, provider };
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
                  else if (obj.type === "download" && obj.download) downloadAcc.push(obj.download);
                  else if (obj.type === "confirm" && obj.action) confirmData = { action: obj.action, correlationId: obj.correlationId ?? "", question: content, model, provider };
                } catch { /* skip */ }
              }
            }
          } catch (streamErr) {
            if ((streamErr as Error)?.name === "AbortError") return;
            throw new Error(streamErr instanceof Error ? streamErr.message : "Stream failed");
          }
          if (confirmData) {
            setPendingConfirmation(confirmData);
            return;
          }
          const finalContent = textAcc.trim() || (thoughtAcc.trim() ? thoughtAcc.trim() : null) || (appAcc.length ? "Results:" : null) || (downloadAcc.length ? "Downloaded files:" : null);
          if (!finalContent) {
            throw new Error("No response from agent. The provider may not support tool calling (try OpenAI).");
          }
          appendMessages(thread.id, [{
            role: "assistant",
            content: finalContent,
            ...(thoughtAcc.trim() ? { thought: thoughtAcc.trim() } : {}),
            ...(appAcc.length ? { apps: appAcc } : {}),
            ...(downloadAcc.length ? { downloads: downloadAcc } : {}),
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
        const controller = new AbortController();
        abortControllerRef.current = controller;
        const messages = [
          ...thread.messages,
          { role: "user" as const, content },
        ];
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages, model, provider }),
          signal: controller.signal,
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
      if ((err as Error)?.name === "AbortError") return;
      appendMessages(thread.id, [
        {
          role: "assistant",
          content: `Error: ${err instanceof Error ? err.message : "Request failed"}`,
        },
      ]);
    } finally {
      abortControllerRef.current = null;
      setSending(false);
      setStreamingContent(null);
      setStreamingThought(null);
      if (typeof rafId === "number") cancelAnimationFrame(rafId);
    }
  }, [activeThread, create, appendMessages, agentMode]);

  const handleConfirmWrite = useCallback(async (scope: "once" | "session" | "forever") => {
    const pending = pendingConfirmation;
    if (!pending || !activeThread) return;
    setPendingConfirmation(null);
    if (scope !== "once") setWriteConfirmationScope(scope);
    setSending(true);
    setStreamingContent("");
    const controller = new AbortController();
    abortControllerRef.current = controller;
    let rafId: number | null = null;
    const history = activeThread.messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role, content: m.content }));
    const body = {
      question: pending.question,
      model: pending.model,
      provider: pending.provider,
      connectedServers: getConnectedMcpServers(),
      tokens: getMcpTokens(),
      history,
      writeConfirmation: { scope },
    };
    try {
      const res = await fetch("/api/agent/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error("Retry failed");
      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let thoughtAcc = "";
      let textAcc = "";
      const appAcc: Array<{ resourceUri: string; toolName: string; result: string; serverId: string }> = [];
      const downloadAcc: Array<{ filename: string; contentBase64: string }> = [];
      const flush = () => {
        rafId = null;
        setStreamingThought(thoughtAcc || null);
        setStreamingContent(textAcc || null);
      };
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
              else if (obj.type === "download" && obj.download) downloadAcc.push(obj.download);
            } catch { /* skip */ }
            if (rafId === null) rafId = requestAnimationFrame(flush);
          }
        }
        for (const line of buffer.split("\n").filter(Boolean)) {
          try {
            const obj = JSON.parse(line);
            if (obj.type === "thought") thoughtAcc += obj.content ?? "";
            else if (obj.type === "text") textAcc += obj.content ?? "";
            else if (obj.type === "app" && obj.app) appAcc.push(obj.app);
            else if (obj.type === "download" && obj.download) downloadAcc.push(obj.download);
          } catch { /* skip */ }
        }
      }
      const content = textAcc.trim() || (thoughtAcc.trim() ? thoughtAcc.trim() : null) || (appAcc.length ? "Results:" : null) || (downloadAcc.length ? "Downloaded files:" : null);
      if (content) {
        appendMessages(activeThread.id, [{
          role: "assistant",
          content,
          ...(thoughtAcc.trim() ? { thought: thoughtAcc.trim() } : {}),
          ...(appAcc.length ? { apps: appAcc } : {}),
          ...(downloadAcc.length ? { downloads: downloadAcc } : {}),
        }]);
      }
    } catch (err) {
      if ((err as Error)?.name === "AbortError") return;
      appendMessages(activeThread.id, [{ role: "assistant", content: `Error: ${err instanceof Error ? err.message : "Retry failed"}` }]);
    } finally {
      abortControllerRef.current = null;
      setSending(false);
      setStreamingContent(null);
      setStreamingThought(null);
      if (typeof rafId === "number") cancelAnimationFrame(rafId);
    }
  }, [pendingConfirmation, activeThread, appendMessages]);

  const handleCancelSend = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  const sidebarThreads = threads.map((t) => ({
    id: t.id,
    title: t.title,
    messages: t.messages,
    createdAt: t.createdAt,
  }));

  return (
    <div className="flex h-screen flex-col">
      {pendingConfirmation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="mx-4 max-w-md rounded-lg border bg-background p-6 shadow-lg">
            <h3 className="mb-2 text-lg font-semibold">Confirm write operation</h3>
            <p className="mb-4 text-sm text-muted-foreground">
              About to run: {pendingConfirmation.action.toolName}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => handleConfirmWrite("once")}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                Once
              </button>
              <button
                type="button"
                onClick={() => handleConfirmWrite("session")}
                className="rounded-md border bg-background px-4 py-2 text-sm font-medium hover:bg-muted"
              >
                This session
              </button>
              <button
                type="button"
                onClick={() => handleConfirmWrite("forever")}
                className="rounded-md border bg-background px-4 py-2 text-sm font-medium hover:bg-muted"
              >
                Forever
              </button>
              <button
                type="button"
                onClick={() => setPendingConfirmation(null)}
                className="rounded-md border px-4 py-2 text-sm font-medium hover:bg-muted"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
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
            onCancel={handleCancelSend}
            onModelChange={(id, provider) =>
              setSelectedModel(`${id} (${PROVIDER_LABELS[provider] || provider})`)
            }
            disabled={sending}
            sending={sending}
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

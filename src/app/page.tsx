"use client";

import { useState, useCallback, useEffect, useRef, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useThreads } from "@/hooks/useThreads";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { ChatContainer } from "@/components/chat/ChatContainer";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
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

const TOOL_LABELS: Record<string, string> = {
  "publish-workbook": "Publish workbook",
  "publish-datasource": "Publish datasource",
  "publish-flow": "Publish flow",
};

function parseStepTimings(thought: string, ref: Record<number, { start: number; end?: number }>, now: number): Record<number, { start: number; end?: number }> {
  const steps = [...thought.matchAll(/Step (\d+):/g)].map((m) => parseInt(m[1], 10));
  const out = { ...ref };
  for (let i = 0; i < steps.length; i++) {
    const n = steps[i];
    const prev = steps[i - 1];
    if (!out[n]) out[n] = { start: now };
    if (prev != null && out[prev] && out[prev].end == null) out[prev] = { ...out[prev], end: now };
  }
  return out;
}

function WriteConfirmDetails({ action, question }: { action: { toolName: string; arguments: Record<string, unknown> }; question?: string }) {
  const { toolName, arguments: args } = action;
  const label = TOOL_LABELS[toolName] ?? toolName;
  const name = args.name as string | undefined;
  const projectPath = args.projectPath as string | undefined;
  const projectName = args.projectName as string | undefined;
  const projectId = args.projectId as string | undefined;
  const projectDisplay = projectPath ?? projectName ?? projectId;
  const hasNameOrPath = projectPath != null || projectName != null;
  const overwrite = args.overwrite as boolean | undefined;
  const append = args.append as boolean | undefined;

  return (
    <div className="text-body mb-4 space-y-2 text-muted-foreground">
      {question && (
        <p className="text-sm">
          <span className="font-medium text-foreground">Your request: </span>
          {question}
        </p>
      )}
      <p className="font-medium text-foreground">{label}</p>
      <dl className="space-y-1 text-sm">
        {name != null && (
          <div>
            <dt className="inline font-medium text-foreground">Name: </dt>
            <dd className="inline">{name}</dd>
          </div>
        )}
        {(projectDisplay != null || projectId != null) && (
          <div>
            <dt className="inline font-medium text-foreground">Project: </dt>
            <dd className="inline">
              {hasNameOrPath ? projectDisplay : null}
              {hasNameOrPath && projectId && projectDisplay !== projectId && (
                <span className="ml-1 text-xs text-muted-foreground">(ID: {projectId})</span>
              )}
              {!hasNameOrPath && projectId && (
                <span className="text-xs text-muted-foreground">ID: {projectId}</span>
              )}
            </dd>
          </div>
        )}
        {overwrite && (
          <div>
            <dt className="inline font-medium text-destructive">Overwrite: </dt>
            <dd className="inline">Yes — existing content with the same name will be replaced</dd>
          </div>
        )}
        {append && toolName === "publish-datasource" && (
          <div>
            <dt className="inline font-medium text-foreground">Append: </dt>
            <dd className="inline">Yes — data will be appended to extract</dd>
          </div>
        )}
      </dl>
    </div>
  );
}

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
    togglePin,
    appendMessages,
    updateConversationState,
  } = useThreads();

  const handleNewChat = () => {
    create();
  };

  const [renameDialog, setRenameDialog] = useState<{ id: string; currentTitle: string } | null>(null);
  const [renameInput, setRenameInput] = useState("");

  const handleRenameThread = (id: string, currentTitle: string) => {
    setRenameInput(currentTitle);
    setRenameDialog({ id, currentTitle });
  };

  const handleRenameConfirm = () => {
    if (!renameDialog) return;
    const trimmed = renameInput.trim();
    if (trimmed) {
      updateTitle(renameDialog.id, trimmed);
    }
    setRenameDialog(null);
  };

  const [sending, setSending] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  const [streamingContent, setStreamingContent] = useState<string | null>(null);
  const [streamingThought, setStreamingThought] = useState<string | null>(null);
  const [stepTimings, setStepTimings] = useState<Record<number, { start: number; end?: number }>>({});
  const stepTimingsRef = useRef<Record<number, { start: number; end?: number }>>({});
  const [pendingConfirmation, setPendingConfirmation] = useState<{
    action: { toolName: string; arguments: Record<string, unknown> };
    correlationId: string;
    question: string;
    model: string;
    provider: string;
    attachments?: { filename: string; contentBase64: string }[];
  } | null>(null);

  const handleSend = useCallback(async (
    content: string,
    model: string,
    provider: string,
    attachments?: { filename: string; contentBase64: string }[]
  ) => {
    let thread = activeThread;
    if (!thread) {
      thread = create();
    }
    appendMessages(thread.id, [{ role: "user", content }]);
    setSending(true);
    setStreamingContent("");
    setStreamingThought(null);
    stepTimingsRef.current = {};
    setStepTimings({});
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
          ...(attachments?.length && { attachments }),
          ...(thread.conversationState && { conversationState: thread.conversationState }),
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
          let toolCallsAcc: string[] = [];
          const appAcc: Array<{ resourceUri: string; toolName: string; result: string; serverId: string }> = [];
          const downloadAcc: Array<{ filename: string; contentBase64: string }> = [];
          let confirmData: { action: { toolName: string; arguments: Record<string, unknown> }; correlationId: string; question: string; model: string; provider: string; attachments?: { filename: string; contentBase64: string }[] } | null = null;
          let conversationState: { currentDatasourceId?: string; lastQuery?: Record<string, unknown>; establishedFilters?: Record<string, unknown> } | undefined;
          const flush = () => {
            rafId = null;
            if (thoughtAcc) {
              const next = parseStepTimings(thoughtAcc, stepTimingsRef.current, Date.now());
              stepTimingsRef.current = next;
              setStepTimings(next);
            }
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
                    else if (obj.type === "confirm" && obj.action) confirmData = { action: obj.action, correlationId: obj.correlationId ?? "", question: content, model, provider, attachments };
                    else if (obj.type === "done") {
                      if (obj.meta?.tool_calls) toolCallsAcc = (obj.meta.tool_calls as { name: string }[]).map((t) => t.name);
                      if (obj.meta?.conversationState) conversationState = obj.meta.conversationState;
                    }
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
                  else if (obj.type === "confirm" && obj.action) confirmData = { action: obj.action, correlationId: obj.correlationId ?? "", question: content, model, provider, attachments };
                  else if (obj.type === "done") {
                    if (obj.meta?.tool_calls) toolCallsAcc = (obj.meta.tool_calls as { name: string }[]).map((t) => t.name);
                    if (obj.meta?.conversationState) conversationState = obj.meta.conversationState;
                  }
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
          if (conversationState != null) updateConversationState(thread.id, conversationState);
          const finalContent = textAcc.trim() || (thoughtAcc.trim() ? thoughtAcc.trim() : null) || (appAcc.length ? "Results:" : null) || (downloadAcc.length ? "Downloaded files:" : null);
          if (!finalContent) {
            throw new Error("No response from agent. The provider may not support tool calling (try OpenAI).");
          }
          const steps = [...thoughtAcc.matchAll(/Step (\d+):/g)].map((m) => parseInt(m[1], 10));
          const lastStep = steps[steps.length - 1];
          const finalTimings = { ...stepTimingsRef.current };
          if (lastStep != null && finalTimings[lastStep]?.end == null) {
            finalTimings[lastStep] = { ...finalTimings[lastStep], end: Date.now() };
          }
          appendMessages(thread.id, [{
            role: "assistant",
            content: finalContent,
            ...(thoughtAcc.trim() ? { thought: thoughtAcc.trim() } : {}),
            ...(Object.keys(finalTimings).length ? { stepTimings: finalTimings } : {}),
            ...(toolCallsAcc.length ? { toolCalls: toolCallsAcc } : {}),
            ...(appAcc.length ? { apps: appAcc } : {}),
            ...(downloadAcc.length ? { downloads: downloadAcc } : {}),
          }]);
        } else {
          const data = await res.json().catch(() => ({}));
          const answer = data.answer ?? "";
          if (!answer) {
            throw new Error(data.error || "No response from agent.");
          }
          if (data.conversationState) updateConversationState(thread.id, data.conversationState);
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
          body: JSON.stringify({
            messages,
            model,
            provider,
            ...(attachments?.length && { attachments }),
          }),
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
      setStepTimings({});
      stepTimingsRef.current = {};
      if (typeof rafId === "number") cancelAnimationFrame(rafId);
    }
  }, [activeThread, create, appendMessages, updateConversationState, agentMode]);

  const handleConfirmWrite = useCallback(async (scope: "once" | "session" | "forever") => {
    const pending = pendingConfirmation;
    if (!pending || !activeThread) return;
    setPendingConfirmation(null);
    if (scope !== "once") setWriteConfirmationScope(scope);
    setSending(true);
    setStreamingContent("");
    stepTimingsRef.current = {};
    setStepTimings({});
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
      confirmedAction: pending.action,
      ...(pending.attachments?.length && { attachments: pending.attachments }),
      ...(activeThread.conversationState && { conversationState: activeThread.conversationState }),
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
      let toolCallsAcc: string[] = [];
      let confirmConversationState: { currentDatasourceId?: string; lastQuery?: Record<string, unknown>; establishedFilters?: Record<string, unknown> } | undefined;
      const appAcc: Array<{ resourceUri: string; toolName: string; result: string; serverId: string }> = [];
      const downloadAcc: Array<{ filename: string; contentBase64: string }> = [];
      const flush = () => {
        rafId = null;
        if (thoughtAcc) {
          const next = parseStepTimings(thoughtAcc, stepTimingsRef.current, Date.now());
          stepTimingsRef.current = next;
          setStepTimings(next);
        }
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
              else if (obj.type === "done") {
                if (obj.meta?.tool_calls) toolCallsAcc = (obj.meta.tool_calls as { name: string }[]).map((t) => t.name);
                if (obj.meta?.conversationState) confirmConversationState = obj.meta.conversationState;
              }
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
            else if (obj.type === "done") {
              if (obj.meta?.tool_calls) toolCallsAcc = (obj.meta.tool_calls as { name: string }[]).map((t) => t.name);
              if (obj.meta?.conversationState) confirmConversationState = obj.meta.conversationState;
            }
          } catch { /* skip */ }
        }
      }
      if (confirmConversationState != null) updateConversationState(activeThread.id, confirmConversationState);
      const content = textAcc.trim() || (thoughtAcc.trim() ? thoughtAcc.trim() : null) || (appAcc.length ? "Results:" : null) || (downloadAcc.length ? "Downloaded files:" : null);
      if (content) {
        const steps = [...thoughtAcc.matchAll(/Step (\d+):/g)].map((m) => parseInt(m[1], 10));
        const lastStep = steps[steps.length - 1];
        const finalTimings = { ...stepTimingsRef.current };
        if (lastStep != null && finalTimings[lastStep]?.end == null) {
          finalTimings[lastStep] = { ...finalTimings[lastStep], end: Date.now() };
        }
        appendMessages(activeThread.id, [{
          role: "assistant",
          content,
          ...(thoughtAcc.trim() ? { thought: thoughtAcc.trim() } : {}),
          ...(Object.keys(finalTimings).length ? { stepTimings: finalTimings } : {}),
          ...(toolCallsAcc.length ? { toolCalls: toolCallsAcc } : {}),
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
      setStepTimings({});
      stepTimingsRef.current = {};
      if (typeof rafId === "number") cancelAnimationFrame(rafId);
    }
  }, [pendingConfirmation, activeThread, appendMessages, updateConversationState]);

  const handleCancelSend = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  const sidebarThreads = threads.map((t) => ({
    id: t.id,
    title: t.title,
    messages: t.messages,
    createdAt: t.createdAt,
    pinned: t.pinned,
  }));

  return (
    <div className="flex h-screen flex-col">
      {pendingConfirmation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="mx-4 max-w-md rounded-lg border bg-background p-6 shadow-lg">
            <h3 className="text-heading mb-2">Confirm write operation</h3>
            <WriteConfirmDetails action={pendingConfirmation.action} question={pendingConfirmation.question} />
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => handleConfirmWrite("once")}
                className="text-body rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground hover:bg-primary/90"
              >
                Once
              </button>
              <button
                type="button"
                onClick={() => handleConfirmWrite("session")}
                className="text-body rounded-md border bg-background px-4 py-2 font-medium hover:bg-muted"
              >
                This session
              </button>
              <button
                type="button"
                onClick={() => handleConfirmWrite("forever")}
                className="text-body rounded-md border bg-background px-4 py-2 font-medium hover:bg-muted"
              >
                Forever
              </button>
              <button
                type="button"
                onClick={() => setPendingConfirmation(null)}
                className="text-body rounded-md border px-4 py-2 font-medium hover:bg-muted"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
      <Dialog open={!!renameDialog} onOpenChange={(open) => !open && setRenameDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename chat</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <Input
              value={renameInput}
              onChange={(e) => setRenameInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleRenameConfirm()}
              placeholder="Chat name"
              autoFocus
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRenameDialog(null)}
                className="text-body rounded-md border px-4 py-2 font-medium hover:bg-muted"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRenameConfirm}
                className="text-body rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground hover:bg-primary/90"
              >
                Rename
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
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
        onPinThread={togglePin}
      />
      <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {activeThread ? (
          <ChatContainer
            title={activeThread.title}
            modelName={selectedModel || "Select model"}
            messages={activeThread.messages}
            threadId={activeThread.id}
            pinned={activeThread.pinned}
            onPin={togglePin}
            onRename={handleRenameThread}
            streamingContent={streamingContent}
            streamingThought={streamingThought}
            stepTimings={stepTimings}
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
          <div className="flex flex-1 flex-col items-center justify-center gap-4">
            <p className="text-caption">Start a new chat to begin</p>
            <button
              onClick={handleNewChat}
              className="text-body text-primary hover:underline"
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

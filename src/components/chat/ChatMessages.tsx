"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { useStreamingDisplay } from "@/hooks/useStreamingDisplay";
import { McpAppFrame } from "./McpAppFrame";
import type { McpApp, FileDownload } from "@/lib/threads";

function sanitizeContent(s: string): string {
  return s.replace(/\s*unhandled errors in a TaskGroup[^\n]*/g, "").trimEnd();
}

const PROSE_CLASSES = [
  "prose prose-sm dark:prose-invert max-w-none break-words",
  "[&_h1]:text-2xl [&_h1]:font-bold [&_h1]:mt-6 [&_h1]:mb-3",
  "[&_h2]:text-xl [&_h2]:font-semibold [&_h2]:mt-6 [&_h2]:mb-3",
  "[&_h3]:text-lg [&_h3]:font-semibold [&_h3]:mt-5 [&_h3]:mb-2",
  "[&_h4]:text-base [&_h4]:font-semibold",
  "[&_ul]:list-disc [&_ul]:pl-6",
  "[&_ol]:list-decimal [&_ol]:pl-6",
  "[&_li]:my-1",
  "[&_p]:my-3",
  "[&_blockquote]:border-l-4 [&_blockquote]:border-muted-foreground [&_blockquote]:pl-4 [&_blockquote]:italic",
  "[&_code]:rounded [&_code]:bg-muted [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:text-sm",
  "[&_pre]:rounded-lg [&_pre]:bg-muted [&_pre]:p-4 [&_pre]:overflow-x-auto",
  "[&_table]:w-full [&_table]:border-collapse",
  "[&_th]:border [&_th]:border-border [&_th]:px-4 [&_th]:py-2 [&_th]:text-left [&_th]:font-semibold [&_th]:bg-muted/50",
  "[&_td]:border [&_td]:border-border [&_td]:px-4 [&_td]:py-2",
];

function MarkdownBody({ content }: { content: string }) {
  return (
    <div className={cn("min-w-0", PROSE_CLASSES)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ children }) => (
            <div className="min-w-0 max-w-full overflow-x-auto">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {sanitizeContent(content)}
      </ReactMarkdown>
    </div>
  );
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${(ms / 1000).toFixed(1)}s`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

function totalThinkingTime(timings: Record<number, { start: number; end?: number }> | undefined): number | null {
  if (!timings || Object.keys(timings).length === 0) return null;
  const entries = Object.values(timings);
  if (entries.some((t) => t.end == null)) return null;
  return entries.reduce((sum, t) => sum + ((t.end ?? t.start) - t.start), 0);
}

function thoughtSummary(timings: Record<number, { start: number; end?: number }> | undefined, isStreaming: boolean): string {
  const total = totalThinkingTime(timings);
  if (total != null) return `Thought (${formatDuration(total)} total)`;
  return isStreaming ? "Thinking" : "Thought";
}

interface Message {
  role: string;
  content: string;
  thought?: string;
  stepTimings?: Record<number, { start: number; end?: number }>;
  toolCalls?: string[];
  apps?: McpApp[];
  downloads?: FileDownload[];
}

interface ChatMessagesProps {
  messages: Message[];
  streamingContent?: string | null;
  streamingThought?: string | null;
  stepTimings?: Record<number, { start: number; end?: number }>;
  className?: string;
}

function ThoughtWithTimers({
  thought,
  timings,
  isStreaming,
}: {
  thought: string;
  timings?: Record<number, { start: number; end?: number }>;
  isStreaming?: boolean;
}) {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!isStreaming || !timings) return;
    const hasActive = Object.values(timings).some((t) => t.end == null);
    if (!hasActive) return;
    const id = setInterval(() => tick((n) => n + 1), 100);
    return () => clearInterval(id);
  }, [isStreaming, timings]);
  const normalized = thought.replace(/\\n/g, "\n");
  if (!timings || Object.keys(timings).length === 0) {
    return <pre className="text-caption mt-1 max-h-[50vh] overflow-auto whitespace-pre-wrap rounded bg-muted/50 p-2">{normalized}</pre>;
  }
  const lines = normalized.split("\n");
  const out: ReactNode[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const m = line.match(/^Step (\d+):/);
    if (m) {
      const n = parseInt(m[1], 10);
      const t = timings[n];
      const dur = t?.end != null ? formatDuration(t.end - t.start) : t?.start != null ? formatDuration(Date.now() - t.start) : null;
      out.push(
        <span key={i}>
          {line}
          {dur != null && <span className="ml-2 text-muted-foreground">({dur})</span>}
          {"\n"}
        </span>
      );
    } else {
      out.push(
        <span key={i}>
          {line}
          {"\n"}
        </span>
      );
    }
  }
  return <pre className="text-caption mt-1 max-h-[50vh] overflow-auto whitespace-pre-wrap rounded bg-muted/50 p-2">{out}</pre>;
}

export function ChatMessages({ messages, streamingContent, streamingThought, stepTimings, className }: ChatMessagesProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const isProgrammaticScrollRef = useRef(false);
  const programmaticScrollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const userTookControlRef = useRef(false);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [mode, setMode] = useState<"passive" | "active">("passive");
  const displayedContent = useStreamingDisplay(streamingContent ?? null);

  useEffect(() => {
    const el = bottomRef.current;
    const vp = contentRef.current?.closest("[data-slot=scroll-area]")?.querySelector("[data-slot=scroll-area-viewport]");
    if (!el || !vp) return;
    const observer = new IntersectionObserver(
      ([entry]) => setIsAtBottom(entry.isIntersecting),
      { root: vp, rootMargin: "20px", threshold: 0 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [messages.length, streamingContent != null, streamingThought != null]);

  const resetDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isAtBottomRef = useRef(isAtBottom);
  isAtBottomRef.current = isAtBottom;
  useEffect(() => {
    if (isAtBottom && mode === "active") {
      if (resetDebounceRef.current) clearTimeout(resetDebounceRef.current);
      resetDebounceRef.current = setTimeout(() => {
        resetDebounceRef.current = null;
        if (!isAtBottomRef.current) return;
        userTookControlRef.current = false;
        setMode("passive");
      }, 300);
    } else if (resetDebounceRef.current) {
      clearTimeout(resetDebounceRef.current);
      resetDebounceRef.current = null;
    }
    return () => {
      if (resetDebounceRef.current) {
        clearTimeout(resetDebounceRef.current);
        resetDebounceRef.current = null;
      }
    };
  }, [isAtBottom, mode]);

  const wasStreamingRef = useRef(false);
  useEffect(() => {
    const isStreaming = streamingContent != null || streamingThought != null;
    if (isStreaming && !wasStreamingRef.current) userTookControlRef.current = false;
    wasStreamingRef.current = isStreaming;
  }, [streamingContent != null, streamingThought != null]);

  useEffect(() => () => {
    if (programmaticScrollTimeoutRef.current) {
      clearTimeout(programmaticScrollTimeoutRef.current);
    }
  }, []);

  useEffect(() => {
    const vp = contentRef.current?.closest("[data-slot=scroll-area]")?.querySelector("[data-slot=scroll-area-viewport]");
    if (!vp) return;
    const onScroll = () => {
      if (!isProgrammaticScrollRef.current) {
        userTookControlRef.current = true;
        setMode("active");
      }
    };
    const onWheel = () => {
      userTookControlRef.current = true;
      setMode("active");
    };
    vp.addEventListener("scroll", onScroll, { passive: true });
    vp.addEventListener("wheel", onWheel, { passive: true });
    return () => {
      vp.removeEventListener("scroll", onScroll);
      vp.removeEventListener("wheel", onWheel);
    };
  }, [messages.length, streamingContent != null, streamingThought != null]);

  const enterActiveOnClick = useCallback(() => {
    userTookControlRef.current = true;
    setMode("active");
  }, []);

  const scrollToBottom = useCallback(() => {
    if (!bottomRef.current) return;
    if (programmaticScrollTimeoutRef.current) clearTimeout(programmaticScrollTimeoutRef.current);
    isProgrammaticScrollRef.current = true;
    bottomRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
    programmaticScrollTimeoutRef.current = setTimeout(() => {
      programmaticScrollTimeoutRef.current = null;
      isProgrammaticScrollRef.current = false;
    }, 400);
  }, []);

  const scrollThrottleRef = useRef(0);
  useEffect(() => {
    if (userTookControlRef.current || mode !== "passive" || !isAtBottom || !bottomRef.current) return;
    const el = bottomRef.current;
    if (!el) return;
    const now = Date.now();
    if ((streamingContent != null || streamingThought != null) && now - scrollThrottleRef.current < 60) return;
    scrollThrottleRef.current = now;
    if (programmaticScrollTimeoutRef.current) clearTimeout(programmaticScrollTimeoutRef.current);
    isProgrammaticScrollRef.current = true;
    el.scrollIntoView({ behavior: "smooth", block: "end" });
    programmaticScrollTimeoutRef.current = setTimeout(() => {
      programmaticScrollTimeoutRef.current = null;
      isProgrammaticScrollRef.current = false;
    }, 400);
    return () => {
      if (programmaticScrollTimeoutRef.current) {
        clearTimeout(programmaticScrollTimeoutRef.current);
        programmaticScrollTimeoutRef.current = null;
      }
    };
  }, [messages, streamingContent, isAtBottom, mode]);

  if (messages.length === 0 && !streamingContent && !streamingThought) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-caption">Send a message to get started</p>
      </div>
    );
  }

  return (
    <div className={cn("relative min-h-0 flex-1 overflow-hidden", className)}>
      <ScrollArea className="h-full">
        <div ref={contentRef} className="mx-auto min-w-0 max-w-3xl space-y-8 p-6">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={cn(
              "flex gap-4",
              msg.role === "user" && "flex-row-reverse"
            )}
          >
            <Avatar className="h-8 w-8 shrink-0">
              <AvatarFallback>
                {msg.role === "user" ? "U" : "A"}
              </AvatarFallback>
            </Avatar>
            <div
              className={cn(
                "min-w-0 rounded-lg px-4 py-3 text-body leading-relaxed",
                msg.role === "user" ? "bg-muted max-w-[80%]" : "flex-1"
              )}
              {...(msg.role === "assistant" && { onPointerDown: enterActiveOnClick })}
            >
              {msg.role === "assistant" ? (
                <>
                  {msg.toolCalls && msg.toolCalls.length > 0 && (
                    <p className="text-caption mb-2 text-muted-foreground">
                      Tools used: {msg.toolCalls.join(", ")}
                    </p>
                  )}
                  {msg.thought && (
                    <details className="mb-3" open>
                      <summary className="text-label cursor-pointer text-muted-foreground hover:text-foreground">
                        {thoughtSummary(msg.stepTimings, false)}
                      </summary>
                      <ThoughtWithTimers thought={msg.thought} timings={msg.stepTimings} isStreaming={false} />
                    </details>
                  )}
                  <MarkdownBody content={msg.content} />
                  {msg.apps?.map((app, j) => (
                    <div key={j} className="mt-4">
                      <McpAppFrame
                        resourceUri={app.resourceUri}
                        toolName={app.toolName}
                        result={app.result}
                        serverId={app.serverId}
                      />
                    </div>
                  ))}
                  {msg.downloads?.map((d, j) => (
                    <div key={j} className="mt-2">
                      <a
                        href={`data:application/octet-stream;base64,${d.contentBase64}`}
                        download={d.filename}
                        className="text-primary underline hover:no-underline"
                      >
                        Download {d.filename}
                      </a>
                    </div>
                  ))}
                </>
              ) : (
                <MarkdownBody content={msg.content} />
              )}
            </div>
          </div>
        ))}
        {(streamingContent != null || streamingThought != null) && (
          <div className="flex gap-4">
            <Avatar className="h-8 w-8 shrink-0">
              <AvatarFallback>A</AvatarFallback>
            </Avatar>
            <div className="min-w-0 flex-1 rounded-lg px-4 py-3 text-body leading-relaxed" onPointerDown={enterActiveOnClick}>
              {streamingThought && (
                <details className="mb-3" open={!!streamingThought}>
                  <summary className="text-label cursor-pointer text-muted-foreground hover:text-foreground">
                    {thoughtSummary(stepTimings, true)}
                  </summary>
                  <ThoughtWithTimers thought={streamingThought} timings={stepTimings} isStreaming />
                </details>
              )}
              <div className="min-w-0">
                {streamingContent != null ? (
                  <MarkdownBody content={displayedContent} />
                ) : (
                  <span className="animate-pulse">...</span>
                )}
              </div>
              {streamingContent != null && (
                <span className="ml-0.5 inline-block h-4 w-px animate-pulse bg-foreground" aria-hidden />
              )}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
        </div>
      </ScrollArea>
      {mode === "active" && (streamingContent != null || streamingThought != null) && (
        <div className="absolute bottom-4 left-1/2 z-10 -translate-x-1/2">
          <button
            type="button"
            onClick={scrollToBottom}
            className="flex items-center gap-1.5 rounded-full bg-muted/90 px-3 py-1.5 text-caption text-muted-foreground shadow-md transition-colors hover:bg-muted hover:text-foreground"
          >
            <ChevronDown className="h-3.5 w-3.5 shrink-0" />
            New content below
          </button>
        </div>
      )}
      {!isAtBottom && !(mode === "active" && (streamingContent != null || streamingThought != null)) && (
        <Button
          variant="secondary"
          size="icon"
          className="absolute bottom-4 right-12 z-10 h-8 w-8 shadow-md"
          onClick={scrollToBottom}
          aria-label="Jump to latest"
        >
          <ChevronDown className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}

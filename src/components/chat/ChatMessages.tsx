"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowUp } from "lucide-react";
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
  const [isAtBottom, setIsAtBottom] = useState(true);
  const displayedContent = useStreamingDisplay(streamingContent ?? null);

  useEffect(() => {
    const el = bottomRef.current;
    const viewport = contentRef.current?.closest("[data-slot=scroll-area]")?.querySelector("[data-slot=scroll-area-viewport]");
    if (!el || !viewport) return;
    const observer = new IntersectionObserver(
      ([entry]) => setIsAtBottom(entry.isIntersecting),
      { root: viewport, rootMargin: "20px", threshold: 0 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [messages.length, streamingContent != null, streamingThought != null]);

  const scrollThrottleRef = useRef(0);
  useEffect(() => {
    if (!isAtBottom || !bottomRef.current) return;
    const el = bottomRef.current;
    const now = Date.now();
    if ((streamingContent != null || streamingThought != null) && now - scrollThrottleRef.current < 60) return;
    scrollThrottleRef.current = now;
    el.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, streamingContent, isAtBottom]);

  if (messages.length === 0 && !streamingContent && !streamingThought) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-caption">Send a message to get started</p>
      </div>
    );
  }

  const scrollToTop = () => {
    const viewport = contentRef.current?.closest("[data-slot=scroll-area]")?.querySelector("[data-slot=scroll-area-viewport]");
    viewport?.scrollTo({ top: 0, behavior: "smooth" });
  };

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
            >
              {msg.role === "assistant" ? (
                <>
                  {msg.toolCalls && msg.toolCalls.length > 0 && (
                    <p className="text-caption mb-2 text-muted-foreground">
                      Tools used: {msg.toolCalls.join(", ")}
                    </p>
                  )}
                  {msg.thought && (
                    <details className="mb-3">
                      <summary className="text-label cursor-pointer text-muted-foreground hover:text-foreground">
                        {thoughtSummary(msg.stepTimings, false)}
                      </summary>
                      <ThoughtWithTimers thought={msg.thought} timings={msg.stepTimings} isStreaming={false} />
                    </details>
                  )}
                  <div className="min-w-0">
                    <div className="prose prose-sm dark:prose-invert max-w-none break-words prose-p:my-3 prose-li:my-1 prose-headings:mt-6 prose-headings:mb-3 prose-th:px-4 prose-th:py-2 prose-td:px-4 prose-td:py-2">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          table: ({ children }) => (
                            <div className="overflow-x-auto">
                              <table>{children}</table>
                            </div>
                          ),
                        }}
                      >
                        {sanitizeContent(msg.content)}
                      </ReactMarkdown>
                    </div>
                  </div>
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
                <p className="text-body whitespace-pre-wrap">{sanitizeContent(msg.content)}</p>
              )}
            </div>
          </div>
        ))}
        {(streamingContent != null || streamingThought != null) && (
          <div className="flex gap-4">
            <Avatar className="h-8 w-8 shrink-0">
              <AvatarFallback>A</AvatarFallback>
            </Avatar>
            <div className="min-w-0 flex-1 rounded-lg px-4 py-3 text-body leading-relaxed">
              {streamingThought && (
                <details className="mb-3" open={!!streamingThought}>
                  <summary className="text-label cursor-pointer text-muted-foreground hover:text-foreground">
                    {thoughtSummary(stepTimings, true)}
                  </summary>
                  <ThoughtWithTimers thought={streamingThought} timings={stepTimings} isStreaming />
                </details>
              )}
              <div className="min-w-0">
                <div className="prose prose-sm dark:prose-invert max-w-none break-words prose-p:my-3 prose-li:my-1 prose-headings:mt-6 prose-headings:mb-3 prose-th:px-4 prose-th:py-2 prose-td:px-4 prose-td:py-2">
                  {streamingContent != null ? (
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        table: ({ children }) => (
                          <div className="overflow-x-auto">
                            <table>{children}</table>
                          </div>
                        ),
                      }}
                    >
                      {sanitizeContent(displayedContent)}
                    </ReactMarkdown>
                  ) : (
                    <span className="animate-pulse">...</span>
                  )}
                </div>
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
      {!isAtBottom && (
        <Button
          variant="secondary"
          size="icon"
          className="absolute bottom-4 right-12 z-10 h-8 w-8 shadow-md"
          onClick={scrollToTop}
          aria-label="Scroll to top"
        >
          <ArrowUp className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}

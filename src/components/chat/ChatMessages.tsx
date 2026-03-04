"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { useStreamingDisplay } from "@/hooks/useStreamingDisplay";
import { McpAppFrame } from "./McpAppFrame";
import type { McpApp } from "@/lib/threads";

interface Message {
  role: string;
  content: string;
  thought?: string;
  apps?: McpApp[];
}

interface ChatMessagesProps {
  messages: Message[];
  streamingContent?: string | null;
  streamingThought?: string | null;
  className?: string;
}

export function ChatMessages({ messages, streamingContent, streamingThought, className }: ChatMessagesProps) {
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
      { root: viewport, rootMargin: "80px", threshold: 0 }
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
      <div className="flex flex-1 items-center justify-center text-muted-foreground">
        <p>Send a message to get started</p>
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
        <div ref={contentRef} className="mx-auto max-w-3xl space-y-8 p-6">
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
                "rounded-lg px-4 py-3 text-sm leading-relaxed",
                msg.role === "user" && "bg-muted"
              )}
            >
              {msg.role === "assistant" ? (
                <>
                  {msg.thought && (
                    <details className="mb-3">
                      <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                        Thinking
                      </summary>
                      <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded bg-muted/50 p-2 text-xs text-muted-foreground">
                        {msg.thought}
                      </pre>
                    </details>
                  )}
                  <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-3 prose-li:my-1 prose-headings:mt-6 prose-headings:mb-3 prose-th:px-4 prose-th:py-2 prose-td:px-4 prose-td:py-2">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
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
                </>
              ) : (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              )}
            </div>
          </div>
        ))}
        {(streamingContent != null || streamingThought != null) && (
          <div className="flex gap-4">
            <Avatar className="h-8 w-8 shrink-0">
              <AvatarFallback>A</AvatarFallback>
            </Avatar>
            <div className="rounded-lg px-4 py-3 text-sm leading-relaxed">
              {streamingThought && (
                <details className="mb-3">
                  <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                    Thinking
                  </summary>
                  <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded bg-muted/50 p-2 text-xs text-muted-foreground">
                    {streamingThought}
                  </pre>
                </details>
              )}
              <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-3 prose-li:my-1 prose-headings:mt-6 prose-headings:mb-3 prose-th:px-4 prose-th:py-2 prose-td:px-4 prose-td:py-2">
                {streamingContent != null ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayedContent}</ReactMarkdown>
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

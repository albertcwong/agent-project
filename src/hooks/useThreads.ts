"use client";

import { useState, useEffect, useCallback } from "react";
import {
  loadThreads,
  saveThreads,
  generateId,
  type Thread,
  type ChatMessage,
} from "@/lib/threads";

export function useThreads() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    const loaded = loadThreads();
    setThreads(loaded);
    if (loaded.length > 0 && !activeId) {
      setActiveId(loaded[0].id);
    }
  }, []);

  useEffect(() => {
    if (threads.length > 0) {
      saveThreads(threads);
    }
  }, [threads]);

  const setActive = useCallback((id: string | null) => {
    setActiveId(id);
  }, []);

  const create = useCallback((): Thread => {
    const thread: Thread = {
      id: generateId(),
      title: "New chat",
      messages: [],
      createdAt: Date.now(),
    };
    setThreads((prev) => [thread, ...prev]);
    setActiveId(thread.id);
    return thread;
  }, []);

  const updateTitle = useCallback((id: string, title: string) => {
    setThreads((prev) =>
      prev.map((t) => (t.id === id ? { ...t, title } : t))
    );
  }, []);

  const remove = useCallback((id: string) => {
    setThreads((prev) => {
      const next = prev.filter((t) => t.id !== id);
      if (activeId === id) {
        setActiveId(next.length > 0 ? next[0].id : null);
      }
      return next;
    });
  }, [activeId]);

  const appendMessages = useCallback(
    (id: string, newMessages: ChatMessage[]) => {
      setThreads((prev) =>
        prev.map((t) => {
          if (t.id !== id) return t;
          const updated = { ...t, messages: [...t.messages, ...newMessages] };
          if (newMessages.length > 0 && newMessages[0].role === "user" && t.title === "New chat") {
            updated.title = newMessages[0].content.slice(0, 50) || "New chat";
          }
          return updated;
        })
      );
    },
    []
  );

  const activeThread = threads.find((t) => t.id === activeId) ?? null;

  return {
    threads,
    activeId,
    activeThread,
    setActive,
    create,
    updateTitle,
    remove,
    appendMessages,
  };
}

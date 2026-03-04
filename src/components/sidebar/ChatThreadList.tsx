"use client";

import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

export interface Thread {
  id: string;
  title: string;
  messages: { role: string; content: string }[];
  createdAt: number;
}

interface ChatThreadListProps {
  threads: Thread[];
  activeId: string | null;
  onSelect: (id: string) => void;
}

export function ChatThreadList({
  threads,
  activeId,
  onSelect,
}: ChatThreadListProps) {
  return (
    <ScrollArea className="flex-1 px-2">
      <div className="space-y-1 py-2">
        {threads.map((thread) => (
          <button
            key={thread.id}
            onClick={() => onSelect(thread.id)}
            className={cn(
              "w-full rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
              activeId === thread.id && "bg-sidebar-accent text-sidebar-accent-foreground"
            )}
          >
            {thread.title || "New chat"}
          </button>
        ))}
      </div>
    </ScrollArea>
  );
}

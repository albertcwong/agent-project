"use client";

import { MoreHorizontal, Pencil, Pin } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

export interface Thread {
  id: string;
  title: string;
  messages: { role: string; content: string }[];
  createdAt: number;
  pinned?: boolean;
}

interface ChatThreadListProps {
  threads: Thread[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onRename?: (id: string, currentTitle: string) => void;
  onPin?: (id: string) => void;
}

export function ChatThreadList({
  threads,
  activeId,
  onSelect,
  onRename,
  onPin,
}: ChatThreadListProps) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto pl-2">
      <div className="space-y-1 py-2 pr-3">
        {threads.map((thread) => (
          <div
            key={thread.id}
            className={cn(
              "group flex items-center gap-1 rounded-md transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
              activeId === thread.id && "bg-sidebar-accent text-sidebar-accent-foreground"
            )}
          >
            <button
              onClick={() => onSelect(thread.id)}
              className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-2 text-left text-body"
            >
              {thread.pinned && <Pin className="h-3.5 w-3.5 shrink-0 fill-current text-muted-foreground" />}
              <span className="min-w-0 truncate">{thread.title || "New chat"}</span>
            </button>
            {(onRename || onPin) && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    className="shrink-0 rounded p-1.5 opacity-100 hover:bg-sidebar-accent/80"
                    aria-label="Thread actions"
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" side="right">
                  {onPin && (
                    <DropdownMenuItem onClick={() => onPin(thread.id)}>
                      <Pin className={cn("h-4 w-4", thread.pinned && "fill-current")} />
                      {thread.pinned ? "Unpin" : "Pin"}
                    </DropdownMenuItem>
                  )}
                  {onRename && (
                    <DropdownMenuItem onClick={() => onRename(thread.id, thread.title || "New chat")}>
                      <Pencil className="h-4 w-4" />
                      Rename
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

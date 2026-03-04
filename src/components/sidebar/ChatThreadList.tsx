"use client";

import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
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
}

interface ChatThreadListProps {
  threads: Thread[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onRename?: (id: string, currentTitle: string) => void;
  onDelete?: (id: string) => void;
}

export function ChatThreadList({
  threads,
  activeId,
  onSelect,
  onRename,
  onDelete,
}: ChatThreadListProps) {
  return (
    <ScrollArea className="flex-1 px-2">
      <div className="space-y-1 py-2">
        {threads.map((thread) => (
          <div
            key={thread.id}
            className={cn(
              "group flex items-center gap-1 rounded-md pr-1 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
              activeId === thread.id && "bg-sidebar-accent text-sidebar-accent-foreground"
            )}
          >
            <button
              onClick={() => onSelect(thread.id)}
              className="min-w-0 flex-1 rounded-md px-3 py-2 text-left text-sm"
            >
              <span className="truncate block">{thread.title || "New chat"}</span>
            </button>
            {(onRename || onDelete) && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    className={cn(
                      "shrink-0 rounded p-1.5 hover:bg-sidebar-accent/80",
                      activeId === thread.id ? "opacity-100" : "opacity-0 group-hover:opacity-100"
                    )}
                    aria-label="Thread actions"
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" side="right">
                  {onRename && (
                    <DropdownMenuItem onClick={() => onRename(thread.id, thread.title || "New chat")}>
                      <Pencil className="h-4 w-4" />
                      Rename
                    </DropdownMenuItem>
                  )}
                  {onDelete && (
                    <DropdownMenuItem
                      variant="destructive"
                      onClick={() => onDelete(thread.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                      Delete
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}

"use client";

import { MoreHorizontal, Pin, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface ChatHeaderProps {
  modelName: string;
  title: string;
  threadId?: string | null;
  pinned?: boolean;
  onPin?: (id: string) => void;
  onRename?: (id: string, currentTitle: string) => void;
}

export function ChatHeader({ modelName, title, threadId, pinned, onPin, onRename }: ChatHeaderProps) {
  const showMenu = threadId && (onPin || onRename);
  return (
    <header className="flex items-center justify-between px-4 py-3">
      <div className="flex items-center gap-2 text-body">
        <span className="text-label">{modelName}</span>
        <span className="text-caption">—</span>
        <span className="text-caption">{title}</span>
      </div>
      {showMenu && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {onPin && (
              <DropdownMenuItem onClick={() => onPin(threadId)}>
                <Pin className={cn("h-4 w-4", pinned && "fill-current")} />
                {pinned ? "Unpin" : "Pin"}
              </DropdownMenuItem>
            )}
            {onRename && (
              <DropdownMenuItem onClick={() => onRename(threadId, title)}>
                <Pencil className="h-4 w-4" />
                Rename
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </header>
  );
}

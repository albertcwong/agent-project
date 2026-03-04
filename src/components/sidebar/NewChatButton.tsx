"use client";

import { Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";

interface NewChatButtonProps {
  onClick: () => void;
}

export function NewChatButton({ onClick }: NewChatButtonProps) {
  return (
    <Button
      variant="ghost"
      className="w-full justify-start gap-2"
      onClick={onClick}
    >
      <Pencil className="h-4 w-4" />
      New chat
    </Button>
  );
}

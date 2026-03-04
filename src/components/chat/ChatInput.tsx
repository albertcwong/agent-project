"use client";

import { useState } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ModeSelector } from "./ModeSelector";
import { ModelSelector, type ModelOption } from "./ModelSelector";

interface ChatInputProps {
  onSend: (content: string, model: string, provider: string) => Promise<void>;
  onModelChange?: (model: string, provider: string) => void;
  agentMode?: boolean;
  onAgentModeChange?: (v: boolean) => void;
  disabled?: boolean;
}

export function ChatInput({ onSend, onModelChange, agentMode, onAgentModeChange, disabled }: ChatInputProps) {
  const [input, setInput] = useState("");
  const [modelOption, setModelOption] = useState<ModelOption | null>(null);

  const handleModelChange = (id: string, provider: string) => {
    setModelOption({ id, provider });
    onModelChange?.(id, provider);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || disabled || !modelOption) return;
    setInput("");
    await onSend(text, modelOption.id, modelOption.provider);
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="flex items-center gap-2 border-t bg-background p-4"
    >
      {onAgentModeChange && (
        <ModeSelector value={agentMode ?? false} onChange={onAgentModeChange} />
      )}
      <ModelSelector
        value={modelOption}
        onChange={handleModelChange}
      />
      <Input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="Enter a prompt..."
        disabled={disabled}
        className="flex-1"
      />
      <Button type="submit" size="icon" disabled={disabled || !input.trim()}>
        <Send className="h-4 w-4" />
      </Button>
    </form>
  );
}

"use client";

import { useRef, useState } from "react";
import { Send, Square, Plus, Paperclip } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ModeSelector } from "./ModeSelector";
import { ModelSelector, type ModelOption } from "./ModelSelector";
import { cn } from "@/lib/utils";

export interface Attachment {
  filename: string;
  contentBase64: string;
}

interface ChatInputProps {
  onSend: (content: string, model: string, provider: string, attachments?: Attachment[]) => Promise<void>;
  onCancel?: () => void;
  onModelChange?: (model: string, provider: string) => void;
  agentMode?: boolean;
  onAgentModeChange?: (v: boolean) => void;
  disabled?: boolean;
  sending?: boolean;
}

const MAX_FILE_SIZE_MB = 64;

export function ChatInput({ onSend, onCancel, onModelChange, agentMode, onAgentModeChange, disabled, sending }: ChatInputProps) {
  const [input, setInput] = useState("");
  const [modelOption, setModelOption] = useState<ModelOption | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleModelChange = (id: string, provider: string) => {
    setModelOption({ id, provider });
    onModelChange?.(id, provider);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files?.length) return;
    const maxBytes = MAX_FILE_SIZE_MB * 1024 * 1024;
    for (const file of Array.from(files)) {
      if (file.size > maxBytes) {
        alert(`File "${file.name}" exceeds ${MAX_FILE_SIZE_MB}MB limit.`);
        continue;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const b64 = (reader.result as string).split(",")[1];
        if (b64) setAttachments((a) => [...a, { filename: file.name, contentBase64: b64 }]);
      };
      reader.readAsDataURL(file);
    }
    e.target.value = "";
  };

  const removeAttachment = (idx: number) => {
    setAttachments((a) => a.filter((_, i) => i !== idx));
  };

  const doSend = async () => {
    const text = input.trim();
    if (!text || disabled || !modelOption) return;
    setInput("");
    const toSend = attachments.length ? attachments : undefined;
    setAttachments([]);
    await onSend(text, modelOption.id, modelOption.provider, toSend);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    doSend();
  };

  return (
    <form
      onSubmit={handleSubmit}
      className={cn(
        "flex flex-col gap-3 rounded-[var(--message-bar-radius)] border border-[var(--message-bar-border)] bg-[var(--message-bar-bg)] p-4 shadow-[var(--message-bar-shadow)]"
      )}
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".twbx,.twb,.tdsx,.tflx,.tfl,.hyper,image/*,.txt,.csv,.json,.md,.log"
        className="hidden"
        onChange={handleFileChange}
      />
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {attachments.map((a, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-caption"
            >
              <Paperclip className="h-3 w-3" />
              {a.filename}
              <button
                type="button"
                onClick={() => removeAttachment(i)}
                className="ml-0.5 rounded p-0.5 hover:bg-muted-foreground/20"
                aria-label="Remove"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex min-h-[2.5rem] flex-1 items-start">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              doSend();
            }
          }}
          placeholder="Enter a prompt..."
          disabled={disabled}
          rows={2}
          className="min-h-[2.5rem] w-full resize-none border-0 bg-transparent text-body placeholder:text-muted-foreground outline-none focus:ring-0 disabled:opacity-50"
        />
      </div>
      <div className="flex items-center justify-between gap-2 text-muted-foreground">
        <div className="flex items-center gap-1">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button type="button" variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-foreground" title="Attachments">
                <Plus className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="top">
              <DropdownMenuItem onSelect={() => fileInputRef.current?.click()}>
                <Paperclip className="h-4 w-4" />
                Upload files
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          {onAgentModeChange && (
            <ModeSelector value={agentMode ?? false} onChange={onAgentModeChange} />
          )}
        </div>
        <div className="flex items-center gap-2">
          <ModelSelector value={modelOption} onChange={handleModelChange} />
          {sending && onCancel ? (
            <Button
              type="button"
              size="icon"
              variant="destructive"
              onClick={onCancel}
              title="Stop generating"
            >
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button
              type="submit"
              size="icon"
              disabled={disabled || !input.trim() || !modelOption}
              title={!modelOption ? "Select a model first" : undefined}
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    </form>
  );
}

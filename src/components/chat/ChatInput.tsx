"use client";

import { useEffect, useRef, useState } from "react";
import TurndownService from "turndown";
import { Send, Square, Plus, Paperclip } from "lucide-react";

const turndown = new TurndownService({ headingStyle: "atx", bulletListMarker: "-" });
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pendingSelectionRef = useRef<number | null>(null);

  const findPrevWordBoundary = (text: string, pos: number): number => {
    if (pos <= 0) return 0;
    let i = pos - 1;
    while (i > 0 && /\s/.test(text[i])) i--;
    while (i > 0 && !/\s/.test(text[i - 1])) i--;
    return i;
  };

  const findNextWordBoundary = (text: string, pos: number): number => {
    if (pos >= text.length) return text.length;
    let i = pos;
    while (i < text.length && /\s/.test(text[i])) i++;
    while (i < text.length && !/\s/.test(text[i])) i++;
    return i;
  };

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

  useEffect(() => {
    const pos = pendingSelectionRef.current;
    if (pos != null && textareaRef.current) {
      pendingSelectionRef.current = null;
      textareaRef.current.setSelectionRange(pos, pos);
    }
  }, [input]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const ta = textareaRef.current;
    if (!ta) return;

    if (e.altKey) {
      if (e.key === "ArrowLeft" || e.key === "Backspace") {
        e.preventDefault();
        if (e.key === "ArrowLeft") {
          const pos = findPrevWordBoundary(input, ta.selectionStart);
          ta.setSelectionRange(pos, pos);
        } else {
          const start = findPrevWordBoundary(input, ta.selectionStart);
          const end = ta.selectionStart;
          if (start < end) {
            pendingSelectionRef.current = start;
            setInput(input.slice(0, start) + input.slice(end));
          }
        }
        return;
      }
      if (e.key === "ArrowRight") {
        e.preventDefault();
        const pos = findNextWordBoundary(input, ta.selectionEnd);
        ta.setSelectionRange(pos, pos);
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      doSend();
    }
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const html = e.clipboardData.getData("text/html");
    const plain = e.clipboardData.getData("text/plain");
    // Only convert HTML→markdown when clipboard has rich content (tables, lists, formatting).
    // Skip if the HTML is just browser chrome (e.g. Next.js dev tools portal) or if plain text is sufficient.
    if (!html || !html.includes("</") || html.includes("<nextjs-portal") || html.includes("data-nextjs")) {
      // Let the browser handle the paste normally (plain text)
      return;
    }
    e.preventDefault();
    const md = turndown.turndown(html);
    // If turndown produced something much longer than the plain text (junk HTML),
    // fall back to plain text
    if (plain && md.length > plain.length * 3 && md.length > 200) {
      const ta = textareaRef.current;
      if (!ta) return;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      setInput(input.slice(0, start) + plain + input.slice(end));
      requestAnimationFrame(() => {
        const pos = start + plain.length;
        ta.setSelectionRange(pos, pos);
      });
      return;
    }
    const ta = textareaRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const before = input.slice(0, start);
    const after = input.slice(end);
    setInput(before + md + after);
    requestAnimationFrame(() => {
      const pos = start + md.length;
      ta.setSelectionRange(pos, pos);
    });
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
        accept=".twbx,.twb,.tdsx,.tflx,.tfl,.hyper,image/*,.txt,.csv,.json,.md,.log,.pdf,.docx"
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
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="Enter a prompt..."
          disabled={disabled}
          rows={2}
          className="min-h-[2.5rem] w-full resize-none border-0 bg-transparent text-body placeholder:text-muted-foreground outline-none focus:ring-0 disabled:opacity-50"
        />
      </div>
      <div className="flex items-center justify-between gap-2 text-muted-foreground">
        <div className="flex items-center gap-1">
          <DropdownMenu modal={false}>
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

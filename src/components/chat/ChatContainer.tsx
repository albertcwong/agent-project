"use client";

import { ChatHeader } from "./ChatHeader";
import { ChatMessages } from "./ChatMessages";
import { ChatInput, type Attachment } from "./ChatInput";
import type { ChatMessage } from "@/lib/threads";

interface ChatContainerProps {
  title: string;
  modelName: string;
  messages: ChatMessage[];
  threadId?: string | null;
  pinned?: boolean;
  onPin?: (id: string) => void;
  onRename?: (id: string, currentTitle: string) => void;
  streamingContent?: string | null;
  streamingThought?: string | null;
  stepTimings?: Record<number, { start: number; end?: number }>;
  onSend: (content: string, model: string, provider: string, attachments?: Attachment[]) => Promise<void>;
  onCancel?: () => void;
  onModelChange?: (model: string, provider: string) => void;
  disabled?: boolean;
  sending?: boolean;
  agentMode?: boolean;
  onAgentModeChange?: (v: boolean) => void;
}

export function ChatContainer({
  title,
  modelName,
  messages,
  threadId,
  pinned,
  onPin,
  onRename,
  streamingContent,
  streamingThought,
  stepTimings,
  onSend,
  onCancel,
  onModelChange,
  disabled,
  sending,
  agentMode,
  onAgentModeChange,
}: ChatContainerProps) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <ChatHeader modelName={modelName} title={title} threadId={threadId} pinned={pinned} onPin={onPin} onRename={onRename} />
      <div className="flex min-h-0 flex-1 flex-col bg-[var(--message-bar-area-bg)]">
        <ChatMessages messages={messages} streamingContent={streamingContent} streamingThought={streamingThought} stepTimings={stepTimings} />
        <div className="shrink-0 p-4">
        <ChatInput
        onSend={onSend}
        onCancel={onCancel}
        onModelChange={onModelChange}
        agentMode={agentMode}
        onAgentModeChange={onAgentModeChange}
        disabled={disabled}
        sending={sending}
      />
        </div>
      </div>
    </div>
  );
}

"use client";

import { ChatHeader } from "./ChatHeader";
import { ChatMessages } from "./ChatMessages";
import { ChatInput } from "./ChatInput";
import type { ChatMessage } from "@/lib/threads";

interface ChatContainerProps {
  title: string;
  modelName: string;
  messages: ChatMessage[];
  streamingContent?: string | null;
  streamingThought?: string | null;
  onSend: (content: string, model: string, provider: string) => Promise<void>;
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
  streamingContent,
  streamingThought,
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
      <ChatHeader modelName={modelName} title={title} />
      <ChatMessages messages={messages} streamingContent={streamingContent} streamingThought={streamingThought} />
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
  );
}

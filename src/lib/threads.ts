export interface McpApp {
  resourceUri: string;
  toolName: string;
  result: string;
  serverId: string;
}

export interface FileDownload {
  filename: string;
  contentBase64: string;
}

export interface ChatMessage {
  role: string;
  content: string;
  thought?: string;
  stepTimings?: Record<number, { start: number; end?: number }>;
  toolCalls?: string[];
  apps?: McpApp[];
  downloads?: FileDownload[];
}

export interface Thread {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: number;
  pinned?: boolean;
}

const STORAGE_KEY = "chat-threads";

export function loadThreads(): Thread[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveThreads(threads: Thread[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(threads));
  } catch {
    // ignore
  }
}

export function generateId(): string {
  return crypto.randomUUID();
}

const MCP_CONNECTED_KEY = "mcp-connected-servers";
const MCP_TOKENS_KEY = "mcp-server-tokens";

export function getMcpServerToken(serverId: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(MCP_TOKENS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed[serverId] ?? null;
  } catch {
    return null;
  }
}

export function setMcpServerToken(serverId: string, token: string): void {
  if (typeof window === "undefined") return;
  try {
    const raw = localStorage.getItem(MCP_TOKENS_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    parsed[serverId] = token;
    localStorage.setItem(MCP_TOKENS_KEY, JSON.stringify(parsed));
  } catch {
    // ignore
  }
}

export function removeMcpServerToken(serverId: string): void {
  if (typeof window === "undefined") return;
  try {
    const raw = localStorage.getItem(MCP_TOKENS_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    delete parsed[serverId];
    localStorage.setItem(MCP_TOKENS_KEY, JSON.stringify(parsed));
  } catch {
    // ignore
  }
}

export function getConnectedMcpServers(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(MCP_CONNECTED_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function setConnectedMcpServers(ids: string[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(MCP_CONNECTED_KEY, JSON.stringify(ids));
  } catch {
    // ignore
  }
}

export function getMcpTokens(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(MCP_TOKENS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

const AGENT_STREAMING_KEY = "agent-streaming-enabled";

export function getAgentStreaming(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const raw = localStorage.getItem(AGENT_STREAMING_KEY);
    if (raw === "false") return false;
    return true;
  } catch {
    return true;
  }
}

export function setAgentStreaming(enabled: boolean): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(AGENT_STREAMING_KEY, String(enabled));
  } catch {
    // ignore
  }
}

const WRITE_CONFIRM_SESSION_KEY = "write-confirmation-scope-session";
const WRITE_CONFIRM_FOREVER_KEY = "write-confirmation-scope-forever";

export function getWriteConfirmationScope(): { scope: "session" | "forever" } | null {
  if (typeof window === "undefined") return null;
  try {
    const forever = localStorage.getItem(WRITE_CONFIRM_FOREVER_KEY);
    if (forever === "forever") return { scope: "forever" };
    const session = sessionStorage.getItem(WRITE_CONFIRM_SESSION_KEY);
    if (session === "session") return { scope: "session" };
    return null;
  } catch {
    return null;
  }
}

export function setWriteConfirmationScope(scope: "session" | "forever"): void {
  if (typeof window === "undefined") return;
  try {
    if (scope === "forever") {
      localStorage.setItem(WRITE_CONFIRM_FOREVER_KEY, "forever");
    } else {
      sessionStorage.setItem(WRITE_CONFIRM_SESSION_KEY, "session");
    }
  } catch {
    // ignore
  }
}

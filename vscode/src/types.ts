export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
  timestamp: number;
}

export type LLMProviderType = "litellm" | "openai" | "anthropic";

export interface LLMProvider {
  streamChat(
    messages: Array<{ role: string; content: string }>,
    model: string,
    signal?: AbortSignal
  ): AsyncGenerator<string, void, unknown>;
}

export const PROVIDER_MODELS: Record<LLMProviderType, Array<{ value: string; label: string }>> = {
  litellm: [
    { value: "claude-sonnet", label: "Claude Sonnet" },
    { value: "claude-haiku", label: "Claude Haiku" },
    { value: "claude-opus", label: "Claude Opus" },
    { value: "gemini-pro", label: "Gemini Pro" },
    { value: "gemini-flash", label: "Gemini Flash" },
    { value: "qwen-coder-32b", label: "Qwen Coder 32B" },
    { value: "qwen-7b", label: "Qwen 7B" },
  ],
  openai: [
    { value: "gpt-4o", label: "GPT-4o" },
    { value: "gpt-4o-mini", label: "GPT-4o Mini" },
    { value: "gpt-4.1", label: "GPT-4.1" },
    { value: "gpt-4.1-mini", label: "GPT-4.1 Mini" },
    { value: "gpt-4.1-nano", label: "GPT-4.1 Nano" },
    { value: "o3", label: "o3" },
    { value: "o4-mini", label: "o4-mini" },
  ],
  anthropic: [
    { value: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
    { value: "claude-opus-4-6", label: "Claude Opus 4.6" },
    { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
  ],
};

/**
 * Flat settings interface for VS Code.
 * All settings come from vscode.workspace.getConfiguration().
 * No device/synced split needed (that was for Obsidian Sync).
 */
export interface HapaxSettings {
  provider: LLMProviderType;
  litellmUrl: string;
  apiKey: string;
  model: string;
  maxTokens: number;
  qdrantUrl: string;
  qdrantCollection: string;
  ollamaUrl: string;
  maxContextLength: number;
  systemPrompt: string;
}

/**
 * Providers sanctioned for use on corporate/work devices.
 * LiteLLM (localhost proxy) is excluded — it requires home network access
 * and routes through infrastructure not visible to corporate security tooling.
 */
export const WORK_VAULT_PROVIDERS: LLMProviderType[] = ["openai", "anthropic"];

export interface QdrantSearchResult {
  id: string | number;
  score: number;
  payload: Record<string, unknown>;
}

export interface QdrantSearchResponse {
  result: QdrantSearchResult[];
  status: string;
  time: number;
}

export interface StreamChoice {
  delta: { content?: string; role?: string };
  index: number;
  finish_reason: string | null;
}

export interface StreamChunk {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: StreamChoice[];
}

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
  timestamp: number;
}

export type LLMProviderType = "litellm";

export interface LLMProvider {
  streamChat(
    messages: Array<{ role: string; content: string }>,
    model: string,
    signal?: AbortSignal
  ): AsyncGenerator<string, void, unknown>;
}

export const PROVIDER_MODELS: Record<LLMProviderType, Array<{ value: string; label: string }>> = {
  litellm: [
    { value: "local-fast", label: "Local Fast" },
    { value: "gemini-pro", label: "Gemini Pro" },
    { value: "gemini-flash", label: "Gemini Flash" },
    { value: "coding", label: "Coding" },
    { value: "reasoning", label: "Reasoning" },
    { value: "qwen-coder-32b", label: "Qwen Coder 32B" },
    { value: "qwen-7b", label: "Qwen 7B" },
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
 * Work vault model calls must route through the local gateway boundary.
 * Direct provider settings are intentionally absent; work-vault enforcement
 * must not silently fall through to them.
 */
export const WORK_VAULT_PROVIDERS: LLMProviderType[] = ["litellm"];

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

import type { LLMProvider } from "../types";

const ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_VERSION = "2023-06-01";

export class AnthropicProvider implements LLMProvider {
  constructor(private apiKey: string, private maxTokens: number = 4096) {}

  async *streamChat(
    messages: Array<{ role: string; content: string }>,
    model: string,
    signal?: AbortSignal
  ): AsyncGenerator<string, void, unknown> {
    // Anthropic expects system as a top-level param, not in messages
    let systemPrompt: string | undefined;
    const filteredMessages: Array<{ role: string; content: string }> = [];
    for (const msg of messages) {
      if (msg.role === "system") {
        systemPrompt = (systemPrompt ? systemPrompt + "\n\n" : "") + msg.content;
      } else {
        filteredMessages.push(msg);
      }
    }

    const body: Record<string, unknown> = {
      model,
      messages: filteredMessages,
      max_tokens: this.maxTokens,
    };
    if (systemPrompt) {
      body.system = systemPrompt;
    }

    const headers = {
      "Content-Type": "application/json",
      "x-api-key": this.apiKey,
      "anthropic-version": ANTHROPIC_VERSION,
    };

    const timeout = AbortSignal.timeout(60_000);
    const combinedSignal = signal
      ? AbortSignal.any([signal, timeout])
      : timeout;

    const response = await fetch(ANTHROPIC_API_URL, {
      method: "POST",
      headers,
      body: JSON.stringify({ ...body, stream: true }),
      signal: combinedSignal,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Anthropic request failed (${response.status}): ${errorText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error("No response body");

    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith("data: ")) continue;
          const data = trimmed.slice(6);

          try {
            const parsed = JSON.parse(data);
            if (parsed.type === "content_block_delta" &&
                parsed.delta?.type === "text_delta" &&
                parsed.delta?.text) {
              yield parsed.delta.text;
            }
            if (parsed.type === "message_stop") return;
          } catch {
            // Skip malformed JSON
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }
}

import type { HapaxSettings } from "./types";
import { createProvider } from "./providers";

export class LLMClient {
  private settings: HapaxSettings;

  constructor(settings: HapaxSettings) {
    this.settings = settings;
  }

  updateSettings(settings: HapaxSettings): void {
    this.settings = settings;
  }

  async *streamChat(
    messages: Array<{ role: string; content: string }>,
    signal?: AbortSignal
  ): AsyncGenerator<string, void, unknown> {
    const provider = createProvider(this.settings);
    yield* provider.streamChat(messages, this.settings.model, signal);
  }
}

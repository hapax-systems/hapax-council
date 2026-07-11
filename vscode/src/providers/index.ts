import type { HapaxSettings, LLMProvider } from "../types";
import { OpenAICompatibleProvider } from "./openai-compatible";

export function createProvider(settings: HapaxSettings): LLMProvider {
  switch (settings.provider) {
    case "litellm":
    default:
      return new OpenAICompatibleProvider(
        settings.litellmUrl,
        settings.apiKey
      );
  }
}

export { OpenAICompatibleProvider } from "./openai-compatible";

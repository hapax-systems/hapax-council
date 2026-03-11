import type { HapaxSettings, LLMProvider } from "../types";
import { OpenAICompatibleProvider } from "./openai-compatible";
import { AnthropicProvider } from "./anthropic";

export function createProvider(settings: HapaxSettings): LLMProvider {
  switch (settings.provider) {
    case "openai":
      return new OpenAICompatibleProvider(
        "https://api.openai.com",
        settings.apiKey
      );
    case "anthropic":
      return new AnthropicProvider(settings.apiKey, settings.maxTokens);
    case "litellm":
    default:
      return new OpenAICompatibleProvider(
        settings.litellmUrl,
        settings.apiKey
      );
  }
}

export { OpenAICompatibleProvider } from "./openai-compatible";
export { AnthropicProvider } from "./anthropic";

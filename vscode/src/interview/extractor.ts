/**
 * LLM structured extraction for interview answers.
 *
 * Sends user answer + extraction prompt to the configured LLM provider.
 * Extracts structured JSON matching the requirement's schema.
 *
 * Respects mg-boundary-001/002 — extraction only, never generates
 * management advice or feedback language.
 */
import type { HapaxSettings } from "../types";
import { createProvider } from "../providers";

export interface ExtractionResult {
  data: Record<string, unknown>;
  incomplete: boolean;
  raw: string;
}

/** Extract JSON string from LLM response that may contain fences or surrounding text. */
function extractJson(raw: string): string {
  // Try fenced code block first
  const fenceMatch = raw.match(/```json?\s*\n?([\s\S]*?)\n?\s*```/);
  if (fenceMatch) return fenceMatch[1].trim();

  // Find the outermost JSON object or array
  const firstBrace = raw.indexOf("{");
  const firstBracket = raw.indexOf("[");
  const start = firstBrace >= 0 && (firstBracket < 0 || firstBrace < firstBracket)
    ? firstBrace : firstBracket;
  if (start >= 0) {
    const close = start === firstBrace ? "}" : "]";
    const lastClose = raw.lastIndexOf(close);
    if (lastClose > start) return raw.slice(start, lastClose + 1);
  }

  // Fallback: return trimmed raw
  return raw.trim();
}

/**
 * Extract structured data from a user's interview answer.
 *
 * @param answer - The user's natural language answer
 * @param extractionPrompt - The prompt describing what to extract
 * @param settings - LLM provider settings
 * @returns Parsed extraction result, or null on failure
 */
export async function extractFromAnswer(
  answer: string,
  extractionPrompt: string,
  settings: HapaxSettings
): Promise<ExtractionResult | { error: string }> {
  const provider = createProvider(settings);

  const messages = [
    {
      role: "system",
      content: `You are a structured data extractor. ${extractionPrompt}

CRITICAL RULES:
- Return ONLY valid JSON, no markdown fences, no explanation
- Only extract what was explicitly stated
- Do not infer, guess, or add information
- If the answer is incomplete, set "incomplete": true
- Never generate feedback language, coaching advice, or management recommendations`,
    },
    {
      role: "user",
      content: answer,
    },
  ];

  let fullResponse = "";
  try {
    const signal = AbortSignal.timeout(30_000);
    for await (const chunk of provider.streamChat(messages, settings.model, signal)) {
      fullResponse += chunk;
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error("Extraction failed:", msg);
    return { error: `LLM call failed: ${msg}` };
  }

  // Parse JSON from response — extract from fences or find raw JSON
  const jsonStr = extractJson(fullResponse);

  try {
    const parsed = JSON.parse(jsonStr);
    console.debug("Hapax: extraction result:", JSON.stringify(parsed));
    return {
      data: parsed,
      incomplete: parsed.incomplete === true,
      raw: fullResponse,
    };
  } catch {
    console.error("Failed to parse extraction JSON:", fullResponse);
    return { error: "Could not parse structured data from LLM response. Try rephrasing your answer." };
  }
}

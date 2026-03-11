import * as vscode from "vscode";
import { execFileSync } from "child_process";
import type { HapaxSettings, LLMProviderType } from "./types";
import { WORK_VAULT_PROVIDERS, PROVIDER_MODELS } from "./types";

/** Map provider to the pass path and env var that holds its key. */
const PROVIDER_KEY_SOURCES: Record<LLMProviderType, { env: string; pass: string }> = {
  litellm: { env: "LITELLM_API_KEY", pass: "litellm/master-key" },
  anthropic: { env: "ANTHROPIC_API_KEY", pass: "api/anthropic" },
  openai: { env: "OPENAI_API_KEY", pass: "api/openai" },
};

/**
 * Resolve API key: VS Code setting > environment variable > pass store.
 * Returns empty string if all sources fail (work machine without pass).
 */
function resolveApiKey(provider: LLMProviderType, explicitKey: string): string {
  if (explicitKey) return explicitKey;

  const sources = PROVIDER_KEY_SOURCES[provider];
  if (!sources) return "";

  // Try environment variable (set by direnv)
  const envVal = process.env[sources.env];
  if (envVal) return envVal;

  // Try pass (GPG password store)
  try {
    return execFileSync("pass", ["show", sources.pass], { timeout: 5000 }).toString().trim();
  } catch {
    return "";
  }
}

/** Read all Hapax settings from VS Code configuration. */
export function getSettings(): HapaxSettings {
  const config = vscode.workspace.getConfiguration("hapax");
  const provider = config.get<LLMProviderType>("provider", "litellm");
  const explicitKey = config.get<string>("apiKey", "");
  return {
    provider,
    apiKey: resolveApiKey(provider, explicitKey),
    model: config.get<string>("model", "claude-sonnet"),
    litellmUrl: config.get<string>("litellmUrl", "http://localhost:4000"),
    qdrantUrl: config.get<string>("qdrantUrl", "http://localhost:6333"),
    qdrantCollection: config.get<string>("qdrantCollection", "documents"),
    ollamaUrl: config.get<string>("ollamaUrl", "http://localhost:11434"),
    maxTokens: config.get<number>("maxTokens", 4096),
    maxContextLength: config.get<number>("maxContextLength", 8000),
    systemPrompt: config.get<string>(
      "systemPrompt",
      "You are Hapax, an assistant embedded in the operator's vault \u2014 one interface within a three-tier autonomous agent system.\n\nThe operator has ADHD and autism. This shapes how you communicate:\n- Lead with the actionable point, not context-setting\n- Use structured output (bullets, headers) over prose\n- Be direct and specific \u2014 no hedging or filler\n- Support task initiation: break large requests into concrete first steps\n- State epistemic confidence. Prefer \"I don't know\" over speculation\n\nYou have access to the current note as context and can search the knowledge base via Qdrant. Be concise and actionable."
    ),
  };
}

/**
 * Enforce provider allowlist for work vaults on corporate networks.
 *
 * The work vault exists on both home and corporate machines (synced via git).
 * At home, LiteLLM is available and should be used. At work, LiteLLM is
 * unreachable and only sanctioned providers (OpenAI, Anthropic) are allowed.
 *
 * Detection: if LiteLLM is reachable, we're at home — no restriction needed.
 * If unreachable and provider is litellm, switch to a sanctioned provider.
 */
export async function enforceWorkVaultProvider(
  isWork: boolean
): Promise<void> {
  if (!isWork) return;

  const config = vscode.workspace.getConfiguration("hapax");
  const provider = config.get<LLMProviderType>("provider", "litellm");

  // Only enforce when using a non-sanctioned provider
  if (WORK_VAULT_PROVIDERS.includes(provider)) return;

  // Check if LiteLLM is reachable (home network indicator)
  const litellmUrl = config.get<string>("litellmUrl", "http://localhost:4000");
  try {
    const resp = await fetch(`${litellmUrl}/health/liveliness`, { signal: AbortSignal.timeout(2000) });
    if (resp.ok) return; // LiteLLM reachable — we're at home, no restriction
  } catch {
    // Unreachable — we're on corporate network
  }

  const corrected = WORK_VAULT_PROVIDERS[0];
  await config.update(
    "provider",
    corrected,
    vscode.ConfigurationTarget.Workspace
  );

  const models = PROVIDER_MODELS[corrected];
  if (models?.length) {
    await config.update(
      "model",
      models[0].value,
      vscode.ConfigurationTarget.Workspace
    );
  }

  vscode.window.showWarningMessage(
    `Hapax: LiteLLM unreachable on corporate network. Switched to "${corrected}".`
  );
}

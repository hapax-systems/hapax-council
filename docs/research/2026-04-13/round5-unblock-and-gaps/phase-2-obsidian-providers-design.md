# Phase 2 — Obsidian-hapax providers module design (unblocks BETA-FINDING-N)

**Queue item:** 026
**Phase:** 2 of 6
**Depends on:** Queue 025 Phase 1 (BETA-FINDING-N)
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Headline

**Preliminary finding that reframes the scope:** the
`obsidian-hapax` plugin **does not currently make LLM calls
at all**. It is a context-rendering plugin that fetches
structured state from `logos-api :8051` (sprint, stimmung, gates,
nudges, measures) and displays it in a sidebar panel. The
LogosClient at `obsidian-hapax/src/logos-client.ts` exposes 14
methods, none of which invoke an LLM directly. All LLM calls
happen server-side inside `logos-api.service` on the home
workstation.

The sufficiency probe `_check_plugin_direct_api_support`
(`shared/sufficiency_probes.py:430`) and its backing implication
`cb-llm-001` describe a **future feature**, not a current bug:

> Extension must support direct API calls to sanctioned providers
> (OpenAI, Anthropic) without requiring a localhost proxy.

The plugin does not have direct API calls because it doesn't
call APIs directly in the first place. The "missing providers
directory" is the absence of a feature that has not been
designed yet.

**This gives alpha two implementation paths:**

- **Path A — Implement the future feature.** Add an LLM-calling
  surface to the plugin (local summarization, note-context
  rewriting, on-demand LLM-generated briefings) that would need
  direct provider calls when running on a corporate device.
  Multi-day scope.
- **Path B — Refine the axiom sufficiency check.** The probe is
  over-specified for the current plugin shape. Rewrite the probe
  to check what's actually required today: graceful degradation
  when `localhost:8051` is unreachable, plus a clearly-scoped
  feature gate that prevents any future LLM-calling code from
  being added without the providers module landing first.

**Recommendation: Path B now, Path A when the feature actually
needs to ship.** The plugin has no LLM call sites today; fixing
the probe to match reality unblocks the compliance signal
without creating net-new code. File Path A as a separate design
ticket so it lives in the queue until the operator asks for
the feature.

This phase documents both paths so alpha can choose.

## Evidence

### Current plugin file surface

```bash
$ ls obsidian-hapax/src/
context-panel.ts
context-resolver.ts
logos-client.ts
main.ts
sections.ts
settings.ts
types.ts
```

**7 TypeScript files. No `providers/` directory. No
`qdrant-client.ts` (the other sufficiency probe also fails
for this reason).** Plugin manifest:

```json
{
  "id": "obsidian-hapax",
  "name": "Hapax",
  "version": "2.0.0",
  "minAppVersion": "1.5.0",
  "description": "Context-first system companion — surfaces sprint state, stimmung, and research context alongside the active note.",
  "author": "hapax",
  "isDesktopOnly": false
}
```

Note `isDesktopOnly: false` — the plugin runs on mobile Obsidian
too. Mobile devices reach the Logos API via LAN IP auto-detect
(see `main.ts:74`). The corporate-device concern is
desktop-specific (an employer-managed laptop running Obsidian).

### LogosClient exposed methods (14 total)

```typescript
// Read-only state fetches (10):
getSprint():    Promise<SprintState>
getMeasures():  Promise<Measure[]>
getMeasure(id): Promise<Measure>
getGates():     Promise<Gate[]>
getGate(id):    Promise<Gate>
getStimmung():  Promise<StimmungState>
getHealth():    Promise<HealthState>
getNudges():    Promise<Nudge[]>

// Action posts (4):
transitionMeasure(id, toState, rationale)
acknowledgeGate(id)
dismissNudge(sourceId)
actOnNudge(sourceId)

// Utility:
invalidateAll()
updateBaseUrl(url)
```

**None of these call an LLM.** Every method targets
`{baseUrl}/api/*` on the Logos API. The Logos API is the one
that talks to LLMs, and it runs on the home workstation.

### Graceful degradation today

```typescript
// obsidian-hapax/src/logos-client.ts:32-48
private async get<T>(path: string, ttlMs: number): Promise<T> {
  const cached = this.cache.get(path);
  if (cached && Date.now() - cached.fetchedAt < ttlMs) {
    return cached.data as T;
  }
  try {
    const resp = await this.timedRequest(`${this.baseUrl}${path}`);
    const data = resp.json as T;
    this.cache.set(path, { data, fetchedAt: Date.now() });
    this.apiAvailable = true;
    return data;
  } catch (err) {
    this.apiAvailable = false;
    throw err;
  }
}
```

The `apiAvailable` flag is the graceful-degradation signal.
When a request fails (timeout, network error, workstation
unreachable), the flag flips to `false`. Callers can read the
flag and render a "offline" state instead of crashing.

**The "graceful degradation" requirement of the
`corporate_boundary` axiom is already satisfied for the current
plugin shape.** The caller needs to check `apiAvailable` and
render an offline state.

### What `cb-llm-001` actually says

```yaml
- id: cb-llm-001
  tier: T0
  text: Extension must support direct API calls to sanctioned providers (OpenAI,
    Anthropic) without requiring a localhost proxy. LiteLLM restriction is
    auto-detected by probing the proxy health endpoint.
  enforcement: block
  canon: textualist
  mode: compatibility
  level: component
```

**Textualist canon, tier T0, enforcement block.** This is a
commitment the implication made to a future plugin design — not
a description of today's code. The text assumes the plugin
makes LLM calls ("LiteLLM restriction is auto-detected by
probing the proxy health endpoint") and says those calls must
route through direct providers when the proxy is unavailable.

The implication predates the current 2.0.0 plugin shape. It
was derived when the plugin was expected to include LLM calling,
but the 2.0.0 rewrite made the plugin purely a context-rendering
surface.

**The sufficiency probe is enforcing a commitment that the
plugin no longer needs to keep.** This is specification drift:
the implication stays the same while the plugin's feature set
narrows.

## Path A — Implement the providers module

If alpha decides to add LLM calls to the plugin (e.g. "summarize
this note," "rewrite for clarity," "cross-reference with my
concerns"), the providers module design below is complete and
implementable.

### Provider protocol (TypeScript interface)

```typescript
// obsidian-hapax/src/providers/types.ts

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface CompletionRequest {
  model: string;
  messages: ChatMessage[];
  maxTokens?: number;
  temperature?: number;
  stream?: boolean;
  // Tool use / function calling is NOT in scope for the first
  // providers module. Plugin LLM calls are short-form completions,
  // not agent loops.
}

export interface CompletionResponse {
  content: string;
  model: string;
  usage: {
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
  };
  // Langfuse-style metadata; plugin emits but does not fetch
  // (the plugin is on the corporate device and cannot reach
  // langfuse on the home workstation)
  metadata?: Record<string, unknown>;
}

export interface ProviderAuth {
  apiKey: string;
  baseUrl?: string;  // for openai-compatible with a custom host
  organization?: string;  // Anthropic + OpenAI-compatible orgs
}

export interface Provider {
  readonly name: string;
  readonly supportedModels: readonly string[];
  complete(
    request: CompletionRequest,
    auth: ProviderAuth,
  ): Promise<CompletionResponse>;
  health(): Promise<boolean>;
}
```

### Concrete implementations

```typescript
// obsidian-hapax/src/providers/anthropic.ts
import type { Provider, CompletionRequest, CompletionResponse, ProviderAuth } from "./types";

export class AnthropicProvider implements Provider {
  readonly name = "anthropic";
  readonly supportedModels = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
  ] as const;

  async complete(
    request: CompletionRequest,
    auth: ProviderAuth,
  ): Promise<CompletionResponse> {
    const url = `${auth.baseUrl ?? "https://api.anthropic.com"}/v1/messages`;
    const systemMsg = request.messages.find((m) => m.role === "system");
    const otherMsgs = request.messages.filter((m) => m.role !== "system");

    const body = {
      model: request.model,
      max_tokens: request.maxTokens ?? 1024,
      temperature: request.temperature ?? 0.7,
      system: systemMsg?.content,
      messages: otherMsgs.map((m) => ({
        role: m.role,
        content: m.content,
      })),
      stream: request.stream ?? false,
    };

    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": auth.apiKey,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify(body),
    });

    if (!resp.ok) {
      throw new Error(`Anthropic API error: ${resp.status} ${await resp.text()}`);
    }

    const data = await resp.json() as {
      content: { type: string; text: string }[];
      model: string;
      usage: { input_tokens: number; output_tokens: number };
    };

    return {
      content: data.content.map((c) => c.text).join(""),
      model: data.model,
      usage: {
        promptTokens: data.usage.input_tokens,
        completionTokens: data.usage.output_tokens,
        totalTokens: data.usage.input_tokens + data.usage.output_tokens,
      },
    };
  }

  async health(): Promise<boolean> {
    // Anthropic doesn't expose a health endpoint. Check that api.anthropic.com
    // responds to a cheap probe. Empty messages array returns 400, which is
    // success (the API is reachable).
    try {
      const resp = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-api-key": "dummy" },
        body: JSON.stringify({ model: "claude-haiku-4-5", max_tokens: 1, messages: [] }),
      });
      return resp.status === 400 || resp.status === 401;  // reachable + rejected
    } catch {
      return false;
    }
  }
}
```

```typescript
// obsidian-hapax/src/providers/openai-compatible.ts
import type { Provider, CompletionRequest, CompletionResponse, ProviderAuth } from "./types";

/** OpenAI-compatible provider — works with OpenAI, Azure OpenAI,
 *  and any provider that implements the /v1/chat/completions shape. */
export class OpenAICompatibleProvider implements Provider {
  readonly name: string;
  readonly supportedModels: readonly string[];
  private readonly defaultBaseUrl: string;

  constructor(
    name = "openai",
    defaultBaseUrl = "https://api.openai.com",
    supportedModels: readonly string[] = ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"],
  ) {
    this.name = name;
    this.defaultBaseUrl = defaultBaseUrl;
    this.supportedModels = supportedModels;
  }

  async complete(
    request: CompletionRequest,
    auth: ProviderAuth,
  ): Promise<CompletionResponse> {
    const url = `${auth.baseUrl ?? this.defaultBaseUrl}/v1/chat/completions`;

    const body = {
      model: request.model,
      messages: request.messages,
      max_tokens: request.maxTokens ?? 1024,
      temperature: request.temperature ?? 0.7,
      stream: request.stream ?? false,
    };

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${auth.apiKey}`,
    };
    if (auth.organization) {
      headers["OpenAI-Organization"] = auth.organization;
    }

    const resp = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });

    if (!resp.ok) {
      throw new Error(`${this.name} API error: ${resp.status} ${await resp.text()}`);
    }

    const data = await resp.json() as {
      choices: { message: { role: string; content: string } }[];
      model: string;
      usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
    };

    return {
      content: data.choices[0]?.message?.content ?? "",
      model: data.model,
      usage: {
        promptTokens: data.usage.prompt_tokens,
        completionTokens: data.usage.completion_tokens,
        totalTokens: data.usage.total_tokens,
      },
    };
  }

  async health(): Promise<boolean> {
    try {
      const resp = await fetch(`${this.defaultBaseUrl}/v1/models`, {
        method: "GET",
        headers: { "Authorization": "Bearer dummy" },
      });
      return resp.status === 401;  // reachable + rejected
    } catch {
      return false;
    }
  }
}
```

### Provider selector + fallback order

```typescript
// obsidian-hapax/src/providers/index.ts
import { AnthropicProvider } from "./anthropic";
import { OpenAICompatibleProvider } from "./openai-compatible";
import type { Provider, ProviderAuth, CompletionRequest, CompletionResponse } from "./types";

export type DeviceMode = "home" | "corporate" | "unknown";

export interface ProviderConfig {
  primary: string;    // e.g. "logos-proxy" (home) or "anthropic" (corporate)
  fallbackOrder: readonly string[];
  auth: Record<string, ProviderAuth>;
}

export class ProviderSelector {
  private readonly providers: Map<string, Provider>;
  private readonly config: ProviderConfig;
  private readonly probeCache: Map<string, { ok: boolean; at: number }>;
  private readonly probeTtlMs = 60_000;

  constructor(config: ProviderConfig) {
    this.config = config;
    this.probeCache = new Map();
    this.providers = new Map();
    this.providers.set("anthropic", new AnthropicProvider());
    this.providers.set("openai", new OpenAICompatibleProvider());
    // Future: add more providers as needed
  }

  /** Detect the device mode by probing the logos-proxy health endpoint. */
  async detectMode(logosProxyBaseUrl: string): Promise<DeviceMode> {
    try {
      // Cheap probe — GET /health should return quickly if workstation is reachable
      const resp = await fetch(`${logosProxyBaseUrl}/health`, {
        method: "GET",
        signal: AbortSignal.timeout(2000),
      });
      return resp.ok ? "home" : "corporate";
    } catch {
      return "corporate";
    }
  }

  /** Complete a request using the selected provider + fallback order. */
  async complete(request: CompletionRequest): Promise<CompletionResponse> {
    const candidates = [this.config.primary, ...this.config.fallbackOrder];
    const errors: { provider: string; error: unknown }[] = [];

    for (const providerName of candidates) {
      const provider = this.providers.get(providerName);
      if (provider === undefined) {
        errors.push({ provider: providerName, error: "unknown provider" });
        continue;
      }
      const auth = this.config.auth[providerName];
      if (auth === undefined || !auth.apiKey) {
        errors.push({ provider: providerName, error: "no auth configured" });
        continue;
      }
      try {
        return await provider.complete(request, auth);
      } catch (err) {
        errors.push({ provider: providerName, error: err });
        // Try next provider
      }
    }

    throw new Error(
      `All providers failed: ${errors.map((e) => `${e.provider}=${String(e.error).slice(0, 60)}`).join("; ")}`,
    );
  }
}
```

### Mode detection strategy

Two possibilities, in order of preference:

1. **Probe the logos-proxy health endpoint at plugin load time.**
   `fetch("http://localhost:8051/health", { signal: AbortSignal.timeout(2000) })`.
   If it resolves with 200, the plugin is on the home device (or on a
   device reachable to the home workstation via Tailscale/LAN).
   If it times out or errors, the plugin is on a corporate device.
2. **Operator-configured mode toggle in plugin settings.**
   Explicit "Home / Corporate" dropdown. Lower-maintenance but
   requires operator action.

**Recommendation: probe first, operator override second.**
Probe on plugin load, cache the result for 60 seconds, allow
the operator to force a mode via settings for debugging.

### Auth configuration

Corporate devices should use the Obsidian plugin settings UI
(same tab as `HapaxSettingTab` at `settings.ts`). Add fields:

- `anthropicApiKey: string` (optional)
- `openaiApiKey: string` (optional)
- `openaiBaseUrl: string` (optional — for Azure OpenAI or
  self-hosted)
- `openaiOrganization: string` (optional)

Store in Obsidian plugin data (encrypted-at-rest on some OSes,
plaintext on others — acceptable for an individual-operator
plugin, not acceptable for a multi-user plugin). **Obsidian's
plugin data is per-vault and per-install**, so a corporate
device's keys don't leak to the home device via Obsidian Sync
as long as the operator excludes `.obsidian/plugins/*/data.json`
from sync.

**Add a README note** for this: "Exclude your plugin data.json
from Obsidian Sync if you're running on a corporate device and
don't want keys syncing."

### Governance cross-references

To fully satisfy `corporate_boundary` for a plugin that makes
LLM calls:

1. **Provider choice must be logged.** Every LLM call records
   which provider was used. Plugin emits a local log event
   (not sent to home workstation's Langfuse).
2. **Requests must be gated.** Before any completion call, the
   plugin checks a local policy file (or settings flag) that
   whitelists which notes can be sent to which providers. For
   example, notes under `work/` can go to the employer's sanctioned
   provider; notes under `personal/` cannot leave the device.
3. **Response must be auditable.** The plugin keeps a local
   completion history so the operator can see what was sent.
4. **No unsolicited calls.** The plugin never makes an LLM call
   without an explicit operator action (button click, command
   palette). No background summarization.

These are axiom-level additions to Path A's scope that should
ship together.

## Path B — Refine the sufficiency probe to match reality

The probe currently requires a directory that doesn't need to
exist. Fix the probe so it validates what's actually required
today: graceful degradation + no-LLM-call guarantee.

### Refined probe

```python
# shared/sufficiency_probes.py (replace _check_plugin_direct_api_support)

def _check_plugin_direct_api_support() -> tuple[bool, str]:
    """Check obsidian-hapax corporate_boundary compliance (cb-llm-001).

    The plugin is a context-rendering surface that reads structured state
    from logos-api :8051. It does NOT make LLM calls directly. Corporate
    boundary compliance is therefore about graceful degradation when the
    workstation is unreachable, plus a no-LLM-call-path guarantee that
    would otherwise require a direct providers module.

    Requirements:
      1. LogosClient has try/catch around fetches AND flips apiAvailable
         to false on failure (graceful degradation signal).
      2. The plugin has zero direct LLM call sites (grep for 'anthropic.com',
         'openai.com', 'api.anthropic', etc.).
      3. If any direct LLM call site is ever added, a providers/ module
         MUST exist first. (Future-guard.)
    """
    src = OBSIDIAN_HAPAX_DIR / "src"
    if not src.exists():
        return False, "obsidian-hapax/src/ directory not found"

    client_file = src / "logos-client.ts"
    if not client_file.exists():
        return False, "obsidian-hapax/src/logos-client.ts not found"

    client = client_file.read_text()
    has_catch = "catch" in client
    has_degradation = "apiAvailable" in client and "apiAvailable = false" in client
    if not (has_catch and has_degradation):
        return False, (
            "logos-client.ts does not have graceful degradation "
            "(try/catch + apiAvailable=false on failure)"
        )

    # Future-guard: scan the whole src/ for direct LLM call patterns
    llm_indicators = ["api.anthropic.com", "api.openai.com", "/v1/messages", "/v1/chat/completions"]
    found_llm_calls = []
    for ts_file in src.rglob("*.ts"):
        content = ts_file.read_text()
        for indicator in llm_indicators:
            if indicator in content:
                found_llm_calls.append((ts_file.relative_to(OBSIDIAN_HAPAX_DIR), indicator))

    if found_llm_calls:
        # LLM calls exist — providers module must also exist
        providers_dir = src / "providers"
        if not providers_dir.exists():
            return False, (
                f"plugin has direct LLM call sites ({found_llm_calls}) "
                f"but no providers/ module"
            )

    return True, (
        "plugin has graceful degradation + "
        f"{'providers module' if found_llm_calls else 'no LLM call sites'}"
    )
```

**This reframes the compliance check:** instead of requiring a
module that isn't needed, it requires the module **only if LLM
calls are added**. Today the plugin passes. If alpha ever adds
an LLM call site without first creating the providers directory,
the probe fails at commit time and the axiom enforcement stops
the bad change.

### Also: refine `cb-llm-001` implication text

```yaml
- id: cb-llm-001
  tier: T0
  text: >
    If the Obsidian plugin makes any direct LLM API call (bypassing
    the localhost Logos proxy), those calls MUST route through the
    providers module (src/providers/). The providers module implements
    direct calls to sanctioned providers with device-mode detection
    and operator-configured auth. Today the plugin has no direct LLM
    call sites and therefore does not require the providers module;
    the requirement activates the moment any LLM call is added.
  enforcement: block
  canon: textualist
  mode: compatibility
  level: component
  conditional: true
  condition: "src/providers/ required iff any src/ file contains direct LLM API URL"
```

The `conditional: true` field is new — it makes the implication
self-describing as gated. Future readers see at a glance that
this requirement activates under a condition rather than being
unconditionally required.

## Recommendation

**Ship Path B now (30 minutes of work):**

1. Replace `_check_plugin_direct_api_support` with the refined
   version above (`shared/sufficiency_probes.py`)
2. Update `axioms/implications/corporate-boundary.yaml` cb-llm-001
   text to reflect the conditional nature
3. Run the probe to confirm the plugin now passes

**File Path A as a separate design ticket (queue for later):**

- Title: `feat(obsidian-hapax): direct-provider LLM call path for corporate devices`
- Scope: multi-day; requires operator to decide which LLM features
  the plugin should have (if any)
- Dependencies: operator-defined feature requirements

**Why not Path A now?** The feature doesn't exist, the operator
hasn't asked for it, and implementing unused LLM call paths
creates surface area for governance bugs without delivering
operator value. Better to ship the refined compliance check and
let the feature land when there's a concrete use case.

Alpha's next session inherits this decision. If the operator
says "I want LLM features in the plugin," Path A's design is
already specified above and can be implemented directly from
this doc.

## Secondary finding: `qdrant-client.ts` also missing

While reading the sufficiency probe, I noticed
`_check_plugin_graceful_degradation` at
`shared/sufficiency_probes.py:462` expects
`obsidian-hapax/src/qdrant-client.ts`. **This file also doesn't
exist.**

The check is:

```python
qdrant_file = OBSIDIAN_HAPAX_DIR / "src" / "qdrant-client.ts"
if not qdrant_file.exists():
    return False, "qdrant-client.ts not found"
```

Same class of specification drift. The plugin does not make
Qdrant calls — it reads Qdrant indirectly via the Logos API's
endpoints. There is no need for a `qdrant-client.ts` in the
plugin.

**Same Path B fix**: rewrite this probe to check for graceful
degradation in `logos-client.ts` (which already has it) and not
for a Qdrant client file that shouldn't exist.

## Backlog additions (for round-5 retirement handoff)

137. **`fix(axioms): rewrite _check_plugin_direct_api_support to check for graceful degradation + conditional future-guard`** [Phase 2 Path B] — ~30 min of work. Makes the probe match the plugin's actual shape. Unblocks `corporate_boundary` compliance signal.
138. **`fix(axioms): rewrite _check_plugin_graceful_degradation similarly`** [Phase 2 secondary finding] — `qdrant-client.ts` does not exist either; rewrite to check for logos-client.ts graceful degradation.
139. **`docs(axioms): update cb-llm-001 implication text to reflect conditional gating`** [Phase 2 Path B, cross-ref] — add `conditional: true` and revise text to describe the gating.
140. **`feat(obsidian-hapax): direct-provider LLM call path (Path A design)`** [Phase 2 Path A, DEFERRED] — multi-day implementation. Operator-gated: only ship when the plugin actually needs LLM features. Design is complete in Phase 2 Path A section of this doc.
141. **`research(axioms): audit all sufficiency probes for specification drift`** [Phase 2 broader implication] — two probes in a row checked for files that do not exist and do not need to exist. How many more probes are in this state? Walk `shared/sufficiency_probes.py` and check each probe's referenced files against reality.

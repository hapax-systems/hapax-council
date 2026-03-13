# CLAUDE.md

## What This Is

VS Code extension for the Hapax system. Replaces the archived `obsidian-hapax` plugin. Provides an LLM chat sidebar, Qdrant RAG search, and management commands -- all embedded in the vault editing workflow.

Part of the three-tier Hapax architecture. This is a Tier 1 interface (interactive). Architecture specs live in [hapax-constitution](https://github.com/ryanklee/hapax-constitution).

## Build and Run

```bash
pnpm install
pnpm run build          # esbuild bundle to dist/extension.js
pnpm run watch          # rebuild on change
pnpm run package        # produce .vsix via vsce
pnpm run lint           # eslint
```

Debug: press F5 in VS Code to launch Extension Development Host (standard VS Code extension workflow). No `.vscode/launch.json` checked in -- VS Code auto-generates it for extension projects.

No test runner is configured yet.

## Entry Point

`src/extension.ts` -- registers the chat webview provider, all commands, and the status bar. Activation trigger: workspace contains `.hapax-vault` sentinel file.

## Provider Architecture

Three LLM providers behind a common `LLMProvider` interface (`src/types.ts`):

| Provider | Class | Transport |
|----------|-------|-----------|
| `litellm` | `OpenAICompatibleProvider` | OpenAI-compatible SSE via LiteLLM proxy (:4000) |
| `openai` | `OpenAICompatibleProvider` | Direct OpenAI API (same SSE format) |
| `anthropic` | `AnthropicProvider` | Anthropic Messages API (`x-api-key`, `content_block_delta` SSE) |

Factory: `src/providers/index.ts` -- `createProvider(settings)` returns the right implementation.

`LLMClient` (`src/llm-client.ts`) delegates to the provider factory. Public API unchanged regardless of provider.

### Corporate Boundary

Work vaults (detected by `10-work/` directory) enforce a provider allowlist. If LiteLLM is unreachable (corporate network), the extension auto-switches to a sanctioned provider (OpenAI or Anthropic) and shows a warning. See `enforceWorkVaultProvider()` in `src/settings.ts`.

### API Key Resolution

Three-tier fallback: VS Code setting > environment variable (direnv) > `pass` store. See `resolveApiKey()` in `src/settings.ts`.

## Key Features

- **Chat sidebar** (`src/chat-view.ts`) -- streaming LLM chat in the activity bar. Markdown rendering via `marked`. History persisted in `globalState`.
- **Note-type awareness** -- detects frontmatter `type` field (person, meeting, decision, etc.) and injects context-appropriate system prompt prefixes. 16 note types supported.
- **Vault context** -- loads `30-system/hapax-context.md` on every message for dynamic system context.
- **Slash commands** (`src/slash-commands.ts`) -- `/prep`, `/review-week`, `/growth`, `/team-risks`, `/setup` (interview), `/setup skip`, `/setup status`. Autocomplete dropdown in chat.
- **RAG search** (`src/qdrant-client.ts`) -- vector search via Qdrant + Ollama embeddings (nomic-embed-text-v2-moe, 768d). Multi-collection search. Degrades silently off home network.
- **Interview engine** (`src/interview/`) -- guided setup to populate foundational management data. Three tiers: foundational, structural, enrichment.
- **Status bar** (`src/status-bar.ts`) -- health status from cockpit API (:8051), 5-minute refresh, silent degradation.
- **Management commands** (`src/commands/`) -- prepare 1:1, team snapshot, knowledge search, nudges, profile view, decision capture. Work-vault only (gated at registration).

## File Layout

```
src/
  extension.ts          # Activation, command registration
  chat-view.ts          # Webview provider (chat UI + streaming)
  llm-client.ts         # LLM client (delegates to providers)
  types.ts              # Shared types, provider models, settings interface
  settings.ts           # VS Code config reader, API key resolution, work vault enforcement
  vault.ts              # Vault file I/O, frontmatter parsing (gray-matter)
  qdrant-client.ts      # Qdrant vector search + Ollama embedding
  slash-commands.ts     # Slash command definitions and matching
  status-bar.ts         # Status bar with health polling
  providers/
    index.ts            # Provider factory
    openai-compatible.ts # OpenAI/LiteLLM SSE streaming
    anthropic.ts        # Anthropic Messages API streaming
  commands/
    prepare-1on1.ts     # 1:1 prep generation
    team-snapshot.ts    # Team snapshot
    search.ts           # Knowledge base search UI
    nudges.ts           # Active nudges viewer
    profile.ts          # Operator profile viewer
    capture-decision.ts # Decision capture
  interview/
    engine.ts           # Interview state machine
    extractor.ts        # Answer extraction
    questions.ts        # Question bank
    knowledge-model.ts  # Knowledge model definitions
    vault-writer.ts     # Interview result persistence
```

## Conventions

- Package manager: `pnpm` (never npm/yarn)
- Language: TypeScript with strict mode
- Bundler: esbuild (not webpack)
- Target: Node 18, VS Code ^1.85.0
- Error handling: catch `unknown`, sanitize errors before showing in UI (strip URLs, truncate)
- Dependencies: `gray-matter` (frontmatter), `marked` (markdown rendering). No other runtime deps.

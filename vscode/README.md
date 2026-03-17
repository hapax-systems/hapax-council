# hapax-vscode

VS Code extension that embeds the Hapax autonomous agent system into the vault editing workflow. Provides an LLM chat sidebar with streaming, Qdrant-backed knowledge search, and management commands for 1:1 prep, team snapshots, and decision capture. Works on both home and corporate networks through a provider abstraction layer.

## Features

- **Chat sidebar** -- streaming LLM chat in the VS Code activity bar with markdown rendering and conversation history
- **Note-type awareness** -- automatically adapts system prompts based on the active file's frontmatter type (person, meeting, decision, coaching, etc.)
- **Slash commands** -- `/prep`, `/review-week`, `/growth`, `/team-risks` with autocomplete
- **Knowledge search** -- semantic search across Qdrant vector collections using Ollama embeddings
- **Management commands** -- 1:1 prep, team snapshots, nudge viewer, operator profile, decision capture
- **Setup interview** -- guided data collection to bootstrap the management knowledge base
- **Health status bar** -- live system health from the cockpit API
- **Corporate boundary support** -- auto-switches to direct provider APIs when the LiteLLM proxy is unreachable

## Installation

### From VSIX

```bash
cd ~/projects/hapax-vscode
pnpm install
pnpm run package
code --install-extension hapax-vscode-0.1.0.vsix
```

### Development

```bash
cd ~/projects/hapax-vscode
pnpm install
pnpm run watch
# Press F5 in VS Code to launch Extension Development Host
```

## Activation

The extension activates when the workspace contains a `.hapax-vault` sentinel file. Management commands (1:1 prep, team snapshot, etc.) are only available in work vaults, detected by the presence of a `10-work/` directory.

## Configuration

All settings are under the `hapax.*` namespace in VS Code settings.

| Setting | Default | Description |
|---------|---------|-------------|
| `hapax.provider` | `litellm` | LLM provider: `litellm`, `openai`, or `anthropic` |
| `hapax.apiKey` | | API key (falls back to env var, then `pass` store) |
| `hapax.model` | `claude-sonnet` | Model name (provider-specific) |
| `hapax.litellmUrl` | `http://localhost:4000` | LiteLLM proxy URL |
| `hapax.qdrantUrl` | `http://localhost:6333` | Qdrant vector DB URL |
| `hapax.qdrantCollection` | `documents` | Default Qdrant collection |
| `hapax.ollamaUrl` | `http://localhost:11434` | Ollama URL for embeddings |
| `hapax.maxTokens` | `4096` | Max response tokens |
| `hapax.maxContextLength` | `8000` | Max context characters from active file |
| `hapax.systemPrompt` | *(built-in)* | System prompt for chat |

### API Key Resolution

Keys are resolved in order: VS Code setting > environment variable (via direnv) > `pass` GPG store. The environment variable and pass path are provider-specific:

| Provider | Env Var | Pass Path |
|----------|---------|-----------|
| litellm | `LITELLM_API_KEY` | `litellm/master-key` |
| openai | `OPENAI_API_KEY` | `api/openai` |
| anthropic | `ANTHROPIC_API_KEY` | `api/anthropic` |

### Work vs. Home Network

On corporate networks where LiteLLM is unreachable, the extension automatically switches to a sanctioned direct provider (OpenAI or Anthropic). RAG search and health status degrade silently -- chat continues working via direct API calls.

## Architecture

```
src/
  extension.ts           Entry point, command registration
  chat-view.ts           Webview chat UI with streaming
  llm-client.ts          LLM client (delegates to providers)
  providers/             LLM provider abstraction
    openai-compatible.ts   LiteLLM + OpenAI (shared SSE format)
    anthropic.ts           Anthropic Messages API
  commands/              Management commands (1:1, snapshot, search, etc.)
  interview/             Guided setup interview engine
  vault.ts               Vault file I/O + frontmatter parsing
  qdrant-client.ts       Vector search + embedding
  slash-commands.ts      Chat slash command definitions
  status-bar.ts          Health status polling
```

The extension is bundled with esbuild to a single `dist/extension.js`. Runtime dependencies are `gray-matter` (frontmatter parsing) and `marked` (markdown rendering).

## Related Repos

| Repo | Purpose |
|------|---------|
| [hapax-constitution](https://github.com/ryanklee/hapax-constitution) | Architecture specs, axioms, design authority |
| [hapax-council](https://github.com/ryanklee/hapax-council) | Tier 2 agent implementations + cockpit API |
| [hapax-officium](https://github.com/ryanklee/hapax-officium) | Management decision support (cockpit API on :8050) |

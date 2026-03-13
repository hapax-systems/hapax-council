# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Externalized executive function infrastructure. LLM agents handle cognitive work (tracking open loops, maintaining context, surfacing what needs attention) for a single operator on a single workstation. Single-operator is a constitutional axiom — no auth, no roles, no multi-user code anywhere.

## Commands

```bash
# Setup
uv sync                                       # install deps (never pip)

# Run agents
uv run python -m agents.<name> [flags]        # e.g. agents.health_monitor --history
uv run python -m agents.management_prep --person "Name" --team-snapshot

# Cockpit API
uv run cockpit-api                            # FastAPI on :8051

# Tests (all mocked, no LLM/infra needed)
uv run pytest tests/ -q                       # full suite
uv run pytest tests/test_scout.py -q          # single file
uv run pytest tests/test_scout.py::TestScout::test_run -q  # single test

# Lint and format
uv run ruff check .                           # lint (ruff.toml config)
uv run ruff format .                          # format
uv run ruff check --fix .                     # auto-fix

# Type checking
uv run pyright                                # basic mode, covers agents/ shared/ cockpit/

# Containers
docker compose up -d                          # both cockpit-api + sync-pipeline
docker compose up -d cockpit-api              # just API
```

## Architecture

**Filesystem-as-bus**: Agents read/write markdown files with YAML frontmatter on disk. A reactive engine (inotify) watches for changes and cascades downstream work automatically.

**Three tiers**:
- **Tier 1** — Interactive interfaces (council-web React SPA at :5173, VS Code extension)
- **Tier 2** — LLM-driven agents (pydantic-ai, routed through LiteLLM at :4000)
- **Tier 3** — Deterministic agents (sync, health, maintenance — no LLM calls)

**Reactive engine** (`cockpit/engine/`): inotify watcher → 12 rules evaluate → phased execution (deterministic first, then LLM work semaphore-bounded at max 2 concurrent).

**Infrastructure**: Qdrant (vector DB, 4 collections: claude-memory, profile-facts, documents, axiom-precedents), LiteLLM (API gateway → Anthropic/Gemini/Ollama), Ollama (local RTX 3090), PostgreSQL, Langfuse (LLM observability), ntfy (push notifications).

## Key Conventions

- **Python 3.12+**, managed with `uv`. Never pip.
- **Type hints mandatory.** Pydantic models for structured data.
- **All LLM calls through LiteLLM** at localhost:4000 via `shared.config.get_model()`. Never direct to providers.
- **Secrets via `pass` + `direnv`**. Never hardcoded. `.envrc` is gitignored.
- **Conventional commits.** Feature branches from `main`.
- **pydantic-ai 1.63.0**: uses `output_type` (not `result_type`) and `result.output` (not `result.data`).
- **Safety:** LLMs prepare, humans deliver. Never generate feedback language or coaching recommendations about individual team members.
- **Ruff config**: line-length 100, isort with first-party = `agents`, `shared`, `cockpit`.

## Testing

Tests use `unittest.mock` — no pytest fixtures in conftest. Each test file is self-contained. `asyncio_mode = "auto"` in pytest config. Tests marked `llm` are excluded by default (`addopts = "-m 'not llm'"`). Other markers: `slow`, `integration`, `hardware`.

## Axiom Governance

5 axioms (3 constitutional, 2 domain) enforced via `shared/axiom_*.py`, `shared/consent.py`, and commit hooks in `hooks/`:

| Axiom | Weight | Constraint |
|-------|--------|------------|
| single_user | 100 | One operator. No auth, roles, or collaboration features. |
| executive_function | 95 | Zero-config agents, errors include next actions, routine work automated. |
| corporate_boundary | 90 | Work data stays in employer systems. Home system = personal + management-practice only. |
| interpersonal_transparency | 88 | No persistent state about non-operator persons without active consent contract. Opt-in, inspectable, revocable. |
| management_governance | 85 | LLMs prepare, humans deliver. No generated feedback/coaching about individuals. |

T0 violations are blocked by SDLC hooks. Axiom definitions in `axioms/registry.yaml`, implications in `axioms/implications/`. Consent contracts in `axioms/contracts/`, enforced via `shared/consent.py`.

## SDLC Pipeline

LLM-driven software development lifecycle. Issues flow through automated stages on GitHub Actions:

```
Issue opened (labeled "agent-eligible")
  → Triage (Sonnet): classify type/complexity, check axiom relevance, find similar closed issues
  → Plan (Sonnet): identify files, acceptance criteria, diff estimate
  → Implement (Opus on Claude Code): sandboxed agent/* branch, run tests, open PR
  → Adversarial Review (Sonnet, independent context): up to 3 rounds, then human escalation
  → Axiom Gate (Haiku): structural checks + semantic LLM judge against 5 axioms
  → Auto-merge (squash) on pass, block on T0 violation, advisory label on T1+
```

**Scripts** (`scripts/`): `sdlc_triage.py`, `sdlc_plan.py`, `sdlc_review.py`, `sdlc_axiom_judge.py`. All support `--dry-run`.

**Workflows** (`.github/workflows/`): `sdlc-triage.yml`, `sdlc-implement.yml`, `sdlc-review.yml`, `sdlc-axiom-gate.yml`.

**Observability**: Each stage logs to `profiles/sdlc-events.jsonl` via `shared/sdlc_log.py`, writes audit trail via `shared/audit.py`, and exports Langfuse traces (file-based in CI, live when Tailscale available). Trace IDs correlate events across stages.

**Metrics**: `agents/sdlc_metrics.py` computes pipeline velocity, quality, and latency from the event log. Zero LLM calls.

**Safety**: Agent PRs only on `agent/*` branches with `agent-authored` label. CODEOWNERS protects governance files. Review rounds capped at 3 before human escalation. Different models for author vs reviewer.

## Project Layout

```
agents/           Agents + agent packages (voice, demo_pipeline, dev_story, system_ops)
cockpit/          FastAPI API (:8051) + data collectors + reactive engine
shared/           35+ utility modules (config, axioms, profile, frontmatter, context)
council-web/      React SPA dashboard (pnpm, Vite, :5173) — see council-web/CLAUDE.md
vscode/           VS Code extension (chat, RAG, management commands) — see vscode/CLAUDE.md
skills/           15 Claude Code skills (slash commands)
hooks/            Claude Code hooks (axiom scanning, session context)
axioms/           Governance axioms (registry + implications + precedents)
systemd/          Timer and service unit files
docker/           Dockerfiles + docker-compose
tests/            Test suite (70+ files)
docs/             Design docs, rules reference, onboarding (docs/first-run.md)
profiles/         Generated operational data (gitignored, only .gitkeep tracked)
```

## Key Modules

- **`shared/config.py`** — Model aliases (`fast`/`balanced`/`local-fast`), LiteLLM/Qdrant clients, embedding, `DATA_DIR`
- **`shared/cycle_mode.py`** — Reads `~/.cache/hapax/cycle-mode`. Agents call `get_cycle_mode()` to adjust thresholds. CLI: `hapax-mode dev|prod`
- **`shared/notify.py`** — `send_notification()` for ntfy + desktop. Topic: `hapax-alerts`
- **`shared/frontmatter.py`** — Canonical frontmatter parser (never duplicate this)
- **`shared/dimensions.py`** — 11 profile dimensions (5 trait, 6 behavioral). Sync agents produce behavioral facts only, validated by `validate_behavioral_write()`
- **`cockpit/api/routes/`** — ~30 REST endpoints across 7 route groups. CORS for council-web at :5173

## Containerization

Two containers via `docker-compose.yml` (`--network host`):
- **cockpit-api** — FastAPI (:8051), `--extra cockpit-api`
- **sync-pipeline** — 7 RAG sync agents on cron, `--extra sync-pipeline`. Requires GPG agent socket + password store mounts for Google OAuth.

`audio_processor` stays on host (requires GPU/CUDA).

## Ingest Agent

`agents/ingest.py` auto-detects `source_service` from `rag-sources` path patterns when not set by frontmatter. Recognized patterns: `gdrive`, `gcalendar`, `gmail`, `youtube`, `takeout`, `proton`, `claude-code`, `obsidian`, `chrome`, `ambient-audio`.

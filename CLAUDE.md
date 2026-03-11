# CLAUDE.md — ai-agents

Single source of truth for all Hapax Python code: 26 agents, cockpit API, shared modules, and container definitions. Runs on a single-user LLM-first workstation.

## Running Agents

```bash
cd ~/projects/ai-agents && eval "$(<.envrc)"
uv run python -m agents.<name> [flags]
```

All agents are stateless per-invocation. Persistent state lives in Qdrant or `profiles/`.

## Key Conventions

- **Python 3.12+**, managed with `uv`. Never pip.
- **Type hints mandatory.** Pydantic models for structured data.
- **All LLM calls through LiteLLM** at localhost:4000. Never direct to providers.
- **Secrets via `pass` + `direnv`**. Never hardcoded. `.envrc` is gitignored.
- **Conventional commits.** Feature branches from `main`.
- **pydantic-ai 1.63.0**: uses `output_type` (not `result_type`) and `result.output` (not `result.data`).
- **Safety:** LLMs prepare, humans deliver. Never generate feedback language or coaching recommendations about individual team members.

## Testing

```bash
uv run pytest tests/ -q    # 1524 tests, all mocked, no LLM calls
```

Tests use `unittest.mock` — no pytest fixtures in conftest. Each test file is self-contained. `asyncio_mode = "auto"` in pytest config.

## Project Layout

```
agents/               26 agents (10 LLM-driven + 11 deterministic + voice daemon + demo pipeline)
  management_*.py     3 management agents (briefing, profiler, activity)
  *_sync.py           7 RAG sync agents (gdrive, gcalendar, gmail, youtube, claude_code, obsidian, chrome)
  audio_processor.py  Audio processing pipeline (VAD, classification, transcription)
  digest.py           Content/knowledge digest
  scout.py            Horizon scanning
  drift_detector.py   Documentation drift detection
  knowledge_maint.py  Qdrant hygiene
  introspect.py       Infrastructure manifest
  ingest.py           Document ingestion
  demo.py             Audience-tailored demos
  system_check.py     Health checks
cockpit/              FastAPI API server (:8051) + data collectors + reactive engine
  api/                REST server with ~30 endpoints across 7 route groups
  data/               Data collectors (nudges, OKRs, incidents, etc.)
  engine/             Reactive engine (watcher, 12 rules, executor, delivery)
shared/               35 utility modules
  config.py           Model aliases, LiteLLM/Qdrant clients, embedding, DATA_DIR
  google_auth.py      Shared Google OAuth2 (Drive, Calendar, Gmail, YouTube)
  vault_writer.py     Vault egress (briefings, digests, nudges, goals)
  axiom_*.py          Axiom governance engine
  frontmatter.py      Canonical frontmatter parser (never duplicate)
tests/                1524+ tests across 70+ files
profiles/             Persistent state (gitignored)
systemd/              Timer and service unit files
sync-pipeline/        Crontab, entrypoint, and run wrapper for containerized sync
```

## Containerization

Two containers managed via `docker-compose.yml`, both using `--network host`:

- `Dockerfile.cockpit-api` — FastAPI cockpit API (:8051), `--extra cockpit-api` (~675MB)
- `Dockerfile.sync-pipeline` — 7 RAG sync agents on cron, `--extra sync-pipeline` (~838MB)

audio_processor stays on host (requires GPU/CUDA).

```bash
# Build and start both
docker compose up -d

# Just cockpit API
docker compose up -d cockpit-api

# Just sync pipeline
docker compose up -d sync-pipeline

# Switch cycle mode
CYCLE_MODE=dev docker compose up -d sync-pipeline
```

The sync-pipeline requires GPG agent socket + password store mounts for Google OAuth.

## Ingest Agent

`agents/ingest.py` auto-detects `source_service` from `rag-sources` path patterns when not set by frontmatter. Recognized patterns: `gdrive`, `gcalendar`, `gmail`, `youtube`, `takeout`, `proton`, `claude-code`, `obsidian`, `chrome`, `ambient-audio`.

## Axiom Governance

4 axioms enforced via `shared/axiom_*.py`: single_user (100), executive_function (95), corporate_boundary (90), management_governance (85). See `~/projects/hapaxromana/axioms/` for definitions. T0 violations are blocked by SDLC hooks.

## Profiles Directory

`profiles/` contains generated operational data. All `*.json`, `*.md`, `*.jsonl`, `*.yaml`, and `*.bak` files are gitignored. Only `.gitkeep` is tracked.

## Project Memory

Stable patterns confirmed across multiple sessions:

- **pydantic-ai 1.63.0**: Uses `output_type` (not `result_type`) and `result.output` (not `result.data`)
- **Tests**: Use `unittest.mock` — no pytest fixtures in conftest. Each test file is self-contained. Currently 1524+ tests.
- **Profile facts**: JSONL format with fields: `dimension`, `key`, `value`, `confidence`, `source`, `evidence`. 11 dimensions defined in `shared/dimensions.py` (5 trait, 6 behavioral).
- **Sync agents**: All sync agent `_generate_profile_facts()` methods produce behavioral dimension facts only. Validated by `shared.dimensions.validate_behavioral_write()`.
- **Cockpit API**: FastAPI at `:8051` with routers in `cockpit/api/routes/`. CORS configured for cockpit-web at `:5173`.
- **Cycle modes**: `shared/cycle_mode.py` reads `~/.cache/hapax/cycle-mode`. Agents call `get_cycle_mode()` at invocation to adjust thresholds. CLI: `hapax-mode dev|prod`.
- **LLM calls**: All Tier 2 agent LLM calls route through LiteLLM at `:4000` via `shared.config.get_model()`. Never direct to providers.
- **Notifications**: Use `shared.notify.send_notification()` for ntfy + desktop. Topic: `hapax-alerts`.

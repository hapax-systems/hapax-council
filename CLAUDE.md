# CLAUDE.md

Externalized executive function infrastructure. LLM agents handle cognitive work (tracking open loops, maintaining context, surfacing what needs attention) for a single operator on a single workstation. Single-operator is a constitutional axiom — no auth, no roles, no multi-user code anywhere.

Shared conventions (uv, ruff, testing, git workflow, pydantic-ai) are in the workspace `CLAUDE.md` — this file covers council-specific details only.

## Architecture

**Filesystem-as-bus**: Agents read/write markdown files with YAML frontmatter on disk. A reactive engine (inotify) watches for changes and cascades downstream work.

**Three tiers**:
- **Tier 1** — Interactive interfaces (council-web React SPA at :5173, VS Code extension)
- **Tier 2** — LLM-driven agents (pydantic-ai, routed through LiteLLM at :4000)
- **Tier 3** — Deterministic agents (sync, health, maintenance — no LLM calls)

**Reactive engine** (`cockpit/engine/`): inotify watcher → 12 rules → phased execution (deterministic first, then LLM semaphore-bounded at max 2 concurrent).

**Infrastructure**: Qdrant (4 collections), LiteLLM (:4000), Ollama (RTX 3090), PostgreSQL, Langfuse, ntfy (push notifications).

## Cockpit API

FastAPI on `:8051`. `uv run cockpit-api` to start. Containers: `docker compose up -d`.

## Council-Specific Conventions

- Hypothesis for property-based algebraic proofs.
- Cycle mode file: `~/.cache/hapax/cycle-mode` (dev/prod).
- Safety: LLMs prepare, humans deliver. Never generate feedback language or coaching recommendations about individual team members.

## Axiom Governance

5 axioms (3 constitutional, 2 domain) enforced via `shared/axiom_*.py`, `shared/consent.py`, and commit hooks:

| Axiom | Weight | Constraint |
|-------|--------|------------|
| single_user | 100 | One operator. No auth, roles, or collaboration features. |
| executive_function | 95 | Zero-config agents, errors include next actions, routine work automated. |
| corporate_boundary | 90 | Work data stays in employer systems. Home system = personal + management-practice only. |
| interpersonal_transparency | 88 | No persistent state about non-operator persons without active consent contract. |
| management_governance | 85 | LLMs prepare, humans deliver. No generated feedback/coaching about individuals. |

T0 violations blocked by SDLC hooks. Definitions in `axioms/registry.yaml`, implications in `axioms/implications/`, consent contracts in `axioms/contracts/`.

## SDLC Pipeline

LLM-driven lifecycle via GitHub Actions: Triage → Plan → Implement → Adversarial Review (3 rounds max) → Axiom Gate → Auto-merge. Scripts in `scripts/`, workflows in `.github/workflows/`. All scripts support `--dry-run`. Observability via `profiles/sdlc-events.jsonl` + Langfuse traces. Agent PRs only on `agent/*` branches with `agent-authored` label.

## Key Modules

- **`shared/config.py`** — Model aliases, LiteLLM/Qdrant clients, embedding, `DATA_DIR`
- **`shared/cycle_mode.py`** — Reads `~/.cache/hapax/cycle-mode`. CLI: `hapax-mode dev|prod`
- **`shared/notify.py`** — `send_notification()` for ntfy + desktop
- **`shared/frontmatter.py`** — Canonical frontmatter parser (never duplicate this)
- **`shared/dimensions.py`** — 11 profile dimensions. Sync agents produce behavioral facts only.
- **`shared/consent.py`** — `ConsentContract`, `ConsentRegistry`, `contract_check()`
- **`shared/agent_registry.py`** — `AgentManifest` (4-layer schema), query by category/capability/RACI

## Voice Grounding Research Continuity

Research state persists in `agents/hapax_voice/proofs/RESEARCH-STATE.md`. After any session with research decisions or implementation progress on the voice grounding project, update this file before ending. When the operator says "refresh research context" or "update research context", read the state file and selectively read the tier-2 documents it references.

## Composition Ladder Protocol (hapax_voice)

Bottom-up building discipline for the hapax_voice type system. 10 layers (L0–L9), all proven. 7-dimension test matrix per layer. Gate rule: no new composition on layer N unless N-1 is matrix-complete. See `agents/hapax_voice/LAYER_STATUS.yaml` for current status and `tests/hapax_voice/test_type_system_matrix*.py` for the 192 matrix tests.

**3-question heuristic** before every change:
1. What layer does this touch?
2. Is the layer below matrix-complete? (If no → fix that first)
3. Which dimensions does this test cover? (Update LAYER_STATUS.yaml)

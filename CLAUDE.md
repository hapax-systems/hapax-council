# CLAUDE.md

Externalized executive function infrastructure. LLM agents handle cognitive work (tracking open loops, maintaining context, surfacing what needs attention) for a single operator on a single workstation. Single-operator is a constitutional axiom — no auth, no roles, no multi-user code anywhere.

Shared conventions (uv, ruff, testing, git workflow, pydantic-ai) are in the workspace `CLAUDE.md` — this file covers council-specific details only.

## Architecture

**Filesystem-as-bus**: Agents read/write markdown files with YAML frontmatter on disk. A reactive engine (inotify) watches for changes and cascades downstream work.

**Three tiers**:
- **Tier 1** — Interactive interfaces (hapax-logos React SPA at :5173, waybar GTK4 status bar, VS Code extension)
- **Tier 2** — LLM-driven agents (pydantic-ai, routed through LiteLLM at :4000)
- **Tier 3** — Deterministic agents (sync, health, maintenance — no LLM calls)

**Reactive engine** (`logos/engine/`): inotify watcher → 14 rules → phased execution (deterministic first, then LLM semaphore-bounded at max 2 concurrent).

**Infrastructure**: Docker Compose for databases/proxies (13 containers), systemd user units for all application services. No process-compose in production. See `systemd/README.md` for boot sequence, resource isolation, and recovery chain.

**Key services**: `hapax-secrets` (credentials) → `logos-api` (:8051) → `waybar` (GTK4 status bar) → `hapax-voice` (GPU) → `visual-layer-aggregator` → `studio-compositor` (GPU). 41 timers for sync, health, backups.

## Design Language

`docs/logos-design-language.md` is the authority document for all visual surfaces. It governs color (§3), typography (§1.6), spatial model (§4), animation (§6), mode switching (§2), and scope (§11). All component colors must use CSS custom properties (`var(--color-*)`) or Tailwind classes — no hardcoded hex except detection overlays (§3.8). `docs/logos-ui-reference.md` governs region content (what appears at each depth). Classification inspector (`C` key) is exempt from density rules — diagnostic tool with theme-aware colors.

## Logos API

FastAPI on `:8051`. `uv run logos-api` to start. Containers: `docker compose up -d`.

## Command Registry

Centralized automation layer for all Logos UI actions. Every action (focus region, activate preset, toggle overlay) is a registered command with typed args and observable events.

**Access points:**
- **Playwright / browser console**: `window.__logos.execute("terrain.focus", { region: "ground" })`
- **Keyboard**: Single adapter in `CommandRegistryProvider`, key map in `lib/keyboardAdapter.ts`
- **External (MCP, voice)**: WebSocket relay at `ws://localhost:8051/ws/commands`
- **CommandPalette**: Reads from `registry.list()` dynamically

**Key files:**
- `hapax-logos/src/lib/commandRegistry.ts` — Core registry (framework-agnostic)
- `hapax-logos/src/lib/commands/*.ts` — Domain registrations (terrain, studio, overlay, detection, nav, split, data)
- `hapax-logos/src/lib/commands/sequences.ts` — Built-in sequences (studio.enter, studio.exit, escape)
- `hapax-logos/src/lib/keyboardAdapter.ts` — Key map with `when`-clause conditional bindings
- `hapax-logos/src/contexts/CommandRegistryContext.tsx` — React provider, `window.__logos`, keyboard handler
- `hapax-logos/src/components/terrain/CommandRegistryBridge.tsx` — Bridges studio/detection contexts
- `logos/api/routes/commands.py` — WebSocket relay endpoint

**State mirrors:** The provider maintains synchronous state mirrors updated eagerly by action wrappers. This ensures `query()` returns post-execution state without waiting for React re-render. Mirrors sync from React state on each render.

**Spec:** `docs/superpowers/specs/2026-03-26-logos-command-registry-design.md`

## Council-Specific Conventions

- Hypothesis for property-based algebraic proofs.
- Working mode file: `~/.cache/hapax/working-mode` (research/rnd). CLI: `hapax-working-mode`.
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

## Claude Code Hooks (`hooks/scripts/`)

PreToolUse hooks enforce branch discipline and safety at the tool-call level:

| Hook | Gates | Blocks when |
|------|-------|-------------|
| `work-resolution-gate.sh` | Edit, Write | Feature branch with commits but no PR; on main with open PRs whose branch is local |
| `no-stale-branches.sh` | Bash | **Branch creation:** any unmerged branches exist. **Destructive commands** (`git reset --hard`, `git checkout .`, `git branch -f`, `git worktree remove`): on a feature branch with commits ahead of main |
| `push-gate.sh` | Bash | Push without passing tests |
| `pii-guard.sh` | Edit, Write | PII patterns in file content |
| `axiom-commit-scan.sh` | Bash | Commit messages violating axiom patterns |
| `session-context.sh` | Bash | Advisory: detects vite dev server worktree mismatch |

Destructive command detection strips quoted strings before matching to prevent false positives from commit messages that discuss git commands.

## Key Modules

- **`shared/config.py`** — Model aliases, LiteLLM/Qdrant clients, embedding, `DATA_DIR`
- **`shared/working_mode.py`** — Reads `~/.cache/hapax/working-mode` (research/rnd). CLI: `hapax-working-mode`
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

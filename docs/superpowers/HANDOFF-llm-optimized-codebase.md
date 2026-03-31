# Handoff: LLM-Optimized Codebase — Remaining Work

**Date:** 2026-03-30
**Prior session:** beta (4 PRs merged: #454, #455, #456, #457)
**Branch state:** Clean. Zero stale branches. HEAD at main.

## What Was Done

Restructured the hapax codebase so LLM agents can navigate, understand, and maintain it with minimal context loading. Four phases shipped:

**Phase 0 — Tooling:** Four AST-based automation scripts at `scripts/llm_*.py`:
- `llm_import_graph.py` — transitive import graph + token cost calculator
- `llm_validate.py` — METADATA.yaml validator with baseline comparison
- `llm_metadata_gen.py` — draft METADATA.yaml generator from source analysis
- `llm_vendor.py` — vendor shared deps into agent packages
- JSON Schema at `schemas/metadata.schema.json`
- Baseline at `profiles/token-baseline.json`

**Phase 1 — Pilot:** `agents/drift_detector/` fully self-contained (38 files, all <200 LOC, zero Any, zero shared deps, METADATA.yaml validated).

**Phase 2 — Metadata:** 90 METADATA.yaml files (78 backend + 12 frontend). `MANIFEST.json` indexes 85 packages.

**Phase 3 — shared/ dissolution:** All consumer code (agents/, logos/) has zero `from shared.*` imports. 66 vendored shim files at `agents/_*.py` and 40 at `logos/_*.py` wrap shared/ types. The shims themselves still reference shared/ internally.

**Phase 4 — Type narrowing:** 287 → 81 `Any` types. Remaining 81 are genuinely dynamic.

**Phase 5 — Monolith decomposition:** studio_compositor (2710 → 20 files), daimonion __main__ (2613 → 17 files), visual_layer_aggregator (2325 → 6 files), reactive_rules (952 → 4 files), chat_agent + studio routes split.

## What Remains

### 1. Vendored shim internals (medium effort, medium value)

22 vendored shim files in `agents/_*.py` and `logos/_*.py` still import from `shared/` internally. These are thin wrappers around complex governance types (`ConsentGatedReader`, `RevocationPropagator`, `CarrierRegistry`, `consent_channels`, etc.).

**Files:** `agents/_consent_channels.py`, `agents/_consent_context.py`, `agents/_consent_gate.py`, `agents/_consent_reader.py`, `agents/_fix_capabilities.py`, `agents/_guest_detection.py`, `agents/_revocation.py`, `agents/_clap.py`, `logos/_agent_governor.py`, `logos/_carrier.py`, `logos/_carrier_intake.py`, `logos/_clap.py`, `logos/_consent_channels.py`, `logos/_consent_reader.py`, `logos/_revocation.py`, `logos/_revocation_wiring.py`, plus `agents/_operator.py`, `logos/_operator.py` (comments only, not real imports).

**Why it's hard:** The governance module (`shared/governance/`, 4000 LOC, 12+ files) has internal circular dependencies broken by `__getattr__` lazy loading. The consent model, revocation propagator, and carrier registry are deeply interconnected. Vendoring them means copying 4000 LOC of interconnected code and resolving the circular deps.

**Options:**
- **A) Inline full governance into each shim** — copy the dep chain, resolve circulars. ~2 days.
- **B) Create a single `agents/_governance_full/` package** — one vendored copy of the entire governance module, all shims import from there. Simpler but doesn't achieve per-agent self-containment.
- **C) Accept shims as the abstraction layer** — shared/ stays as an internal implementation detail behind the shim API. Consumer code never touches it.

**Recommendation:** Option B as a practical middle ground.

### 2. Large single-class files (low effort, low value)

15 files still over 1000 LOC. All are single classes with 20-30 methods sharing instance state through `self`:

| File | LOC | Why it resists splitting |
|------|-----|------------------------|
| `agents/profiler.py` | 2049 | Single Agent with many tools |
| `agents/hapax_daimonion/backends/vision.py` | 1861 | VisionBackend class |
| `agents/hapax_daimonion/conversation_pipeline.py` | 1846 | ConversationPipeline class |
| `agents/audio_processor.py` | 1744 | AudioProcessor class |
| `agents/demo.py` | 1703 | DemoAgent with pipeline |
| `agents/hapax_daimonion/tools.py` | 1566 | 30+ tool functions |
| `agents/demo_pipeline/critique.py` | 1400 | CritiqueAgent |
| `agents/profiler_sources.py` | 1370 | Source discovery |
| `agents/demo_pipeline/research.py` | 1311 | ResearchAgent |
| `agents/visual_layer_aggregator/aggregator.py` | 1235 | Aggregator class |
| `agents/_sufficiency_probes.py` | 1205 | 22 probes |
| `agents/video_processor.py` | 1114 | VideoProcessor class |
| `agents/av_correlator.py` | 1051 | AVCorrelator class |
| `agents/briefing.py` | 1007 | BriefingAgent |
| `agents/activity_analyzer.py` | 984 | ActivityAnalyzer |

**Splitting approach:** Mixin inheritance or delegation. Extract method groups into mixin classes (`class VisionCaptureMixin`, `class VisionProcessingMixin`), compose the main class from mixins. This adds indirection but keeps files small.

**Recommendation:** Low priority. These are coherent single-responsibility classes. An LLM reading METADATA.yaml + the class docstring understands what the file does without reading all 2000 lines.

### 3. Cross-repo independence (medium effort, high value for multi-repo LLM work)

#### 3a. Eliminate hapax-sdlc dependency

Both `hapax-council` and `hapax-officium` depend on `hapax-sdlc` (published from `hapax-constitution`):

```toml
# hapax-council/pyproject.toml
"hapax-sdlc @ git+https://github.com/ryanklee/hapax-constitution.git@cbdf204..."

# hapax-officium/pyproject.toml
"hapax-sdlc[demo] @ git+https://github.com/ryanklee/hapax-constitution.git@cbdf204..."
```

**What hapax-sdlc provides:** Axiom schemas, implication types, SDLC pipeline helpers, demo fixtures.

**Fix:**
1. `cd hapax-constitution && ls src/hapax_sdlc/` to inventory what's in the package
2. Copy the needed types/helpers into `hapax-council/agents/_sdlc/` (or similar)
3. Copy into `hapax-officium/agents/_sdlc/`
4. Remove the git+ dependency from both `pyproject.toml` files
5. `uv sync && uv run pytest tests/ -q` in each repo

**Risk:** The SDLC pipeline scripts (`scripts/sdlc_*.py`) and GitHub Actions workflows import from `hapax_sdlc`. All of those need updating.

#### 3b. hapax-mcp — already independent

hapax-mcp already has its own models at `src/hapax_mcp/models/` (health.py, profile.py, infrastructure.py, working_mode.py). It communicates with council/officium via HTTP only. **No work needed.**

#### 3c. hapax-watch — already independent

hapax-watch is a Kotlin/Android app. API contract is HTTP POST to `/api/watch/biometrics`. Schema lives in the Watch app's Kotlin data classes and in the council's `logos/api/routes/watch.py`. **No shared Python types.** No work needed.

#### 3d. hapax-officium shared types

Officium has its own `shared/` directory (separate from council's). It imports from `hapax-sdlc` (see 3a) but doesn't import from council's shared/. Fixing 3a covers this.

### 4. Remaining Any types (low effort, low value)

81 `Any` types remain. Categories:
- **GStreamer** (studio_compositor, effect_graph/pipeline) — no Python type stubs exist for GStreamer elements
- **ML model lazy-loading** (`self._model: Any = None` for CLIP, MoViNet, PANNs) — conditional imports, model type unknown until runtime
- **Hardware interfaces** (MIDI via mido, OBS WebSocket, Pedalboard audio effects) — optional deps without stubs
- **Duck-typed daemon interfaces** — compound_goals daemon param

**Fix:** Create Protocol classes for each category. Not worth doing unless pyright strict mode is a goal.

### 5. Frontend Context elimination (trivial effort, trivial value)

2 React components use `useContext`, 8 files reference `createContext`/`useContext` total. The frontend is already well-structured (avg 125 LOC per file). Not worth the prop-drilling refactor.

## Key Files for Orientation

| File | Purpose |
|------|---------|
| `scripts/llm_import_graph.py` | Run `--baseline` to snapshot token costs, `--module X` to check one module |
| `scripts/llm_validate.py` | Run to validate all METADATA.yaml, `--compare-baseline` for before/after |
| `scripts/llm_metadata_gen.py` | Run `--all-agents --write` to generate METADATA.yaml for new agents |
| `scripts/llm_vendor.py` | Run with agent name to vendor shared deps (dry-run by default, `--apply` to write) |
| `schemas/metadata.schema.json` | JSON Schema for METADATA.yaml validation |
| `MANIFEST.json` | Repo-wide package index (85 packages) |
| `profiles/token-baseline.json` | Token cost baseline (663 modules) |
| `agents/drift_detector/` | Reference implementation of a fully self-contained agent package |

## Recommended Next Session Priority

1. **Cross-repo: eliminate hapax-sdlc** (3a) — highest value, unblocks repo independence
2. **Vendored shim consolidation** (1, option B) — create `agents/_governance_full/` package
3. **Skip everything else** — diminishing returns

# Demo Pipeline Consolidation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Design spec:** `docs/superpowers/specs/2026-03-12-demo-consolidation-design.md`

**Context:** The demo pipeline is 95% duplicated across hapax-council and hapax-officium. This plan extracts the shared rendering modules into a pip-installable package, adds async job infrastructure for API-driven demo generation, and unifies data gathering with the shared data-access layer.

**Prerequisite:** hapax-sdlc package extraction is complete (committed and pushed to all 3 repos).

---

## Phase 0: Extract `hapax-demo` Package

### Task 0.1: Create demo/models.py in hapax-constitution

**Files:**
- Create: `~/projects/hapax-constitution/demo/__init__.py`
- Create: `~/projects/hapax-constitution/demo/models.py`
- Source: `~/projects/hapax-council/agents/demo_models.py`

**Changes:**
- Copy `demo_models.py` content to `demo/models.py`
- Replace hardcoded `PERSONAS_PATH` / `AUDIENCES_PATH` with module-level configurables
- Add `configure_paths(*, personas: Path | None, audiences: Path | None)` function
- Add `configure_model_provider(fn: Callable)` for LLM model resolution (used by eval_rubrics, critique)
- Keep all Pydantic models unchanged: DemoScene, DemoScript, DemoEvalReport, ScreenshotSpec, InteractionSpec, InteractionStep, IllustrationSpec, AudiencePersona, AudienceDossier, ContentSkeleton
- Tests: model construction, configure_paths, load_personas/load_audiences with injected paths

### Task 0.2: Create demo/pipeline/ — zero-coupling modules (10 files)

**Files:**
- Create: `~/projects/hapax-constitution/demo/pipeline/__init__.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/audio_convert.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/charts.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/diagrams.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/history.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/lessons.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/narrative.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/title_cards.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/video.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/voice.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/vram.py`
- Source: `~/projects/hapax-council/agents/demo_pipeline/`

**Changes:**
- Direct copy — these modules have zero repo-specific imports
- `narrative.py`: change `STYLE_PATH` from hardcoded `profiles/` to `demo.models.get_config_dir()` call
- `lessons.py`: change `LESSONS_PATH` from hardcoded `profiles/` to `demo.models.get_config_dir()` call
- Tests: import from `demo.pipeline.*` and verify core functions work

### Task 0.3: Create demo/pipeline/ — model-coupled modules (7 files)

**Files:**
- Create: `~/projects/hapax-constitution/demo/pipeline/screenshots.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/screencasts.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/slides.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/html_player.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/chapters.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/dossier.py`
- Create: `~/projects/hapax-constitution/demo/pipeline/illustrations.py`
- Source: `~/projects/hapax-council/agents/demo_pipeline/`

**Changes:**
- Copy from council
- Change all `from agents.demo_models import ...` → `from demo.models import ...`
- Change all `from agents.demo_pipeline.X import ...` → `from demo.pipeline.X import ...`
- `illustrations.py`: make model name configurable (council uses imagen-3.0, officium uses imagen-4.0)
- Tests: import from `demo.pipeline.*` and verify

### Task 0.4: Copy domain corpus and templates as package data

**Files:**
- Create: `~/projects/hapax-constitution/demo/domain_corpus/` (6 .md files)
- Create: `~/projects/hapax-constitution/demo/templates/` (gruvbox-marp.css, player.html.j2)
- Source: `~/projects/hapax-council/agents/demo_pipeline/domain_corpus/` and `templates/`

**Changes:**
- Direct copy
- Update `slides.py`, `html_player.py` to resolve template paths via `importlib.resources` or `Path(__file__).parent / "templates"`
- Update `research.py` (in-repo) to reference domain_corpus via package path
- Add to pyproject.toml: `[tool.hatch.build.targets.wheel] packages = ["sdlc", "demo"]`

### Task 0.5: Update hapax-constitution pyproject.toml

**Files:**
- Modify: `~/projects/hapax-constitution/pyproject.toml`

**Changes:**
- Add `"demo"` to `[tool.hatch.build.targets.wheel] packages`
- Add `[project.optional-dependencies] demo = [...]` with: httpx, jinja2, matplotlib, moviepy, numpy, Pillow, playwright, typing-extensions
- Commit and push to make package available

### Task 0.6: Re-export wrappers in hapax-council

**Files:**
- Modify: `~/projects/hapax-council/agents/demo_pipeline/*.py` (17 files)
- Modify: `~/projects/hapax-council/agents/demo_models.py`
- Modify: `~/projects/hapax-council/pyproject.toml` (add `hapax-sdlc[demo]` dependency)

**Changes:**
- Each pipeline module → re-export wrapper: `from demo.pipeline.X import *`
- `demo_models.py` → re-export wrapper with `configure_paths()` call using council's paths
- Add startup hook in `demo.py` to call `demo.models.configure_paths(personas=PROFILES_DIR / "demo-personas.yaml", audiences=PROFILES_DIR / "demo-audiences.yaml")`
- Run `uv sync` to install package
- Tests: full demo test suite passes unchanged

### Task 0.7: Re-export wrappers in hapax-officium

**Files:**
- Modify: `~/projects/hapax-officium/agents/demo_pipeline/*.py` (17 files)
- Modify: `~/projects/hapax-officium/agents/demo_models.py`
- Modify: `~/projects/hapax-officium/pyproject.toml` (add `hapax-sdlc[demo]` dependency)

**Changes:**
- Same pattern as council but with officium's config paths
- `configure_paths(personas=CONFIG_DIR / "demo-personas.yaml", audiences=CONFIG_DIR / "demo-audiences.yaml")`
- Run `uv sync`, verify test suite passes

---

## Phase 1: Async Job Infrastructure

### Task 1.1: DemoJobManager

**Files:**
- Create: `~/projects/hapax-council/cockpit/api/demo_jobs.py`

**Changes:**
- `DemoJob` dataclass: id, status, request, format, timestamps, phase, progress_pct, result_path, error
- `DemoJobManager` class:
  - `__init__()`: creates `profiles/jobs/` dir, asyncio.Lock, current job state
  - `submit(request, format)`: creates job JSON, starts background task via `asyncio.create_task()`
  - `cancel(job_id)`: sets asyncio.Event, awaits task cancellation
  - `get(job_id)`: reads `profiles/jobs/{id}.json`
  - `list_jobs(limit)`: lists job files, returns newest first
  - `stream(job_id)`: yields events from asyncio.Queue
  - `_run_demo(job)`: calls `generate_demo()` with `on_progress` wired to queue, handles completion/failure/cancellation
  - `_save(job)`: atomic JSON write to `profiles/jobs/{id}.json`
- Tests: submit/get/cancel lifecycle, concurrent submit rejected while running, progress events emitted

### Task 1.2: API routes for demo generation

**Files:**
- Modify: `~/projects/hapax-council/cockpit/api/routes/demos.py`

**Changes:**
- `POST /api/demos/generate`: accepts `{"request": str, "format": str}`, calls `manager.submit()`, returns `{"job_id": str, "status": "queued"}`
- `GET /api/demos/jobs`: calls `manager.list_jobs()`, returns list
- `GET /api/demos/jobs/{job_id}`: calls `manager.get()`, returns job state
- `GET /api/demos/jobs/{job_id}/stream`: SSE EventSourceResponse from `manager.stream()`
- `DELETE /api/demos/jobs/{job_id}`: calls `manager.cancel()`, returns success/not-found
- Tests: endpoint integration tests with mocked generate_demo

### Task 1.3: Register in app lifespan

**Files:**
- Modify: `~/projects/hapax-council/cockpit/api/app.py`

**Changes:**
- Import DemoJobManager
- In lifespan: `app.state.demo_jobs = DemoJobManager()`
- Wire into demo routes via `request.app.state.demo_jobs`

---

## Phase 2: Unify Data Access in research.py

### Task 2.1: Refactor council research.py to use shared modules

**Files:**
- Modify: `~/projects/hapax-council/agents/demo_pipeline/research.py`

**Changes:**
- Replace `_gather_health_summary()` body → `ops_live.get_infra_snapshot(PROFILES_DIR)`
- Replace `_gather_introspect()` body → `ops_live.get_manifest_section(PROFILES_DIR, section)`
- Replace `_gather_langfuse_metrics()` body → `ops_live.query_langfuse_cost(days=7)`
- Replace `_gather_qdrant_stats()` body → `ops_live.query_qdrant_stats()`
- Replace `_gather_profile_facts()` body → `knowledge_search.search_profile(scope, limit=15)`
- Replace `_gather_briefing()` body → `knowledge_search.read_briefing(PROFILES_DIR)`
- Replace `_gather_scout_summary()` body → `knowledge_search.read_scout_report(PROFILES_DIR)`
- Replace `_gather_operator_philosophy()` body → `knowledge_search.get_operator_goals(PROFILES_DIR)`
- Replace `_gather_architecture_rag()` body → `knowledge_search.search_documents(scope, source_service="claude-code", limit=10)`
- Keep unchanged: `_gather_audit_findings()`, `_gather_web_research()`, `_gather_domain_literature()`, `_gather_workflow_patterns()`, `_gather_component_registry()`, `_gather_design_plans()`
- Remove dead imports (agents.health_monitor, agents.introspect, etc.)
- Tests: mock shared modules, verify gather_research() produces expected sections

### Task 2.2: Refactor officium research.py to use shared modules

**Files:**
- Modify: `~/projects/hapax-officium/agents/demo_pipeline/research.py`

**Changes:**
- Same pattern as council but with officium's subset of sources
- Replace `_gather_health_summary()` body → `ops_live.get_infra_snapshot(PROFILES_DIR)`
- Officium has fewer sources (no introspect, drift, scout, live_system_state) — those gather functions are removed entirely
- Keep demo-unique functions unchanged
- Tests: verify gather_research() produces expected sections

### Task 2.3: Verify end-to-end demo generation

**Files:** None (verification only)

**Changes:**
- Run full demo generation in council with refactored research: `python -m agents.demo "system overview for family"`
- Verify output quality matches pre-refactor (same data, same formatting)
- Run full test suite in both repos

---

## Dependency Graph

```
Task 0.1 (models) ──→ Task 0.2 (zero-coupling) ──→ Task 0.4 (package data) ──→ Task 0.5 (pyproject)
     │                      │                                                         │
     └──→ Task 0.3 (model-coupled) ─────────────────────────────────────────────────→─┤
                                                                                      │
                                                                          Task 0.6 (council wrappers)
                                                                          Task 0.7 (officium wrappers)

Task 1.1 (job manager) ──→ Task 1.2 (API routes) ──→ Task 1.3 (lifespan)

Task 2.1 (council research) ──→ Task 2.3 (e2e verify)
Task 2.2 (officium research) ──→ Task 2.3 (e2e verify)
```

Phase 0 must complete before Phase 1 or 2 can start.
Phases 1 and 2 are independent of each other.

---

## Verification (all phases)

```bash
# Phase 0: package builds, both repos pass demo tests
cd ~/projects/hapax-constitution && uv build
cd ~/projects/hapax-council && uv sync && uv run pytest tests/test_demo_*.py -v
cd ~/projects/hapax-officium && uv sync && uv run pytest tests/test_demo_*.py -v

# Phase 1: job API works
cd ~/projects/hapax-council && uv run pytest tests/test_demo_jobs.py -v

# Phase 2: research uses shared modules, full suite green
cd ~/projects/hapax-council && uv run pytest tests/test_demo_research.py -v
cd ~/projects/hapax-council && uv run pytest -q  # full suite
cd ~/projects/hapax-officium && uv run pytest -q  # full suite
```

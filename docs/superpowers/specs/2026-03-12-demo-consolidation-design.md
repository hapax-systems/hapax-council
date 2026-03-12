# Demo Pipeline Consolidation — Design Spec

> **Status:** Draft
> **Date:** 2026-03-12
> **Scope:** `agents/demo_pipeline/`, `agents/demo.py`, `agents/demo_models.py`, `cockpit/api/routes/demos.py`, `shared/`

## Problem

The demo pipeline is duplicated across hapax-council and hapax-officium — 31 files each, 95% identical. The 5% divergence is concentrated in data-gathering modules (`research.py`, `sufficiency.py`, `readiness.py`, `critique.py`) that import repo-specific agents. Meanwhile, demo's `research.py` reimplements data access that the query agent shared modules (`ops_live`, `ops_db`, `knowledge_search`) already provide.

Additionally, demo generation has no API endpoint — it's CLI-only, preventing voice daemon and cockpit web from triggering demos.

## Goal

1. Extract shared demo pipeline into a pip-installable `hapax-demo` package (same pattern as `hapax-sdlc`)
2. Add async job infrastructure so demos can be triggered and tracked via API
3. Unify demo's data gathering with the shared data-access layer that query agents already use

## Non-Goals

- Making demo a fourth query agent type (wrong abstraction — different output type, duration, and UX pattern)
- Extracting repo-specific orchestration (`demo.py`, `demo_eval.py`) into the shared package
- Changing the query dispatch system's synchronous contract

---

## Phase 0: Extract `hapax-demo` Package

### Architecture

```
hapax-constitution/demo/           ← new package (pip-installable)
├── __init__.py
├── models.py                      ← extracted from agents/demo_models.py
├── pipeline/
│   ├── __init__.py
│   ├── audio_convert.py           ← zero coupling
│   ├── charts.py                  ← zero coupling
│   ├── chapters.py                ← imports models, pipeline.audio_convert, pipeline.video
│   ├── diagrams.py                ← zero coupling
│   ├── dossier.py                 ← imports models
│   ├── history.py                 ← zero coupling
│   ├── html_player.py             ← imports models, pipeline.slides, pipeline.title_cards
│   ├── illustrations.py           ← imports models
│   ├── lessons.py                 ← zero coupling
│   ├── narrative.py               ← zero coupling
│   ├── screenshots.py             ← imports models
│   ├── screencasts.py             ← imports models, pipeline.screenshots
│   ├── slides.py                  ← imports models
│   ├── title_cards.py             ← zero coupling
│   ├── video.py                   ← zero coupling
│   ├── voice.py                   ← zero coupling
│   └── vram.py                    ← zero coupling
├── domain_corpus/                 ← package data (6 markdown files)
│   ├── autonomous-agent-architectures.md
│   ├── cognitive-load-theory.md
│   ├── executive-function-accommodation.md
│   ├── llm-interaction-design.md
│   ├── neurodivergent-technology-design.md
│   └── personal-knowledge-management.md
└── templates/                     ← package data
    ├── gruvbox-marp.css
    └── player.html.j2
```

### The `demo_models` Coupling Problem

7 of 17 pipeline modules import `agents.demo_models` for types like `DemoScript`, `DemoScene`, `ScreenshotSpec`, `InteractionSpec`, `IllustrationSpec`, `AudienceDossier`. The models themselves are pure Pydantic — no repo-specific logic — but they load persona/audience YAML from hardcoded paths:

```python
# Current (council): profiles/demo-personas.yaml
# Current (officium): config/demo-personas.yaml
```

**Solution:** Extract models into `demo/models.py` with path injection:

```python
# demo/models.py

_personas_path: Path | None = None
_audiences_path: Path | None = None

def configure_paths(*, personas: Path | None = None, audiences: Path | None = None) -> None:
    """Called once at startup by the host repo."""
    global _personas_path, _audiences_path
    if personas is not None:
        _personas_path = personas
    if audiences is not None:
        _audiences_path = audiences

def load_personas() -> dict[str, AudiencePersona]:
    if _personas_path is None:
        raise RuntimeError("demo.models.configure_paths() not called")
    ...
```

Host repos call `configure_paths()` at startup (e.g., in `demo.py` before any pipeline work).

### What Stays In-Repo

These modules have deep repo-specific coupling and remain in each repo's `agents/demo_pipeline/`:

| Module | Why it stays |
|--------|-------------|
| `research.py` | Imports repo-specific agents (health_monitor vs system_check), 20+ data sources differ |
| `sufficiency.py` | Imports shared.config, shared.operator, checks repo-specific health agents |
| `readiness.py` | Checks repo-specific ports, services, health agents |
| `critique.py` | Imports pydantic_ai + shared.config.get_model(); officium has diverged visual logic |
| `eval_rubrics.py` | Imports pydantic_ai + shared.config.get_model() for LLM-as-judge |

These 5 modules become thin repo-local files that import the shared package for rendering but implement their own data-gathering and evaluation logic.

Additionally, these orchestration files stay in-repo (they wire everything together):
- `agents/demo.py` — entry point, request parsing, audience resolution, pipeline orchestration
- `agents/demo_eval.py` — evaluation loop (generate → evaluate → heal)

### Backwards Compatibility

Same pattern as `hapax-sdlc` extraction. Each repo gets re-export wrappers:

```python
# agents/demo_pipeline/charts.py (council and officium)
"""Re-export from hapax-demo package."""
from demo.pipeline.charts import *  # noqa: F401, F403
```

### pyproject.toml Addition (hapax-constitution)

```toml
[tool.hatch.build.targets.wheel]
packages = ["sdlc", "demo"]

[project]
name = "hapax-sdlc"  # or rename to "hapax-infra" to reflect broader scope
dependencies = [
    "pyyaml>=6.0",
    "pydantic>=2.12",
    # demo extras below
]

[project.optional-dependencies]
demo = [
    "httpx>=0.28.0",
    "jinja2>=3.1",
    "matplotlib>=3.9",
    "moviepy>=2.0.0",
    "numpy>=1.24.0",
    "Pillow>=11.0.0",
    "playwright>=1.50.0",
    "typing-extensions>=4.5.0",
]
```

Downstream repos add: `hapax-sdlc[demo] @ git+https://github.com/ryanklee/hapax-constitution.git`

### Verification

After extraction, both repos should pass their existing demo test suites unchanged (re-export wrappers preserve import paths).

---

## Phase 1: Async Job Infrastructure + `/api/demos/generate`

### Existing Primitives

The codebase already has the building blocks:

| Pattern | Location | What it does |
|---------|----------|-------------|
| `asyncio.create_task()` + callbacks | `cockpit/api/cache.py:145-169` | Background refresh loops with auto-cleanup |
| Queue-based SSE streaming | `cockpit/api/routes/chat.py:221-244` | asyncio.Queue → EventSourceResponse |
| Single-concurrent locking | `cockpit/api/sessions.py:29-39` | asyncio.Lock enforces one agent at a time |
| Cancellation chain | `cockpit/api/routes/chat.py:156-203` | asyncio.Event → task.cancel() |
| Filesystem state | `output/demos/*/metadata.json` | Demo output already persisted as JSON |

### New Components

**1. Job state file** — `profiles/jobs/{job_id}.json`

```python
@dataclass
class DemoJob:
    id: str                              # uuid4
    status: Literal["queued", "running", "complete", "failed", "cancelled"]
    request: str                         # original request text
    format: str                          # "slides" | "video" | "markdown-only"
    created_at: str                      # ISO 8601
    started_at: str | None
    completed_at: str | None
    phase: str | None                    # current pipeline phase for progress
    progress_pct: int                    # 0-100
    result_path: str | None              # output/demos/... when complete
    error: str | None                    # error message if failed
```

**2. Job manager** — `cockpit/api/demo_jobs.py`

```python
class DemoJobManager:
    """Single-concurrent demo job execution with progress tracking."""

    _lock: asyncio.Lock                  # one demo at a time
    _current: DemoJob | None
    _task: asyncio.Task | None
    _queue: asyncio.Queue[dict]          # progress events

    async def submit(self, request: str, format: str = "slides") -> DemoJob:
        """Create job, start background execution, return immediately."""

    async def cancel(self, job_id: str) -> bool:
        """Cancel in-flight job via asyncio.Event."""

    async def get(self, job_id: str) -> DemoJob | None:
        """Read job state from profiles/jobs/."""

    async def list_jobs(self, limit: int = 20) -> list[DemoJob]:
        """List recent jobs, newest first."""

    async def stream(self, job_id: str) -> AsyncIterator[dict]:
        """Yield SSE events for a running job."""
```

Concurrency: `asyncio.Lock` prevents parallel demos (Playwright/VRAM conflicts). Queued jobs wait for the lock.

Progress: The existing `on_progress` callback in `generate_demo()` feeds the asyncio.Queue. Each callback maps to an SSE event:

```python
async def _run_demo(self, job: DemoJob) -> None:
    def on_progress(msg: str):
        self._queue.put_nowait({"event": "progress", "data": {"phase": msg, "job_id": job.id}})

    demo_dir = await generate_demo(
        job.request, format=job.format, on_progress=on_progress
    )
    job.status = "complete"
    job.result_path = str(demo_dir)
    self._save(job)
    self._queue.put_nowait({"event": "done", "data": {"job_id": job.id, "path": str(demo_dir)}})
```

**3. API routes** — `cockpit/api/routes/demos.py` (extend existing)

```
POST   /api/demos/generate              → {job_id, status_url}
GET    /api/demos/jobs                   → [{job_id, status, request, ...}]
GET    /api/demos/jobs/{job_id}          → {job_id, status, phase, progress_pct, result_path, ...}
GET    /api/demos/jobs/{job_id}/stream   → SSE (progress, done, error events)
DELETE /api/demos/jobs/{job_id}          → cancel in-flight job

# Existing endpoints unchanged:
GET    /api/demos                        → list completed demos
GET    /api/demos/{demo_id}              → demo metadata + files
GET    /api/demos/{demo_id}/files/{path} → serve demo file
DELETE /api/demos/{demo_id}              → delete completed demo
```

**4. Lifecycle** — registered in `cockpit/api/app.py` lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.demo_jobs = DemoJobManager()
    yield
```

### Resource Constraints

- **VRAM:** TTS needs 8GB; Ollama models unloaded before TTS. Lock prevents concurrent demos.
- **Playwright:** Single headless browser per demo. Lock prevents display conflicts.
- **Disk:** Each demo is 10-200MB. `output/demos/` accumulates; existing DELETE endpoint handles cleanup.
- **Timeout:** Default 15 minutes. Jobs exceeding timeout are cancelled automatically.

---

## Phase 2: Unify Demo Research with Shared Data-Access Layer

### Current State

Demo's `research.py` has 20+ `_gather_*()` functions that access the same data sources as the query agent shared modules:

| Demo gather function | Shared module equivalent |
|---------------------|-------------------------|
| `_gather_health_summary()` | `ops_live.get_infra_snapshot()` |
| `_gather_introspect()` | `ops_live.get_manifest_section(section)` |
| `_gather_langfuse_metrics()` | `ops_live.query_langfuse_cost()` |
| `_gather_qdrant_stats()` | `ops_live.query_qdrant_stats()` |
| `_gather_profile_facts()` | `knowledge_search.search_profile(query)` |
| `_gather_briefing()` | `knowledge_search.read_briefing(profiles_dir)` |
| `_gather_architecture_rag()` | `knowledge_search.search_documents(query, source_service="claude-code")` |
| `_gather_operator_philosophy()` | `knowledge_search.get_operator_goals(profiles_dir)` + `read_briefing()` |
| `_gather_scout_summary()` | `knowledge_search.read_scout_report(profiles_dir)` |
| `_gather_audit_findings()` | — (unique to demo, reads `profiles/audit.jsonl` directly) |
| `_gather_web_research()` | — (unique to demo, calls Tavily API) |
| `_gather_domain_literature()` | — (unique to demo, reads corpus files) |
| `_gather_workflow_patterns()` | — (unique to demo, reads workflow-registry.yaml) |
| `_gather_component_registry()` | — (unique to demo, reads component-registry.yaml) |
| `_gather_design_plans()` | — (unique to demo, reads docs/plans/*.md) |

### Refactored research.py

Replace the 10 overlapping gather functions with calls to the shared modules. Keep the 5 demo-unique functions as-is.

```python
# agents/demo_pipeline/research.py (refactored)

from shared.ops_live import get_infra_snapshot, get_manifest_section, query_langfuse_cost, query_qdrant_stats
from shared.knowledge_search import (
    search_documents, search_profile, read_briefing, read_digest,
    read_scout_report, get_operator_goals,
)
from shared.config import PROFILES_DIR

# Replace _gather_health_summary:
def _gather_health_summary() -> str:
    return get_infra_snapshot(PROFILES_DIR)

# Replace _gather_introspect:
def _gather_introspect(partial: bool = False) -> str:
    sections = ["docker", "gpu", "ollama"] if partial else None
    if sections:
        return "\n\n".join(get_manifest_section(PROFILES_DIR, s) for s in sections)
    return get_manifest_section(PROFILES_DIR, "all")

# Replace _gather_langfuse_metrics:
def _gather_langfuse_metrics() -> str:
    return query_langfuse_cost(days=7)

# ... etc.

# KEEP as-is (demo-unique):
def _gather_audit_findings() -> str: ...
def _gather_web_research(scope: str) -> str: ...
def _gather_domain_literature(scope: str) -> str: ...
def _gather_workflow_patterns() -> str: ...
def _gather_component_registry() -> str: ...
def _gather_design_plans(scope: str) -> str: ...
```

### Benefits

1. **Single source of truth** — data access logic maintained in one place
2. **Consistency** — demo, query agents, voice daemon, and cockpit all see the same data
3. **Testability** — shared modules already have tests; demo research inherits coverage
4. **Maintenance** — adding a new data source (e.g., new Qdrant collection) propagates everywhere

### Officium Alignment

Officium's `research.py` is 184 lines shorter because it lacks introspect/drift/scout sources. After this refactor, both repos' `research.py` become thin files that:
1. Import from shared data-access modules
2. Define `AUDIENCE_SOURCES` mappings (repo-specific selection of which sources each audience sees)
3. Keep demo-unique gather functions

The shared modules themselves come from `hapax-sdlc` (or remain as repo-local `shared/` files — the data-access layer is already deduplicated since both repos import `hapax-sdlc` and have their own `shared/config.py`).

---

## Dependency Graph

```
Phase 0 (extract hapax-demo package)
    │
    ├──→ Phase 1 (async job infrastructure)
    │       independent — only needs demo.generate_demo() callable
    │
    └──→ Phase 2 (unify data access in research.py)
            independent — only needs shared/ modules importable
```

Phases 1 and 2 are independent of each other. Phase 0 should go first because it establishes the package boundary.

---

## Critical Files

### New
- `~/projects/hapax-constitution/demo/` — shared package (17 pipeline modules + models + data)
- `~/projects/hapax-council/cockpit/api/demo_jobs.py` — job manager
- `~/projects/hapax-council/profiles/jobs/` — job state directory

### Modified
- `~/projects/hapax-constitution/pyproject.toml` — add demo package + optional deps
- `~/projects/hapax-council/pyproject.toml` — add `hapax-sdlc[demo]` dependency
- `~/projects/hapax-officium/pyproject.toml` — add `hapax-sdlc[demo]` dependency
- `~/projects/hapax-council/agents/demo_pipeline/*.py` — re-export wrappers (17 files)
- `~/projects/hapax-officium/agents/demo_pipeline/*.py` — re-export wrappers (17 files)
- `~/projects/hapax-council/agents/demo_pipeline/research.py` — use shared data-access modules
- `~/projects/hapax-officium/agents/demo_pipeline/research.py` — same
- `~/projects/hapax-council/cockpit/api/routes/demos.py` — add generate/jobs endpoints
- `~/projects/hapax-council/cockpit/api/app.py` — register DemoJobManager in lifespan

## Verification

### Phase 0
```bash
# Both repos: existing demo tests pass with re-export wrappers
cd ~/projects/hapax-council && uv run pytest tests/test_demo_*.py -v
cd ~/projects/hapax-officium && uv run pytest tests/test_demo_*.py -v
```

### Phase 1
```bash
# Job API integration test
cd ~/projects/hapax-council && uv run pytest tests/test_demo_jobs.py -v
# Manual: submit job, poll status, verify output
curl -X POST http://localhost:8051/api/demos/generate -d '{"request": "system overview for family"}'
```

### Phase 2
```bash
# Research module tests (verify shared module delegation)
cd ~/projects/hapax-council && uv run pytest tests/test_demo_research.py -v
# Full demo generation with shared data access
python -m agents.demo "system overview for family"
```

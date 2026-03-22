# Cockpit Web Phase 1: API Skeleton + Dashboard

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deployable FastAPI backend serving cockpit data + React SPA dashboard accessible from phone via Tailscale.

**Architecture:** FastAPI in `cockpit/api/` imports existing `cockpit/data/` collectors directly. React 19 SPA in `~/projects/hapax-logos/` polls the API. Docker service on :8050.

**Tech Stack:** FastAPI, uvicorn, httpx (test client), React 19, Vite, TypeScript, pnpm, TanStack Query, Tailwind CSS 4, Lucide React

**Design doc:** `docs/plans/2026-03-02-hapax-logos-migration-design.md`

---

## Task 1: Add FastAPI dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add fastapi and uvicorn to dependencies**

In `pyproject.toml`, add to the `dependencies` list:

```toml
dependencies = [
    "fastapi>=0.115.0",
    "langfuse>=3.14.5",
    "ollama>=0.6.1",
    "pydantic>=2.12.5",
    "pydantic-ai[litellm]>=1.63.0",
    "pyyaml>=6.0",
    "qdrant-client>=1.17.0",
    "sse-starlette>=2.0.0",
    "textual>=8.0.0",
    "uvicorn>=0.34.0",
]
```

Add httpx to dev dependencies:

```toml
[dependency-groups]
dev = [
    "httpx>=0.28.0",
    "pytest>=9.0.2",
    "pytest-asyncio>=1.3.0",
]
```

**Step 2: Install**

Run: `cd ~/projects/hapax-council && uv sync`
Expected: Clean install, no conflicts.

**Step 3: Verify imports work**

Run: `cd ~/projects/hapax-council && uv run python -c "import fastapi; import uvicorn; import sse_starlette; print('ok')"`
Expected: `ok`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add fastapi, uvicorn, sse-starlette dependencies"
```

---

## Task 2: FastAPI app skeleton with CORS

**Files:**
- Create: `cockpit/api/__init__.py`
- Create: `cockpit/api/app.py`
- Test: `tests/test_api.py`

**Step 1: Write the failing test**

Create `tests/test_api.py`:

```python
"""Tests for cockpit API."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    from cockpit.api.app import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAppSkeleton:
    async def test_root_returns_info(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "cockpit-api"
        assert "version" in data

    async def test_cors_headers_present(self, client):
        resp = await client.options(
            "/",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_api.py -v`
Expected: ImportError — `cockpit.api.app` doesn't exist yet.

**Step 3: Write minimal implementation**

Create `cockpit/api/__init__.py`:

```python
"""cockpit.api — FastAPI backend for the cockpit web UI."""
```

Create `cockpit/api/app.py`:

```python
"""FastAPI application for the cockpit API.

Serves data from cockpit/data/ collectors over HTTP.
Designed to be consumed by the React SPA at hapax-logos/.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="cockpit-api",
    description="Cockpit dashboard API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Vite dev server
        "http://localhost:8050",   # Production (self-hosted SPA)
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8050",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"name": "cockpit-api", "version": "0.1.0"}
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_api.py -v`
Expected: 2 passed.

**Step 5: Commit**

```bash
git add cockpit/api/__init__.py cockpit/api/app.py tests/test_api.py
git commit -m "feat(api): FastAPI app skeleton with CORS"
```

---

## Task 3: Background cache for data collectors

The API caches collector results in memory and refreshes them on timers (30s fast, 5min slow), same as the Textual TUI.

**Files:**
- Create: `cockpit/api/cache.py`
- Test: `tests/test_api_cache.py`

**Step 1: Write the failing test**

Create `tests/test_api_cache.py`:

```python
"""Tests for cockpit API data cache."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from cockpit.api.cache import DataCache


class TestDataCache:
    def test_initial_state_empty(self):
        cache = DataCache()
        assert cache.health is None
        assert cache.gpu is None
        assert cache.containers == []
        assert cache.timers == []
        assert cache.nudges == []

    async def test_refresh_fast_populates_health(self):
        cache = DataCache()
        mock_health = AsyncMock()
        mock_health.return_value = type("H", (), {
            "overall_status": "healthy", "total_checks": 49,
            "healthy": 49, "degraded": 0, "failed": 0,
            "duration_ms": 100, "failed_checks": [], "timestamp": "",
        })()
        with patch("cockpit.data.health.collect_live_health", mock_health), \
             patch("cockpit.data.infrastructure.collect_docker", AsyncMock(return_value=[])), \
             patch("cockpit.data.infrastructure.collect_timers", AsyncMock(return_value=[])), \
             patch("cockpit.data.gpu.collect_vram", AsyncMock(return_value=None)):
            await cache.refresh_fast()
        assert cache.health is not None
        assert cache.health.overall_status == "healthy"

    async def test_refresh_slow_populates_nudges(self):
        cache = DataCache()
        with patch("cockpit.data.nudges.collect_nudges", return_value=[
            type("N", (), {"category": "test", "priority_score": 50,
                           "priority_label": "medium", "title": "Test nudge",
                           "detail": "", "suggested_action": "", "command_hint": "",
                           "source_id": ""})()
        ]):
            await cache.refresh_slow()
        assert len(cache.nudges) == 1
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_api_cache.py -v`
Expected: ImportError — `cockpit.api.cache` doesn't exist.

**Step 3: Write implementation**

Create `cockpit/api/cache.py`:

```python
"""Background data cache for the cockpit API.

Refreshes data collectors on timers matching the original TUI cadence:
- Fast (30s): health, GPU, containers, timers
- Slow (5min): briefing, scout, drift, cost, goals, readiness, management, nudges
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("cockpit.api")


@dataclass
class DataCache:
    """In-memory cache for all data collector results."""

    # Fast refresh (30s)
    health: Any = None
    gpu: Any = None
    containers: list = field(default_factory=list)
    timers: list = field(default_factory=list)

    # Slow refresh (5min)
    briefing: Any = None
    scout: Any = None
    drift: Any = None
    cost: Any = None
    goals: Any = None
    readiness: Any = None
    management: Any = None
    nudges: list = field(default_factory=list)
    agents: list = field(default_factory=list)
    accommodations: Any = None

    async def refresh_fast(self) -> None:
        """Refresh fast-cadence data (health, GPU, infra)."""
        from cockpit.data.gpu import collect_vram
        from cockpit.data.health import collect_live_health
        from cockpit.data.infrastructure import collect_docker, collect_timers

        try:
            health, containers, vram, timers = await asyncio.gather(
                collect_live_health(),
                collect_docker(),
                collect_vram(),
                collect_timers(),
                return_exceptions=True,
            )
            if not isinstance(health, BaseException):
                self.health = health
            if not isinstance(containers, BaseException):
                self.containers = containers
            if not isinstance(vram, BaseException):
                self.gpu = vram
            if not isinstance(timers, BaseException):
                self.timers = timers
        except Exception as e:
            log.warning("Fast refresh failed: %s", e)

    async def refresh_slow(self) -> None:
        """Refresh slow-cadence data (briefing, scout, nudges, etc.)."""
        from cockpit.data.agents import get_agent_registry
        from cockpit.data.briefing import collect_briefing
        from cockpit.data.cost import collect_cost
        from cockpit.data.drift import collect_drift
        from cockpit.data.goals import collect_goals
        from cockpit.data.management import collect_management_state
        from cockpit.data.nudges import collect_nudges
        from cockpit.data.readiness import collect_readiness
        from cockpit.data.scout import collect_scout

        try:
            self.briefing = collect_briefing()
            self.scout = collect_scout()
            self.drift = collect_drift()
            self.cost = collect_cost()
            self.goals = collect_goals()
            self.readiness = collect_readiness()
            self.management = collect_management_state()
            self.agents = get_agent_registry()
        except Exception as e:
            log.warning("Slow refresh error: %s", e)

        try:
            self.nudges = collect_nudges(briefing=self.briefing)
        except Exception as e:
            log.warning("Nudge collection error: %s", e)

        try:
            from cockpit.accommodations import load_accommodations
            self.accommodations = load_accommodations()
        except Exception as e:
            log.warning("Accommodation load error: %s", e)


# Singleton cache instance
cache = DataCache()

FAST_INTERVAL = 30   # seconds
SLOW_INTERVAL = 300  # seconds


async def start_refresh_loop() -> None:
    """Start background refresh tasks. Called from FastAPI lifespan."""
    # Initial load
    await cache.refresh_fast()
    await cache.refresh_slow()

    async def _fast_loop():
        while True:
            await asyncio.sleep(FAST_INTERVAL)
            await cache.refresh_fast()

    async def _slow_loop():
        while True:
            await asyncio.sleep(SLOW_INTERVAL)
            await cache.refresh_slow()

    asyncio.create_task(_fast_loop())
    asyncio.create_task(_slow_loop())
```

**Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_api_cache.py -v`
Expected: 3 passed.

**Step 5: Commit**

```bash
git add cockpit/api/cache.py tests/test_api_cache.py
git commit -m "feat(api): background data cache with 30s/5min refresh"
```

---

## Task 4: Wire lifespan into FastAPI app

**Files:**
- Modify: `cockpit/api/app.py`

**Step 1: Add lifespan to app.py**

Update `cockpit/api/app.py` to wire the cache refresh loop into FastAPI's lifespan:

```python
from contextlib import asynccontextmanager

from cockpit.api.cache import start_refresh_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_refresh_loop()
    yield


app = FastAPI(
    title="cockpit-api",
    description="Cockpit dashboard API",
    version="0.1.0",
    lifespan=lifespan,
)
```

**Step 2: Verify existing tests still pass**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_api.py tests/test_api_cache.py -v`
Expected: All pass (the test client fixture creates the app, lifespan runs in test context).

**Step 3: Commit**

```bash
git add cockpit/api/app.py
git commit -m "feat(api): wire cache refresh into FastAPI lifespan"
```

---

## Task 5: Data endpoints — fast cadence (health, GPU, infrastructure)

**Files:**
- Create: `cockpit/api/routes/data.py`
- Create: `cockpit/api/routes/__init__.py`
- Modify: `cockpit/api/app.py`
- Test: `tests/test_api.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
from unittest.mock import AsyncMock, patch
from cockpit.api.cache import cache


class TestHealthEndpoint:
    async def test_health_returns_data(self, client):
        # Seed the cache directly
        cache.health = type("H", (), {
            "overall_status": "healthy", "total_checks": 49,
            "healthy": 49, "degraded": 0, "failed": 0,
            "duration_ms": 120, "failed_checks": [], "timestamp": "2026-03-02T10:00:00",
        })()
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_status"] == "healthy"
        assert data["total_checks"] == 49

    async def test_health_returns_null_when_empty(self, client):
        cache.health = None
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() is None


class TestGpuEndpoint:
    async def test_gpu_returns_data(self, client):
        cache.gpu = type("G", (), {
            "name": "RTX 3090", "total_mb": 24576, "used_mb": 8000,
            "free_mb": 16576, "usage_pct": 32.6, "temperature_c": 55,
            "loaded_models": ["qwen2.5-coder:32b"],
        })()
        resp = await client.get("/api/gpu")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "RTX 3090"
        assert data["usage_pct"] == 32.6


class TestInfrastructureEndpoint:
    async def test_containers_returns_list(self, client):
        cache.containers = [
            type("C", (), {
                "name": "ollama", "service": "ollama", "state": "running",
                "health": "healthy", "image": "ollama:latest", "ports": ["11434"],
            })()
        ]
        resp = await client.get("/api/infrastructure")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["containers"]) == 1
        assert data["containers"][0]["name"] == "ollama"
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_api.py::TestHealthEndpoint -v`
Expected: 404 — route doesn't exist.

**Step 3: Write implementation**

Create `cockpit/api/routes/__init__.py`:

```python
"""API route modules."""
```

Create `cockpit/api/routes/data.py`:

```python
"""Data endpoints — serve cached collector results.

All endpoints return the latest cached data from the background
refresh loop. Clients poll at matching cadence (30s fast, 5min slow).
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter

from cockpit.api.cache import cache

router = APIRouter(prefix="/api", tags=["data"])


def _to_dict(obj: Any) -> Any:
    """Convert a dataclass (or list of dataclasses) to a dict."""
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    return obj


# ── Fast cadence (30s) ───────────────────────────────────────────────────

@router.get("/health")
async def get_health():
    return _to_dict(cache.health)


@router.get("/health/history")
async def get_health_history():
    from cockpit.data.health import collect_health_history
    history = collect_health_history()
    return _to_dict(history)


@router.get("/gpu")
async def get_gpu():
    return _to_dict(cache.gpu)


@router.get("/infrastructure")
async def get_infrastructure():
    return {
        "containers": _to_dict(cache.containers),
        "timers": _to_dict(cache.timers),
    }


# ── Slow cadence (5min) ──────────────────────────────────────────────────

@router.get("/briefing")
async def get_briefing():
    return _to_dict(cache.briefing)


@router.get("/scout")
async def get_scout():
    return _to_dict(cache.scout)


@router.get("/drift")
async def get_drift():
    return _to_dict(cache.drift)


@router.get("/cost")
async def get_cost():
    return _to_dict(cache.cost)


@router.get("/goals")
async def get_goals():
    return _to_dict(cache.goals)


@router.get("/readiness")
async def get_readiness():
    return _to_dict(cache.readiness)


@router.get("/management")
async def get_management():
    return _to_dict(cache.management)


@router.get("/nudges")
async def get_nudges():
    return _to_dict(cache.nudges)


@router.get("/agents")
async def get_agents():
    return _to_dict(cache.agents)


@router.get("/accommodations")
async def get_accommodations():
    return _to_dict(cache.accommodations)
```

Register the router in `cockpit/api/app.py` — add after `app.add_middleware(...)`:

```python
from cockpit.api.routes.data import router as data_router
app.include_router(data_router)
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_api.py -v`
Expected: All pass (skeleton + health + GPU + infrastructure tests).

**Step 5: Commit**

```bash
git add cockpit/api/routes/__init__.py cockpit/api/routes/data.py cockpit/api/app.py tests/test_api.py
git commit -m "feat(api): data endpoints for health, GPU, infrastructure, and all slow-cadence collectors"
```

---

## Task 6: API entry point

**Files:**
- Create: `cockpit/api/__main__.py`

**Step 1: Write the entry point**

Create `cockpit/api/__main__.py`:

```python
"""Run the cockpit API server.

Usage:
    uv run python -m cockpit.api
    uv run python -m cockpit.api --port 8050 --host 127.0.0.1
"""
from __future__ import annotations

import argparse
import logging

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cockpit API server",
        prog="python -m cockpit.api",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8050, help="Bind port (default: 8050)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on file changes")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    uvicorn.run(
        "cockpit.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
```

**Step 2: Verify it starts (manual smoke test)**

Run: `cd ~/projects/hapax-council && timeout 5 uv run python -m cockpit.api --verbose 2>&1 || true`
Expected: uvicorn startup log, then timeout.

**Step 3: Add script entry point to pyproject.toml**

```toml
[project.scripts]
cockpit = "cockpit.__main__:main"
cockpit-api = "cockpit.api.__main__:main"
```

**Step 4: Commit**

```bash
git add cockpit/api/__main__.py pyproject.toml
git commit -m "feat(api): uvicorn entry point with CLI flags"
```

---

## Task 7: Scaffold React SPA project

**Files:**
- Create: `~/projects/hapax-logos/` (new repo)

**Step 1: Create the project**

```bash
cd ~/projects
pnpm create vite hapax-logos -- --template react-ts
cd hapax-logos
pnpm install
```

**Step 2: Install dependencies**

```bash
cd ~/projects/hapax-logos
pnpm add @tanstack/react-query lucide-react react-markdown remark-gfm recharts
pnpm add -D tailwindcss @tailwindcss/vite
```

**Step 3: Configure Tailwind**

Update `vite.config.ts`:

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8050",
    },
  },
});
```

Replace `src/index.css` with:

```css
@import "tailwindcss";
```

**Step 4: Initialize git**

```bash
cd ~/projects/hapax-logos
git init
echo "node_modules/\ndist/\n.env\n" > .gitignore
git add .
git commit -m "init: React 19 + Vite + TypeScript + Tailwind + TanStack Query"
```

**Step 5: Verify it builds**

Run: `cd ~/projects/hapax-logos && pnpm run build`
Expected: Clean build in `dist/`.

---

## Task 8: API client module

**Files:**
- Create: `~/projects/hapax-logos/src/api/client.ts`
- Create: `~/projects/hapax-logos/src/api/types.ts`

**Step 1: Define TypeScript types matching Python dataclasses**

Create `src/api/types.ts`:

```typescript
// Types matching cockpit/data/ Python dataclasses

export interface HealthSnapshot {
  overall_status: "healthy" | "degraded" | "failed";
  total_checks: number;
  healthy: number;
  degraded: number;
  failed: number;
  duration_ms: number;
  failed_checks: string[];
  timestamp: string;
}

export interface VramSnapshot {
  name: string;
  total_mb: number;
  used_mb: number;
  free_mb: number;
  usage_pct: number;
  temperature_c: number;
  loaded_models: string[];
}

export interface ContainerStatus {
  name: string;
  service: string;
  state: string;
  health: string;
  image: string;
  ports: string[];
}

export interface TimerStatus {
  unit: string;
  next_fire: string;
  last_fired: string;
  activates: string;
}

export interface Infrastructure {
  containers: ContainerStatus[];
  timers: TimerStatus[];
}

export interface Nudge {
  category: string;
  priority_score: number;
  priority_label: "critical" | "high" | "medium" | "low";
  title: string;
  detail: string;
  suggested_action: string;
  command_hint: string;
  source_id: string;
}

export interface BriefingData {
  headline: string;
  generated_at: string;
  body: string;
  action_items: ActionItem[];
}

export interface ActionItem {
  priority: string;
  action: string;
  reason: string;
  command: string;
}

export interface GoalSnapshot {
  goals: GoalStatus[];
  active_count: number;
  stale_count: number;
  primary_stale: string[];
}

export interface GoalStatus {
  id: string;
  name: string;
  status: string;
  category: string;
  last_activity_h: number | null;
  stale: boolean;
  progress_summary: string;
  description: string;
}

export interface ReadinessSnapshot {
  level: "bootstrapping" | "developing" | "operational";
  interview_conducted: boolean;
  profile_coverage_pct: number;
  total_facts: number;
  populated_dimensions: number;
  total_dimensions: number;
  missing_dimensions: string[];
  sparse_dimensions: string[];
  top_gap: string;
  gaps: string[];
}

export interface AgentInfo {
  name: string;
  uses_llm: boolean;
  description: string;
  command: string;
  module: string;
  flags: AgentFlag[];
}

export interface AgentFlag {
  flag: string;
  description: string;
  flag_type: string;
  default: string | null;
  choices: string[] | null;
  metavar: string | null;
}

export interface ScoutData {
  generated_at: string;
  components_scanned: number;
  recommendations: ScoutRecommendation[];
  adopt_count: number;
  evaluate_count: number;
}

export interface ScoutRecommendation {
  component: string;
  current: string;
  tier: string;
  summary: string;
  confidence: string;
  migration_effort: string;
}

export interface CostSnapshot {
  today_cost: number;
  period_cost: number;
  daily_average: number;
  top_models: { model: string; cost: number }[];
  available: boolean;
}
```

**Step 2: Create API client with fetch helpers**

Create `src/api/client.ts`:

```typescript
const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

export const api = {
  health: () => get<import("./types").HealthSnapshot | null>("/health"),
  gpu: () => get<import("./types").VramSnapshot | null>("/gpu"),
  infrastructure: () => get<import("./types").Infrastructure>("/infrastructure"),
  nudges: () => get<import("./types").Nudge[]>("/nudges"),
  briefing: () => get<import("./types").BriefingData | null>("/briefing"),
  goals: () => get<import("./types").GoalSnapshot>("/goals"),
  readiness: () => get<import("./types").ReadinessSnapshot>("/readiness"),
  agents: () => get<import("./types").AgentInfo[]>("/agents"),
  scout: () => get<import("./types").ScoutData | null>("/scout"),
  cost: () => get<import("./types").CostSnapshot>("/cost"),
};
```

**Step 3: Commit**

```bash
cd ~/projects/hapax-logos
git add src/api/
git commit -m "feat: API client with typed fetch helpers"
```

---

## Task 9: TanStack Query hooks

**Files:**
- Create: `~/projects/hapax-logos/src/api/hooks.ts`

**Step 1: Create query hooks with matching poll cadence**

Create `src/api/hooks.ts`:

```typescript
import { useQuery } from "@tanstack/react-query";
import { api } from "./client";

const FAST = 30_000; // 30s
const SLOW = 300_000; // 5min

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: FAST });

export const useGpu = () =>
  useQuery({ queryKey: ["gpu"], queryFn: api.gpu, refetchInterval: FAST });

export const useInfrastructure = () =>
  useQuery({ queryKey: ["infrastructure"], queryFn: api.infrastructure, refetchInterval: FAST });

export const useNudges = () =>
  useQuery({ queryKey: ["nudges"], queryFn: api.nudges, refetchInterval: SLOW });

export const useBriefing = () =>
  useQuery({ queryKey: ["briefing"], queryFn: api.briefing, refetchInterval: SLOW });

export const useGoals = () =>
  useQuery({ queryKey: ["goals"], queryFn: api.goals, refetchInterval: SLOW });

export const useReadiness = () =>
  useQuery({ queryKey: ["readiness"], queryFn: api.readiness, refetchInterval: SLOW });

export const useAgents = () =>
  useQuery({ queryKey: ["agents"], queryFn: api.agents, staleTime: Infinity });

export const useScout = () =>
  useQuery({ queryKey: ["scout"], queryFn: api.scout, refetchInterval: SLOW });

export const useCost = () =>
  useQuery({ queryKey: ["cost"], queryFn: api.cost, refetchInterval: SLOW });
```

**Step 2: Commit**

```bash
cd ~/projects/hapax-logos
git add src/api/hooks.ts
git commit -m "feat: TanStack Query hooks with 30s/5min polling"
```

---

## Task 10: App shell layout

**Files:**
- Modify: `~/projects/hapax-logos/src/App.tsx`
- Modify: `~/projects/hapax-logos/src/main.tsx`
- Create: `~/projects/hapax-logos/src/components/Header.tsx`
- Create: `~/projects/hapax-logos/src/components/Sidebar.tsx`
- Create: `~/projects/hapax-logos/src/components/MainPanel.tsx`

**Step 1: Set up QueryClientProvider in main.tsx**

Replace `src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 10_000 },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
);
```

**Step 2: Create Header component**

Create `src/components/Header.tsx`:

```tsx
import { Activity } from "lucide-react";
import { useHealth } from "../api/hooks";

export function Header() {
  const { data: health } = useHealth();

  const statusColor =
    health?.overall_status === "healthy"
      ? "text-green-400"
      : health?.overall_status === "degraded"
        ? "text-yellow-400"
        : health?.overall_status === "failed"
          ? "text-red-400"
          : "text-zinc-500";

  return (
    <header className="flex items-center justify-between border-b border-zinc-700 bg-zinc-900 px-4 py-2">
      <div className="flex items-center gap-2">
        <Activity className="h-5 w-5 text-zinc-400" />
        <span className="text-sm font-medium text-zinc-200">cockpit</span>
      </div>
      <div className="flex items-center gap-3 text-xs">
        <span className={statusColor}>
          {health ? `${health.healthy}/${health.total_checks} checks` : "loading..."}
        </span>
      </div>
    </header>
  );
}
```

**Step 3: Create Sidebar component**

Create `src/components/Sidebar.tsx`:

```tsx
import { useHealth, useGpu, useReadiness, useGoals, useInfrastructure } from "../api/hooks";

export function Sidebar() {
  const { data: health } = useHealth();
  const { data: gpu } = useGpu();
  const { data: readiness } = useReadiness();
  const { data: goals } = useGoals();
  const { data: infra } = useInfrastructure();

  return (
    <aside className="w-72 shrink-0 space-y-4 overflow-y-auto border-l border-zinc-700 bg-zinc-900/50 p-3 text-xs">
      {/* Health */}
      <Section title="Health">
        {health ? (
          <p className={health.overall_status === "healthy" ? "text-green-400" : "text-yellow-400"}>
            {health.overall_status} — {health.healthy}/{health.total_checks} ({health.duration_ms}ms)
          </p>
        ) : (
          <p className="text-zinc-500">loading...</p>
        )}
        {health?.failed_checks.map((c) => (
          <p key={c} className="text-red-400">✗ {c}</p>
        ))}
      </Section>

      {/* VRAM */}
      <Section title="VRAM">
        {gpu ? (
          <>
            <div className="mb-1 flex justify-between">
              <span>{gpu.name}</span>
              <span>{gpu.usage_pct.toFixed(0)}%</span>
            </div>
            <div className="h-2 rounded-full bg-zinc-700">
              <div
                className="h-2 rounded-full bg-blue-500"
                style={{ width: `${gpu.usage_pct}%` }}
              />
            </div>
            <p className="mt-1 text-zinc-500">
              {gpu.used_mb}MB / {gpu.total_mb}MB — {gpu.temperature_c}°C
            </p>
            {gpu.loaded_models.length > 0 && (
              <p className="text-zinc-400">{gpu.loaded_models.join(", ")}</p>
            )}
          </>
        ) : (
          <p className="text-zinc-500">unavailable</p>
        )}
      </Section>

      {/* Readiness */}
      <Section title="Readiness">
        {readiness ? (
          <>
            <p className="capitalize">{readiness.level}</p>
            <p className="text-zinc-500">
              {readiness.populated_dimensions}/{readiness.total_dimensions} dimensions ·{" "}
              {readiness.total_facts} facts
            </p>
            {readiness.top_gap && <p className="text-yellow-400">Gap: {readiness.top_gap}</p>}
          </>
        ) : (
          <p className="text-zinc-500">loading...</p>
        )}
      </Section>

      {/* Goals */}
      <Section title="Goals">
        {goals ? (
          <>
            <p>
              {goals.active_count} active
              {goals.stale_count > 0 && (
                <span className="text-yellow-400"> · {goals.stale_count} stale</span>
              )}
            </p>
            {goals.goals.slice(0, 4).map((g) => (
              <p key={g.id} className={g.stale ? "text-yellow-400" : "text-zinc-400"}>
                {g.stale ? "⚠ " : ""}
                {g.name}
              </p>
            ))}
          </>
        ) : (
          <p className="text-zinc-500">loading...</p>
        )}
      </Section>

      {/* Timers */}
      <Section title="Timers">
        {infra?.timers.slice(0, 5).map((t) => (
          <p key={t.unit} className="text-zinc-400">
            {t.unit.replace(".timer", "")} — {t.next_fire}
          </p>
        ))}
      </Section>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-1 font-medium text-zinc-300">{title}</h3>
      <div className="space-y-0.5 text-zinc-400">{children}</div>
    </div>
  );
}
```

**Step 4: Create MainPanel component**

Create `src/components/MainPanel.tsx`:

```tsx
import { useNudges, useAgents } from "../api/hooks";
import type { Nudge, AgentInfo } from "../api/types";

export function MainPanel() {
  const { data: nudges } = useNudges();
  const { data: agents } = useAgents();

  return (
    <main className="flex-1 space-y-4 overflow-y-auto p-4">
      <NudgeList nudges={nudges ?? []} />
      <AgentList agents={agents ?? []} />
    </main>
  );
}

function NudgeList({ nudges }: { nudges: Nudge[] }) {
  const priorityColor = {
    critical: "border-red-500 bg-red-500/10",
    high: "border-orange-500 bg-orange-500/10",
    medium: "border-yellow-500 bg-yellow-500/10",
    low: "border-zinc-600 bg-zinc-800",
  };

  return (
    <section>
      <h2 className="mb-2 text-sm font-medium text-zinc-300">
        Action Items ({nudges.length})
      </h2>
      {nudges.length === 0 ? (
        <p className="text-xs text-zinc-500">No action items right now.</p>
      ) : (
        <ul className="space-y-2">
          {nudges.map((n, i) => (
            <li
              key={`${n.source_id}-${i}`}
              className={`rounded border-l-2 p-2 text-xs ${priorityColor[n.priority_label] ?? priorityColor.low}`}
            >
              <div className="flex items-start justify-between">
                <span className="font-medium text-zinc-200">{n.title}</span>
                <span className="ml-2 shrink-0 text-zinc-500">{n.category}</span>
              </div>
              {n.detail && <p className="mt-1 text-zinc-400">{n.detail}</p>}
              {n.command_hint && (
                <code className="mt-1 block text-zinc-500">{n.command_hint}</code>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function AgentList({ agents }: { agents: AgentInfo[] }) {
  return (
    <section>
      <h2 className="mb-2 text-sm font-medium text-zinc-300">
        Agents ({agents.length})
      </h2>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {agents.map((a) => (
          <div
            key={a.name}
            className="cursor-pointer rounded border border-zinc-700 p-2 text-xs hover:border-zinc-500"
          >
            <div className="flex items-center gap-1.5">
              <span className={`h-1.5 w-1.5 rounded-full ${a.uses_llm ? "bg-blue-400" : "bg-green-400"}`} />
              <span className="font-medium text-zinc-200">{a.name}</span>
            </div>
            <p className="mt-1 text-zinc-500">{a.description}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
```

**Step 5: Wire into App.tsx**

Replace `src/App.tsx`:

```tsx
import { Header } from "./components/Header";
import { Sidebar } from "./components/Sidebar";
import { MainPanel } from "./components/MainPanel";

export default function App() {
  return (
    <div className="flex h-screen flex-col bg-zinc-950 text-zinc-100">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <MainPanel />
        <Sidebar />
      </div>
    </div>
  );
}
```

**Step 6: Remove boilerplate files**

```bash
cd ~/projects/hapax-logos
rm -f src/App.css src/assets/react.svg public/vite.svg
```

**Step 7: Verify build**

Run: `cd ~/projects/hapax-logos && pnpm run build`
Expected: Clean build.

**Step 8: Commit**

```bash
cd ~/projects/hapax-logos
git add -A
git commit -m "feat: dashboard layout with header, sidebar, nudge list, agent list"
```

---

## Task 11: Docker service definition

**Files:**
- Create: `~/projects/hapax-council/Dockerfile.api`
- Modify: `~/llm-stack/docker-compose.yml`

**Step 1: Create Dockerfile**

Create `Dockerfile.api` in `~/projects/hapax-council/`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock ./
COPY agents/ agents/
COPY cockpit/ cockpit/
COPY shared/ shared/
COPY profiles/ profiles/

# Install dependencies
RUN uv sync --frozen --no-dev

EXPOSE 8050

CMD ["uv", "run", "python", "-m", "cockpit.api", "--host", "0.0.0.0"]
```

**Step 2: Add to docker-compose.yml**

Add to `~/llm-stack/docker-compose.yml` under services:

```yaml
  cockpit-api:
    build:
      context: ~/projects/hapax-council
      dockerfile: Dockerfile.api
    container_name: cockpit-api
    restart: unless-stopped
    ports:
      - "127.0.0.1:8050:8050"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ~/projects/hapax-council/profiles:/app/profiles
      - ~/Documents/Personal:/vault:ro
    environment:
      - OBSIDIAN_VAULT_PATH=/vault
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8050/')"]
      interval: 30s
      timeout: 5s
      retries: 3
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "3"
```

**Note:** The Dockerfile and compose entry may need adjustments once tested against the real environment (systemd access from container, DBUS socket for timer queries, etc.). This is a starting point.

**Step 3: Commit**

```bash
cd ~/projects/hapax-council
git add Dockerfile.api
git commit -m "build: Dockerfile for cockpit-api service"
```

---

## Task 12: Smoke test — full stack integration

**No new files.** This is a manual verification step.

**Step 1: Start the API server locally (not Docker)**

```bash
cd ~/projects/hapax-council && uv run python -m cockpit.api --verbose &
```

**Step 2: Verify data endpoints**

```bash
curl -s http://127.0.0.1:8050/ | jq .
curl -s http://127.0.0.1:8050/api/health | jq .
curl -s http://127.0.0.1:8050/api/gpu | jq .
curl -s http://127.0.0.1:8050/api/nudges | jq .
curl -s http://127.0.0.1:8050/api/agents | jq .
```

Expected: JSON responses with real data from the running system.

**Step 3: Start the frontend dev server**

```bash
cd ~/projects/hapax-logos && pnpm run dev
```

Open `http://localhost:5173` in browser. Expected: Dashboard renders with live data from the API.

**Step 4: Test from phone over Tailscale**

Open `http://<tailscale-ip>:8050/api/health` from phone browser. Expected: JSON response.

**Step 5: Kill the API server**

```bash
kill %1  # or the PID
```

---

## Phase 1 Complete Checklist

After all 12 tasks:

- [ ] FastAPI + uvicorn + sse-starlette in pyproject.toml
- [ ] `cockpit/api/app.py` — FastAPI app with CORS + lifespan
- [ ] `cockpit/api/cache.py` — background refresh (30s/5min)
- [ ] `cockpit/api/routes/data.py` — 15 data endpoints
- [ ] `cockpit/api/__main__.py` — uvicorn entry point
- [ ] `tests/test_api.py` — endpoint tests
- [ ] `tests/test_api_cache.py` — cache tests
- [ ] `~/projects/hapax-logos/` — React SPA with dashboard
- [ ] `Dockerfile.api` — container definition
- [ ] All existing tests still pass (`uv run pytest tests/ -q`)
- [ ] Dashboard accessible from phone via Tailscale

---

## Next Phases

Phase 2 (Agent Execution), Phase 3 (Chat System), and Phase 4 (Polish/Cleanup) will be planned as separate documents when Phase 1 is deployed and validated.

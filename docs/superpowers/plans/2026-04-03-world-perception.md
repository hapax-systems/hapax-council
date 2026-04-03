# World Perception Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the DMN's imagination access to the whole world by promoting existing sensor data into the imagination context and registering all available data sources as affordances.

**Architecture:** Most data already flows to `/dev/shm/hapax-sensors/*.json` — the work is wiring it through `read_all()` into `assemble_context()` and registering affordances in Qdrant. No new data sources are created in this phase; existing ones are surfaced. New external APIs (web search, Wikipedia) are registered as affordances with `consent_required=True` but implementation is deferred to Phase 3 content resolution.

**Tech Stack:** Python 3.12, Pydantic, Qdrant, pytest, ruff

**Spec:** `docs/superpowers/specs/2026-04-03-total-affordance-field-design.md` Phase 2

---

## Key Discovery

14 sensor state files already exist in `/dev/shm/hapax-sensors/`: chrome, claude_code, gcalendar, gdrive, git, gmail, langfuse, obsidian, snapshot, sprint, stimmung, watch, weather, youtube. `read_sensors()` in `agents/dmn/sensor.py` reads them all. But `assemble_context()` in `agents/imagination.py` only renders perception, stimmung, watch, and a dead weather branch. The data is there — the imagination just can't see it.

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `agents/dmn/sensor.py` | Promote key sensors to top-level in read_all() |
| Modify | `agents/imagination.py` | Expand assemble_context() to render promoted sensors |
| Create | `shared/affordance_registry.py` | Centralized affordance definitions for ALL domains |
| Modify | `agents/reverie/_affordances.py` | Import from shared registry instead of local defs |
| Modify | `agents/hapax_daimonion/tool_affordances.py` | Import from shared registry |
| Create | `tests/test_world_perception.py` | Tests for expanded sensor layer |
| Create | `tests/test_affordance_registry.py` | Tests for centralized registry |

---

### Task 1: Promote sensors into imagination context

**Files:**
- Modify: `agents/dmn/sensor.py`
- Modify: `agents/imagination.py`
- Create: `tests/test_world_perception.py`

The core wiring fix: `read_all()` already reads `/dev/shm/hapax-sensors/weather.json` into `sensors["weather"]`, but `assemble_context()` reads `sensor_snapshot.get("weather", {})` at the top level. Same gap exists for all 13 sensor files.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_world_perception.py
"""Test that the DMN sensor layer promotes key sensors into the imagination context."""

import time
from agents.imagination import assemble_context


def test_weather_appears_in_context():
    snapshot = {
        "perception": {"activity": "idle", "flow_score": 0.3},
        "stimmung": {"stance": "nominal", "operator_stress": {"value": 0.2}},
        "watch": {"heart_rate": 72},
        "weather": {"temperature_f": 68, "humidity_pct": 45, "description": "Partly cloudy"},
    }
    ctx = assemble_context(["stable"], [], snapshot)
    assert "68" in ctx or "Partly cloudy" in ctx


def test_time_appears_in_context():
    snapshot = {
        "perception": {"activity": "coding", "flow_score": 0.7},
        "stimmung": {"stance": "nominal", "operator_stress": {"value": 0.1}},
        "watch": {"heart_rate": 65},
        "time": {"hour": 14, "period": "afternoon", "weekday": "Thursday"},
    }
    ctx = assemble_context(["active coding"], [], snapshot)
    assert "afternoon" in ctx or "14" in ctx


def test_music_appears_in_context():
    snapshot = {
        "perception": {"activity": "making_music", "flow_score": 0.9},
        "stimmung": {"stance": "nominal", "operator_stress": {"value": 0.1}},
        "watch": {"heart_rate": 80},
        "music": {"tempo_bpm": 92, "genre": "boom-bap", "mixer_energy": 0.7},
    }
    ctx = assemble_context(["active music production"], [], snapshot)
    assert "92" in ctx or "boom-bap" in ctx


def test_goals_appear_in_context():
    snapshot = {
        "perception": {"activity": "idle", "flow_score": 0.2},
        "stimmung": {"stance": "nominal", "operator_stress": {"value": 0.3}},
        "watch": {"heart_rate": 70},
        "goals": {"active_count": 3, "stale_count": 1, "top_domain": "research"},
    }
    ctx = assemble_context(["stable"], [], snapshot)
    assert "research" in ctx or "3" in ctx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_world_perception.py -v`
Expected: FAIL — weather/time/music/goals not in context

- [ ] **Step 3: Promote sensor data in read_all()**

In `agents/dmn/sensor.py`, add a promotion step at the end of `read_all()` that hoists key sensor data from `sensors` to the top level. Add before the return statement:

```python
    # Promote key sensors to top-level for imagination context
    sensors = result.get("sensors", {})
    if "weather" in sensors:
        result["weather"] = sensors["weather"]
    # Time context (always available)
    now = time.localtime()
    result["time"] = {
        "hour": now.tm_hour,
        "minute": now.tm_min,
        "period": "morning" if now.tm_hour < 12 else "afternoon" if now.tm_hour < 17 else "evening" if now.tm_hour < 21 else "night",
        "weekday": time.strftime("%A"),
        "date": time.strftime("%Y-%m-%d"),
    }
    # Music context from perception-state
    perception = result.get("perception", {})
    if perception.get("activity") in ("making_music", "listening"):
        result["music"] = {
            "genre": perception.get("music_genre", "unknown"),
            "tempo_bpm": perception.get("tempo_bpm"),
            "mixer_energy": perception.get("mixer_energy"),
        }
    # Goals from sprint sensor
    if "sprint" in sensors:
        sprint = sensors["sprint"]
        result["goals"] = {
            "active_count": sprint.get("active_measures", 0),
            "stale_count": sprint.get("stale_measures", 0),
            "top_domain": sprint.get("top_domain", "unknown"),
        }
```

- [ ] **Step 4: Expand assemble_context() to render new sections**

In `agents/imagination.py`, the `## System State` section currently has 4 conditional lines. Extend it to include the new top-level keys. After the existing Watch and Weather lines, add:

```python
    # Time
    time_ctx = sensor_snapshot.get("time", {})
    if time_ctx:
        lines.append(
            f"- Time: {time_ctx.get('period', '?')}, "
            f"{time_ctx.get('weekday', '?')} {time_ctx.get('date', '?')} "
            f"{time_ctx.get('hour', '?')}:{time_ctx.get('minute', 0):02d}"
        )
    # Music
    music = sensor_snapshot.get("music", {})
    if music:
        parts = []
        if music.get("genre"):
            parts.append(f"genre={music['genre']}")
        if music.get("tempo_bpm"):
            parts.append(f"tempo={music['tempo_bpm']}bpm")
        if music.get("mixer_energy") is not None:
            parts.append(f"energy={music['mixer_energy']:.1f}")
        if parts:
            lines.append(f"- Music: {', '.join(parts)}")
    # Goals
    goals = sensor_snapshot.get("goals", {})
    if goals:
        lines.append(
            f"- Goals: {goals.get('active_count', 0)} active, "
            f"{goals.get('stale_count', 0)} stale, "
            f"focus={goals.get('top_domain', 'unknown')}"
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_world_perception.py -v`
Expected: 4 PASS

- [ ] **Step 6: Run broader suite**

Run: `uv run pytest tests/ -q -k "imagination" --timeout=30`
Expected: no new failures

- [ ] **Step 7: Commit**

```bash
git add agents/dmn/sensor.py agents/imagination.py tests/test_world_perception.py
git commit -m "feat: promote weather, time, music, goals into imagination context

The DMN sensor layer already reads 14 sensor files from /dev/shm/hapax-sensors/
but assemble_context() only rendered 3 of them. Now promotes weather (from
weather_sync), time (computed), music (from perception-state activity), and
goals (from sprint sensor) into the imagination LLM context. The imagination
can now reason about the operator's temporal, atmospheric, musical, and
goal-oriented context."
```

---

### Task 2: Create centralized affordance registry

**Files:**
- Create: `shared/affordance_registry.py`
- Create: `tests/test_affordance_registry.py`

Move affordance definitions out of `agents/reverie/_affordances.py` and `agents/hapax_daimonion/tool_affordances.py` into a single shared registry. This is the Gibson-verb taxonomy from the spec — 9 domains, ~80 affordances.

- [ ] **Step 1: Write the test**

```python
# tests/test_affordance_registry.py
"""Test that the centralized affordance registry covers all domains."""

from shared.affordance_registry import ALL_AFFORDANCES, AFFORDANCE_DOMAINS


def test_all_domains_present():
    expected = {"env", "body", "studio", "space", "digital", "knowledge", "social", "system", "world"}
    assert set(AFFORDANCE_DOMAINS.keys()) == expected


def test_all_affordances_have_descriptions():
    for record in ALL_AFFORDANCES:
        assert len(record.description) >= 15, f"{record.name} has too-short description"
        assert record.daemon, f"{record.name} missing daemon"


def test_affordance_names_are_dot_namespaced():
    for record in ALL_AFFORDANCES:
        assert "." in record.name, f"{record.name} is not dot-namespaced"


def test_no_duplicate_names():
    names = [r.name for r in ALL_AFFORDANCES]
    assert len(names) == len(set(names)), f"Duplicate affordance names: {[n for n in names if names.count(n) > 1]}"


def test_consent_required_on_world_affordances():
    world = [r for r in ALL_AFFORDANCES if r.name.startswith("world.")]
    for r in world:
        assert r.operational.consent_required, f"{r.name} should require consent"
```

- [ ] **Step 2: Create the registry**

Create `shared/affordance_registry.py` with the full taxonomy from the spec (§5). Include all 9 domains. Each affordance is a `CapabilityRecord` with Gibson-verb description, daemon assignment, and `OperationalProperties` (latency_class, medium, consent_required).

The file should export:
- `AFFORDANCE_DOMAINS: dict[str, list[CapabilityRecord]]` — domain name → list of records
- `ALL_AFFORDANCES: list[CapabilityRecord]` — flat list of all records
- `SHADER_NODE_AFFORDANCES` — the existing 12 shader node affordances (moved from _affordances.py)
- `LEGACY_AFFORDANCES` — the existing 3 legacy affordances

Domain assignments:
- `env.*`, `body.*`, `studio.*`, `space.*` → `daemon="perception"` (they describe what can be perceived)
- `digital.*`, `social.*` → `daemon="perception"` with `latency_class="slow"`
- `knowledge.*` → `daemon="recall"` with `latency_class="slow"`
- `system.*` → `daemon="system"`
- `world.*` → `daemon="discovery"` with `consent_required=True`, `requires_network=True`
- `node.*` → `daemon="reverie"` with `latency_class="realtime"`, `medium="visual"`

Use the exact Gibson-verb descriptions from spec §5.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_affordance_registry.py -v`
Expected: 5 PASS

- [ ] **Step 4: Commit**

```bash
git add shared/affordance_registry.py tests/test_affordance_registry.py
git commit -m "feat: centralized affordance registry — 9 domains, ~80 Gibson-verb affordances

Moves affordance definitions from per-daemon files into shared/affordance_registry.py.
All affordances use dot-namespaced names (env.weather_conditions, body.heart_rate, etc.)
with Gibson-verb descriptions for Qdrant embedding. World-domain affordances require
consent. This is the shared taxonomy all faculties recruit from."
```

---

### Task 3: Wire registry into Reverie pipeline

**Files:**
- Modify: `agents/reverie/_affordances.py`

- [ ] **Step 1: Update _affordances.py to import from shared registry**

Replace the local `SHADER_NODE_AFFORDANCES`, `PERCEPTION_AFFORDANCES`, `CONTENT_AFFORDANCES`, and `LEGACY_AFFORDANCES` lists with imports from `shared/affordance_registry.py`. The `build_reverie_pipeline_affordances()` function should now return all affordances that Reverie can handle (all `node.*`, `content.*`, `space.*`, plus legacy), pulling from the shared registry.

`build_reverie_pipeline()` continues to create its own `AffordancePipeline()` instance (per SCM Property 1 — no centralized coordinator), but it indexes ALL affordances from the shared registry, not just its own.

- [ ] **Step 2: Run existing Reverie tests**

Run: `uv run pytest tests/ -q -k "reverie or visual_chain or affordance" --timeout=30`
Expected: no new failures

- [ ] **Step 3: Commit**

```bash
git add agents/reverie/_affordances.py
git commit -m "refactor: Reverie imports affordances from shared registry

build_reverie_pipeline_affordances() now pulls from shared/affordance_registry.py
instead of local definitions. Reverie's AffordancePipeline indexes ALL shared
affordances (not just visual ones) so it can see the full world and route
to other faculties via cross-daemon activation summaries."
```

---

### Task 4: Register all perception backends as affordances

**Files:**
- Modify: `shared/affordance_registry.py` (add perception backend affordances if not already covered by §5 taxonomy)

This task ensures that every signal from the 22 perception backends has a corresponding affordance in the registry. Many are already covered by the taxonomy in Task 2 (e.g., `body.heart_rate` covers WatchBackend's HR signal, `studio.midi_beat` covers MidiClockBackend). Verify coverage and add any missing ones.

- [ ] **Step 1: Audit coverage**

Compare the 22 backends (from `agents/hapax_daimonion/init_backends.py`) against the registry. List any backend signals without a corresponding affordance.

- [ ] **Step 2: Add missing affordances**

For each unregistered backend signal, add a CapabilityRecord with Gibson-verb description to the appropriate domain in `shared/affordance_registry.py`.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_affordance_registry.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add shared/affordance_registry.py
git commit -m "feat: register all perception backend signals as affordances

Ensures every signal from the 22 perception backends has a corresponding
Gibson-verb affordance in the shared registry. The affordance pipeline can
now recruit any sensor signal in the system."
```

---

## Execution Notes

- **Do not touch** `agents/hapax_daimonion/conversation_pipeline.py` — experiment freeze
- Task 1 is the critical wiring fix — it gives imagination access to weather, time, music, goals
- Task 2 creates the shared taxonomy — this is the largest task (writing ~80 Gibson-verb descriptions)
- Task 3 refactors Reverie to use the shared registry — backward compatible
- Task 4 is an audit/coverage task — ensures no perception signals are invisible to recruitment
- After all tasks: restart `logos-api` and the imagination daemon to pick up changes

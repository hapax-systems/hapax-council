# Vision Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 1-of-17 signal gap between the dense vision stack (YOLO-World, SCRFD, MediaPipe, Places365, SigLIP-2, ByteTrack) and the livestream director. Ship 3 phased integrations behind feature flags.

**Architecture:** New `agents/studio_compositor/scene_family_router.py` consumes `per_camera_scenes`; operator-editable `config/scene-family-map.yaml`; object-presence ward triggers via `SceneInventory` reads; one-line hero-gate in `dispatch_camera_hero`.

**Tech Stack:** Python 3.12+, Pydantic, YAML, existing `perception-state.json` flowchart
---

## Reference Material

- Spec: `docs/superpowers/specs/2026-04-18-vision-integration-design.md`
- Research: `tmp/cvs-research-150.md`
- Adjacent tasks: #135 (camera naming, hard dep for Phase 1), #121 (HARDM), #158 (director no-op)

## Global Preconditions

- Working directory: the cascade worktree (check `pwd` matches the worktree slug you were dispatched into)
- Branch: per session policy (alpha or beta), never switch
- `uv sync --all-extras` already satisfied
- TDD throughout: write failing test first, implement, re-run
- Commits: conventional (`feat:`, `test:`, `fix:`, `docs:`), one per checkpoint
- Feature flags read per-tick; no restart required to toggle off

---

## Phase 0 — Feature-Flag Plumbing

### Task 0.1 — Inspect existing feature-flag module

**Files:**
- `shared/feature_flags.py` (read-only inspection)

**Steps:**
- [ ] Open `shared/feature_flags.py`. Note the existing flag pattern (env var name, default, read site).
- [ ] If the module does not exist, skip to Task 0.2. Otherwise record the exact signature (e.g., `bool_flag(name, default)`).

**Command:**
```
ls shared/feature_flags.py || echo "MISSING — create in 0.2"
```

**Expected output:** either the file path is echoed, or `MISSING — create in 0.2`.

**No commit.** This is reconnaissance.

### Task 0.2 — Add the three new flags

**Files:**
- `shared/feature_flags.py` (new or amended)
- `tests/shared/test_feature_flags.py` (new if file absent, else appended)

**Steps:**
- [ ] Write a failing test that asserts `scene_bias_enabled()`, `object_wards_enabled()`, and `hero_gate_enabled()` return `False`, `False`, `True` respectively with a clean env.
- [ ] Write a second test that asserts each flipping to its opposite when the corresponding env var is set to `"1"`.
- [ ] Implement the three accessor functions:

```python
# shared/feature_flags.py
import os

def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")

def scene_bias_enabled() -> bool:
    return _bool_env("HAPAX_VISION_SCENE_BIAS", default=False)

def object_wards_enabled() -> bool:
    return _bool_env("HAPAX_VISION_OBJECT_WARDS", default=False)

def hero_gate_enabled() -> bool:
    return _bool_env("HAPAX_VISION_HERO_GATE", default=True)
```

- [ ] Run `uv run pytest tests/shared/test_feature_flags.py -q`.

**Expected output:** `4 passed`.

**Commit:** `feat(vision): add three feature flags for phased vision integration`

---

## Phase 1 (P0) — Scene → Preset-Family Bias

### Task 1.1 — Seed `config/scene-family-map.yaml`

**Files:**
- `config/scene-family-map.yaml` (new)

**Steps:**
- [ ] Create the file with the spec-prescribed defaults and explanatory header:

```yaml
# Scene label (SigLIP-2 or Places365) → preset family bias.
# Operator-editable. Missing key → no bias (router no-ops).
# Families must match compositional_consumer.dispatch_preset_bias keys.
turntable: fx.family.audio-reactive
mpc_station: fx.family.audio-reactive
modular_rack: fx.family.generative-field
desk_work: fx.family.text-mode
room_wide: fx.family.ambient
kitchen: fx.family.ambient
empty_studio: fx.family.ambient
```

- [ ] Verify YAML parses:

```
uv run python -c "import yaml,pathlib; print(len(yaml.safe_load(pathlib.Path('config/scene-family-map.yaml').read_text())))"
```

**Expected output:** `7`.

**Commit:** `feat(vision): seed scene-family map with 7 default scene->family bindings`

### Task 1.2a — Write failing tests for `scene_family_router`

**Files:**
- `tests/agents/studio_compositor/test_scene_family_router.py` (new)

**Steps:**
- [ ] Create the test module. Each test is self-contained (no conftest). Use `unittest.mock` only.

```python
# tests/agents/studio_compositor/test_scene_family_router.py
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from agents.studio_compositor.scene_family_router import SceneFamilyRouter

SEED = {
    "turntable": "fx.family.audio-reactive",
    "desk_work": "fx.family.text-mode",
    "kitchen": "fx.family.ambient",
}


@pytest.fixture
def map_path(tmp_path: Path) -> Path:
    p = tmp_path / "scene-family-map.yaml"
    p.write_text(yaml.safe_dump(SEED))
    return p


def test_emits_family_on_first_scene(map_path):
    router = SceneFamilyRouter(map_path=map_path, debounce_seconds=20.0)
    out = router.tick(hero_role="desk", per_camera_scenes={"desk": "desk_work"}, now=100.0)
    assert out == [("fx.family.text-mode", 0.4)]


def test_debounces_same_family(map_path):
    router = SceneFamilyRouter(map_path=map_path, debounce_seconds=20.0)
    router.tick(hero_role="desk", per_camera_scenes={"desk": "desk_work"}, now=100.0)
    out = router.tick(hero_role="desk", per_camera_scenes={"desk": "desk_work"}, now=110.0)
    assert out == []


def test_refires_after_debounce(map_path):
    router = SceneFamilyRouter(map_path=map_path, debounce_seconds=20.0)
    router.tick(hero_role="desk", per_camera_scenes={"desk": "desk_work"}, now=100.0)
    out = router.tick(hero_role="desk", per_camera_scenes={"desk": "desk_work"}, now=121.0)
    assert out == [("fx.family.text-mode", 0.4)]


def test_unknown_scene_noops(map_path):
    router = SceneFamilyRouter(map_path=map_path, debounce_seconds=20.0)
    out = router.tick(hero_role="desk", per_camera_scenes={"desk": "garage"}, now=100.0)
    assert out == []


def test_missing_hero_role_noops(map_path):
    router = SceneFamilyRouter(map_path=map_path, debounce_seconds=20.0)
    out = router.tick(hero_role="desk", per_camera_scenes={}, now=100.0)
    assert out == []


def test_scene_change_fires_new_family(map_path):
    router = SceneFamilyRouter(map_path=map_path, debounce_seconds=20.0)
    router.tick(hero_role="room", per_camera_scenes={"room": "desk_work"}, now=100.0)
    out = router.tick(hero_role="room", per_camera_scenes={"room": "turntable"}, now=105.0)
    assert out == [("fx.family.audio-reactive", 0.4)]


def test_hero_switch_treated_as_scene_change(map_path):
    router = SceneFamilyRouter(map_path=map_path, debounce_seconds=20.0)
    router.tick(
        hero_role="desk",
        per_camera_scenes={"desk": "desk_work", "overhead": "turntable"},
        now=100.0,
    )
    out = router.tick(
        hero_role="overhead",
        per_camera_scenes={"desk": "desk_work", "overhead": "turntable"},
        now=105.0,
    )
    assert out == [("fx.family.audio-reactive", 0.4)]
```

- [ ] Run the tests; all 7 should fail with `ModuleNotFoundError`.

**Commit:** `test(vision): pin scene_family_router contract (7 cases)`

### Task 1.2b — Implement `scene_family_router.py`

**Files:**
- `agents/studio_compositor/scene_family_router.py` (new)

**Steps:**
- [ ] Write the module. Keep LOC under ~180 per spec §8.

```python
# agents/studio_compositor/scene_family_router.py
"""Scene -> preset-family router.

Reads ``per_camera_scenes[hero_role]`` from the perceptual field, looks up
an operator-editable YAML map, and emits ``preset.bias.<family>`` intents
with 20s per-family debounce.

Feature flag: ``HAPAX_VISION_SCENE_BIAS`` (read by the twitch director, not here).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml

SALIENCE = 0.4


@dataclass
class SceneFamilyRouter:
    map_path: Path
    debounce_seconds: float = 20.0
    _map: dict[str, str] = field(init=False)
    _last_emit: dict[str, float] = field(default_factory=dict, init=False)
    _last_scene: str | None = field(default=None, init=False)
    _last_hero: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._map = self._load_map(self.map_path)

    @staticmethod
    def _load_map(path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        raw = yaml.safe_load(path.read_text()) or {}
        return {str(k): str(v) for k, v in raw.items()}

    def tick(
        self,
        *,
        hero_role: str | None,
        per_camera_scenes: Mapping[str, str],
        now: float,
    ) -> list[tuple[str, float]]:
        """Return list of (family_intent, salience) to emit this tick."""
        if hero_role is None:
            return []
        scene = per_camera_scenes.get(hero_role)
        if scene is None:
            return []
        family = self._map.get(scene)
        if family is None:
            return []

        hero_changed = hero_role != self._last_hero
        scene_changed = scene != self._last_scene
        self._last_hero = hero_role
        self._last_scene = scene

        last = self._last_emit.get(family, float("-inf"))
        if not (hero_changed or scene_changed):
            if now - last < self.debounce_seconds:
                return []
        if now - last < self.debounce_seconds and not (hero_changed or scene_changed):
            return []

        self._last_emit[family] = now
        return [(family, SALIENCE)]
```

- [ ] Run `uv run pytest tests/agents/studio_compositor/test_scene_family_router.py -q`.

**Expected output:** `7 passed`.

- [ ] Run `uv run ruff check agents/studio_compositor/scene_family_router.py` and `uv run ruff format agents/studio_compositor/scene_family_router.py`.

**Expected output:** `All checks passed!` and no diff after format.

**Commit:** `feat(vision): implement SceneFamilyRouter with YAML-driven map + 20s debounce`

### Task 1.3a — Locate `dispatch_preset_bias` call surface

**Files:**
- `agents/studio_compositor/twitch_director.py` (read-only)
- `agents/studio_compositor/compositional_consumer.py` (read-only)

**Steps:**
- [ ] Confirm `compositional_consumer.dispatch_preset_bias` accepts `fx.family.<family>` strings. Grep for the function and note the call signature.
- [ ] Locate the `_emit_if_cool` machinery in `twitch_director`. Note the existing cooldown table structure.
- [ ] Locate the `tick_once` entry point and where it reads `field.visual`.

**Command:**
```
grep -n "dispatch_preset_bias\|_emit_if_cool\|tick_once\|field.visual" agents/studio_compositor/twitch_director.py agents/studio_compositor/compositional_consumer.py
```

**No commit.** Reconnaissance only.

### Task 1.3b — Wire router into `tick_once`

**Files:**
- `agents/studio_compositor/twitch_director.py` (edit)

**Steps:**
- [ ] At module top, import the router and the feature-flag accessor:

```python
from pathlib import Path

from shared.feature_flags import scene_bias_enabled
from agents.studio_compositor.scene_family_router import SceneFamilyRouter
```

- [ ] In the twitch-director constructor, instantiate the router lazily once per process:

```python
self._scene_family_router = SceneFamilyRouter(
    map_path=Path("config/scene-family-map.yaml"),
    debounce_seconds=20.0,
)
```

- [ ] Inside `tick_once`, after the existing `field.visual` reads, add:

```python
if scene_bias_enabled():
    hero_role = self._current_hero_role()  # reuse existing accessor
    per_camera_scenes = getattr(field.visual, "per_camera_scenes", {}) or {}
    for family, salience in self._scene_family_router.tick(
        hero_role=hero_role,
        per_camera_scenes=per_camera_scenes,
        now=now,
    ):
        self._dispatch_preset_bias(family, salience=salience, source="scene-family-router")
```

- [ ] If `_current_hero_role` does not exist, locate how hero role is tracked today (likely `self._hero_role` or similar) and use that accessor. Never invent a new field.

### Task 1.3c — Integration test for the wiring

**Files:**
- `tests/agents/studio_compositor/test_twitch_director_scene_bias.py` (new)

**Steps:**
- [ ] Write a test that constructs a twitch director with a fake `PerceptualField`, flips the env flag via `monkeypatch.setenv("HAPAX_VISION_SCENE_BIAS", "1")`, invokes `tick_once`, and asserts `dispatch_preset_bias` was called with `"fx.family.audio-reactive"`.
- [ ] Write a second test asserting that with the flag unset, the dispatcher is NOT called for family bias.

```python
# tests/agents/studio_compositor/test_twitch_director_scene_bias.py
from unittest.mock import MagicMock

import pytest


def _make_field(hero_scene: str, hero_role: str = "overhead"):
    field = MagicMock()
    field.visual.per_camera_scenes = {hero_role: hero_scene}
    field.visual.detected_action = "present"
    return field


@pytest.mark.skip(reason="fill in fixture once twitch_director constructor is confirmed")
def test_tick_emits_family_bias_when_flag_on(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPAX_VISION_SCENE_BIAS", "1")
    # Construct minimal director, stub dispatcher, invoke tick_once.
    ...


@pytest.mark.skip(reason="fill in fixture once twitch_director constructor is confirmed")
def test_tick_skips_family_bias_when_flag_off(monkeypatch, tmp_path):
    monkeypatch.delenv("HAPAX_VISION_SCENE_BIAS", raising=False)
    ...
```

- [ ] Remove the `skip` markers once the fixture shape is known from reading `twitch_director.py`. Expected final state: both tests pass.
- [ ] Run `uv run pytest tests/agents/studio_compositor/test_twitch_director_scene_bias.py -q`.

**Expected output:** `2 passed`.

**Commit:** `feat(vision): wire SceneFamilyRouter into twitch_director.tick_once behind HAPAX_VISION_SCENE_BIAS`

### Task 1.4 — Confirm flag default is OFF

**Files:**
- `shared/feature_flags.py` (verify, already done in Task 0.2)
- `systemd/hapax-studio-compositor.service` or equivalent (verify not exporting the flag)

**Steps:**
- [ ] Grep systemd unit files for `HAPAX_VISION_SCENE_BIAS`. Expect zero hits.

```
grep -r HAPAX_VISION_SCENE_BIAS systemd/ .envrc 2>/dev/null
```

**Expected output:** empty.

- [ ] Run suite to confirm nothing regresses:

```
uv run pytest tests/ -q -k "scene_family or twitch_director or feature_flag"
```

**Expected output:** all green.

**No commit** (nothing changed).

### Task 1.5 — 30-minute livestream smoke test

**Files:** none modified.

**Steps:**
- [ ] `hapax-working-mode rnd` (or confirm already in rnd).
- [ ] Export the flag in a terminal and restart compositor:

```
HAPAX_VISION_SCENE_BIAS=1 systemctl --user restart hapax-studio-compositor
```

- [ ] Tail the compositor log for `preset.bias.fx.family.` dispatches. Expect at least one emission when hero camera changes scene.

```
journalctl --user -u hapax-studio-compositor -f | grep "preset.bias"
```

- [ ] Operator walks between turntable / desk / kitchen over 30 minutes. Note emissions in a scratch log.
- [ ] Confirm debounce: two `turntable` ticks within 20s produce one emission, not two.
- [ ] If smoke passes, persist the env export in the systemd drop-in (operator decision; not in this plan).
- [ ] If smoke fails, `unset HAPAX_VISION_SCENE_BIAS` and restart; system reverts to Phase 0 behavior.

**Commit (docs only, optional):** `docs(vision): record Phase 1 smoke-test notes under handoff`

---

## Phase 2 (P0) — Object-Presence Ward Triggers

### Task 2.0 — Seed `config/object-ward-map.yaml`

**Files:**
- `config/object-ward-map.yaml` (new)

**Steps:**
- [ ] Create the file per spec §5.

```yaml
# Object label -> ward intent. Queried against SceneInventory.
# Each rule: label, required mobility (static|dynamic|any), ward intent, TTL seconds.
- label: book
  mobility: static
  recency_max_seconds: 60
  ward: ward.highlight.citation.foreground
  ttl_seconds: 15
- label: guitar
  mobility: dynamic
  recency_max_seconds: 30
  ward: ward.appearance.instrument.tint-warm
  ttl_seconds: 20
  also_bias: fx.family.audio-reactive
- label: keyboard
  mobility: dynamic
  recency_max_seconds: 30
  ward: ward.appearance.instrument.tint-warm
  ttl_seconds: 20
  also_bias: fx.family.audio-reactive
```

- [ ] Validate YAML:

```
uv run python -c "import yaml,pathlib; print(len(yaml.safe_load(pathlib.Path('config/object-ward-map.yaml').read_text())))"
```

**Expected output:** `3`.

**Commit:** `feat(vision): seed object-ward map (book, guitar, keyboard)`

### Task 2.1a — Write failing tests for `object_ward_router`

**Files:**
- `tests/agents/studio_compositor/test_object_ward_router.py` (new)

**Steps:**
- [ ] Build hand-crafted `SceneInventory` fakes (a Protocol-satisfying stub with `by_label(label)` and `recent(seconds)` methods).

```python
# tests/agents/studio_compositor/test_object_ward_router.py
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from agents.studio_compositor.object_ward_router import ObjectWardRouter


@dataclass
class FakeEntry:
    label: str
    mobility: str
    last_seen_age_seconds: float


class FakeInventory:
    def __init__(self, entries: list[FakeEntry], recent_labels: list[str]):
        self._entries = entries
        self._recent_labels = recent_labels

    def by_label(self, label: str) -> list[FakeEntry]:
        return [e for e in self._entries if e.label == label]

    def recent(self, seconds: float) -> list[str]:
        return list(self._recent_labels)


MAP = [
    {
        "label": "book",
        "mobility": "static",
        "recency_max_seconds": 60,
        "ward": "ward.highlight.citation.foreground",
        "ttl_seconds": 15,
    },
    {
        "label": "guitar",
        "mobility": "dynamic",
        "recency_max_seconds": 30,
        "ward": "ward.appearance.instrument.tint-warm",
        "ttl_seconds": 20,
        "also_bias": "fx.family.audio-reactive",
    },
]


@pytest.fixture
def map_path(tmp_path: Path) -> Path:
    p = tmp_path / "object-ward-map.yaml"
    p.write_text(yaml.safe_dump(MAP))
    return p


def test_static_book_emits_citation_ward(map_path):
    router = ObjectWardRouter(map_path=map_path, novelty_window_seconds=600)
    inv = FakeInventory([FakeEntry("book", "static", 10.0)], recent_labels=["book"])
    out = router.tick(inventory=inv, now=0.0)
    assert ("ward.highlight.citation.foreground", 15, None) in out


def test_stale_book_noops(map_path):
    router = ObjectWardRouter(map_path=map_path, novelty_window_seconds=600)
    inv = FakeInventory([FakeEntry("book", "static", 120.0)], recent_labels=[])
    out = router.tick(inventory=inv, now=0.0)
    assert out == []


def test_dynamic_guitar_emits_ward_and_bias(map_path):
    router = ObjectWardRouter(map_path=map_path, novelty_window_seconds=600)
    inv = FakeInventory([FakeEntry("guitar", "dynamic", 5.0)], recent_labels=["guitar"])
    out = router.tick(inventory=inv, now=0.0)
    assert ("ward.appearance.instrument.tint-warm", 20, "fx.family.audio-reactive") in out


def test_novel_label_fires_once(map_path):
    router = ObjectWardRouter(map_path=map_path, novelty_window_seconds=600)
    inv1 = FakeInventory([], recent_labels=["tambourine"])
    out1 = router.tick(inventory=inv1, now=0.0)
    wards1 = [w for w, _, _ in out1]
    assert "ward.staging.novelty-cue.top" in wards1
    inv2 = FakeInventory([], recent_labels=["tambourine"])
    out2 = router.tick(inventory=inv2, now=5.0)
    wards2 = [w for w, _, _ in out2]
    assert "ward.staging.novelty-cue.top" not in wards2


def test_mobility_mismatch_suppresses(map_path):
    router = ObjectWardRouter(map_path=map_path, novelty_window_seconds=600)
    inv = FakeInventory([FakeEntry("book", "dynamic", 10.0)], recent_labels=["book"])
    out = router.tick(inventory=inv, now=0.0)
    assert out == []
```

- [ ] Run tests; expect `ModuleNotFoundError`.

**Commit:** `test(vision): pin object_ward_router contract (5 cases)`

### Task 2.1b — Implement `object_ward_router.py`

**Files:**
- `agents/studio_compositor/object_ward_router.py` (new)

**Steps:**
- [ ] Write the module.

```python
# agents/studio_compositor/object_ward_router.py
"""Object-presence -> ward router.

Pure read-only queries against ``SceneInventory``. No new inference.

Emits tuples ``(ward_intent, ttl_seconds, optional_bias_family)``.
Feature flag is checked by the caller (twitch director).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

NOVELTY_WARD = "ward.staging.novelty-cue.top"
NOVELTY_TTL = 8


class InventoryLike(Protocol):
    def by_label(self, label: str) -> list[Any]: ...
    def recent(self, seconds: float) -> list[str]: ...


@dataclass
class _Rule:
    label: str
    mobility: str
    recency_max_seconds: float
    ward: str
    ttl_seconds: int
    also_bias: str | None = None


@dataclass
class ObjectWardRouter:
    map_path: Path
    novelty_window_seconds: float = 600.0
    _rules: list[_Rule] = field(init=False)
    _known_labels: set[str] = field(default_factory=set, init=False)
    _last_novelty_emit: float = field(default=float("-inf"), init=False)

    def __post_init__(self) -> None:
        self._rules = self._load_rules(self.map_path)

    @staticmethod
    def _load_rules(path: Path) -> list[_Rule]:
        if not path.exists():
            return []
        raw = yaml.safe_load(path.read_text()) or []
        return [
            _Rule(
                label=str(r["label"]),
                mobility=str(r.get("mobility", "any")),
                recency_max_seconds=float(r.get("recency_max_seconds", 60)),
                ward=str(r["ward"]),
                ttl_seconds=int(r.get("ttl_seconds", 15)),
                also_bias=(str(r["also_bias"]) if r.get("also_bias") else None),
            )
            for r in raw
        ]

    def tick(
        self,
        *,
        inventory: InventoryLike,
        now: float,
    ) -> list[tuple[str, int, str | None]]:
        out: list[tuple[str, int, str | None]] = []
        for rule in self._rules:
            hits = inventory.by_label(rule.label)
            for hit in hits:
                mobility = getattr(hit, "mobility", "any")
                age = getattr(hit, "last_seen_age_seconds", float("inf"))
                if rule.mobility != "any" and mobility != rule.mobility:
                    continue
                if age > rule.recency_max_seconds:
                    continue
                out.append((rule.ward, rule.ttl_seconds, rule.also_bias))
                break  # one emission per rule per tick

        current_recent = set(inventory.recent(30.0))
        novel = current_recent - self._known_labels
        if novel and (now - self._last_novelty_emit) >= self.novelty_window_seconds:
            out.append((NOVELTY_WARD, NOVELTY_TTL, None))
            self._last_novelty_emit = now
        self._known_labels |= current_recent

        return out
```

- [ ] Run `uv run pytest tests/agents/studio_compositor/test_object_ward_router.py -q`.

**Expected output:** `5 passed`.

- [ ] Run `uv run ruff check agents/studio_compositor/object_ward_router.py`.

**Expected output:** `All checks passed!`.

**Commit:** `feat(vision): implement ObjectWardRouter with static/dynamic/novelty rules`

### Task 2.2 — Wire router into `twitch_director.tick_once`

**Files:**
- `agents/studio_compositor/twitch_director.py` (edit)

**Steps:**
- [ ] Import:

```python
from shared.feature_flags import object_wards_enabled
from agents.studio_compositor.object_ward_router import ObjectWardRouter
```

- [ ] In constructor:

```python
self._object_ward_router = ObjectWardRouter(
    map_path=Path("config/object-ward-map.yaml"),
    novelty_window_seconds=600.0,
)
```

- [ ] Acquire a `SceneInventory` reference. `scene_inventory.py` in `agents/hapax_daimonion/` is canonical; the director must read a shared view. If no accessor exists, add one via the perceptual-field bridge. Grep first:

```
grep -rn "SceneInventory\|scene_inventory" agents/studio_compositor agents/hapax_daimonion
```

- [ ] Inside `tick_once`, after the scene-family-router block, add:

```python
if object_wards_enabled():
    inv = self._scene_inventory()  # returns None or an InventoryLike
    if inv is not None:
        for ward, ttl, bias in self._object_ward_router.tick(inventory=inv, now=now):
            self._dispatch_ward(ward, ttl_seconds=ttl, source="object-ward-router")
            if bias is not None:
                self._dispatch_preset_bias(bias, salience=0.4, source="object-ward-router")
```

- [ ] If `_dispatch_ward` does not exist, use whatever call pattern `compositional_consumer` already exposes for `ward.highlight.*` / `ward.appearance.*` / `ward.staging.*`. Never invent new dispatcher functions.

### Task 2.2b — Integration test for the wiring

**Files:**
- `tests/agents/studio_compositor/test_twitch_director_object_wards.py` (new)

**Steps:**
- [ ] Write a test that seeds a fake inventory (book static, last_seen 10s), flips `HAPAX_VISION_OBJECT_WARDS=1`, invokes `tick_once`, asserts ward dispatcher received `ward.highlight.citation.foreground`.
- [ ] Write a second test asserting that with the flag unset, no ward dispatches occur.
- [ ] Run `uv run pytest tests/agents/studio_compositor/test_twitch_director_object_wards.py -q`.

**Expected output:** `2 passed`.

**Commit:** `feat(vision): wire ObjectWardRouter into twitch_director behind HAPAX_VISION_OBJECT_WARDS`

### Task 2.3 — Confirm flag default OFF

**Files:** none modified.

**Steps:**
- [ ] Grep systemd unit for `HAPAX_VISION_OBJECT_WARDS`. Expect empty.

```
grep -r HAPAX_VISION_OBJECT_WARDS systemd/ .envrc 2>/dev/null
```

**Expected output:** empty.

**No commit.**

### Task 2.4 — 30-minute smoke test

**Steps:**
- [ ] `HAPAX_VISION_OBJECT_WARDS=1 systemctl --user restart hapax-studio-compositor`.
- [ ] Place a book on desk → confirm `ward.highlight.citation.foreground` fires within two ticks.
- [ ] Bring guitar or MIDI keyboard on-camera → confirm `ward.appearance.instrument.tint-warm` and `fx.family.audio-reactive` both dispatch.
- [ ] Introduce a novel object never seen in the prior 10 min → confirm `ward.staging.novelty-cue.top` fires exactly once.
- [ ] Watch for cross-talk with Phase 1 family bias. No regressions expected because routers operate on disjoint keys.
- [ ] If smoke fails, `unset HAPAX_VISION_OBJECT_WARDS` and restart.

**Commit (docs):** `docs(vision): record Phase 2 smoke-test notes`

---

## Phase 3 (P0) — `per_camera_person_count` Hero Gate

### Task 3.1a — Read current `dispatch_camera_hero` logic

**Files:**
- `agents/studio_compositor/objective_hero_switcher.py` (read-only)

**Steps:**
- [ ] Open the file. Locate `dispatch_camera_hero`. Note where candidates are ranked and where a hero is ultimately selected.
- [ ] Note how `PerceptualField` reaches this function (parameter, attribute, or getter).
- [ ] Locate `detected_action == "away"` handling to preserve the fallback path.

**No commit.**

### Task 3.1b — Add the gate

**Files:**
- `agents/studio_compositor/objective_hero_switcher.py` (edit)

**Steps:**
- [ ] Import the flag:

```python
from shared.feature_flags import hero_gate_enabled
```

- [ ] In `dispatch_camera_hero`, after candidates are computed and before final selection, add:

```python
if hero_gate_enabled():
    counts = getattr(field.visual, "per_camera_person_count", {}) or {}
    non_empty = [c for c in candidates if counts.get(c.role, 0) > 0]
    if non_empty:
        candidates = non_empty
    # else: all cameras empty — preserve existing behavior
    # (detected_action='away' fallback path, etc.)
```

- [ ] Exact variable names (`candidates`, `c.role`, `field`) must match what the file already uses. Adjust names during edit, do not invent.

### Task 3.2 — Regression tests

**Files:**
- `tests/agents/studio_compositor/test_objective_hero_switcher.py` (edit or new)

**Steps:**
- [ ] Add three cases:

```python
def test_hero_skips_empty_camera(monkeypatch):
    monkeypatch.setenv("HAPAX_VISION_HERO_GATE", "1")
    # Build PerceptualField with per_camera_person_count={"a":0, "b":2}
    # Assert chosen hero is "b".
    ...


def test_hero_preserved_when_all_empty(monkeypatch):
    monkeypatch.setenv("HAPAX_VISION_HERO_GATE", "1")
    # per_camera_person_count={"a":0,"b":0}, detected_action="away"
    # Assert current fallback behavior preserved.
    ...


def test_hero_unchanged_when_flag_off(monkeypatch):
    monkeypatch.delenv("HAPAX_VISION_HERO_GATE", raising=False)
    # per_camera_person_count={"a":0,"b":2}
    # Assert behavior matches pre-gate selection regardless of counts.
    ...
```

- [ ] Flesh in the fixture using the same construction pattern the existing tests in this file already use. No new helpers.
- [ ] Run `uv run pytest tests/agents/studio_compositor/test_objective_hero_switcher.py -q`.

**Expected output:** all green.

**Commit:** `feat(vision): gate empty cameras out of hero selection behind HAPAX_VISION_HERO_GATE (default on)`

### Task 3.3 — Confirm flag default ON

**Files:** none modified.

**Steps:**
- [ ] Verify Task 0.2 default for `hero_gate_enabled` is `True`.
- [ ] Grep systemd units for the flag; absence is fine because the default is on.

```
grep -r HAPAX_VISION_HERO_GATE systemd/ 2>/dev/null
```

**Expected output:** empty (default-on, no unit plumbing needed).

**No commit.**

### Task 3.4 — Smoke test

**Steps:**
- [ ] `systemctl --user restart hapax-studio-compositor` (flag on by default; no env needed).
- [ ] Operator steps out of frame of one camera while remaining in another. Confirm hero does NOT switch to the empty camera when alternatives exist.
- [ ] Operator leaves ALL cameras (detected_action goes to "away"). Confirm behavior matches pre-gate: current away handling preserved, no infinite-switch loop.
- [ ] If regression observed, `HAPAX_VISION_HERO_GATE=0` + restart to revert.

**Commit (docs):** `docs(vision): record Phase 3 smoke-test notes`

---

## Cross-Phase Verification

### Final Task — Full test suite + ruff + pyright

**Steps:**
- [ ] `uv run pytest tests/ -q -k "scene_family or object_ward or hero_switcher or feature_flag or twitch_director"`.

**Expected output:** all green.

- [ ] `uv run ruff check agents/studio_compositor/ shared/feature_flags.py`.

**Expected output:** `All checks passed!`.

- [ ] `uv run ruff format --check agents/studio_compositor/ shared/feature_flags.py`.

**Expected output:** no diff.

- [ ] `uv run pyright agents/studio_compositor/scene_family_router.py agents/studio_compositor/object_ward_router.py`.

**Expected output:** `0 errors`.

- [ ] If all three phases smoke-tested green in rnd mode, the phase-1 and phase-2 flags stay off by default but are wired; operator flips per session.

**No commit** (verification only).

---

## Rollback Table

| Phase | Flag | Default | Rollback |
|---|---|---|---|
| 1 | `HAPAX_VISION_SCENE_BIAS` | off | `unset` env var + `systemctl --user restart hapax-studio-compositor`. Router no-ops. |
| 2 | `HAPAX_VISION_OBJECT_WARDS` | off | `unset` env + restart. Ward router skipped. |
| 3 | `HAPAX_VISION_HERO_GATE` | on | `HAPAX_VISION_HERO_GATE=0` + restart. Hero switcher reverts to count-blind. |

All flags re-read every tick (~4s); toggle-off during a live session is safe without restart once flags are in the unit's `Environment=`.

---

## Open Questions (Deferred from Spec §11)

1. Debounce windows operator-tunable (YAML) or hard-coded? This plan hard-codes `20.0`/`600.0` as the default; pulling them into YAML is a +15m follow-up.
2. SigLIP-2 confidence floor (proposed 0.55). Not in this plan; Phase 1 accepts any returned label. Follow-up after smoke.
3. Multi-hero arbitration: this plan treats hero change as a scene change (verified in Task 1.2a test 7).
4. Prompt hint to `director_loop.py` acknowledging twitch autonomy — defer to post-smoke.
5. Phase 4+ integrations (emotion ward-appearance, scene-novelty -> Reverie, gesture intent) gated on Phases 1–3 stability + #121 HARDM landing.

---

## Dependency Sequencing

| Dep | Notes |
|---|---|
| **#135 camera naming** | Must land before Phase 1 smoke. `scene-family-map.yaml` keys on camera `role` strings stabilized by #135. If #135 has not landed when this plan begins, Phase 1 unit tests still pass (they mock roles), but smoke must wait. |
| **#121 HARDM** | Not a blocker. This plan publishes the signals HARDM will render. |
| **#136 follow-mode** | Shares the YOLO track layer. Coordinate on ByteTrack surface; no structural blocker. |
| **#158 director no-op** | This plan partially remediates: Phases 1–3 give the deterministic director three more reasons to act. |

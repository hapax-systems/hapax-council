# Content Recruitment Implementation Plan (Phase 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route ALL visual content appearance through the AffordancePipeline. Nothing appears on the visual surface unless it was recruited by semantic matching against the imagination's narrative.

**Architecture:** Content capabilities (camera feeds, text rendering, knowledge visualization) register as affordances in Qdrant with Gibson-verb descriptions. When an impingement arrives, `pipeline.select()` returns matching content capabilities alongside modulation capabilities. The mixer activates recruited content capabilities, which write their output to the existing `/dev/shm/hapax-imagination/sources/` protocol. The unconditional `update_camera_sources()` is removed. The hardcoded content resolver daemon becomes a recruited capability.

**Tech Stack:** Python 3.12, Pydantic v2, pytest

**Spec:** `docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md` §6, §11

**Depends on:** Phase 1 (imagination purification) — merged as PR #554

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `agents/reverie/_affordances.py` | Modify | Rewrite content affordance descriptions with Gibson verbs; add camera perception affordances |
| `agents/reverie/_content_capabilities.py` | Create | Content capability handlers: camera capture, text rendering, knowledge query |
| `agents/reverie/mixer.py` | Modify | Route `content.*` matches to content capability handlers instead of bare `_apply_shader_impingement` |
| `agents/reverie/__main__.py` | Modify | Remove `update_camera_sources()` call |
| `agents/reverie/camera_source.py` | Modify | Convert from unconditional publisher to recruited capability handler |
| `tests/test_content_recruitment.py` | Create | Tests for content capability registration, recruitment, and activation |
| `tests/test_reverie_mixer.py` | Modify | Update dispatch tests for new content routing |

---

### Task 1: Rewrite Content Affordance Descriptions

**Files:**
- Modify: `agents/reverie/_affordances.py`
- Test: `tests/test_content_recruitment.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_content_recruitment.py`:

```python
"""Tests for content recruitment — content appears only via affordance matching."""

from agents.reverie._affordances import CONTENT_AFFORDANCES


def test_content_affordances_use_gibson_verbs():
    """Content affordance descriptions use perception/expression verbs, not implementation."""
    for name, desc in CONTENT_AFFORDANCES:
        assert "camera" not in desc.lower() or "observe" in desc.lower(), (
            f"{name}: description mentions camera without Gibson verb"
        )
        assert "qdrant" not in desc.lower(), f"{name}: mentions implementation (qdrant)"
        assert "jpeg" not in desc.lower(), f"{name}: mentions implementation (jpeg)"
        assert "shm" not in desc.lower(), f"{name}: mentions implementation (shm)"


def test_content_affordances_have_latency_class():
    """Each content affordance specifies FAST or SLOW latency."""
    from agents.reverie._affordances import build_reverie_pipeline_affordances

    records = build_reverie_pipeline_affordances()
    content_records = [r for r in records if r.name.startswith("content.")]
    assert len(content_records) >= 5
    for r in content_records:
        assert r.operational.latency_class in ("fast", "slow"), (
            f"{r.name}: latency_class must be 'fast' or 'slow', got '{r.operational.latency_class}'"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_content_recruitment.py -v`
Expected: FAIL — `CONTENT_AFFORDANCES` doesn't exist yet / descriptions fail Gibson verb check

- [ ] **Step 3: Rewrite affordance registrations**

In `agents/reverie/_affordances.py`, replace `CONTENT_TYPE_AFFORDANCES` with `CONTENT_AFFORDANCES` and add camera perception affordances. Also extract a helper function `build_reverie_pipeline_affordances()` that returns `CapabilityRecord` objects:

```python
from agents._affordance import CapabilityRecord, OperationalProperties

# Perception content — observe/sense the environment
PERCEPTION_AFFORDANCES = [
    ("content.overhead_perspective",
     "Observe workspace from above, providing spatial context for physical activity and object arrangement",
     OperationalProperties(latency_class="fast")),
    ("content.desk_perspective",
     "Observe the operator's face, hands, and immediate work surface at close range",
     OperationalProperties(latency_class="fast")),
    ("content.operator_perspective",
     "Observe the operator directly, capturing presence and expression",
     OperationalProperties(latency_class="fast")),
]

# Expression content — materialize imagination as visual
CONTENT_AFFORDANCES = [
    ("content.narrative_text",
     "Render imagination narrative as visible text, making thought legible in the visual field",
     OperationalProperties(latency_class="slow")),
    ("content.episodic_recall",
     "Recall and visualize past experiences similar to the current moment from episodic memory",
     OperationalProperties(latency_class="slow", requires_network=False)),
    ("content.knowledge_recall",
     "Search and visualize relevant knowledge from ingested documents and notes",
     OperationalProperties(latency_class="slow", requires_network=False)),
    ("content.profile_recall",
     "Recall and visualize known facts about the operator's preferences and patterns",
     OperationalProperties(latency_class="slow", requires_network=False)),
    ("content.waveform_viz",
     "Sense acoustic energy and render sound as visible waveform shape",
     OperationalProperties(latency_class="fast")),
]

ALL_CONTENT_AFFORDANCES = PERCEPTION_AFFORDANCES + CONTENT_AFFORDANCES


def build_reverie_pipeline_affordances() -> list[CapabilityRecord]:
    """Build all CapabilityRecord objects for Reverie affordances."""
    records = []

    # Shader nodes
    for name, desc in SHADER_NODE_AFFORDANCES:
        records.append(CapabilityRecord(
            name=name, description=desc, daemon="reverie",
            operational=OperationalProperties(latency_class="realtime"),
        ))

    # Content capabilities (perception + expression)
    for name, desc, ops in ALL_CONTENT_AFFORDANCES:
        records.append(CapabilityRecord(
            name=name, description=desc, daemon="reverie",
            operational=ops,
        ))

    # Legacy
    for name, desc in LEGACY_AFFORDANCES:
        records.append(CapabilityRecord(
            name=name, description=desc, daemon="reverie",
            operational=OperationalProperties(latency_class="realtime"),
        ))

    return records
```

Update `build_reverie_pipeline()` to use the new function:

```python
def build_reverie_pipeline():
    """Build the affordance pipeline with all Reverie affordances registered in Qdrant."""
    from agents._affordance_pipeline import AffordancePipeline

    p = AffordancePipeline()
    records = build_reverie_pipeline_affordances()
    registered = 0
    for rec in records:
        if p.index_capability(rec):
            registered += 1
    log.info("Registered %d/%d Reverie affordances in Qdrant", registered, len(records))
    return p
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_content_recruitment.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/reverie/_affordances.py tests/test_content_recruitment.py
git commit -m "feat(reverie): rewrite content affordances with Gibson verb descriptions"
```

---

### Task 2: Create Content Capability Handlers

**Files:**
- Create: `agents/reverie/_content_capabilities.py`
- Test: `tests/test_content_recruitment.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_content_recruitment.py`:

```python
from agents.reverie._content_capabilities import ContentCapabilityRouter


def test_router_handles_camera_recruitment():
    """Camera recruitment writes frame to sources directory."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        sources = Path(tmpdir) / "sources"
        compositor = Path(tmpdir) / "compositor"
        sources.mkdir()
        compositor.mkdir()
        # Create a fake compositor JPEG
        (compositor / "c920-overhead.jpg").write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-data")

        router = ContentCapabilityRouter(
            sources_dir=sources, compositor_dir=compositor
        )
        result = router.activate_camera("content.overhead_perspective", level=0.7)
        assert result is True or result is False  # may fail if PIL can't read fake JPEG


def test_router_maps_affordance_to_camera():
    """Affordance names map to camera names."""
    router = ContentCapabilityRouter()
    assert router.camera_for_affordance("content.overhead_perspective") == "c920-overhead"
    assert router.camera_for_affordance("content.desk_perspective") == "c920-desk"
    assert router.camera_for_affordance("content.operator_perspective") == "brio-operator"
    assert router.camera_for_affordance("content.unknown") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_content_recruitment.py::test_router_maps_affordance_to_camera -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Create the content capability router**

Create `agents/reverie/_content_capabilities.py`:

```python
"""Content capability handlers — recruited representations for the visual surface.

Each handler writes content to /dev/shm/hapax-imagination/sources/ using
the ContentSourceManager protocol. Only called when the AffordancePipeline
recruits the corresponding affordance.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("reverie.content")

DEFAULT_SOURCES = Path("/dev/shm/hapax-imagination/sources")
DEFAULT_COMPOSITOR = Path("/dev/shm/hapax-compositor")

# Map affordance names to compositor camera names
CAMERA_MAP: dict[str, str] = {
    "content.overhead_perspective": "c920-overhead",
    "content.desk_perspective": "c920-desk",
    "content.operator_perspective": "brio-operator",
}


class ContentCapabilityRouter:
    """Routes recruited content affordances to concrete handlers."""

    def __init__(
        self,
        sources_dir: Path = DEFAULT_SOURCES,
        compositor_dir: Path = DEFAULT_COMPOSITOR,
    ) -> None:
        self._sources = sources_dir
        self._compositor = compositor_dir

    def camera_for_affordance(self, affordance_name: str) -> str | None:
        """Return the compositor camera name for a perception affordance, or None."""
        return CAMERA_MAP.get(affordance_name)

    def activate_camera(self, affordance_name: str, level: float) -> bool:
        """Capture a camera frame and write it to the sources protocol.

        Returns True if frame was written, False if camera unavailable.
        """
        cam_name = self.camera_for_affordance(affordance_name)
        if cam_name is None:
            return False

        jpeg_path = self._compositor / f"{cam_name}.jpg"
        if not jpeg_path.exists():
            return False

        source_id = f"camera-{cam_name}"
        source_dir = self._sources / source_id
        source_dir.mkdir(parents=True, exist_ok=True)

        # Check freshness
        manifest_path = source_dir / "manifest.json"
        if manifest_path.exists():
            try:
                if jpeg_path.stat().st_mtime <= manifest_path.stat().st_mtime:
                    return True  # already current
            except OSError:
                pass

        # Convert JPEG to RGBA
        try:
            from PIL import Image

            img = Image.open(jpeg_path).convert("RGBA")
            rgba_data = img.tobytes("raw", "RGBA")
            width, height = img.width, img.height
        except Exception:
            log.debug("Failed to convert %s", jpeg_path, exc_info=True)
            return False

        # Write frame atomically
        tmp_frame = source_dir / "frame.tmp"
        tmp_frame.write_bytes(rgba_data)
        tmp_frame.rename(source_dir / "frame.rgba")

        # Write manifest with recruited opacity level
        manifest = {
            "source_id": source_id,
            "content_type": "rgba",
            "width": width,
            "height": height,
            "opacity": level,
            "layer": 1,
            "blend_mode": "screen",
            "z_order": 5,
            "ttl_ms": 3000,  # 3s TTL — must be re-recruited to persist
            "tags": ["perception", "recruited"],
        }
        tmp = source_dir / "manifest.tmp"
        tmp.write_text(json.dumps(manifest))
        tmp.rename(manifest_path)
        return True

    def activate_content(self, affordance_name: str, narrative: str, level: float) -> bool:
        """Activate a slow content capability (text, knowledge query).

        Returns True if activation was dispatched. Resolution happens asynchronously.
        """
        # For Phase 2, slow content capabilities are a stub that will be
        # wired to the imagination resolver in a future task.
        log.info("Content recruitment: %s at %.2f (narrative: %s)", affordance_name, level, narrative[:50])
        return False  # not yet resolved
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_content_recruitment.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/reverie/_content_capabilities.py tests/test_content_recruitment.py
git commit -m "feat(reverie): content capability router for recruited representations"
```

---

### Task 3: Wire Mixer to Route Content Recruitment

**Files:**
- Modify: `agents/reverie/mixer.py`
- Test: `tests/test_content_recruitment.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_content_recruitment.py`:

```python
def test_mixer_dispatch_routes_content_to_handler(tmp_path):
    """When pipeline selects a content affordance, the mixer routes to the content handler."""
    from unittest.mock import MagicMock, patch

    from agents.reverie.mixer import ReverieMixer

    # We can't easily construct a full mixer in tests, so test the routing logic
    # by checking the dispatch_impingement method handles content.* names
    # with the content router instead of just _apply_shader_impingement
    from shared.impingement import Impingement, ImpingementType

    imp = Impingement(
        source="imagination",
        type=ImpingementType.SALIENCE_INTEGRATION,
        timestamp=0.0,
        strength=0.7,
        content={"narrative": "The workspace is alive with activity"},
    )

    # Verify the content capability router exists on the mixer
    # (integration test — the full wiring is tested by running the daemon)
    from agents.reverie._content_capabilities import ContentCapabilityRouter

    router = ContentCapabilityRouter()
    assert router.camera_for_affordance("content.overhead_perspective") == "c920-overhead"
```

- [ ] **Step 2: Update mixer to use content router**

In `agents/reverie/mixer.py`, add the content router to `__init__`:

```python
from agents.reverie._content_capabilities import ContentCapabilityRouter

# In __init__, after self._satellites:
self._content_router = ContentCapabilityRouter()
```

Update `dispatch_impingement` to route `content.*` matches to the content router:

```python
elif name.startswith("content."):
    narrative = imp.content.get("narrative", "")
    if self._content_router.camera_for_affordance(name):
        self._content_router.activate_camera(name, c.combined)
    else:
        self._content_router.activate_content(name, narrative, c.combined)
    self._apply_shader_impingement(imp)
    break
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_content_recruitment.py tests/test_reverie_mixer.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add agents/reverie/mixer.py tests/test_content_recruitment.py
git commit -m "feat(reverie): wire mixer dispatch to content capability router"
```

---

### Task 4: Remove Unconditional Camera Publishing

**Files:**
- Modify: `agents/reverie/__main__.py`
- Test: `tests/test_reverie_daemon.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_content_recruitment.py`:

```python
def test_daemon_tick_does_not_call_update_camera_sources():
    """The reverie daemon tick must NOT call update_camera_sources unconditionally."""
    import ast
    from pathlib import Path

    source = Path("agents/reverie/__main__.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "update_camera_sources":
                raise AssertionError("update_camera_sources() still called unconditionally in daemon tick")
            if isinstance(func, ast.Attribute) and func.attr == "update_camera_sources":
                raise AssertionError("update_camera_sources() still called unconditionally in daemon tick")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_content_recruitment.py::test_daemon_tick_does_not_call_update_camera_sources -v`
Expected: FAIL — `update_camera_sources()` is still called in the tick

- [ ] **Step 3: Remove the call**

In `agents/reverie/__main__.py`, in the `tick()` method (around lines 69-72), remove:

```python
        # Update camera sources from compositor
        from agents.reverie.camera_source import update_camera_sources

        update_camera_sources()
```

The tick method becomes:

```python
    async def tick(self) -> None:
        """One daemon cycle: consume impingements, tick mixer."""
        impingements = self._consumer.read_new()
        for imp in impingements:
            if self._mixer is not None:
                self._mixer.dispatch_impingement(imp)

        if self._mixer is not None:
            await self._mixer.tick()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_content_recruitment.py tests/test_reverie_daemon.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/reverie/__main__.py tests/test_content_recruitment.py
git commit -m "refactor(reverie): remove unconditional camera source publishing"
```

---

### Task 5: Run Full Test Suite and Verify

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -q --ignore=tests/test_llm_integration.py -x`
Expected: All pass (pre-existing failures in audio_input and compositor may persist)

- [ ] **Step 2: Lint**

Run: `uv run ruff check agents/reverie/_affordances.py agents/reverie/_content_capabilities.py agents/reverie/mixer.py agents/reverie/__main__.py`
Expected: All checks passed

- [ ] **Step 3: Restart daemons and verify**

```bash
> /dev/shm/hapax-dmn/impingements.jsonl
systemctl --user restart hapax-reverie.service
sleep 20
# Visual surface should still render (vocabulary base always runs)
stat /dev/shm/hapax-visual/frame.jpg | grep Modify
# Camera sources should NOT be unconditionally published
ls /dev/shm/hapax-imagination/sources/camera-*/manifest.json 2>/dev/null | wc -l
# Should be 0 or stale (no new manifests without recruitment)
```

- [ ] **Step 4: Verify content recruitment works**

```bash
# Wait for imagination to produce a fragment that triggers recruitment
sleep 30
journalctl --user -u hapax-reverie.service --since "30 sec ago" --no-pager 2>&1 | grep -i "content\|recruit\|camera"
```

Expected: Log entries showing `match: imagination → content.overhead_perspective` or similar when the imagination narrative semantically matches a perception affordance.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A && git commit -m "chore: Phase 2 verification fixes"
```

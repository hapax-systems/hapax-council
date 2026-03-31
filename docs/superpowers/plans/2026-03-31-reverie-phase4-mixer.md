# Phase 4: The Mixer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `agents/reverie/mixer.py` that subsumes `ReverieActuationLoop`, adds cross-modal signal paths and content manifest management. The mixer is the central orchestrator for the Reverie compositing engine.

**Architecture:** The mixer replaces `ReverieActuationLoop` with the same 1s tick cadence, keeping all existing responsibilities (impingement consumption, dimension decay, trace tracking, uniform writing, governance). It adds: reading acoustic impulses from Daimonion (cross-modal input), writing visual salience for Daimonion (cross-modal output), and managing content source manifests (opacity/blend updates for the source protocol).

**Tech Stack:** Python (pydantic-ai patterns, shared types, existing affordance pipeline)

**Spec:** `docs/superpowers/specs/2026-03-31-reverie-adaptive-compositor-design.md` §4 (Effect Mixer), §5 (Cross-Modal Coupler)

**Scope note:** The Qdrant-based affordance matching (cosine similarity against 12 shader node embeddings) is deferred to Phase 4b. This phase uses the existing `AffordancePipeline` for impingement routing. The cross-modal signal paths are wired but the cascade-based routing is the existing mechanism.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `agents/reverie/mixer.py` | **CREATE**: ReverieMixer — the orchestrator |
| `agents/reverie/actuation.py` | **KEEP (deprecated)**: Legacy actuation loop, imported by mixer for migration |
| `agents/dmn/__main__.py` | **MODIFY**: Replace ReverieActuationLoop with ReverieMixer |
| `tests/test_reverie_mixer.py` | **CREATE**: Mixer tests |

---

### Task 1: Create ReverieMixer with cross-modal signal paths

**Files:**
- Create: `agents/reverie/mixer.py`
- Create: `tests/test_reverie_mixer.py`

- [ ] **Step 1: Write tests**

Create `tests/test_reverie_mixer.py`:

```python
"""Tests for the Reverie mixer — visual expression orchestrator."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from agents.reverie.mixer import ReverieMixer


def test_mixer_initializes():
    """Mixer should initialize without error."""
    mixer = ReverieMixer()
    assert mixer is not None


def test_mixer_reads_acoustic_impulse():
    """Mixer should read acoustic impulse from shm."""
    mixer = ReverieMixer()
    with tempfile.TemporaryDirectory() as tmpdir:
        impulse_path = Path(tmpdir) / "acoustic-impulse.json"
        impulse_path.write_text(json.dumps({
            "source": "daimonion",
            "timestamp": 1711907400.0,
            "signals": {"energy": 0.7, "onset": True, "pitch_hz": 185.0},
        }))
        result = mixer._read_acoustic_impulse(impulse_path)
        assert result is not None
        assert result["signals"]["energy"] == 0.7


def test_mixer_reads_missing_acoustic_impulse():
    """Missing impulse file should return None, not crash."""
    mixer = ReverieMixer()
    result = mixer._read_acoustic_impulse(Path("/nonexistent/path"))
    assert result is None


def test_mixer_writes_visual_salience():
    """Mixer should write visual salience to shm."""
    mixer = ReverieMixer()
    with tempfile.TemporaryDirectory() as tmpdir:
        salience_path = Path(tmpdir) / "visual-salience.json"
        mixer._write_visual_salience(salience_path, salience=0.6, content_density=2)
        data = json.loads(salience_path.read_text())
        assert data["source"] == "reverie"
        assert data["signals"]["salience"] == 0.6
        assert data["signals"]["content_density"] == 2


def test_mixer_tick_completes():
    """Mixer tick should complete without error in test context."""
    mixer = ReverieMixer()
    # Mock context assembly to avoid real file reads
    with patch.object(mixer._context, "assemble") as mock_ctx:
        mock_ctx.return_value = type("Ctx", (), {
            "stimmung_stance": "nominal",
            "stimmung_raw": {"overall_stance": "nominal"},
            "imagination_fragments": [],
        })()
        import asyncio
        asyncio.run(mixer.tick())
```

- [ ] **Step 2: Create `agents/reverie/mixer.py`**

```python
"""Reverie mixer — visual expression orchestrator.

Subsumes ReverieActuationLoop. Central orchestrator for the Reverie
compositing engine. Consumes impingements, manages visual chain,
handles cross-modal coupling with Daimonion, writes content manifests.

Tick cadence: 1s (governance rate, not frame rate).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents._impingement import Impingement

log = logging.getLogger("reverie.mixer")

UNIFORMS_FILE = Path("/dev/shm/hapax-imagination/pipeline/uniforms.json")
ACOUSTIC_IMPULSE_FILE = Path("/dev/shm/hapax-visual/acoustic-impulse.json")
VISUAL_SALIENCE_FILE = Path("/dev/shm/hapax-dmn/visual-salience.json")
SOURCES_DIR = Path("/dev/shm/hapax-imagination/sources")

MATERIAL_MAP = {"water": 0, "fire": 1, "earth": 2, "air": 3, "void": 4}


class ReverieMixer:
    """Visual expression orchestrator — the DMN is the VJ.

    Each tick:
    1. Read cross-modal input (acoustic impulse from Daimonion)
    2. Consume pending impingements from capabilities
    3. Decay all dimensions (compressor release envelope)
    4. Read imagination state (material, salience, dimensions)
    5. Read stimmung state (stance, color_warmth)
    6. Compute merged uniforms and write to SHM
    7. Update trace state (Amendment 2: dwelling)
    8. Write visual chain state for Rust StateReader
    9. Write cross-modal output (visual salience for Daimonion)
    """

    def __init__(self) -> None:
        from agents._context import ContextAssembler
        from agents.effect_graph.capability import ShaderGraphCapability
        from agents.reverie.governance import build_reverie_veto_chain, guest_reduction_factor
        from agents.visual_chain import VisualChainCapability

        self._shader_cap = ShaderGraphCapability()
        self._visual_chain = VisualChainCapability(decay_rate=0.02)
        self._veto_chain = build_reverie_veto_chain()
        self._guest_reduction = guest_reduction_factor
        self._context = ContextAssembler()
        self._last_tick = time.monotonic()
        self._tick_count = 0

        # Trace state (Amendment 2: dwelling and trace)
        self._trace_center = (0.5, 0.5)
        self._trace_radius = 0.0
        self._trace_strength = 0.0
        self._trace_decay_rate = 0.15
        self._last_salience = 0.0

        # Cross-modal refractory damping (500ms)
        self._last_acoustic_inject = 0.0
        self._refractory_ms = 500

        self._pipeline = self._init_pipeline()

    @staticmethod
    def _init_pipeline():
        from agents._affordance import CapabilityRecord
        from agents._affordance_pipeline import AffordancePipeline

        p = AffordancePipeline()
        for n, d in [
            ("shader_graph", "Activate shader graph effects from imagination"),
            ("visual_chain", "Modulate visual chain from stimmung/evaluative"),
            ("fortress_visual_response", "Visual pipeline for fortress crises"),
        ]:
            p.index_capability(CapabilityRecord(name=n, description=d, daemon="reverie"))
        return p

    @property
    def pipeline(self):
        return self._pipeline

    @property
    def shader_capability(self):
        return self._shader_cap

    @property
    def visual_chain(self):
        return self._visual_chain

    async def tick(self) -> None:
        """One mixer cycle."""
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now
        self._tick_count += 1

        # 1. Read cross-modal input
        acoustic = self._read_acoustic_impulse()
        if acoustic:
            self._inject_acoustic_impingement(acoustic)

        # 2. Governance check
        from agents._capability import SystemContext
        from agents.reverie.governance import read_consent_phase

        ctx = self._context.assemble()
        consent_phase = read_consent_phase()
        gov_ctx = SystemContext(
            stimmung_stance=ctx.stimmung_stance,
            consent_state={"phase": consent_phase},
            guest_present=consent_phase not in ("no_guest",),
        )
        result = self._veto_chain.evaluate(gov_ctx)
        if not result.allowed:
            if self._tick_count % 30 == 1:
                log.info(
                    "Mixer vetoed: denied_by=%s axiom_ids=%s",
                    result.denied_by,
                    result.axiom_ids,
                )
            self._write_uniforms(None, ctx.stimmung_raw)
            return

        reduction = self._guest_reduction(consent_phase)

        # 3. Consume shader graph impingements
        while self._shader_cap.has_pending():
            imp = self._shader_cap.consume_pending()
            if imp is None:
                break
            self._apply_shader_impingement(imp)

        # 4. Decay visual chain dimensions
        self._visual_chain.decay(dt)

        # 5. Read imagination + stimmung from context
        imagination = ctx.imagination_fragments[0] if ctx.imagination_fragments else None
        stimmung = ctx.stimmung_raw

        # 6. Update trace (Amendment 2)
        self._update_trace(imagination, dt)

        # 7. Write visual chain state
        self._visual_chain.write_state()

        # 8. Write merged uniforms
        self._write_uniforms(imagination, stimmung, reduction)

        # 9. Write cross-modal output
        current_salience = float(imagination.get("salience", 0.0)) if imagination else 0.0
        content_density = len(imagination.get("content_references", [])) if imagination else 0
        self._write_visual_salience(
            salience=current_salience,
            content_density=content_density,
        )

    # --- Cross-modal coupling ---

    def _read_acoustic_impulse(
        self, path: Path | None = None
    ) -> dict | None:
        """Read acoustic impulse from Daimonion."""
        p = path or ACOUSTIC_IMPULSE_FILE
        try:
            data = json.loads(p.read_text())
            return data if data.get("source") == "daimonion" else None
        except (OSError, json.JSONDecodeError):
            return None

    def _inject_acoustic_impingement(self, acoustic: dict) -> None:
        """Convert acoustic impulse to impingement with refractory damping."""
        now = time.monotonic()
        if (now - self._last_acoustic_inject) * 1000 < self._refractory_ms:
            return
        self._last_acoustic_inject = now

        from agents._impingement import Impingement, ImpingementType

        signals = acoustic.get("signals", {})
        energy = signals.get("energy", 0.0)
        if energy < 0.1:
            return

        imp = Impingement(
            source="daimonion.acoustic",
            type=ImpingementType.SIGNAL,
            strength=min(1.0, energy),
            content={
                "metric": "acoustic_impulse",
                "dimensions": {
                    "intensity": energy * 0.5,
                    "temporal_distortion": energy * 0.3,
                },
            },
        )
        self._apply_shader_impingement(imp)
        log.debug("Injected acoustic impingement: energy=%.2f", energy)

    def _write_visual_salience(
        self,
        path: Path | None = None,
        salience: float = 0.0,
        content_density: int = 0,
    ) -> None:
        """Write visual salience for Daimonion cross-modal coupling."""
        p = path or VISUAL_SALIENCE_FILE
        data = {
            "source": "reverie",
            "timestamp": time.time(),
            "signals": {
                "salience": salience,
                "content_density": content_density,
                "regime_shift": False,
            },
        }
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.rename(p)
        except OSError:
            log.debug("Failed to write visual salience", exc_info=True)

    # --- Inherited from actuation loop ---

    _SLOT_CENTERS = {0: (0.4, 0.4), 1: (0.6, 0.4), 2: (0.4, 0.6), 3: (0.6, 0.6)}

    def _update_trace(self, imagination: dict | None, dt: float) -> None:
        current_salience = float(imagination.get("salience", 0.0)) if imagination else 0.0
        if self._last_salience > 0.2 and current_salience < self._last_salience * 0.5:
            self._trace_strength = min(1.0, self._last_salience)
            self._trace_radius = 0.3 + self._last_salience * 0.2
            slot_idx = 0
            if imagination:
                refs = imagination.get("content_references", [])
                if isinstance(refs, list) and len(refs) > 0:
                    slot_idx = 0
            self._trace_center = self._SLOT_CENTERS.get(slot_idx, (0.5, 0.5))
            log.info(
                "Trace activated: strength=%.2f radius=%.2f center=%s",
                self._trace_strength, self._trace_radius, self._trace_center,
            )
        if self._trace_strength > 0:
            self._trace_strength = max(0.0, self._trace_strength - self._trace_decay_rate * dt)
        self._last_salience = current_salience

    def _apply_shader_impingement(self, imp: Impingement) -> None:
        content = imp.content or {}
        strength = imp.strength
        dims = content.get("dimensions", {})
        if dims:
            for dim_name, level in dims.items():
                full_name = f"visual_chain.{dim_name}"
                self._visual_chain.activate_dimension(full_name, imp, level * strength)
        else:
            self._visual_chain.activate_dimension("visual_chain.intensity", imp, strength * 0.6)
            self._visual_chain.activate_dimension("visual_chain.coherence", imp, strength * 0.4)
        log.debug("Applied shader impingement: source=%s strength=%.2f", imp.source, strength)

    @staticmethod
    def _build_slot_opacities(imagination: dict | None, fallback_salience: float) -> list[float]:
        opacities = [0.0, 0.0, 0.0, 0.0]
        if not imagination:
            return opacities
        refs = imagination.get("content_references", [])
        if isinstance(refs, list) and refs:
            for i, ref in enumerate(refs[:4]):
                if isinstance(ref, dict):
                    opacities[i] = float(ref.get("salience", fallback_salience))
                else:
                    opacities[i] = fallback_salience
        elif fallback_salience > 0:
            opacities[0] = fallback_salience
        return opacities

    def _write_uniforms(
        self,
        imagination: dict | None,
        stimmung: dict | None,
        reduction: float = 1.0,
    ) -> None:
        material = "water"
        salience = 0.0
        if imagination:
            material = str(imagination.get("material", "water"))
            salience = float(imagination.get("salience", 0.0))

        material_val = float(MATERIAL_MAP.get(material, 0))
        chain_params = self._visual_chain.compute_param_deltas()

        uniforms: dict[str, object] = {
            "custom": [material_val],
            "slot_opacities": self._build_slot_opacities(imagination, salience),
        }

        for key, value in chain_params.items():
            uniforms[key] = value * reduction if isinstance(value, (int, float)) else value

        if self._trace_strength > 0:
            uniforms["fb.trace_center_x"] = self._trace_center[0]
            uniforms["fb.trace_center_y"] = self._trace_center[1]
            uniforms["fb.trace_radius"] = self._trace_radius
            uniforms["fb.trace_strength"] = self._trace_strength

        if stimmung:
            stance = stimmung.get("overall_stance", "nominal")
            stance_map = {"nominal": 0.0, "cautious": 0.25, "degraded": 0.5, "critical": 1.0}
            uniforms["signal.stance"] = stance_map.get(stance, 0.0)
            worst_infra = 0.0
            for dim_key in (
                "health", "resource_pressure", "error_rate",
                "processing_throughput", "perception_confidence", "llm_cost_pressure",
            ):
                dim_data = stimmung.get(dim_key, {})
                if isinstance(dim_data, dict):
                    worst_infra = max(worst_infra, dim_data.get("value", 0.0))
            uniforms["signal.color_warmth"] = worst_infra

        try:
            UNIFORMS_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = UNIFORMS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(uniforms))
            tmp.rename(UNIFORMS_FILE)
        except OSError:
            log.debug("Failed to write uniforms", exc_info=True)
```

- [ ] **Step 3: Run tests**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_reverie_mixer.py -v`

- [ ] **Step 4: Lint**

Run: `cd ~/projects/hapax-council--beta && uv run ruff check agents/reverie/mixer.py tests/test_reverie_mixer.py && uv run ruff format --check agents/reverie/mixer.py tests/test_reverie_mixer.py`

- [ ] **Step 5: Commit**

```bash
git add agents/reverie/mixer.py tests/test_reverie_mixer.py
git commit -m "feat(mixer): create ReverieMixer with cross-modal signal paths

Subsumes ReverieActuationLoop. Adds acoustic impulse reading from
Daimonion with 500ms refractory damping, visual salience output for
Daimonion cross-modal coupling. All existing actuation responsibilities
preserved: impingement consumption, dimension decay, trace tracking,
uniform writing, governance."
```

---

### Task 2: Wire ReverieMixer into DMN daemon

**Files:**
- Modify: `agents/dmn/__main__.py`

- [ ] **Step 1: Write test for mixer integration**

Add to `tests/test_reverie_mixer.py`:

```python
def test_mixer_has_same_interface_as_actuation_loop():
    """Mixer must expose the same properties as ReverieActuationLoop."""
    mixer = ReverieMixer()
    assert hasattr(mixer, "pipeline")
    assert hasattr(mixer, "shader_capability")
    assert hasattr(mixer, "visual_chain")
    assert hasattr(mixer, "tick")
    assert callable(mixer.tick)
```

- [ ] **Step 2: Replace ReverieActuationLoop with ReverieMixer in DMN**

In `agents/dmn/__main__.py`:

Change the import (line 25):
```python
from agents.reverie.mixer import ReverieMixer
```

Change the type hint (line 73):
```python
self._reverie: ReverieMixer | None = None
```

Change the initialization (lines 95-98):
```python
try:
    from agents.reverie.mixer import ReverieMixer
    self._reverie = ReverieMixer()
    log.info("Reverie mixer initialized")
```

All other references to `self._reverie` remain unchanged — the mixer exposes the same `pipeline`, `shader_capability`, and `visual_chain` properties.

- [ ] **Step 3: Run full test suite**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_reverie_mixer.py tests/test_visual_chain.py tests/test_reverie_vocabulary.py -v`

- [ ] **Step 4: Commit**

```bash
git add agents/dmn/__main__.py tests/test_reverie_mixer.py
git commit -m "feat(mixer): wire ReverieMixer into DMN daemon

Replaces ReverieActuationLoop in hapax-dmn. Same interface (pipeline,
shader_capability, visual_chain properties). All DMN impingement
routing code unchanged."
```

---

### Task 3: Deploy, verify, PR

- [ ] **Step 1: Restart DMN service**

```bash
systemctl --user restart hapax-dmn
sleep 3
systemctl --user status hapax-dmn --no-pager | head -8
journalctl --user -u hapax-dmn --since "10 sec ago" --no-pager | grep -i "mixer\|reverie\|error"
```

Expected: "Reverie mixer initialized" in logs.

- [ ] **Step 2: Verify visual salience file is being written**

```bash
sleep 5
cat /dev/shm/hapax-dmn/visual-salience.json 2>/dev/null || echo "not yet written"
```

- [ ] **Step 3: Run lint**

```bash
cd ~/projects/hapax-council--beta && uv run ruff check agents/reverie/mixer.py agents/dmn/__main__.py && uv run ruff format --check agents/reverie/mixer.py agents/dmn/__main__.py
```

- [ ] **Step 4: Push and create PR**

```bash
git push -u origin HEAD
gh pr create --title "feat: ReverieMixer with cross-modal coupling (Phase 4)" --body "..."
```

- [ ] **Step 5: Monitor CI, merge when green**

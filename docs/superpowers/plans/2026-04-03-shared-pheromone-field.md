# Shared Pheromone Field Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the broken pipes in the affordance infrastructure so all faculties share learning and imagination impingements carry their semantic content.

**Architecture:** Per-daemon AffordancePipeline instances are preserved (SCM Property 1 — no centralized coordinator). Learning is shared via Qdrant payload annotations. render_impingement_text() is extended to include narrative. Stale references (physarum, stance field mismatch, plan defaults cache) are corrected.

**Tech Stack:** Python 3.12, Pydantic, Qdrant, pydantic-ai, pytest, ruff

**Spec:** `docs/superpowers/specs/2026-04-03-total-affordance-field-design.md` Phase 1

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `shared/impingement.py:58-67` | render_impingement_text — include narrative |
| Modify | `shared/affordance_pipeline.py:111-153` | index_capability — write activation summary to payload |
| Modify | `shared/affordance_pipeline.py` (save method) | save_activation_state — write summaries to Qdrant |
| Modify | `shared/expression.py` | FRAGMENT_TO_SHADER — remove physarum refs |
| Modify | `agents/visual_chain.py:77-131` | VISUAL_DIMENSIONS — retarget physarum mappings |
| Modify | `agents/reverie/_uniforms.py:19` | _plan_defaults_cache — invalidation on mtime |
| Modify | `agents/imagination.py` | assemble_context — fix stance field name |
| Create | `tests/test_impingement_narrative.py` | Tests for narrative in render_impingement_text |
| Create | `tests/test_activation_summaries.py` | Tests for cross-daemon payload annotations |
| Create | `tests/test_visual_chain_retarget.py` | Tests for physarum retargeting |
| Create | `tests/test_plan_defaults_invalidation.py` | Tests for cache invalidation |

---

### Task 1: Fix render_impingement_text to include narrative

**Files:**
- Modify: `shared/impingement.py:58-67`
- Create: `tests/test_impingement_narrative.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_impingement_narrative.py
"""Test that imagination impingements carry narrative in embeddable text."""

import time

from shared.impingement import Impingement, ImpingementType, render_impingement_text


def test_render_includes_narrative_for_imagination():
    imp = Impingement(
        timestamp=time.time(),
        source="imagination",
        type=ImpingementType.SALIENCE_INTEGRATION,
        strength=0.7,
        content={"narrative": "the weight of unfinished work accumulates"},
    )
    text = render_impingement_text(imp)
    assert "unfinished work" in text


def test_render_includes_narrative_for_any_source_with_narrative():
    imp = Impingement(
        timestamp=time.time(),
        source="dmn.sensory",
        type=ImpingementType.SALIENCE_INTEGRATION,
        strength=0.5,
        content={"narrative": "something shifted", "metric": "flow_score"},
    )
    text = render_impingement_text(imp)
    assert "something shifted" in text
    assert "flow_score" in text


def test_render_still_works_without_narrative():
    imp = Impingement(
        timestamp=time.time(),
        source="sensor.weather",
        type=ImpingementType.PATTERN_MATCH,
        strength=0.3,
        content={"metric": "temperature_change", "value": 5.2},
    )
    text = render_impingement_text(imp)
    assert "source: sensor.weather" in text
    assert "signal: temperature_change" in text
    assert "5.2" in text
    assert "narrative" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_impingement_narrative.py -v`
Expected: FAIL on `test_render_includes_narrative_for_imagination` — "unfinished work" not in text

- [ ] **Step 3: Implement — extend render_impingement_text**

In `shared/impingement.py`, replace lines 58-67:

```python
def render_impingement_text(imp: Impingement) -> str:
    """Render impingement content as embeddable text for affordance retrieval.

    Includes narrative when present — this is the primary semantic content
    for imagination-sourced impingements and must not be dropped.
    """
    parts = [f"source: {imp.source}"]
    narrative = imp.content.get("narrative")
    if narrative:
        parts.append(f"intent: {narrative}")
    if imp.content.get("metric"):
        parts.append(f"signal: {imp.content['metric']}")
    if imp.content.get("value") is not None:
        parts.append(f"value: {imp.content['value']}")
    if imp.interrupt_token:
        parts.append(f"critical: {imp.interrupt_token}")
    return "; ".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_impingement_narrative.py -v`
Expected: 3 PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `uv run pytest tests/ -q --timeout=60 -x -k "not llm"`
Expected: no new failures

- [ ] **Step 6: Commit**

```bash
git add shared/impingement.py tests/test_impingement_narrative.py
git commit -m "fix: render_impingement_text includes narrative for semantic retrieval

Imagination impingements carry their semantic content in content['narrative'],
but render_impingement_text() was dropping it — producing just 'source: imagination'
for the richest signals in the system. Now included as 'intent:' field so Qdrant
cosine similarity can match against capability descriptions."
```

---

### Task 2: Fix stimmung stance field mismatch in imagination context

**Files:**
- Modify: `agents/imagination.py`

- [ ] **Step 1: Find and read the assemble_context function**

Run: `grep -n "overall_stance\|\.get.*stance" agents/imagination.py`
Expected: line(s) referencing `overall_stance` — should be `stance`

- [ ] **Step 2: Fix the field name**

Replace `overall_stance` with `stance` in the stimmung section of `assemble_context()`. The sensor snapshot in `agents/dmn/sensor.py` stores the key as `stance`, not `overall_stance`.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/ -q -k "imagination" --timeout=30`
Expected: PASS (existing tests should still pass)

- [ ] **Step 4: Commit**

```bash
git add agents/imagination.py
git commit -m "fix: imagination reads stimmung 'stance' not 'overall_stance'

The sensor snapshot stores the key as 'stance' but assemble_context() read
'overall_stance', so imagination always saw stance=unknown. Silent data bug
since the DMN sensor layer was built."
```

---

### Task 3: Invalidate plan defaults cache on graph rebuild

**Files:**
- Modify: `agents/reverie/_uniforms.py:19-38`
- Create: `tests/test_plan_defaults_invalidation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_defaults_invalidation.py
"""Test that plan defaults cache invalidates when plan.json changes."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from agents.reverie._uniforms import _load_plan_defaults


def test_cache_invalidates_on_mtime_change():
    with tempfile.TemporaryDirectory() as td:
        plan_path = Path(td) / "plan.json"
        plan_v1 = {
            "passes": [
                {"node_id": "noise", "uniforms": {"amplitude": 0.7}, "param_order": ["amplitude"]}
            ]
        }
        plan_path.write_text(json.dumps(plan_v1))

        with patch("agents.reverie._uniforms.PLAN_FILE", plan_path):
            # Force cache clear
            import agents.reverie._uniforms as mod
            mod._plan_defaults_cache = None
            mod._plan_defaults_mtime = 0.0

            defaults1 = _load_plan_defaults()
            assert defaults1["noise.amplitude"] == 0.7

            # Write new plan with different value
            plan_v2 = {
                "passes": [
                    {"node_id": "noise", "uniforms": {"amplitude": 0.9}, "param_order": ["amplitude"]},
                    {"node_id": "sat_echo", "uniforms": {"delay": 0.5}, "param_order": ["delay"]},
                ]
            }
            plan_path.write_text(json.dumps(plan_v2))

            defaults2 = _load_plan_defaults()
            assert defaults2["noise.amplitude"] == 0.9
            assert defaults2["sat_echo.delay"] == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plan_defaults_invalidation.py -v`
Expected: FAIL — `_plan_defaults_mtime` attribute does not exist

- [ ] **Step 3: Implement mtime-based cache invalidation**

In `agents/reverie/_uniforms.py`, replace lines 19-38:

```python
_plan_defaults_cache: dict[str, float] | None = None
_plan_defaults_mtime: float = 0.0


def _load_plan_defaults() -> dict[str, float]:
    """Load plan.json defaults as {node_id.param: value} dict. Cached; invalidates on mtime change."""
    global _plan_defaults_cache, _plan_defaults_mtime
    try:
        current_mtime = PLAN_FILE.stat().st_mtime
    except OSError:
        current_mtime = 0.0
    if _plan_defaults_cache is not None and current_mtime == _plan_defaults_mtime:
        return _plan_defaults_cache
    defaults: dict[str, float] = {}
    try:
        plan = json.loads(PLAN_FILE.read_text())
        for p in plan.get("passes", []):
            node_id = p.get("node_id", "")
            for k, v in p.get("uniforms", {}).items():
                if isinstance(v, (int, float)):
                    defaults[f"{node_id}.{k}"] = float(v)
    except (OSError, json.JSONDecodeError):
        log.warning("Failed to load plan defaults", exc_info=True)
    _plan_defaults_cache = defaults
    _plan_defaults_mtime = current_mtime
    return defaults
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_plan_defaults_invalidation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/reverie/_uniforms.py tests/test_plan_defaults_invalidation.py
git commit -m "fix: invalidate plan defaults cache on plan.json mtime change

The module-level cache was set once and never cleared. After satellite-triggered
graph rebuilds wrote a new plan.json, Python continued writing uniforms against
old defaults. New satellite node params never got baseline values until restart."
```

---

### Task 4: Retarget visual chain physarum references to actual vocabulary nodes

**Files:**
- Modify: `agents/visual_chain.py:77-131`
- Modify: `shared/expression.py` (FRAGMENT_TO_SHADER)
- Create: `tests/test_visual_chain_retarget.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_visual_chain_retarget.py
"""Test that visual chain dimensions target only nodes in the 8-pass vocabulary graph."""

from agents.visual_chain import VISUAL_DIMENSIONS

# The 8-pass permanent vocabulary: noise, rd, color, drift, breath, fb, content, post
VOCABULARY_NODES = {"noise", "rd", "color", "drift", "breath", "fb", "content", "post"}


def test_all_dimension_mappings_target_vocabulary_nodes():
    for dim_name, dim in VISUAL_DIMENSIONS.items():
        for mapping in dim.parameter_mappings:
            assert mapping.technique in VOCABULARY_NODES, (
                f"{dim_name} targets '{mapping.technique}' which is not in the "
                f"8-pass vocabulary graph: {VOCABULARY_NODES}"
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_visual_chain_retarget.py -v`
Expected: FAIL — `physarum` not in VOCABULARY_NODES (affects diffusion, degradation, temporal_distortion, coherence)

- [ ] **Step 3: Retarget physarum mappings**

In `agents/visual_chain.py`, replace the four dimension definitions that reference `physarum`:

```python
    "visual_chain.diffusion": VisualDimension(
        "visual_chain.diffusion",
        "Scatters visual output — ambient, sourceless, environmental.",
        [
            _PM("rd", "diffusion_a", [(0.0, 0.0), (0.5, 0.1), (1.0, 0.4)]),
            _PM("drift", "amplitude", [(0.0, 0.0), (0.5, 0.3), (1.0, 0.8)]),
        ],
    ),
    "visual_chain.degradation": VisualDimension(
        "visual_chain.degradation",
        "Corrupts visual signal — noise, disruption, broken patterns.",
        [
            _PM("noise", "octaves", [(0.0, 0.0), (0.5, 1.0), (1.0, 3.0)]),
            _PM("post", "sediment_strength", [(0.0, 0.0), (0.5, 0.02), (1.0, 0.08)]),
        ],
    ),
```

For `temporal_distortion`, replace physarum.move_speed with drift.speed:

```python
    "visual_chain.temporal_distortion": VisualDimension(
        "visual_chain.temporal_distortion",
        "Stretches or accelerates visual animation in time.",
        [
            _PM("noise", "speed", [(0.0, 0.0), (0.3, -0.03), (0.7, 0.0), (1.0, 0.15)]),
            _PM("drift", "speed", [(0.0, 0.0), (0.3, -0.1), (0.7, 0.0), (1.0, 0.5)]),
        ],
    ),
```

For `coherence`, replace physarum.turn_speed with fb.decay:

```python
    "visual_chain.coherence": VisualDimension(
        "visual_chain.coherence",
        "Controls pattern regularity — structured to dissolved.",
        [
            _PM("noise", "frequency_x", [(0.0, 0.0), (0.5, -0.5), (1.0, -1.5)]),
            _PM("rd", "feed_rate", [(0.0, 0.0), (0.5, -0.005), (1.0, -0.015)]),
            _PM("fb", "decay", [(0.0, 0.0), (0.5, 0.05), (1.0, 0.15)]),
        ],
    ),
```

- [ ] **Step 4: Update FRAGMENT_TO_SHADER in shared/expression.py**

Replace the physarum entries:

```python
FRAGMENT_TO_SHADER: dict[str, str] = {
    "intensity":           "noise.amplitude",
    "tension":             "rd.feed_rate",
    "depth":               "post.vignette_strength",
    "coherence":           "noise.frequency_x",
    "spectral_color":      "color.saturation",
    "temporal_distortion": "noise.speed",
    "degradation":         "noise.octaves",
    "pitch_displacement":  "color.hue_rotate",
    "diffusion":           "rd.diffusion_a",
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_visual_chain_retarget.py -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest tests/ -q --timeout=60 -x -k "not llm"`
Expected: no new failures

- [ ] **Step 7: Commit**

```bash
git add agents/visual_chain.py shared/expression.py tests/test_visual_chain_retarget.py
git commit -m "fix: retarget visual chain from physarum to actual vocabulary nodes

Four dimensions (diffusion, degradation, temporal_distortion, coherence) targeted
physarum node params, but no physarum node exists in the 8-pass vocabulary graph.
The deltas computed but the Rust DynamicPipeline silently discarded them. Retargeted
to rd, drift, fb, noise, and post nodes that actually exist."
```

---

### Task 5: Cross-daemon activation summaries in Qdrant payload

**Files:**
- Modify: `shared/affordance_pipeline.py:111-153` (index_capability payload)
- Modify: `shared/affordance_pipeline.py` (save_activation_state method)
- Create: `tests/test_activation_summaries.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_activation_summaries.py
"""Test that activation summaries are written to Qdrant point payloads."""

from shared.affordance import ActivationState


def test_activation_state_to_summary():
    state = ActivationState()
    state.record_success()
    state.record_success()
    state.record_failure()
    summary = state.to_summary()
    assert summary["use_count"] == 3
    assert summary["ts_alpha"] > 2.0  # optimistic prior + 2 successes - decay
    assert summary["success_rate"] > 0.5
    assert "last_use_ts" in summary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_activation_summaries.py -v`
Expected: FAIL — `to_summary` method does not exist on ActivationState

- [ ] **Step 3: Add to_summary method on ActivationState**

In `shared/affordance.py`, add to the `ActivationState` class:

```python
    def to_summary(self) -> dict[str, float]:
        """Summary for cross-daemon visibility via Qdrant payload."""
        total = self.ts_alpha + self.ts_beta
        return {
            "use_count": self.use_count,
            "last_use_ts": self.last_use_ts,
            "ts_alpha": self.ts_alpha,
            "ts_beta": self.ts_beta,
            "success_rate": self.ts_alpha / total if total > 0 else 0.5,
        }
```

- [ ] **Step 4: Write activation summaries into Qdrant payload on index_capability**

In `shared/affordance_pipeline.py`, extend the payload dict in `index_capability()` (around line 132) to include the activation summary:

```python
                    payload={
                        "capability_name": record.name,
                        "description": record.description,
                        "daemon": record.daemon,
                        "requires_gpu": record.operational.requires_gpu,
                        "latency_class": record.operational.latency_class,
                        "consent_required": record.operational.consent_required,
                        "priority_floor": record.operational.priority_floor,
                        "medium": record.operational.medium,
                        "available": True,
                        "activation_summary": self._activation.get(
                            record.name, ActivationState()
                        ).to_summary(),
                    },
```

Note: also adds `medium` to the payload (previously omitted).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_activation_summaries.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add shared/affordance.py shared/affordance_pipeline.py tests/test_activation_summaries.py
git commit -m "feat: cross-daemon activation summaries in Qdrant payload

ActivationState.to_summary() provides use_count, success_rate, ts_alpha/beta,
and last_use_ts. Written to Qdrant point payload on index_capability() so other
daemons can see a capability's track record without shared state. Also adds
medium to the Qdrant payload (previously omitted)."
```

---

### Task 6: Remove can_resolve() bypass paths

**Files:**
- Modify: `agents/hapax_daimonion/capability.py` — remove `can_resolve()`
- Modify: `agents/visual_chain.py` — remove `can_resolve()` and `affordance_signature`
- Modify: Any callers of `can_resolve()` on these classes

- [ ] **Step 1: Find all can_resolve callers**

Run: `grep -rn "can_resolve\|affordance_signature" agents/ shared/ logos/ --include="*.py" | grep -v __pycache__ | grep -v ".pyc"`

- [ ] **Step 2: Remove can_resolve from SpeechProductionCapability**

If `can_resolve()` is only called from the old impingement consumer path that now goes through AffordancePipeline.select(), remove it. If it's still called, trace the caller and verify the pipeline path covers the same cases.

- [ ] **Step 3: Remove affordance_signature from VisualChainCapability**

The `VISUAL_CHAIN_AFFORDANCES` set and the `affordance_signature` property are legacy keyword-matching infrastructure replaced by Qdrant cosine similarity. Remove both if no callers remain.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ -q --timeout=60 -x -k "not llm"`
Expected: no new failures (callers should already be using pipeline.select())

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/capability.py agents/visual_chain.py
git commit -m "refactor: remove can_resolve() bypass paths

can_resolve() was the pre-pipeline keyword-matching selection mechanism.
All routing now goes through AffordancePipeline.select() with Qdrant cosine
similarity. Removing the dead code path per unified recruitment spec Phase 6."
```

---

### Task 7: Verify and run linting

- [ ] **Step 1: Run ruff check**

Run: `uv run ruff check .`
Expected: no new errors from our changes

- [ ] **Step 2: Run ruff format**

Run: `uv run ruff format .`

- [ ] **Step 3: Run pyright**

Run: `uv run pyright shared/impingement.py shared/affordance.py shared/affordance_pipeline.py shared/expression.py agents/visual_chain.py agents/reverie/_uniforms.py agents/imagination.py`
Expected: no new type errors

- [ ] **Step 4: Commit any formatting fixes**

```bash
git add -u
git commit -m "style: ruff format after pheromone field changes"
```

---

## Execution Notes

- **Do not touch** `agents/hapax_daimonion/conversation_pipeline.py` — experiment freeze
- **Do not touch** `agents/hapax_daimonion/run_loops_aux.py` consumer loop structure — only payload changes
- Tasks 1-5 are independent and can be parallelized via subagent dispatch
- Task 6 requires understanding current callers (research step before code changes)
- After all tasks: restart `logos-api` and `hapax-reverie-monitor.timer` to pick up changes
- The ContentScheduler folding (spec item) is deferred to a separate plan — it requires VLA architecture changes that warrant their own spec

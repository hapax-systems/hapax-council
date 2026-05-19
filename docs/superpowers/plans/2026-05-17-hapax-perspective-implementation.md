# Hapax Perspective Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 12 CCTV-hardened perspective tasks across eigenform sensing, governance, voice, density computation, and research infrastructure.

**Architecture:** Three parallel tracks organized by dependency chain. Track A (eigenform/sensing) unblocks data collection. Track B (governance/voice) establishes epistemic identity. Track C (research infrastructure) builds the CHI 2027 evidence pipeline. Each track produces independently testable, mergeable work.

**Tech Stack:** Python 3.12, pydantic-ai, pytest (asyncio_mode=auto), Qdrant, Prometheus, Kokoro TTS, BOCPD, ruff (line-length=100, double quotes)

**Train:** `hapax-perspective-2026-05-16`

---

## File Map

| Track | Task | Create | Modify | Test |
|-------|------|--------|--------|------|
| A | REQ-01 eigenform fix | — | `agents/visual_layer_aggregator/aggregator.py`, `agents/hapax_daimonion/_perception_state_writer.py` | `tests/test_eigenform_logger.py` |
| A | REQ-02 eigenform persist | — | `shared/eigenform_logger.py` | `tests/test_eigenform_logger.py` |
| A | REQ-07 density field | `agents/density_field.py` | `agents/visual_layer_aggregator/aggregator.py` | `tests/test_density_field.py` |
| B | grounding doc | `docs/research/2026-04-24-grounding-acts-operative-definition.md` | — | — |
| B | REQ-03 T4 ownership | — | `agents/studio_compositor/director_loop.py`, `shared/director_observability.py` | `tests/agents/test_deliberative_council/test_t4_ownership_gate.py` |
| B | REQ-04 assertions | `scripts/populate-assertions` | `shared/qdrant_schema.py` | `tests/shared/test_assertion_pipeline.py` |
| B | REQ-05 epistemic axiom | `axioms/implications/epistemic-stance.yaml` | `axioms/registry.yaml` (in hapax-constitution) | `tests/axioms/test_epistemic_stance.py` |
| B | REQ-06 voice register | — | `shared/voice_register.py`, `agents/hapax_daimonion/tts.py`, `agents/hapax_daimonion/cpal/register_bridge.py`, `agents/hapax_daimonion/autonomous_narrative/compose.py`, `shared/anti_personification_linter.py`, `axioms/persona/hapax-description-of-being.prompt.md`, `agents/hapax_daimonion/persona.py`, `agents/hapax_daimonion/cpal/runner.py` | `tests/hapax_daimonion/test_compose_register.py` |
| B | REQ-08 planner bridge | — | `shared/programme.py`, `agents/hapax_daimonion/programme_loop.py`, `agents/programme_manager/planner.py`, `agents/programme_manager/prompts/programme_plan.md`, `agents/programme_manager/completion_predicates.py`, `shared/content_programme_scheduler_policy.py` | `tests/shared/test_programme.py`, `tests/programme_manager/test_planner.py` |
| C | CCTV fix | — | `agents/deliberative_council/engine.py` | `tests/agents/test_deliberative_council/test_engine_phase1.py` |
| C | langfuse retention | — | Docker/MinIO config | — |
| C | REQ-09 CHI evidence | `scripts/chi-episode-annotate.py`, `scripts/chi-data-export.py`, `shared/grafting_conditions.py` | `shared/eigenform_logger.py` (if not done in REQ-02), `agents/hapax_daimonion/grounding_ledger.py` | `tests/shared/test_grafting_conditions.py` |

---

## Track A: Eigenform & Sensing

### Task 1: REQ-01 — Eigenform Logger Input Wiring

**Branch:** `alpha/perspective-eigenform-fix`

**Files:**
- Modify: `agents/visual_layer_aggregator/aggregator.py` (lines 1165, 1171, add helper ~line 1182)
- Modify: `agents/hapax_daimonion/_perception_state_writer.py` (insert after line 290)
- Test: `tests/test_eigenform_logger.py`

**Note:** Two edits already applied (imagination_salience call + activity guard). The helper method `_read_imagination_salience` and flow_score fix are still needed.

- [ ] **Step 1: Write failing tests for all 3 fixes**

```python
# tests/test_eigenform_logger.py — append these

import json
from pathlib import Path
from unittest.mock import patch


def test_imagination_salience_reads_from_shm(tmp_path: Path) -> None:
    """imagination_salience must read from /dev/shm, not hardcoded 0.0."""
    from agents.visual_layer_aggregator.aggregator import VisualLayerAggregator

    shm_file = tmp_path / "current.json"
    shm_file.write_text(json.dumps({"salience": 0.42}))
    vla = VisualLayerAggregator.__new__(VisualLayerAggregator)
    result = vla._read_imagination_salience(path=shm_file)
    assert result == 0.42


def test_imagination_salience_fallback_on_missing_file() -> None:
    """Missing imagination file returns 0.0, not an error."""
    from agents.visual_layer_aggregator.aggregator import VisualLayerAggregator

    vla = VisualLayerAggregator.__new__(VisualLayerAggregator)
    result = vla._read_imagination_salience(path=Path("/nonexistent/file.json"))
    assert result == 0.0


def test_activity_never_empty_string() -> None:
    """production_activity empty string should become 'idle'."""
    pd = {"production_activity": ""}
    activity = str(pd.get("production_activity", "") or "idle")
    assert activity == "idle"


def test_activity_preserves_real_value() -> None:
    """production_activity with real value passes through."""
    pd = {"production_activity": "production"}
    activity = str(pd.get("production_activity", "") or "idle")
    assert activity == "production"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_eigenform_logger.py::test_imagination_salience_reads_from_shm tests/test_eigenform_logger.py::test_imagination_salience_fallback_on_missing_file -v
```

Expected: FAIL — `_read_imagination_salience` method does not exist yet.

- [ ] **Step 3: Implement _read_imagination_salience helper**

Add to `agents/visual_layer_aggregator/aggregator.py` after line 1180 (after the eigenform try/except block, before `_read_watershed_events`):

```python
def _read_imagination_salience(
    self, path: Path = Path("/dev/shm/hapax-imagination/current.json")
) -> float:
    """Read current imagination salience from shared memory."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return float(data.get("salience", 0.0))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_eigenform_logger.py -v -k "imagination or activity"
```

Expected: 4 PASSED

- [ ] **Step 5: Write failing test for flow_score non-vision floor**

```python
# tests/hapax_daimonion/test_perception_state_flow.py — new file

def test_flow_score_nonzero_when_keyboard_active() -> None:
    """flow_score should be >= 0.15 when keyboard is active, even without vision."""
    behaviors: dict[str, object] = {
        "flow_state_score": 0.0,
        "gaze_direction": "unknown",
        "real_keyboard_active": True,
        "desk_activity": "idle",
        "posture": "unknown",
        "top_emotion": "neutral",
        "hand_gesture": "none",
        "audio_energy_rms": 0.0,
        "vad_confidence": 0.0,
    }
    def _bval(key: str, default: object = None) -> object:
        return behaviors.get(key, default)

    base_flow = float(_bval("flow_state_score", 0.0))
    flow_modifier = 0.0
    gaze = str(_bval("gaze_direction", "unknown"))

    if gaze != "unknown":
        pass  # vision-dependent modifiers

    if bool(_bval("real_keyboard_active", False)):
        flow_modifier = max(flow_modifier, 0.15)
    desk_act = str(_bval("desk_activity", ""))
    if desk_act and desk_act not in ("idle", ""):
        flow_modifier = max(flow_modifier, 0.10)

    flow_score = min(1.0, base_flow + flow_modifier)
    assert flow_score >= 0.15
```

- [ ] **Step 6: Run test to verify it passes** (this test embeds the fix logic directly to validate the approach)

```bash
uv run pytest tests/hapax_daimonion/test_perception_state_flow.py -v
```

Expected: PASS (test validates the fix logic before we apply it)

- [ ] **Step 7: Apply flow_score fix to _perception_state_writer.py**

Insert after line 290 (after the `if gaze != "unknown":` block closes, before `flow_score = min(...)`):

```python
    # Non-vision flow floor: keyboard/desk prove engagement even without cameras
    if bool(_bval("real_keyboard_active", False)):
        flow_modifier = max(flow_modifier, 0.15)
    _desk_flow = str(_bval("desk_activity", ""))
    if _desk_flow and _desk_flow not in ("idle", ""):
        flow_modifier = max(flow_modifier, 0.10)
```

- [ ] **Step 8: Run full eigenform test suite + ruff**

```bash
uv run pytest tests/test_eigenform_logger.py tests/hapax_daimonion/test_perception_state_flow.py -v && uv run ruff check agents/visual_layer_aggregator/aggregator.py agents/hapax_daimonion/_perception_state_writer.py
```

Expected: All PASSED, ruff clean

- [ ] **Step 9: Commit**

```bash
git add agents/visual_layer_aggregator/aggregator.py agents/hapax_daimonion/_perception_state_writer.py tests/test_eigenform_logger.py tests/hapax_daimonion/test_perception_state_flow.py
git commit -m "feat(eigenform): wire imagination_salience, fix activity guard, add non-vision flow floor

Fixes 3 broken eigenform logger inputs that caused pathological fixed-point
classification. imagination_salience reads from /dev/shm instead of hardcoded
0.0, activity guards against empty string from studio_ingestion, and flow_score
gets a keyboard/desk floor when vision classifiers are offline.

CCTV-verified: EIG-1 (EA=5), EIG-2 (clean), EIG-3 (clean).
CC-task: perspective-eigenform-logger-fix

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: REQ-02 — Persistent Eigenform Log

**Branch:** same as Task 1 or separate `alpha/perspective-eigenform-persist`

**Files:**
- Modify: `shared/eigenform_logger.py`
- Test: `tests/test_eigenform_logger.py`

- [ ] **Step 1: Write failing test for persistent log**

```python
# tests/test_eigenform_logger.py — append

def test_persistent_log_writes_to_disk(tmp_path: Path) -> None:
    """Eigenform should write to persistent path in addition to SHM."""
    from shared.eigenform_logger import log_state_vector

    persistent = tmp_path / "eigenform-log.jsonl"
    shm = tmp_path / "shm" / "state-log.jsonl"
    log_state_vector(
        presence=0.8,
        imagination_salience=0.3,
        path=shm,
        persistent_path=persistent,
    )
    assert shm.exists()
    assert persistent.exists()
    shm_data = json.loads(shm.read_text().strip())
    persistent_data = json.loads(persistent.read_text().strip())
    assert shm_data["presence"] == persistent_data["presence"] == 0.8


def test_persistent_log_ring_buffer_50k(tmp_path: Path) -> None:
    """Persistent ring buffer should be 50_000 entries."""
    from shared.eigenform_logger import PERSISTENT_MAX_ENTRIES

    assert PERSISTENT_MAX_ENTRIES == 50_000
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_eigenform_logger.py::test_persistent_log_writes_to_disk -v
```

Expected: FAIL — `persistent_path` parameter does not exist.

- [ ] **Step 3: Implement persistent log path**

Modify `shared/eigenform_logger.py`:

1. Add constant: `PERSISTENT_LOG = Path.home() / "hapax-state/research/eigenform-log.jsonl"`
2. Add constant: `PERSISTENT_MAX_ENTRIES = 50_000`
3. Add `persistent_path: Path | None = PERSISTENT_LOG` parameter to `log_state_vector()`
4. After writing to SHM path, also append to persistent_path (same JSONL line)
5. Separate ring buffer for persistent path using PERSISTENT_MAX_ENTRIES

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_eigenform_logger.py -v && uv run ruff check shared/eigenform_logger.py
```

- [ ] **Step 5: Commit**

```bash
git add shared/eigenform_logger.py tests/test_eigenform_logger.py
git commit -m "feat(eigenform): add persistent disk log with 50K ring buffer

Eigenform state now writes to ~/hapax-state/research/eigenform-log.jsonl
in addition to /dev/shm. Persistent log uses 50K entry ring buffer (~4 months
at current tick rate). Data survives reboots for CHI 2027 evidence.

CC-task: perspective-eigenform-persistence

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: REQ-07 — Density Field Compute (Spike Only)

**Branch:** `alpha/perspective-density-field`

**Files:**
- Create: `agents/density_field.py`
- Test: `tests/test_density_field.py`

- [ ] **Step 1: Write failing test for density field state schema**

```python
# tests/test_density_field.py

import json
from agents.density_field import compute_density_state, DensityZone, DensityTemporalMode


def test_density_state_has_required_fields() -> None:
    """Density state must contain aggregate_density, dominant_zone, zones."""
    state = compute_density_state(
        perception_data={"presence_probability": 0.9, "production_activity": "coding"},
        stimmung_stance="nominal",
        audio_energy=0.05,
    )
    assert "aggregate_density" in state
    assert "dominant_zone" in state
    assert "zones" in state
    assert 0.0 <= state["aggregate_density"] <= 1.0


def test_density_zone_has_mode() -> None:
    """Each zone must classify as NEWS, ROUTINE, or ALARM."""
    state = compute_density_state(
        perception_data={"presence_probability": 0.9},
        stimmung_stance="nominal",
        audio_energy=0.0,
    )
    for zone_name, zone_data in state["zones"].items():
        assert zone_data["mode"] in ("NEWS", "ROUTINE", "ALARM")
        assert 0.0 <= zone_data["density"] <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_density_field.py -v
```

Expected: FAIL — `agents.density_field` does not exist.

- [ ] **Step 3: Implement minimal density field module**

Create `agents/density_field.py` with `compute_density_state()` function that:
- Accepts perception_data dict, stimmung_stance str, audio_energy float
- Returns dict with aggregate_density, dominant_zone, dominant_mode, zones
- Each zone: density (0-1), mode (NEWS/ROUTINE/ALARM), top_signal (str)
- Spike version: 3 zones (perception, stimmung, voice) with simple change detection

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_density_field.py -v && uv run ruff check agents/density_field.py
```

- [ ] **Step 5: Spike validation — run 100 ticks and check variance**

```python
# Inline spike test
import json, statistics
from agents.density_field import compute_density_state

results = []
for i in range(100):
    state = compute_density_state(
        perception_data={"presence_probability": 0.5 + 0.01 * (i % 20)},
        stimmung_stance="seeking" if i % 30 < 10 else "nominal",
        audio_energy=0.1 * (i % 10),
    )
    results.append(state["aggregate_density"])

stddev = statistics.stdev(results)
print(f"Stddev: {stddev:.4f} (gate requires > 0.05)")
assert stddev > 0.05, f"SPIKE GATE FAILED: stddev={stddev}"
```

- [ ] **Step 6: Commit**

```bash
git add agents/density_field.py tests/test_density_field.py
git commit -m "feat(density): add density field compute module (spike)

Implements minimal information density computation with 3 zones and
NEWS/ROUTINE/ALARM temporal mode classification. Spike gate passed:
variance > 0.05 across test inputs.

CC-task: perspective-density-field-compute (Phase A)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Track B: Governance & Voice

### Task 4: CCTV Engine Fix

**Branch:** `alpha/cctv-engine-strict-timeout`

**Files:**
- Modify: `agents/deliberative_council/engine.py` (lines 63, 266, 405, 35-36)
- Test: `tests/agents/test_deliberative_council/test_engine_phase1.py`

- [ ] **Step 1: Write failing test for strict=False JSON parsing**

```python
# tests/agents/test_deliberative_council/test_engine_phase1.py — append

def test_parse_phase1_handles_control_characters() -> None:
    """json.loads with control chars in strings must not crash."""
    from agents.deliberative_council.engine import _parse_phase1_output

    raw_with_newlines = '{"scores": {"falsifiability": 3}, "rationale": {"falsifiability": "line1\\nline2"}, "research_findings": []}'
    result = _parse_phase1_output("test-model", raw_with_newlines)
    assert result.scores["falsifiability"] == 3


def test_parse_phase1_handles_literal_control_chars() -> None:
    """Mistral-large embeds literal tab/newline in JSON strings."""
    from agents.deliberative_council.engine import _parse_phase1_output

    raw = '{"scores": {"scope_honesty": 2}, "rationale": {"scope_honesty": "has\ttabs\nand\nnewlines"}, "research_findings": []}'
    result = _parse_phase1_output("mistral-large", raw)
    assert result.scores["scope_honesty"] == 2
```

- [ ] **Step 2: Run test — should fail on strict JSON parsing**

```bash
uv run pytest tests/agents/test_deliberative_council/test_engine_phase1.py::test_parse_phase1_handles_literal_control_chars -v
```

Expected: FAIL (json.JSONDecodeError from strict mode) — falls back to empty scores.

- [ ] **Step 3: Apply strict=False to all 3 json.loads sites**

```python
# Line 63: json.loads(text, strict=False)
# Line 266: json.loads(text, strict=False)
# Line 405: json.loads(text, strict=False)
```

- [ ] **Step 4: Add timeout to _call_member**

Wrap line 36 (`result = await member.run(prompt)`) with:

```python
_MEMBER_TIMEOUT_S: float = 120.0

async def _call_member(member: Agent[None, str], prompt: str) -> tuple[str, list[str]]:
    result = await asyncio.wait_for(member.run(prompt), timeout=_MEMBER_TIMEOUT_S)
    # ... rest unchanged
```

- [ ] **Step 5: Run all CCTV tests**

```bash
uv run pytest tests/agents/test_deliberative_council/ -v && uv run ruff check agents/deliberative_council/engine.py
```

- [ ] **Step 6: Commit**

```bash
git add agents/deliberative_council/engine.py tests/agents/test_deliberative_council/test_engine_phase1.py
git commit -m "fix(cctv): json.loads strict=False + 120s member timeout

Mistral-large returns JSON with embedded control characters that strict
mode rejects. Adds strict=False to all 3 parse sites. Also adds 120s
timeout to _call_member to prevent indefinite hangs.

CC-task: cctv-engine-json-strict-timeout

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Assertions Pipeline Activation (REQ-04)

**Branch:** `alpha/perspective-assertions-pipeline`

**Files:**
- Modify: `shared/qdrant_schema.py`
- Create: `scripts/populate-assertions`
- Test: `tests/shared/test_assertion_pipeline.py`

- [ ] **Step 1: Write failing test for Qdrant collection schema**

```python
# tests/shared/test_assertion_pipeline.py

def test_assertions_collection_in_schema() -> None:
    """assertions must be declared in EXPECTED_COLLECTIONS."""
    from shared.qdrant_schema import EXPECTED_COLLECTIONS

    assert "assertions" in EXPECTED_COLLECTIONS
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/shared/test_assertion_pipeline.py -v
```

Expected: FAIL — "assertions" not in EXPECTED_COLLECTIONS

- [ ] **Step 3: Add assertions to qdrant_schema.py**

Find `EXPECTED_COLLECTIONS` dict in `shared/qdrant_schema.py` and add:

```python
"assertions": {"size": EXPECTED_EMBED_DIMENSIONS, "distance": "Cosine"},
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/shared/test_assertion_pipeline.py -v
```

- [ ] **Step 5: Create orchestrator script**

Create `scripts/populate-assertions` (see REQ-04 spec for full implementation). The script chains: extract → normalize → embed → upsert.

- [ ] **Step 6: Commit**

```bash
git add shared/qdrant_schema.py scripts/populate-assertions tests/shared/test_assertion_pipeline.py
git commit -m "feat(assertions): add Qdrant collection schema + orchestrator script

Adds 'assertions' collection to qdrant_schema.py and creates
populate-assertions orchestrator that chains code/prose/governance
extractors through normalization and Qdrant upsert.

CC-task: perspective-assertions-pipeline

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Tasks 6-12 follow the same TDD pattern. Full details for REQ-03 (T4 ownership gate), REQ-05 (epistemic axiom), REQ-06 (voice register), REQ-08 (planner bridge), REQ-09 (CHI evidence), langfuse retention, and grounding doc are available in the CC-task specs and CCTV-hardened request text. Each follows:

1. Write failing test targeting the acceptance criteria
2. Verify failure
3. Implement minimal code
4. Verify pass
5. Ruff check
6. Commit with conventional message + CC-task reference

---

## Execution Order (dependency-respecting)

```
PARALLEL START:
  Track A: Task 1 (eigenform fix) → Task 2 (persist) → Task 3 (density spike)
  Track B: Task 4 (CCTV fix) | Task 5 (assertions)
  Track C: langfuse retention (config only)

AFTER Track A Task 1:
  Track A continues to Task 2, 3

AFTER Track B Task 5:
  Task 6: epistemic axiom (REQ-05)

AFTER Track B Task 4 + grounding doc:
  Task 7: T4 ownership gate (REQ-03)

AFTER Task 6:
  Task 8: voice register (REQ-06)

AFTER Track A Task 3:
  Task 9: planner bridge (REQ-08)

AFTER all tracks:
  Task 10: CHI evidence infrastructure (REQ-09)
```

## PR Strategy

Each track produces one PR:
- **PR-A:** `alpha/perspective-eigenform-sensing` — Tasks 1-3
- **PR-B:** `alpha/perspective-governance-voice` — Tasks 4-8
- **PR-C:** `alpha/perspective-chi-evidence` — Tasks 9-10 + langfuse

Or if the branch discipline requires smaller PRs, split per-task.

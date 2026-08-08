"""Convergence contract: admission gate-event emission lights the gate-events feed.

The intake fit-shadow slice emits one observational ``GateEvent`` per planned dispatch to
``~/.cache/hapax/sdlc-routing/gate-events.jsonl`` — the plane the reins ``:route`` lens
reads. Tests cover: the ``GateEvent.fit_score`` round-trip, the emit stamping
reqvec+routing_class+fit_score on a measured task, DARK/partial honesty (``fit_score=None``),
and fail-open (a lost measurement never crashes the dispatch tick).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.coordinator.core import Coordinator, _parse_task
from shared.gate_log import GateEvent

_LANE = MagicMock()
_LANE.platform = "codex"

_FULL_FM = """---
type: cc-task
task_id: T-full
title: full demand
status: offered
assigned_to: unassigned
wsjf: 8.0
effort_class: standard
platform_suitability:
  - codex
quality_floor: deterministic_ok
requirement_vector:
  quality_floor: 3
  information_scope: 4
  context_length: 4
  mutation_risk: 5
  verification_demand: 3
  ambiguity_novelty: 2
  composition_coupling: 1
  governance_sensitivity: 2
routing_class: source_python
mutation_surface: source
authority_level: authoritative
created_at: 2026-07-04T00:00:00Z
---

# body
"""

_PARTIAL_FM = """---
type: cc-task
task_id: T-partial
title: partial
status: offered
assigned_to: unassigned
wsjf: 5.0
effort_class: standard
platform_suitability:
  - codex
quality_floor: deterministic_ok
requirement_vector:
  context_length: 4
routing_class: source_python
created_at: 2026-07-04T00:00:00Z
---

# body
"""

_DARK_FM = """---
type: cc-task
task_id: T-dark
title: no demand shape
status: offered
assigned_to: unassigned
wsjf: 5.0
effort_class: standard
platform_suitability:
  - codex
quality_floor: deterministic_ok
created_at: 2026-07-04T00:00:00Z
---

# body
"""


def _task(fm: str, tmp_path: Path):
    p = tmp_path / "T.md"
    p.write_text(fm, encoding="utf-8")
    task = _parse_task(p)
    assert task is not None
    return task


# ----------------------------------------------------------------- GateEvent.fit_score


def test_gate_event_fit_score_round_trip() -> None:
    # The additive field serializes + deserializes; default is None (not scored).
    event = GateEvent(route="codex", routing_class="source_python", fit_score=3.5)
    assert event.fit_score == 3.5
    rt = GateEvent.model_validate_json(event.model_dump_json())
    assert rt.fit_score == 3.5
    # default is None (the DARK / not-yet-scored sentinel)
    assert GateEvent(route="codex", routing_class="c").fit_score is None


# --------------------------------------------------------------- admission emit


def test_emit_admission_stamps_measured_fields(tmp_path: Path) -> None:
    task = _task(_FULL_FM, tmp_path)
    coord = Coordinator()
    with patch("agents.coordinator.core.append_gate_event") as appended:
        coord._emit_admission_gate_event(task, _LANE, accepted=True)
    appended.assert_called_once()
    event = appended.call_args.args[0]
    assert event.gate_result == "accept"
    assert event.provenance == "admission"
    assert event.gate_type == "none"
    assert event.route == "codex"
    assert event.routing_class == "source_python"
    # the full 8-dim measured vector is present
    assert set(event.requirement_vector) == {
        "quality_floor",
        "information_scope",
        "context_length",
        "mutation_risk",
        "verification_demand",
        "ambiguity_novelty",
        "composition_coupling",
        "governance_sensitivity",
    }
    # fit_score = mean of non-quality dims = (4+4+5+3+2+1+2)/7 = 3.0
    assert event.fit_score == 3.0


def test_emit_admission_partial_vector_is_dark_fit_score(tmp_path: Path) -> None:
    # A partial vector is NOT a measured vector (reins' _measured_reqvec_or_absent): the
    # producer emits an empty requirement_vector and the spine stamps fit_score=None
    # (DARK), never a fabricated score over partial data.
    task = _task(_PARTIAL_FM, tmp_path)
    coord = Coordinator()
    with patch("agents.coordinator.core.append_gate_event") as appended:
        coord._emit_admission_gate_event(task, _LANE, accepted=True)
    event = appended.call_args.args[0]
    assert event.requirement_vector == {}
    assert event.fit_score is None


def test_emit_admission_dark_task_fit_score_none(tmp_path: Path) -> None:
    task = _task(_DARK_FM, tmp_path)
    coord = Coordinator()
    with patch("agents.coordinator.core.append_gate_event") as appended:
        coord._emit_admission_gate_event(task, _LANE, accepted=False)
    event = appended.call_args.args[0]
    assert event.requirement_vector == {}
    assert event.fit_score is None
    assert event.gate_result == "reject"  # a refused dispatch is recorded as a reject


def test_emit_admission_fail_open(tmp_path: Path) -> None:
    # A lost measurement must never crash the dispatch tick — assembly or I/O failure is
    # swallowed (fail-open to observation; the plan is authoritative).
    task = _task(_FULL_FM, tmp_path)
    coord = Coordinator()
    with (
        patch(
            "agents.coordinator.core.build_gate_event",
            side_effect=OSError("disk full"),
        ),
        patch("agents.coordinator.core.append_gate_event") as appended,
    ):
        coord._emit_admission_gate_event(task, _LANE, accepted=True)  # must not raise
    appended.assert_not_called()

"""Gate-0A coordinator dispatch containment tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import agents.coordinator.core as coordinator_core
from agents.coordinator.core import Coordinator, LaneState, Task
from shared.methodology_dispatch_carrier import (
    canonical_dispatch_carrier_bytes,
    seal_methodology_dispatch_carrier,
)
from shared.sdlc_pressure_gate import AdmissionDecision


def _held_carrier() -> bytes:
    carrier = seal_methodology_dispatch_carrier(
        {
            "event": "methodology_dispatch",
            "task_id": "T-held",
            "lane": "cx-red",
            "platform": "codex",
            "mode": "headless",
            "profile": "full",
            "requested_operation": "launch",
            "launched": False,
            "may_authorize": False,
            "receipt_is_admission": False,
        }
    )
    return canonical_dispatch_carrier_bytes(carrier) + b"\n"


def test_coordinator_has_no_gate_event_publication_path() -> None:
    assert not hasattr(Coordinator, "_emit_admission_gate_event")
    assert not hasattr(coordinator_core, "INTAKE_FIT_OBSERVE_ENV")
    assert not hasattr(coordinator_core, "append_gate_event")
    assert not hasattr(coordinator_core, "build_gate_event")


def test_held_carrier_has_zero_mq_gate_log_or_notification_effects(
    tmp_path: Path,
) -> None:
    dispatcher = tmp_path / "hapax-methodology-dispatch"
    dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    dispatcher.chmod(0o755)
    task = Task(
        task_id="T-held",
        title="held",
        status="offered",
        assigned_to="unassigned",
        wsjf=10.0,
        effort_class="standard",
        platform_suitability=("codex",),
        quality_floor="deterministic_ok",
        path=tmp_path / "T-held.md",
        authority_case="CASE-HELD-001",
    )
    lane = LaneState(role="cx-red", platform="codex", alive=True, idle=True)
    coordinator = Coordinator()
    state_path = tmp_path / "shm" / "state.json"

    with (
        patch.object(coordinator, "_scan_tasks", return_value=[task]),
        patch.object(coordinator, "_check_lanes", return_value={"cx-red": lane}),
        patch(
            "agents.coordinator.core.observe_admission_state",
            return_value=AdmissionDecision(state="open"),
        ),
        patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
        patch(
            "agents.coordinator.core.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=_held_carrier(),
                stderr=b"",
            ),
        ),
        patch("agents.coordinator.core.SHM_DIR", state_path.parent),
        patch("agents.coordinator.core.SHM_FILE", state_path),
        patch("shared.relay_mq.send_message") as send_mq,
        patch("shared.gate_log.append_gate_event") as append_gate,
        patch.dict("os.environ", {"HAPAX_INTAKE_FIT_OBSERVE": "1"}),
    ):
        coordinator.tick()

    send_mq.assert_not_called()
    append_gate.assert_not_called()
    assert not hasattr(coordinator, "_last_dispatch")
    assert coordinator._refusal_ledger._entries == {}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["dispatches_this_tick"] == 0

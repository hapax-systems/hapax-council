"""Source-level pins that the resource-shielding scheme stays wired end-to-end.

The integration glue (bash self-attach, the dispatch chokepoint, the watchdog
gate) is hard to unit-test in isolation, so these assert the load-bearing wiring
is present in the scripts that carry it.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DISPATCH = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"
CLAUDE_HEADLESS = REPO_ROOT / "scripts" / "hapax-claude-headless"
WATCHDOG = REPO_ROOT / "scripts" / "hapax-lane-idle-watchdog"
SUPERVISOR = REPO_ROOT / "scripts" / "hapax-lane-supervisor"
COORDINATOR = REPO_ROOT / "agents" / "coordinator" / "core.py"


def test_dispatch_wraps_lane_launches_into_the_slice() -> None:
    text = DISPATCH.read_text()
    assert "from shared.sdlc_pressure_gate import" in text
    # All four headless launchers route through the slice-wrapping call.
    assert text.count("_sliced_call(") >= 4
    assert "sdlc_slice_wrap" in text


def test_dispatch_has_the_pressure_chokepoint() -> None:
    text = DISPATCH.read_text()
    assert "_await_sdlc_admission(args)" in text
    # The chokepoint queues (DELAYED receipt), never refuses.
    assert "sdlc-pressure-delayed" in text
    assert "queued_not_dropped" in text


def test_claude_headless_self_attaches_to_slice() -> None:
    text = CLAUDE_HEADLESS.read_text()
    assert "--slice=hapax-sdlc.slice" in text
    assert "HAPAX_SDLC_SLICE_ATTACHED" in text
    # Re-exec with the saved original argv (arg parsing shifts "$@").
    assert "ORIG_ARGS" in text


def test_watchdog_respawn_floor_yields_when_closed() -> None:
    text = WATCHDOG.read_text()
    assert "sdlc_admission_state" in text
    assert "shared.sdlc_pressure_gate --state" in text
    # Both the Claude and Codex respawn floors gate on admission.
    assert text.count('"$SDLC_ADMISSION" != "closed"') >= 2
    assert "HAPAX_LOCAL_DEV_MAINTENANCE_MODE" in text
    assert "appendix-only local-dev maintenance" in text


def test_supervisor_appendix_only_suppresses_unclaimed_idle_await_respawn() -> None:
    text = SUPERVISOR.read_text()
    assert "HAPAX_LOCAL_DEV_MAINTENANCE_MODE" in text
    assert "appendix-only local-dev maintenance" in text
    assert "suppresses idle-await respawn" in text
    assert "active claimed-task resumes preserved" in text


def test_coordinator_paces_dispatch_under_pressure() -> None:
    text = COORDINATOR.read_text()
    assert "from shared.sdlc_pressure_gate import admission_state" in text
    assert "pressure_dispatch_budget(" in text

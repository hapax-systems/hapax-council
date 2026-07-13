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


def test_dispatch_holds_before_slice_attachment_or_process_launch() -> None:
    text = DISPATCH.read_text()
    assert "    sdlc_slice_wrap," not in text
    assert "    wait_until_admitted," not in text
    assert text.count("_sliced_call(") >= 4
    assert '_hold_gate0a_effect("process.launch")' in text
    assert "sdlc_slice_wrap" not in text


def test_dispatch_holds_before_pressure_wait_or_delayed_receipt() -> None:
    text = DISPATCH.read_text()
    assert "_await_sdlc_admission(args)" not in text
    assert "def _await_sdlc_admission" in text
    assert '_hold_gate0a_effect("dispatch.pressure-wait")' in text
    assert "sdlc-pressure-delayed" not in text
    assert "queued_not_dropped" not in text


def test_claude_headless_self_attaches_to_slice() -> None:
    text = CLAUDE_HEADLESS.read_text()
    assert "--slice=hapax-sdlc.slice" in text
    assert "HAPAX_SDLC_SLICE_ATTACHED" in text
    # Re-exec with the saved original argv (arg parsing shifts "$@").
    assert "ORIG_ARGS" in text


def test_watchdog_is_observation_only_without_respawn_or_pressure_gate() -> None:
    text = WATCHDOG.read_text()
    assert "support_only=true effects=0" in text
    for forbidden in (
        "sdlc_admission_state",
        "shared.sdlc_pressure_gate",
        "tmux send-keys",
        "hapax-methodology-dispatch",
        "hapax-codex-headless",
        "hapax-claude-headless",
        "hapax-codex --",
        "hapax-claude --",
        "HAPAX_LOCAL_DEV_MAINTENANCE_MODE",
    ):
        assert forbidden not in text


def test_supervisor_appendix_only_suppresses_unclaimed_idle_await_respawn() -> None:
    text = SUPERVISOR.read_text()
    assert "HAPAX_LOCAL_DEV_MAINTENANCE_MODE" in text
    assert "appendix-only local-dev maintenance" in text
    assert "suppresses idle-await respawn" in text
    assert "active claimed-task resumes preserved" in text


def test_coordinator_records_pressure_without_candidate_influence() -> None:
    text = COORDINATOR.read_text()
    assert "from shared.sdlc_pressure_gate import observe_admission_state" in text
    assert '"candidate_influence": "none"' in text
    assert "MAX_HELD_CANDIDATES_PER_TICK" in text
    assert "pressure_dispatch_budget(" not in text
    assert "converge_action_cap(" not in text

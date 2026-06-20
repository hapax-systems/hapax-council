"""Tests for shared.sdlc_pressure_gate — the L3 PSI-feedback admission gate.

The gate turns CPU pressure into a {open, paced, closed} admission state with
hysteresis (separate enter/exit thresholds) and a min-dwell so it never flaps.
It must QUEUE (pace/pause) under pressure, never DROP — the wave governor runs
every item, just in pressure-gated waves.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.sdlc_pressure_gate import (
    AdmissionDecision,
    GateState,
    PressureReading,
    admission_state,
    decide,
    parse_psi_some,
    run_in_waves,
    sdlc_slice_wrap,
    wait_until_admitted,
)


def _reading(
    psi: float, load: float = 0.0, mode: str = "research", team: str | None = None
) -> PressureReading:
    return PressureReading(
        psi_some_avg10=psi,
        psi_some_avg60=psi,
        load_per_core=load,
        working_mode=mode,
        team_level=team,
    )


# ── PSI parsing ──────────────────────────────────────────────────────────────


def test_parse_psi_some_extracts_avg10_and_avg60() -> None:
    line = "some avg10=51.46 avg60=42.15 avg300=38.63 total=13687610732\nfull avg10=0.00"
    reading = parse_psi_some(line)
    assert reading.some_avg10 == 51.46
    assert reading.some_avg60 == 42.15


# ── decide(): raw state mapping + hysteresis + min-dwell ─────────────────────


def test_open_stays_open_under_low_pressure() -> None:
    state = decide(_reading(psi=10.0, load=0.5), prev=GateState("open", 0.0), now=100.0)
    assert state.state == "open"


def test_open_escalates_to_paced_when_psi_crosses_enter() -> None:
    state = decide(_reading(psi=40.0), prev=GateState("open", 0.0), now=100.0)
    assert state.state == "paced"


def test_open_escalates_to_closed_on_high_psi() -> None:
    state = decide(_reading(psi=70.0), prev=GateState("open", 0.0), now=100.0)
    assert state.state == "closed"


def test_open_escalates_to_paced_on_load_per_core() -> None:
    state = decide(_reading(psi=5.0, load=2.0), prev=GateState("open", 0.0), now=100.0)
    assert state.state == "paced"


def test_paced_holds_inside_hysteresis_band() -> None:
    # psi=25 is below the paced ENTER (35) but above the paced EXIT (20):
    # an already-paced gate must NOT relax — that's the whole point of hysteresis.
    prev = GateState("paced", 0.0)
    state = decide(_reading(psi=25.0), prev=prev, now=1000.0)
    assert state.state == "paced"


def test_paced_relaxes_to_open_below_exit_after_min_dwell() -> None:
    prev = GateState("paced", 0.0)
    state = decide(_reading(psi=10.0), prev=prev, now=1000.0)  # dwell long elapsed
    assert state.state == "open"


def test_paced_cannot_relax_before_min_dwell() -> None:
    prev = GateState("paced", 995.0)  # only 5s in state, min-dwell not met
    state = decide(_reading(psi=10.0), prev=prev, now=1000.0)
    assert state.state == "paced"


def test_escalation_is_immediate_ignoring_min_dwell() -> None:
    # Just entered paced 1s ago; pressure spikes — must jump to closed at once.
    prev = GateState("paced", 999.0)
    state = decide(_reading(psi=70.0), prev=prev, now=1000.0)
    assert state.state == "closed"


def test_closed_relaxes_one_step_to_paced_after_dwell() -> None:
    # psi=40 < closed EXIT (45) but > paced ENTER (35): closed -> paced, not open.
    prev = GateState("closed", 0.0)
    state = decide(_reading(psi=40.0), prev=prev, now=1000.0)
    assert state.state == "paced"


def test_fortress_mode_tightens_thresholds() -> None:
    # psi=25 is "open" in research (enter 35) but "paced" in fortress (enter 20).
    research = decide(_reading(psi=25.0, mode="research"), prev=GateState("open", 0.0), now=100.0)
    fortress = decide(_reading(psi=25.0, mode="fortress"), prev=GateState("open", 0.0), now=100.0)
    assert research.state == "open"
    assert fortress.state == "paced"


def test_team_load_red_forces_closed() -> None:
    # The reused hapax-team-load classifier is load-bearing: a red team level
    # closes admission even when raw PSI/load look calm.
    state = decide(_reading(psi=5.0, load=0.1, team="red"), prev=GateState("open", 0.0), now=100.0)
    assert state.state == "closed"


# ── admission_state(): live wrapper persists across calls ────────────────────


def test_admission_state_persists_state_to_file(tmp_path: Path) -> None:
    state_path = tmp_path / "sdlc-pressure-state.json"
    first = admission_state(now=1000.0, reading=_reading(psi=80.0), state_path=state_path)
    assert isinstance(first, AdmissionDecision)
    assert first.state == "closed"
    on_disk = json.loads(state_path.read_text())
    assert on_disk["state"] == "closed"


def test_admission_state_holds_closed_within_dwell_on_next_call(tmp_path: Path) -> None:
    state_path = tmp_path / "sdlc-pressure-state.json"
    admission_state(now=1000.0, reading=_reading(psi=80.0), state_path=state_path)
    # 5s later, pressure gone, but min-dwell (20s) not elapsed -> still closed.
    second = admission_state(now=1005.0, reading=_reading(psi=2.0), state_path=state_path)
    assert second.state == "closed"


# ── run_in_waves(): the wave governor never drops an item ────────────────────


def test_run_in_waves_emits_every_item_in_order() -> None:
    waves = list(run_in_waves(range(7), wave_size=3, is_open=lambda: True, sleep=lambda _s: None))
    assert waves == [[0, 1, 2], [3, 4, 5], [6]]
    assert [item for wave in waves for item in wave] == list(range(7))


def test_run_in_waves_waits_while_closed_then_still_emits_the_wave() -> None:
    gate = iter([False, False, True, True, True])  # closed twice, then open
    slept: list[float] = []

    waves = list(
        run_in_waves(
            range(4),
            wave_size=2,
            is_open=lambda: next(gate),
            sleep=slept.append,
        )
    )

    # All four items still emitted (queued, not dropped) ...
    assert [item for wave in waves for item in wave] == [0, 1, 2, 3]
    # ... and it actually waited while the gate was closed.
    assert len(slept) >= 2


# ── sdlc_slice_wrap(): attach a lane launch to hapax-sdlc.slice ──────────────


def test_slice_wrap_prefixes_systemd_run_scope() -> None:
    wrapped = sdlc_slice_wrap(
        ["hapax-claude-headless", "--task", "t", "zeta"],
        already_attached=False,
        systemd_run="/usr/bin/systemd-run",
        slice_available=True,
    )
    assert wrapped[0] == "/usr/bin/systemd-run"
    assert "--scope" in wrapped
    assert "--slice=hapax-sdlc.slice" in wrapped
    # original argv preserved after the `--` separator
    assert wrapped[-4:] == ["hapax-claude-headless", "--task", "t", "zeta"]


def test_slice_wrap_preserves_explicit_dispatch_environment() -> None:
    wrapped = sdlc_slice_wrap(
        ["hapax-claude-headless", "--task", "t", "alpha"],
        already_attached=False,
        systemd_run="/usr/bin/systemd-run",
        slice_available=True,
        setenv={
            "HAPAX_CLAUDE_HEADLESS_WORKDIR": "/tmp/clean-worktree",
            "HAPAX_DISPATCH_HOST": "local",
        },
    )

    separator = wrapped.index("--")
    assert "--setenv=HAPAX_CLAUDE_HEADLESS_WORKDIR=/tmp/clean-worktree" in wrapped[:separator]
    assert "--setenv=HAPAX_DISPATCH_HOST=local" in wrapped[:separator]
    assert wrapped[separator + 1 :] == ["hapax-claude-headless", "--task", "t", "alpha"]


def test_slice_wrap_is_noop_when_already_attached() -> None:
    argv = ["hapax-codex-headless", "cx-amber"]
    assert (
        sdlc_slice_wrap(argv, already_attached=True, systemd_run="/x", slice_available=True) == argv
    )


def test_slice_wrap_is_noop_without_systemd_run() -> None:
    # Dispatch must never hard-fail just because the fence is unavailable.
    argv = ["hapax-vibe", "vbe-1"]
    assert sdlc_slice_wrap(argv, already_attached=False, systemd_run=None) == argv


def test_slice_wrap_is_noop_when_slice_unavailable() -> None:
    argv = ["hapax-antigrav", "antigrav"]
    out = sdlc_slice_wrap(argv, already_attached=False, systemd_run="/x", slice_available=False)
    assert out == argv


# ── wait_until_admitted(): the block-and-wait chokepoint ─────────────────────


def test_wait_until_admitted_blocks_then_returns_on_reopen() -> None:
    seq = iter(
        [
            AdmissionDecision(state="closed"),
            AdmissionDecision(state="closed"),
            AdmissionDecision(state="open"),
        ]
    )
    delays: list[AdmissionDecision] = []
    slept: list[float] = []

    final = wait_until_admitted(
        lambda: next(seq),
        sleep=slept.append,
        on_delay=delays.append,
        poll_interval=3.0,
    )

    assert final.state == "open"
    assert len(slept) == 2  # waited through both closed polls
    assert len(delays) == 2  # a DELAYED receipt refreshed each closed poll


def test_wait_until_admitted_proceeds_after_max_wait_never_drops() -> None:
    # Gate stays closed forever; the dispatch must still proceed (queued, not
    # dropped) once the cap is hit.
    slept: list[float] = []
    final = wait_until_admitted(
        lambda: AdmissionDecision(state="closed"),
        sleep=slept.append,
        poll_interval=5.0,
        max_wait_s=10.0,
    )
    assert final.state == "closed"
    assert sum(slept) >= 10.0

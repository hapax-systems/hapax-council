"""Closed master −14 LUFS-I loop (segment-audio-remainder AC#2).

A SLOW, bounded controller nudges the broadcast master makeup toward
``EGRESS_TARGET_LUFS_I`` (−14), replacing reliance on the open-loop +16 dB
makeup (which stays as the never-remove fallback). It is time-constant-separated
from the duck (10 ms / 400 ms): it integrates over tens of seconds, nudges only
every several seconds in ≤ ``MASTER_LUFS_MAX_STEP_DB`` steps, and FREEZES while
the bus is ducked so it can never chase a ducked-quieter bus upward.

It is DARK BY DEFAULT (``enabled=False``): it measures + publishes what it WOULD
do but never actuates until proven at the alpha-gated go-live.

The controller is pure logic over injected readers/actuator, so the whole
control law is exercised with no PipeWire and no real audio.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from agents.hapax_daimonion import master_lufs_loop as mll
from agents.hapax_daimonion.master_lufs_loop import (
    MasterLufsController,
    compute_makeup_step,
    parse_ebur128_integrated_lufs,
    should_freeze,
)
from shared.audio_loudness import (
    DUCK_RELEASE_MS,
    EGRESS_TARGET_LUFS_I,
    MASTER_INPUT_MAKEUP_DB,
    MASTER_LUFS_INTEGRATION_WINDOW_S,
    MASTER_LUFS_MAKEUP_BAND_DB,
    MASTER_LUFS_MAX_STEP_DB,
    MASTER_LUFS_UPDATE_INTERVAL_S,
)

# ── time-constant separation (slow loop vs fast duck) ────────────────────────


def test_loop_is_slow_relative_to_the_duck() -> None:
    duck_release_s = DUCK_RELEASE_MS / 1000.0
    # Nudge cadence is at least 10× the duck's release so the slow loop never
    # reacts within a duck event.
    assert 10 * duck_release_s <= MASTER_LUFS_UPDATE_INTERVAL_S
    # Integrate over at least one update interval.
    assert MASTER_LUFS_INTEGRATION_WINDOW_S >= MASTER_LUFS_UPDATE_INTERVAL_S


def test_step_is_small_and_band_stays_in_ladspa_range() -> None:
    assert 0 < MASTER_LUFS_MAX_STEP_DB <= 1.0
    # makeup band around the static +16 must stay inside the LADSPA [-20, +20].
    assert MASTER_INPUT_MAKEUP_DB + MASTER_LUFS_MAKEUP_BAND_DB <= 20
    assert MASTER_INPUT_MAKEUP_DB - MASTER_LUFS_MAKEUP_BAND_DB >= -20


# ── compute_makeup_step (bounded control law) ────────────────────────────────

_BAND = (
    MASTER_INPUT_MAKEUP_DB - MASTER_LUFS_MAKEUP_BAND_DB,
    MASTER_INPUT_MAKEUP_DB + MASTER_LUFS_MAKEUP_BAND_DB,
)


def test_too_quiet_increases_makeup_within_one_step() -> None:
    # measured (−20) below target (−14) → need more makeup, by at most one step.
    new = compute_makeup_step(16.0, -20.0, target=-14.0, max_step_db=0.5, makeup_band=_BAND)
    assert new == 16.5


def test_too_loud_decreases_makeup_within_one_step() -> None:
    new = compute_makeup_step(16.0, -8.0, target=-14.0, max_step_db=0.5, makeup_band=_BAND)
    assert new == 15.5


def test_on_target_holds_makeup() -> None:
    assert (
        compute_makeup_step(16.0, -14.0, target=-14.0, max_step_db=0.5, makeup_band=_BAND) == 16.0
    )


def test_step_never_exceeds_max_even_on_large_error() -> None:
    new = compute_makeup_step(16.0, -40.0, target=-14.0, max_step_db=0.5, makeup_band=_BAND)
    assert abs(new - 16.0) <= 0.5


def test_makeup_never_leaves_the_band() -> None:
    # Already at the top of the band and still too quiet → cannot rise further.
    assert (
        compute_makeup_step(19.0, -30.0, target=-14.0, max_step_db=0.5, makeup_band=(13.0, 19.0))
        == 19.0
    )
    # At the bottom and still too loud → cannot fall further.
    assert (
        compute_makeup_step(13.0, 0.0, target=-14.0, max_step_db=0.5, makeup_band=(13.0, 19.0))
        == 13.0
    )


# ── should_freeze (don't chase the duck) ─────────────────────────────────────


def test_clean_bus_does_not_freeze() -> None:
    assert (
        should_freeze(
            {"trigger_cause": "none", "commanded_music_duck_gain": 1.0, "fail_open": False}
        )
        is False
    )


def test_active_duck_freezes() -> None:
    assert (
        should_freeze({"trigger_cause": "operator_voice", "commanded_music_duck_gain": 0.25})
        is True
    )


def test_partial_duck_gain_freezes() -> None:
    assert should_freeze({"trigger_cause": "none", "commanded_music_duck_gain": 0.5}) is True


def test_fail_open_freezes() -> None:
    assert (
        should_freeze(
            {"trigger_cause": "none", "commanded_music_duck_gain": 1.0, "fail_open": True}
        )
        is True
    )


def test_missing_or_malformed_duck_state_freezes_conservatively() -> None:
    assert should_freeze(None) is True
    assert should_freeze({}) is True


# ── MasterLufsController.tick ────────────────────────────────────────────────


def _controller(
    *, enabled: bool, measured, duck, actuator=None, publisher=None
) -> MasterLufsController:  # noqa: ANN001
    return MasterLufsController(
        lufs_reader=lambda: measured,
        ducker_state_reader=lambda: duck,
        actuator=actuator,
        publisher=publisher,
        enabled=enabled,
    )


_CLEAN = {"trigger_cause": "none", "commanded_music_duck_gain": 1.0, "fail_open": False}


def _ok_actuator(sink: list[float]):  # noqa: ANN202
    """Actuator that records the value and reports a successful live actuation."""

    def _act(value: float) -> bool:
        sink.append(value)
        return True

    return _act


def test_dark_by_default_never_actuates() -> None:
    actuations: list[float] = []
    ctrl = _controller(enabled=False, measured=-20.0, duck=_CLEAN, actuator=actuations.append)
    status = ctrl.tick()
    assert actuations == []  # no live gain change while dark
    assert ctrl.makeup_db == MASTER_INPUT_MAKEUP_DB  # believed-live gain unchanged
    assert status["proposed_makeup_db"] == 16.5  # but it reports what it WOULD do


def test_enabled_actuates_toward_target_when_clean() -> None:
    actuations: list[float] = []
    ctrl = _controller(enabled=True, measured=-20.0, duck=_CLEAN, actuator=_ok_actuator(actuations))
    ctrl.tick()
    assert actuations == [16.5]
    assert ctrl.makeup_db == 16.5


def test_makeup_does_not_advance_when_actuation_fails() -> None:
    # The actuator reports failure (e.g. the live set-param did not take) →
    # the believed-live makeup must NOT advance, so the next tick retries.
    ctrl = MasterLufsController(
        lufs_reader=lambda: -20.0,
        ducker_state_reader=lambda: _CLEAN,
        actuator=lambda _value: False,
        enabled=True,
    )
    status = ctrl.tick()
    assert ctrl.makeup_db == MASTER_INPUT_MAKEUP_DB
    assert status["actuated"] is False


def test_frozen_while_ducked_does_not_measure_or_actuate() -> None:
    actuations: list[float] = []
    measured_calls: list[int] = []

    def _reader() -> float:
        measured_calls.append(1)
        return -20.0

    ctrl = MasterLufsController(
        lufs_reader=_reader,
        ducker_state_reader=lambda: {"trigger_cause": "tts", "commanded_music_duck_gain": 0.4},
        actuator=actuations.append,
        enabled=True,
    )
    status = ctrl.tick()

    assert status["frozen"] is True
    assert actuations == []  # never nudges a ducked bus
    assert measured_calls == []  # doesn't even integrate the ducked signal
    assert ctrl.makeup_db == MASTER_INPUT_MAKEUP_DB


def test_no_measurement_holds_and_does_not_actuate() -> None:
    actuations: list[float] = []
    ctrl = _controller(enabled=True, measured=None, duck=_CLEAN, actuator=actuations.append)
    status = ctrl.tick()
    assert actuations == []
    assert status["measured_lufs_i"] is None
    assert ctrl.makeup_db == MASTER_INPUT_MAKEUP_DB


def test_converges_in_bounded_steps_and_caps_at_band() -> None:
    actuations: list[float] = []
    ctrl = MasterLufsController(
        lufs_reader=lambda: -30.0,  # persistently too quiet
        ducker_state_reader=lambda: _CLEAN,
        actuator=_ok_actuator(actuations),
        enabled=True,
    )
    for _ in range(40):
        ctrl.tick()

    # Rises in ≤ max-step increments and never exceeds the +3 dB band cap.
    assert ctrl.makeup_db == MASTER_INPUT_MAKEUP_DB + MASTER_LUFS_MAKEUP_BAND_DB
    assert (
        max(b - a for a, b in zip(actuations, actuations[1:], strict=False))
        <= MASTER_LUFS_MAX_STEP_DB
    )
    # EGRESS target wiring sanity.
    assert EGRESS_TARGET_LUFS_I == -14.0


# ── ebur128 integrated-LUFS parser (the live tap's reading) ──────────────────


def test_parse_ebur128_integrated_reads_the_summary_value() -> None:
    summary = (
        "[Parsed_ebur128_0 @ 0x55] Summary:\n"
        "\n"
        "  Integrated loudness:\n"
        "    I:         -16.3 LUFS\n"
        "    Threshold: -26.5 LUFS\n"
        "\n"
        "  Loudness range:\n"
        "    LRA:         6.1 LU\n"
    )
    assert parse_ebur128_integrated_lufs(summary) == -16.3


def test_parse_ebur128_returns_none_when_absent() -> None:
    assert parse_ebur128_integrated_lufs("no loudness here") is None


def test_lufs_reader_reaps_capture_and_closes_pipe(monkeypatch) -> None:  # noqa: ANN001
    # The live reader pipes pw-cat → ffmpeg every tick; it MUST close the pipe
    # and reap the capture child or it leaks an fd + a zombie process per tick.
    capture = MagicMock()
    ffmpeg = MagicMock()
    ffmpeg.stderr = b"  I:         -16.0 LUFS\n"
    monkeypatch.setattr(mll.subprocess, "Popen", lambda *a, **k: capture)
    monkeypatch.setattr(mll.subprocess, "run", lambda *a, **k: ffmpeg)

    result = mll.read_broadcast_lufs_i(window_s=0.01)

    assert result == -16.0
    capture.stdout.close.assert_called_once()
    capture.wait.assert_called_once()


# ── reachability: the supervised loop actually ticks, and stays dark ─────────


def test_loop_ticks_the_controller_and_stays_dark_by_default(monkeypatch) -> None:  # noqa: ANN001
    daemon = MagicMock()
    daemon._running = True
    daemon.cfg.master_lufs_controller_enabled = False  # dark default

    published: list[dict] = []
    actuations: list[float] = []
    monkeypatch.setattr(mll, "read_broadcast_lufs_i", lambda *a, **k: -20.0)
    monkeypatch.setattr(mll, "read_ducker_state", lambda *a, **k: _CLEAN)
    monkeypatch.setattr(mll, "publish_status", lambda status, *a, **k: published.append(status))
    monkeypatch.setattr(
        mll, "actuate_master_makeup", lambda value, *a, **k: actuations.append(value)
    )

    async def _stop_after_one(_seconds: float) -> None:
        daemon._running = False

    monkeypatch.setattr(mll.asyncio, "sleep", _stop_after_one)

    asyncio.run(mll.master_lufs_loop(daemon))

    # The loop stood the tap up and ticked the controller at least once …
    assert published, "loop never ticked — the LUFS tap is dead wiring"
    assert published[-1]["enabled"] is False
    # … but DARK BY DEFAULT means it never touched the live master makeup.
    assert actuations == []


def test_loop_actuates_once_enabled(monkeypatch) -> None:  # noqa: ANN001
    daemon = MagicMock()
    daemon._running = True
    daemon.cfg.master_lufs_controller_enabled = True

    actuations: list[float] = []
    monkeypatch.setattr(mll, "read_broadcast_lufs_i", lambda *a, **k: -20.0)
    monkeypatch.setattr(mll, "read_ducker_state", lambda *a, **k: _CLEAN)
    monkeypatch.setattr(mll, "publish_status", lambda *a, **k: None)
    monkeypatch.setattr(
        mll, "actuate_master_makeup", lambda value, *a, **k: actuations.append(value)
    )

    async def _stop_after_one(_seconds: float) -> None:
        daemon._running = False

    monkeypatch.setattr(mll.asyncio, "sleep", _stop_after_one)

    asyncio.run(mll.master_lufs_loop(daemon))

    assert actuations == [16.5]  # one bounded step toward −14

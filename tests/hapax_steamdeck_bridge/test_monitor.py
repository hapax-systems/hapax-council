"""Monitor FSM tests — v4l2-ctl polling + capture spawn lifecycle."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from agents.hapax_steamdeck_bridge.monitor import (
    SignalState,
    SteamDeckMonitor,
    _has_dv_timings,
)


def _runner_returning(
    *, returncode: int, stdout: str = ""
) -> Callable[[list[str]], subprocess.CompletedProcess]:
    def _run(argv: list[str]) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=argv,
            returncode=returncode,
            stdout=stdout,
            stderr="",
        )

    return _run


class _StubCapture:
    """Minimal stand-in for SteamDeckCapture that records lifecycle."""

    def __init__(self, *, fail_start: bool = False) -> None:
        self.started = False
        self.stopped = False
        self.fail_start = fail_start

    def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("simulated start failure")
        self.started = True

    def stop(self) -> None:
        self.stopped = True


# ── _has_dv_timings ───────────────────────────────────────────────────


def test_has_dv_timings_true_on_active_width_in_stdout() -> None:
    runner = _runner_returning(
        returncode=0,
        stdout="Active width: 1920\nActive height: 1080\n",
    )
    assert _has_dv_timings("/dev/video40", runner=runner) is True


def test_has_dv_timings_false_on_nonzero_returncode() -> None:
    runner = _runner_returning(returncode=1, stdout="ENOLINK")
    assert _has_dv_timings("/dev/video40", runner=runner) is False


def test_has_dv_timings_false_on_empty_stdout() -> None:
    runner = _runner_returning(returncode=0, stdout="")
    assert _has_dv_timings("/dev/video40", runner=runner) is False


def test_has_dv_timings_false_on_runner_exception() -> None:
    def _boom(argv: list[str]) -> subprocess.CompletedProcess:
        raise FileNotFoundError("v4l2-ctl missing")

    assert _has_dv_timings("/dev/video40", runner=_boom) is False


# ── SteamDeckMonitor FSM ──────────────────────────────────────────────


def test_initial_state_is_no_signal() -> None:
    monitor = SteamDeckMonitor(
        v4l2_runner=_runner_returning(returncode=0, stdout=""),
    )
    assert monitor.state is SignalState.NO_SIGNAL
    assert monitor.capture is None


def test_tick_transitions_to_signal_present_when_timings_lock() -> None:
    captures: list[_StubCapture] = []

    def factory(device: str) -> _StubCapture:
        cap = _StubCapture()
        captures.append(cap)
        return cap  # type: ignore[return-value]

    monitor = SteamDeckMonitor(
        capture_factory=factory,
        v4l2_runner=_runner_returning(returncode=0, stdout="Active width: 1920"),
    )
    monitor.tick_once()
    assert monitor.state is SignalState.SIGNAL_PRESENT
    assert len(captures) == 1
    assert captures[0].started is True
    assert monitor.capture is captures[0]


def test_tick_transitions_back_to_no_signal_on_signal_loss() -> None:
    cap = _StubCapture()

    def factory(_device: str) -> _StubCapture:
        return cap  # type: ignore[return-value]

    runner_states = iter(
        [
            _runner_returning(returncode=0, stdout="Active width: 1920"),
            _runner_returning(returncode=1, stdout=""),
        ]
    )
    current_runner = {"value": next(runner_states)}

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        return current_runner["value"](argv)

    monitor = SteamDeckMonitor(
        capture_factory=factory,
        v4l2_runner=runner,
    )
    monitor.tick_once()
    assert monitor.state is SignalState.SIGNAL_PRESENT

    current_runner["value"] = next(runner_states)
    monitor.tick_once()
    assert monitor.state is SignalState.NO_SIGNAL
    assert cap.stopped is True
    assert monitor.capture is None


def test_tick_is_idempotent_when_signal_remains_present() -> None:
    spawn_count = 0

    def factory(_device: str) -> _StubCapture:
        nonlocal spawn_count
        spawn_count += 1
        return _StubCapture()  # type: ignore[return-value]

    monitor = SteamDeckMonitor(
        capture_factory=factory,
        v4l2_runner=_runner_returning(returncode=0, stdout="Active width: 1920"),
    )
    monitor.tick_once()
    monitor.tick_once()
    monitor.tick_once()
    assert spawn_count == 1
    assert monitor.state is SignalState.SIGNAL_PRESENT


def test_capture_factory_failure_keeps_state_no_signal() -> None:
    def factory(_device: str) -> _StubCapture:
        return _StubCapture(fail_start=True)  # type: ignore[return-value]

    monitor = SteamDeckMonitor(
        capture_factory=factory,
        v4l2_runner=_runner_returning(returncode=0, stdout="Active width: 1920"),
    )
    monitor.tick_once()
    assert monitor.state is SignalState.NO_SIGNAL
    assert monitor.capture is None


def test_stop_breaks_run_forever_loop_quickly() -> None:
    """run_forever() must return promptly when stop() is called.

    Drives the loop in a thread + signals stop; uses a fast poll
    interval so the test stays under a second.
    """

    import threading

    monitor = SteamDeckMonitor(
        v4l2_runner=_runner_returning(returncode=1),
        poll_interval_s=0.01,
    )
    thread = threading.Thread(target=monitor.run_forever, daemon=True)
    thread.start()
    monitor.stop()
    thread.join(timeout=1.0)
    assert not thread.is_alive()

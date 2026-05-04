"""Two-stage monitor: Magewell USB → HDMI signal → capture spawn.

The udev rule pulls ``hapax-steamdeck-monitor.service`` into the
graph when the Magewell USB device appears. This monitor then polls
``v4l2-ctl --query-dv-timings`` against the Magewell's V4L2 device
node to detect when the Steam Deck actually starts driving HDMI
into the capture card. Once the timings come back valid, the
monitor spawns a :class:`capture.SteamDeckCapture` instance; if the
HDMI signal drops, it tears the capture down and waits for the
signal to return.

Polling cadence — 2 Hz per the cc-task spec. v4l2-ctl is a
~30 ms-class subprocess on idle, so 500 ms is well within budget;
faster polling buys nothing because the EDID handshake itself takes
~1 s.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from collections.abc import Callable
from enum import StrEnum

from agents.hapax_steamdeck_bridge.capture import SteamDeckCapture

log = logging.getLogger(__name__)

DEFAULT_V4L2_DEVICE = "/dev/video40"
DEFAULT_POLL_INTERVAL_S = 0.5
_V4L2_CTL_TIMEOUT_S = 5.0


class SignalState(StrEnum):
    """FSM state for the two-stage activation."""

    NO_SIGNAL = "no_signal"
    SIGNAL_PRESENT = "signal_present"


def _has_dv_timings(
    device: str,
    *,
    runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
) -> bool:
    """Return True iff ``v4l2-ctl --query-dv-timings`` reports a valid lock.

    Default runner shells out to the system ``v4l2-ctl``; tests
    inject a stub. A valid lock is signalled by a stdout line that
    contains ``Active width:`` (or, equivalently, the absence of the
    ``ENOLINK`` error). We treat anything that doesn't match as
    "no signal" — false negatives are cheap (the next poll catches
    up), false positives would spawn the capture pipeline against an
    empty signal which wastes CPU + spams logs.
    """

    if runner is None:
        if shutil.which("v4l2-ctl") is None:
            log.debug("v4l2-ctl not on PATH; treating as no-signal")
            return False
        runner = _default_runner

    try:
        result = runner(["v4l2-ctl", "-d", device, "--query-dv-timings"])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    except Exception:  # noqa: BLE001
        log.debug("v4l2-ctl invocation raised", exc_info=True)
        return False

    if result.returncode != 0:
        return False
    return "Active width:" in (result.stdout or "")


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=_V4L2_CTL_TIMEOUT_S,
        check=False,
    )


class SteamDeckMonitor:
    """Polls v4l2-ctl, spawns/tears the capture pipeline.

    Owns the FSM state but not the GStreamer pipeline itself —
    delegated to :class:`SteamDeckCapture`. Tests inject both the
    polling runner and a capture factory so the FSM can be exercised
    without any subprocess or GStreamer side-effects.
    """

    def __init__(
        self,
        *,
        v4l2_device: str = DEFAULT_V4L2_DEVICE,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        capture_factory: Callable[[str], SteamDeckCapture] | None = None,
        v4l2_runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
    ) -> None:
        self._device = v4l2_device
        self._poll_interval_s = poll_interval_s
        self._capture_factory = capture_factory or self._default_capture_factory
        self._v4l2_runner = v4l2_runner
        self._state = SignalState.NO_SIGNAL
        self._capture: SteamDeckCapture | None = None
        self._stop_evt = threading.Event()

    @staticmethod
    def _default_capture_factory(device: str) -> SteamDeckCapture:
        return SteamDeckCapture(v4l2_device=device)

    @property
    def state(self) -> SignalState:
        return self._state

    @property
    def capture(self) -> SteamDeckCapture | None:
        return self._capture

    def tick_once(self) -> None:
        """Drive one iteration of the FSM."""

        signal = _has_dv_timings(self._device, runner=self._v4l2_runner)
        if signal and self._state is SignalState.NO_SIGNAL:
            self._enter_signal_present()
        elif not signal and self._state is SignalState.SIGNAL_PRESENT:
            self._enter_no_signal()

    def run_forever(self) -> None:
        """Block + poll until SIGTERM/SIGINT.

        Ctrl-C / systemd stop sets ``self._stop_evt``; the next poll
        wakes up and the FSM tears down whatever is running before
        returning.
        """

        import signal as _signal

        for sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(sig, lambda *_: self._stop_evt.set())
            except ValueError:
                pass

        log.info("steamdeck monitor starting on device=%s", self._device)
        while not self._stop_evt.is_set():
            try:
                self.tick_once()
            except Exception:  # noqa: BLE001
                log.exception("monitor tick raised; continuing")
            self._stop_evt.wait(self._poll_interval_s)

        # Ensure the capture is torn down on stop.
        if self._capture is not None:
            try:
                self._capture.stop()
            except Exception:  # noqa: BLE001
                log.warning("capture stop on shutdown failed", exc_info=True)
            self._capture = None
        self._state = SignalState.NO_SIGNAL

    def stop(self) -> None:
        self._stop_evt.set()

    # ── State transitions ─────────────────────────────────────────────

    def _enter_signal_present(self) -> None:
        log.info("steamdeck HDMI signal locked on %s — spawning capture", self._device)
        try:
            capture = self._capture_factory(self._device)
            capture.start()
        except Exception:  # noqa: BLE001
            log.exception("capture spawn failed; staying in NO_SIGNAL")
            return
        self._capture = capture
        self._state = SignalState.SIGNAL_PRESENT

    def _enter_no_signal(self) -> None:
        log.info("steamdeck HDMI signal lost on %s — tearing down capture", self._device)
        if self._capture is not None:
            try:
                self._capture.stop()
            except Exception:  # noqa: BLE001
                log.warning("capture teardown failed", exc_info=True)
            self._capture = None
        self._state = SignalState.NO_SIGNAL

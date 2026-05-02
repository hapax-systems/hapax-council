"""M8 button-press perception backend.

Polls the m8c-hapax SHM sidecar at `/dev/shm/hapax-sources/m8-buttons.json`
(written on every 0xFB joypad-keypressed-state SLIP packet) and publishes:

  - `m8_button_activity_rate`: float (presses/sec, 1s rolling window)
  - `m8_button_engaged`: bool (rate > 0.5 in last 5s)

This is the M8-side analog of the OXI MIDI clock signal — direct
artefact of the operator touching M8 hardware. Wired into
`operator_activity_engine` as a positive-only signal alongside
`midi_clock_active`.

cc-task: m8-button-activity-perception-signal
"""

from __future__ import annotations

import collections
import json
import logging
import time
from pathlib import Path

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior

log = logging.getLogger(__name__)

_SHM_PATH = Path("/dev/shm/hapax-sources/m8-buttons.json")
_RATE_WINDOW_S = 1.0
_ENGAGED_WINDOW_S = 5.0
_ENGAGED_RATE_THRESHOLD = 0.5  # presses/sec sustained


class M8ButtonsBackend:
    """Reads M8 0xFB button state from SHM sidecar and publishes activity."""

    def __init__(self, shm_path: Path = _SHM_PATH) -> None:
        self._shm_path = shm_path
        self._last_mask: int | None = None
        self._last_ts_str: str | None = None
        # (monotonic_ts, mask) for press events; trimmed to >5s of history.
        self._press_history: collections.deque[tuple[float, int]] = collections.deque()

    @property
    def name(self) -> str:
        return "m8_buttons"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"m8_button_activity_rate", "m8_button_engaged"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST  # SHM read is sub-millisecond

    def available(self) -> bool:
        # Reachable even if M8 unplugged — backend tolerates missing file.
        return True

    def _read_sidecar(self) -> dict | None:
        if not self._shm_path.exists():
            return None
        try:
            return json.loads(self._shm_path.read_text())
        except (OSError, ValueError):
            return None

    def _record_press_if_new(self, payload: dict, now: float) -> None:
        ts_str = payload.get("ts")
        mask = int(payload.get("mask", 0))
        if ts_str == self._last_ts_str:
            return  # no new packet since last poll
        self._last_ts_str = ts_str
        # Treat any 0xFB packet with non-zero mask as a press event.
        # Mask transitions from non-zero → 0 are key-up — count once
        # at the down edge by checking against the last seen mask.
        if mask != 0 and mask != self._last_mask:
            self._press_history.append((now, mask))
        self._last_mask = mask

    def _trim_history(self, now: float) -> None:
        cutoff = now - _ENGAGED_WINDOW_S
        while self._press_history and self._press_history[0][0] < cutoff:
            self._press_history.popleft()

    def _rate_in_window(self, now: float, window_s: float) -> float:
        cutoff = now - window_s
        count = sum(1 for ts, _ in self._press_history if ts >= cutoff)
        return count / window_s

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()
        payload = self._read_sidecar()
        if payload is not None:
            self._record_press_if_new(payload, now)
        self._trim_history(now)

        rate = self._rate_in_window(now, _RATE_WINDOW_S)
        sustained_rate = self._rate_in_window(now, _ENGAGED_WINDOW_S)
        engaged = sustained_rate > _ENGAGED_RATE_THRESHOLD

        behaviors["m8_button_activity_rate"] = Behavior(rate)
        behaviors["m8_button_engaged"] = Behavior(engaged)

    def start(self) -> None:
        log.info("M8 buttons backend started (sidecar=%s)", self._shm_path)

    def stop(self) -> None:
        log.info("M8 buttons backend stopped")

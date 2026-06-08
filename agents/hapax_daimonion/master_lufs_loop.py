"""Closed master −14 LUFS-I control loop (segment-audio-remainder AC#2).

A SLOW, bounded controller nudges the broadcast master makeup toward
``EGRESS_TARGET_LUFS_I`` (−14), measured as integrated LUFS-I on the public
source ``hapax-broadcast-normalized``. It replaces *reliance* on the open-loop
``MASTER_INPUT_MAKEUP_DB`` (+16 dB) makeup while keeping that static makeup as
the never-remove fallback: the loop only trims within a bounded ±dB band around
it, and it is **dark by default** (``master_lufs_controller_enabled=False``) —
it measures + publishes what it WOULD do but never actuates until proven at the
alpha-gated go-live.

Time-constant separation from the duck (``DUCK_ATTACK_MS=10`` /
``DUCK_RELEASE_MS=400``) is the load-bearing invariant. The loop integrates over
tens of seconds, nudges in ≤ ``MASTER_LUFS_MAX_STEP_DB`` steps every several
seconds (≥10× the duck release), and **freezes entirely while the bus is
ducked** — so the slow makeup loop can never chase the fast duck up.

Actuation, when enabled, nudges the EXISTING master node's makeup control port
(``master_limiter:Input gain (dB)`` on ``hapax-broadcast-master``) within the
band — no new PipeWire conf node is added, so the static +16 dB stays the
untouched fallback. The live tap / actuation mechanism is exercised by alpha at
go-live; this module's control law is fully unit-tested over injected I/O.

Lives as a daimonion-supervised background task (registered in ``run_inner``),
because the new daemon has no in-scope systemd home and ``hapax-daimonion`` is
already PipeWire-attached and long-lived.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shared.audio_loudness import (
    EGRESS_TARGET_LUFS_I,
    MASTER_INPUT_MAKEUP_DB,
    MASTER_LUFS_INTEGRATION_WINDOW_S,
    MASTER_LUFS_MAKEUP_BAND_DB,
    MASTER_LUFS_MAX_STEP_DB,
    MASTER_LUFS_UPDATE_INTERVAL_S,
)

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger(__name__)

__all__ = [
    "MasterLufsController",
    "compute_makeup_step",
    "master_lufs_loop",
    "parse_ebur128_integrated_lufs",
    "should_freeze",
]

BROADCAST_SOURCE_NODE = "hapax-broadcast-normalized"
MASTER_MAKEUP_NODE = "hapax-broadcast-master"
MASTER_MAKEUP_CONTROL = "master_limiter:Input gain (dB)"
DUCKER_STATE_PATH = Path("/dev/shm/hapax-audio-ducker/state.json")
STATUS_PATH = Path("/dev/shm/hapax-daimonion/master-lufs.json")

_EBUR128_I_RE = re.compile(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS")


# ── pure control law ─────────────────────────────────────────────────────────


def compute_makeup_step(
    current_makeup_db: float,
    measured_lufs_i: float,
    *,
    target: float,
    max_step_db: float,
    makeup_band: tuple[float, float],
) -> float:
    """Return the next makeup gain — one bounded step toward ``target``.

    ``error = target - measured``: when the bus measures quieter than target the
    error is positive and makeup rises; louder → makeup falls. The move is
    clamped to ``±max_step_db`` per step and the result is clamped into
    ``makeup_band`` (and thus inside the LADSPA-accepted range).
    """
    error = target - measured_lufs_i
    step = max(-max_step_db, min(max_step_db, error))
    low, high = makeup_band
    return max(low, min(high, current_makeup_db + step))


def should_freeze(ducker_state: dict[str, Any] | None) -> bool:
    """True when the makeup loop must NOT integrate or nudge.

    Freezes while the bus is being ducked (so the slow loop never chases the
    fast duck up), and conservatively when the duck state is missing or
    malformed — the loop defaults to not actuating unless it can confirm the
    bus is clean.
    """
    if not isinstance(ducker_state, dict) or not ducker_state:
        return True
    if ducker_state.get("fail_open"):
        return True
    cause = ducker_state.get("trigger_cause", "none")
    if cause and cause != "none":
        return True
    try:
        if float(ducker_state.get("commanded_music_duck_gain", 1.0)) < 0.999:
            return True
    except (TypeError, ValueError):
        return True
    return False


def parse_ebur128_integrated_lufs(ffmpeg_stderr: str) -> float | None:
    """Extract the integrated-loudness ``I:`` value from ffmpeg ebur128 output.

    Returns the LAST ``I:`` reading (the end-of-stream Summary's integrated
    value), or ``None`` when no integrated reading is present.
    """
    matches = _EBUR128_I_RE.findall(ffmpeg_stderr)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except (TypeError, ValueError):
        return None


# ── controller ───────────────────────────────────────────────────────────────


class MasterLufsController:
    """Slow, bounded, duck-aware master makeup controller (dark by default)."""

    def __init__(
        self,
        *,
        lufs_reader: Callable[[], float | None],
        ducker_state_reader: Callable[[], dict[str, Any] | None],
        actuator: Callable[[float], None] | None = None,
        publisher: Callable[[dict[str, Any]], None] | None = None,
        enabled: bool = False,
        initial_makeup_db: float = MASTER_INPUT_MAKEUP_DB,
        target_lufs_i: float = EGRESS_TARGET_LUFS_I,
        max_step_db: float = MASTER_LUFS_MAX_STEP_DB,
        makeup_band_db: float = MASTER_LUFS_MAKEUP_BAND_DB,
    ) -> None:
        self._lufs_reader = lufs_reader
        self._ducker_state_reader = ducker_state_reader
        self._actuator = actuator
        self._publisher = publisher
        self._enabled = bool(enabled)
        self._makeup = float(initial_makeup_db)
        self._target = float(target_lufs_i)
        self._max_step = float(max_step_db)
        self._band = (initial_makeup_db - makeup_band_db, initial_makeup_db + makeup_band_db)

    @property
    def makeup_db(self) -> float:
        """The believed-live makeup gain — only moves when actuation happens."""
        return self._makeup

    @property
    def enabled(self) -> bool:
        return self._enabled

    def tick(self) -> dict[str, Any]:
        """One control step. Returns (and publishes) the status dict."""
        duck = _safe_call(self._ducker_state_reader)
        if should_freeze(duck):
            return self._publish(
                {
                    "enabled": self._enabled,
                    "frozen": True,
                    "reason": "ducked",
                    "measured_lufs_i": None,
                    "makeup_db": self._makeup,
                    "proposed_makeup_db": self._makeup,
                    "actuated": False,
                }
            )

        measured = _safe_call(self._lufs_reader)
        if measured is None:
            return self._publish(
                {
                    "enabled": self._enabled,
                    "frozen": False,
                    "reason": "no_measurement",
                    "measured_lufs_i": None,
                    "makeup_db": self._makeup,
                    "proposed_makeup_db": self._makeup,
                    "actuated": False,
                }
            )

        proposed = compute_makeup_step(
            self._makeup,
            float(measured),
            target=self._target,
            max_step_db=self._max_step,
            makeup_band=self._band,
        )
        actuated = False
        if self._enabled and proposed != self._makeup:
            if self._actuator is not None:
                self._actuator(proposed)
            self._makeup = proposed
            actuated = True

        return self._publish(
            {
                "enabled": self._enabled,
                "frozen": False,
                "reason": "ok",
                "measured_lufs_i": float(measured),
                "makeup_db": self._makeup,
                "proposed_makeup_db": proposed,
                "actuated": actuated,
            }
        )

    def _publish(self, status: dict[str, Any]) -> dict[str, Any]:
        if self._publisher is not None:
            try:
                self._publisher(status)
            except Exception:  # noqa: BLE001 — observability must never break control
                log.debug("master-lufs status publish failed", exc_info=True)
        return status


def _safe_call(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception:  # noqa: BLE001 — a flaky reader holds the loop, never crashes it
        log.debug("master-lufs reader failed", exc_info=True)
        return None


# ── live I/O (dark by default; exercised at the alpha-gated go-live) ─────────


def read_ducker_state(path: Path = DUCKER_STATE_PATH) -> dict[str, Any] | None:
    """Read the ducker's published state, or ``None`` if unavailable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_broadcast_lufs_i(
    node: str = BROADCAST_SOURCE_NODE,
    window_s: float = MASTER_LUFS_INTEGRATION_WINDOW_S,
) -> float | None:
    """Capture ``window_s`` of the public broadcast source → integrated LUFS-I.

    Blocks for ~``window_s`` (run from a worker thread). Returns ``None`` on any
    failure so the controller holds. The go-live refinement is a persistent
    rolling integrator so the tap doesn't re-capture each tick.
    """
    capture = None
    try:
        capture = subprocess.Popen(
            [
                "pw-cat",
                "--record",
                "--target",
                node,
                "--rate",
                "48000",
                "--channels",
                "2",
                "--format",
                "s16",
                "--raw",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        ffmpeg = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-f",
                "s16le",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-t",
                str(window_s),
                "-i",
                "pipe:0",
                "-af",
                "ebur128=framelog=verbose",
                "-f",
                "null",
                "-",
            ],
            stdin=capture.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=window_s + 10.0,
            check=False,
        )
        return parse_ebur128_integrated_lufs(ffmpeg.stderr.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 — measurement failure → hold (None)
        log.debug("master LUFS-I read failed", exc_info=True)
        return None
    finally:
        if capture is not None:
            try:
                capture.terminate()
            except Exception:  # noqa: BLE001
                pass


def actuate_master_makeup(
    makeup_db: float,
    *,
    node: str = MASTER_MAKEUP_NODE,
    control: str = MASTER_MAKEUP_CONTROL,
) -> None:
    """Nudge the EXISTING master makeup control port to ``makeup_db``.

    Adds no conf node — the static +16 dB stays as the fallback. Only invoked
    when the controller is enabled. Best-effort; the precise live set-param
    syntax for the LADSPA control port is confirmed at the alpha-gated go-live.
    """
    try:
        subprocess.run(
            ["pw-cli", "set-param", node, "Props", f'{{ params = [ "{control}" {makeup_db} ] }}'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5.0,
            check=False,
        )
    except Exception:  # noqa: BLE001 — actuation failure must not crash the loop
        log.warning("master makeup actuation failed (node=%s)", node, exc_info=True)


def publish_status(status: dict[str, Any], path: Path = STATUS_PATH) -> None:
    """Atomically publish the controller status for observability."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(status), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.debug("master-lufs status write failed", exc_info=True)


def _resolve_enabled(daemon: VoiceDaemon) -> bool:
    cfg = getattr(daemon, "cfg", None)
    return bool(getattr(cfg, "master_lufs_controller_enabled", False))


async def master_lufs_loop(daemon: VoiceDaemon) -> None:
    """Daimonion-supervised slow LUFS-I makeup loop. Dark unless config enables it.

    Runs each control tick in a worker thread (the live LUFS-I read blocks for
    the integration window) so the daemon event loop stays responsive.
    """
    enabled = _resolve_enabled(daemon)
    controller = MasterLufsController(
        lufs_reader=read_broadcast_lufs_i,
        ducker_state_reader=read_ducker_state,
        actuator=actuate_master_makeup,
        publisher=publish_status,
        enabled=enabled,
    )
    log.info(
        "master_lufs_loop starting (enabled=%s, interval %.1fs, target %.1f LUFS-I)",
        enabled,
        MASTER_LUFS_UPDATE_INTERVAL_S,
        EGRESS_TARGET_LUFS_I,
    )
    while daemon._running:
        try:
            await asyncio.to_thread(controller.tick)
        except Exception:  # noqa: BLE001 — a tick failure must not take the daemon down
            log.debug("master_lufs tick failed", exc_info=True)
        await asyncio.sleep(MASTER_LUFS_UPDATE_INTERVAL_S)

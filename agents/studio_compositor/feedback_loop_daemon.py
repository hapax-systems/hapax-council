"""Daemon wrapper for the L-12 feedback-loop detector.

Owns the ``parec`` subprocess that streams the existing 14-channel
USB capture surface, drives :class:`feedback_loop_detector.FeedbackLoopDetector`,
and dispatches the four production side-effects on each trigger:

1. **Smooth auto-mute** — modulates the broadcast master via wpctl
   envelope (~250 ms ease-in / 3 s hold / 1 s ease-out, ≈ 4.25 s total).
   Never a binary ``set-mute`` per ``feedback_no_blinking_homage_wards``.
2. **Awareness state push** — atomic write to
   ``/dev/shm/hapax-awareness/state.json`` adding/refreshing a
   ``feedback_risk`` block. Graceful-skip if shm path missing.
3. **Refusal-log entry** — appends to ``/dev/shm/hapax-refusals/log.jsonl``
   under axiom ``broadcast_no_loopback``.
4. **ntfy + Prometheus** — HIGH-priority operator notification +
   ``hapax_feedback_loop_detections_total`` /
   ``hapax_feedback_loop_auto_mute_seconds_total`` counters.

Lifecycle: ``Type=notify`` systemd service. ``main()`` calls
``sd_notify(READY=1)`` once the detector is hot, kicks the watchdog
each tick, and tears down cleanly on SIGTERM.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .feedback_loop_detector import (
    DEFAULT_CHANNELS,
    DEFAULT_SAMPLE_RATE_HZ,
    FeedbackLoopDetector,
    TriggerEvent,
    emit_trigger_side_effects,
)

LOG = logging.getLogger("feedback-loop-daemon")

# ── Constants ──────────────────────────────────────────────────────────────

DEFAULT_PAREC_SOURCE: str | None = None
"""ALSA source name for the L-12 USB capture (14-channel s32 multichannel).

``None`` means "auto-discover via :func:`discover_l12_source` at start
time" — production use should always leave this None because the
hardware serial is encoded into the source name and varies per device.
Tests can pin to a specific name via the constructor.
"""

DEFAULT_L12_SOURCE_SUBSTRING = "ZOOM_Corporation_L-12"
"""Substring matched against ``pactl list sources short`` output.

The full source name carries the device serial, e.g.
``alsa_input.usb-ZOOM_Corporation_L-12_8253...-00.multichannel-input``.
Matching the vendor-and-model substring is robust across device serials
while still pinning to the L-12 (ignoring other USB audio interfaces
such as the S-4)."""

# 250 ms windows × 14 channels × 4 bytes (s32) ≈ 168 kB per read at 48 kHz.
_PAREC_FORMAT = "s32le"
_PAREC_SAMPLE_BYTES = 4

# Auto-mute envelope shape (research §Auto-mute action).
DEFAULT_DUCK_IN_MS = 250
DEFAULT_HOLD_MS = 3000
DEFAULT_DUCK_OUT_MS = 1000
DEFAULT_RAMP_STEPS = 16

# Broadcast master node. ``hapax-livestream-tap`` is the canonical sink
# fed by the studio_compositor's RTMP/HLS/V4L2 fanout per the L-12
# architecture diagram in the alpha post-compaction handoff.
DEFAULT_BROADCAST_SINK = "hapax-livestream-tap"

# /dev/shm targets per the awareness-state-stream-canonical contract.
DEFAULT_AWARENESS_STATE_PATH = Path("/dev/shm/hapax-awareness/state.json")
DEFAULT_REFUSAL_LOG_PATH = Path("/dev/shm/hapax-refusals/log.jsonl")

# Killswitch: mirrors the cc-hygiene pattern.
KILLSWITCH_ENV = "HAPAX_FEEDBACK_LOOP_DETECTOR_OFF"

BROADCAST_PATH_CHANNELS: tuple[int, ...] = (2, 3, 4, 5)
"""Per L-12 narrowing PR #1471, AUX1/3/4/5_L/5_R reach broadcast — but
the contact mic on AUX1 (idx 0) is structurally non-feedback-capable
and is excluded.

Channel indices in the raw 14-channel parec stream (0-based):
  2 = strip 3 (AUX3, sampler) — could feedback through sampler chain
  3 = strip 4 (AUX4, rode vocal) — true acoustic-feedback risk
  4 = strip 5 (AUX5_L, Evil Pet wet L) — pedal self-oscillation risk
  5 = strip 6 (AUX5_R, Evil Pet wet R) — pedal self-oscillation risk

Excluded:

* Index 0 (AUX1, contact mic): a piezo vibration sensor. Cannot
  participate in an acoustic OR digital feedback loop — it captures
  desk-surface mechanical contact (typing, mug placement, foot taps,
  HVAC vibration), all of which routinely produce sustained narrow-
  band content in the 200-1000 Hz range that trips the 6 dB / 12 dB
  thresholds. Field deploy of #1532 still saw 10 false triggers in
  5 min on this channel (typing percussion, mug rings).
* Index 1 (strip 2, spare) + 6-11 (strips 7-12) + 12-13 (MASTER) are
  not in the broadcast path post-#1471 narrowing.

Trade-off: dropping AUX1 from the watch set means a hypothetical
feedback path through the contact mic would not be detected. Counter-
argument: contact-mic feedback would require the broadcast playback to
mechanically vibrate the desk loudly enough to dominate the contact
mic's pickup, which would already be audible to the operator and
manually correctable."""


# ── parec subprocess wrapper ──────────────────────────────────────────────


def discover_l12_source(substring: str = DEFAULT_L12_SOURCE_SUBSTRING) -> str | None:
    """Find the L-12 multichannel-input source by vendor/model substring.

    Returns the full ALSA source name on success, ``None`` if no match
    (the L-12 isn't currently exposed by PipeWire/PulseAudio). Robust
    against the device-serial portion of the name varying per unit.
    """
    try:
        result = subprocess.run(
            ["pactl", "list", "sources", "short"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        LOG.debug("pactl list sources short failed", exc_info=True)
        return None
    for line in result.stdout.splitlines():
        cols = line.split("\t")
        if len(cols) < 2:
            continue
        name = cols[1]
        if substring in name and "multichannel-input" in name:
            return name
    return None


class ParecCapture:
    """Thin wrapper that streams 14-channel s32 frames from PulseAudio.

    ``read_window`` returns one numpy array shaped ``(window_samples,
    channels)`` normalised to float32 [-1, 1]. Subprocess restart is
    the daemon's responsibility — the wrapper raises on EOF.

    ``source`` defaults to ``None``, which triggers
    :func:`discover_l12_source` at :meth:`start` time. Tests pin to a
    specific name via the constructor.
    """

    def __init__(
        self,
        *,
        source: str | None = DEFAULT_PAREC_SOURCE,
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
        channels: int = DEFAULT_CHANNELS,
    ) -> None:
        self.source = source
        self.sample_rate_hz = sample_rate_hz
        self.channels = channels
        self._proc: subprocess.Popen | None = None

    def _resolve_source(self) -> str:
        if self.source is not None:
            return self.source
        discovered = discover_l12_source()
        if discovered is None:
            raise OSError(
                "L-12 multichannel-input source not found via pactl; no parec device to attach to"
            )
        LOG.info("L-12 source auto-discovered: %s", discovered)
        return discovered

    def start(self) -> None:
        """Spawn the parec child."""
        device = self._resolve_source()
        cmd = [
            "parec",
            f"--device={device}",
            f"--rate={self.sample_rate_hz}",
            f"--channels={self.channels}",
            f"--format={_PAREC_FORMAT}",
            "--raw",
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        LOG.info("parec started: %s", " ".join(cmd))

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        finally:
            self._proc = None

    def read_window(self, window_samples: int) -> np.ndarray:
        """Read one window of audio. Returns float32 normalised in [-1, 1].

        ``stdout.read(n)`` on a pipe with bufsize=0 returns *up to* n
        bytes, not exactly n — partial reads are normal when the pipe
        buffer is smaller than the requested window. Loop until we
        either fill the buffer or hit a true EOF (``read`` returns b'').
        """
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("parec not started")
        n_bytes = window_samples * self.channels * _PAREC_SAMPLE_BYTES
        chunks: list[bytes] = []
        remaining = n_bytes
        while remaining > 0:
            chunk = self._proc.stdout.read(remaining)
            if not chunk:
                got = n_bytes - remaining
                raise EOFError(f"parec EOF after {got}/{n_bytes} bytes")
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        # s32le → int32 → float32 in [-1, 1].
        arr = np.frombuffer(raw, dtype="<i4").reshape(window_samples, self.channels)
        return (arr.astype(np.float32) / 2_147_483_648.0).astype(np.float32, copy=False)


# ── side-effect implementations ───────────────────────────────────────────


def make_wpctl_auto_mute(
    *,
    sink_name: str = DEFAULT_BROADCAST_SINK,
    duck_in_ms: int = DEFAULT_DUCK_IN_MS,
    hold_ms: int = DEFAULT_HOLD_MS,
    duck_out_ms: int = DEFAULT_DUCK_OUT_MS,
    ramp_steps: int = DEFAULT_RAMP_STEPS,
) -> Callable[[TriggerEvent], None]:
    """Return a side-effect callable that ducks ``sink_name`` via wpctl.

    Sine-eased envelope (cos² curve). Spawns a background thread per
    trigger so the analysis loop does not block on the ~4 s envelope.
    """

    def _ramp(start_vol: float, end_vol: float, ms: int, steps: int) -> None:
        if steps <= 0 or ms <= 0:
            return
        step_dt = (ms / 1000.0) / steps
        for i in range(1, steps + 1):
            progress = i / steps
            ease = 0.5 - 0.5 * np.cos(np.pi * progress)
            vol = float(start_vol + (end_vol - start_vol) * ease)
            try:
                subprocess.run(
                    ["wpctl", "set-volume", sink_name, str(max(0.0, min(1.0, vol)))],
                    timeout=2.0,
                    capture_output=True,
                    check=False,
                )
            except (subprocess.SubprocessError, OSError):
                LOG.debug("wpctl set-volume failed during envelope ramp", exc_info=True)
            time.sleep(step_dt)

    def _envelope(_event: TriggerEvent) -> None:
        baseline_vol = 1.0
        try:
            result = subprocess.run(
                ["wpctl", "get-volume", sink_name],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            for tok in result.stdout.split():
                try:
                    baseline_vol = float(tok)
                    break
                except ValueError:
                    continue
        except (subprocess.SubprocessError, OSError):
            LOG.debug("wpctl get-volume failed; assuming baseline 1.0")

        _ramp(baseline_vol, 0.0, duck_in_ms, ramp_steps)
        time.sleep(hold_ms / 1000.0)
        _ramp(0.0, baseline_vol, duck_out_ms, ramp_steps)

    def _entry(event: TriggerEvent) -> None:
        thread = threading.Thread(
            target=_envelope, args=(event,), daemon=True, name="feedback-loop-mute"
        )
        thread.start()

    return _entry


def make_awareness_writer(
    state_path: Path = DEFAULT_AWARENESS_STATE_PATH,
) -> Callable[[TriggerEvent], None]:
    """Return a callable that updates the awareness state with feedback_risk."""

    def _update(event: TriggerEvent) -> None:
        if not state_path.parent.exists():
            LOG.debug("awareness state dir missing; skipping update")
            return
        try:
            current: dict[str, Any] = {}
            if state_path.exists():
                try:
                    current = json.loads(state_path.read_text(encoding="utf-8"))
                    if not isinstance(current, dict):
                        current = {}
                except (OSError, json.JSONDecodeError):
                    current = {}
            current["feedback_risk"] = {
                "active": True,
                "channel_aux": event.channel_index + 1,
                "frequency_hz": round(event.dominant_frequency_hz, 2),
                "spectral_ratio_db": round(event.spectral_ratio_db, 2),
                "triggered_at": event.timestamp.isoformat(),
                "auto_mute_envelope_seconds": (
                    DEFAULT_DUCK_IN_MS + DEFAULT_HOLD_MS + DEFAULT_DUCK_OUT_MS
                )
                / 1000.0,
            }
            tmp = state_path.with_suffix(state_path.suffix + ".feedback-loop.tmp")
            tmp.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(state_path)
        except OSError:
            LOG.debug("awareness state write failed", exc_info=True)

    return _update


def make_refusal_logger(
    log_path: Path = DEFAULT_REFUSAL_LOG_PATH,
) -> Callable[[TriggerEvent], None]:
    """Return a callable that appends a refusal-log entry on trigger."""

    def _log(event: TriggerEvent) -> None:
        if not log_path.parent.exists():
            LOG.debug("refusal log dir missing; skipping append")
            return
        entry = {
            "timestamp": event.timestamp.isoformat(),
            "axiom": "broadcast_no_loopback",
            "surface": "studio-compositor:feedback-loop-detector",
            "reason": (
                f"L-12 channel {event.channel_index + 1} oscillation "
                f"{event.dominant_frequency_hz:.0f} Hz sustained ≥ 500 ms; "
                f"auto-muted broadcast master "
                f"{(DEFAULT_DUCK_IN_MS + DEFAULT_HOLD_MS + DEFAULT_DUCK_OUT_MS) / 1000.0}s"
            ),
            "public": False,
        }
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            LOG.debug("refusal-log append failed", exc_info=True)

    return _log


def make_prometheus_counter() -> Callable[[TriggerEvent], None]:
    """Return a callable that increments the trigger counters.

    Returns a no-op if prometheus_client isn't installed.
    """
    try:
        from prometheus_client import Counter  # noqa: PLC0415

        det_counter = Counter(
            "hapax_feedback_loop_detections_total",
            "Per-channel feedback-loop detector triggers",
            ["channel_aux"],
        )
        mute_seconds = Counter(
            "hapax_feedback_loop_auto_mute_seconds_total",
            "Cumulative wall-clock seconds of broadcast master ducking",
        )
    except Exception:
        return lambda _ev: None

    envelope_s = (DEFAULT_DUCK_IN_MS + DEFAULT_HOLD_MS + DEFAULT_DUCK_OUT_MS) / 1000.0

    def _inc(event: TriggerEvent) -> None:
        det_counter.labels(channel_aux=str(event.channel_index + 1)).inc()
        mute_seconds.inc(envelope_s)

    return _inc


def default_notifier() -> Callable[..., Any] | None:
    """Resolve ``shared.notify.send_notification`` lazily."""
    try:
        from shared.notify import send_notification  # noqa: PLC0415

        return send_notification
    except Exception:
        return None


# ── daemon ────────────────────────────────────────────────────────────────


class FeedbackLoopDaemon:
    """Tie the parec wrapper, detector, and side-effects together.

    Designed for ``Type=notify`` systemd: ``run`` calls sd_notify on
    READY + each tick (so the watchdog kicks). Stops cleanly on SIGTERM.
    """

    def __init__(
        self,
        *,
        capture: ParecCapture | None = None,
        detector: FeedbackLoopDetector | None = None,
        auto_mute: Callable[[TriggerEvent], None] | None = None,
        awareness_writer: Callable[[TriggerEvent], None] | None = None,
        refusal_logger: Callable[[TriggerEvent], None] | None = None,
        notifier: Callable[..., Any] | None = None,
        counter_inc: Callable[[TriggerEvent], None] | None = None,
        sd_notify: Callable[[str], None] | None = None,
    ) -> None:
        self._capture = capture or ParecCapture()
        # Default detector scopes to the broadcast-path channels per
        # PR #1471's L-12 narrowing — feedback off-broadcast is a false-
        # positive surface (contact mic + spare strips dominated initial
        # field-test trigger volume).
        self._detector = detector or FeedbackLoopDetector(watch_channels=BROADCAST_PATH_CHANNELS)
        self._auto_mute = auto_mute or make_wpctl_auto_mute()
        self._awareness_writer = awareness_writer or make_awareness_writer()
        self._refusal_logger = refusal_logger or make_refusal_logger()
        self._notifier = notifier or default_notifier()
        self._counter_inc = counter_inc or make_prometheus_counter()
        self._sd_notify = sd_notify or _resolve_sd_notify()
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> int:
        """Main loop. Returns systemd exit code (0 clean, 1 error)."""
        if os.environ.get(KILLSWITCH_ENV) == "1":
            LOG.info("killswitch %s=1 → no-op exit", KILLSWITCH_ENV)
            self._sd_notify("READY=1")
            self._sd_notify("STATUS=killswitch active; no-op")
            self._stop_event.wait()
            return 0

        try:
            self._capture.start()
        except OSError:
            LOG.exception("parec start failed")
            return 1

        window_samples = self._detector.window_size_samples()
        self._sd_notify("READY=1")
        self._sd_notify(f"STATUS=watching {self._detector.channels} channels")

        while not self._stop_event.is_set():
            # Kick the watchdog at the top of every loop iteration —
            # including EOF-restart cycles and exception backoff. The
            # tail-side WATCHDOG=1 alone fails systemd's WatchdogSec
            # timer if parec hits sustained EOF (loop never reaches
            # the tail). 4 reads/sec × WatchdogSec=120s gives a 480×
            # safety margin in steady-state.
            self._sd_notify("WATCHDOG=1")
            try:
                buffer = self._capture.read_window(window_samples)
            except EOFError:
                LOG.warning("parec EOF; restarting in 1 s")
                self._capture.stop()
                if self._stop_event.wait(1.0):
                    break
                try:
                    self._capture.start()
                except OSError:
                    LOG.exception("parec restart failed; exiting")
                    return 1
                continue
            except Exception:
                LOG.exception("parec read failed; backing off")
                if self._stop_event.wait(1.0):
                    break
                continue

            now = datetime.now(UTC)
            events = self._detector.process_buffer(buffer, now=now)
            for event in events:
                LOG.warning(
                    "FEEDBACK LOOP: ch=%d freq=%.1f Hz spectral=%.1f dB; auto-muting",
                    event.channel_index + 1,
                    event.dominant_frequency_hz,
                    event.spectral_ratio_db,
                )
                emit_trigger_side_effects(
                    event,
                    auto_mute=self._auto_mute,
                    awareness_writer=self._awareness_writer,
                    refusal_logger=self._refusal_logger,
                    notifier=self._notifier,
                    counter_inc=self._counter_inc,
                )
            self._sd_notify("WATCHDOG=1")

        self._capture.stop()
        return 0


def _resolve_sd_notify() -> Callable[[str], None]:
    """Resolve ``sdnotify.SystemdNotifier``; fall back to a no-op."""
    try:
        from sdnotify import SystemdNotifier  # noqa: PLC0415

        notifier = SystemdNotifier()
        return lambda msg: notifier.notify(msg)
    except Exception:
        return lambda _msg: None


# ── entrypoint ────────────────────────────────────────────────────────────


def _install_signal_handlers(daemon: FeedbackLoopDaemon) -> None:
    def _term(_signum: int, _frame: Any) -> None:
        LOG.info("SIGTERM received; shutting down")
        daemon.stop()

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)


def main(argv: list[str] | None = None) -> int:
    """Module entrypoint. ``python -m agents.studio_compositor.feedback_loop_daemon``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    daemon = FeedbackLoopDaemon()
    _install_signal_handlers(daemon)
    return daemon.run()


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "BROADCAST_PATH_CHANNELS",
    "DEFAULT_AWARENESS_STATE_PATH",
    "DEFAULT_BROADCAST_SINK",
    "DEFAULT_L12_SOURCE_SUBSTRING",
    "DEFAULT_PAREC_SOURCE",
    "DEFAULT_REFUSAL_LOG_PATH",
    "FeedbackLoopDaemon",
    "ParecCapture",
    "default_notifier",
    "discover_l12_source",
    "make_awareness_writer",
    "make_prometheus_counter",
    "make_refusal_logger",
    "make_wpctl_auto_mute",
    "main",
]

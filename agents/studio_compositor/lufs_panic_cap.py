"""LUFS-S panic-cap on the broadcast master.

Defense-in-depth ceiling on broadcast loudness, independent of the
per-channel feedback-loop detector and PipeWire-config narrowing. If the
broadcast master output sustains -6 LUFS-S for >300ms, this module ducks
the master output -40 dB via a smooth sine-eased envelope, holds 3
seconds, and releases over 1 second. Total event ~4.2s.

Why -6 LUFS-S: well above normal stream loudness target (-16 to -23
LUFS-I). Designed to fire only on genuine pathology. Feedback whistles
push past -3 LUFS-S; normal program material sits 10+ LU below.

Why smooth envelope: ``feedback_no_blinking_homage_wards`` — hard mute /
square-wave gate is constitutional violation. Sine ease 200 ms attack,
3s hold @ -40 dB, 1s release.

Constitutional binders:
- ``feedback_l12_equals_livestream_invariant`` (inverse): broadcast
  must be safe regardless of upstream pathology
- ``feedback_no_blinking_homage_wards``: smooth envelope only
- ``feedback_features_on_by_default``: cap is ON in production

Source: researcher report a09d834c (L-12 broadcast feedback-loop
diagnosis 2026-04-25).
"""

from __future__ import annotations

import json
import logging
import math
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


LUFS_WINDOW_S: float = 3.0
"""EBU R128 short-term loudness window."""

MEASURE_INTERVAL_S: float = 0.100
"""Recompute LUFS-S every 100 ms."""

DEFAULT_THRESHOLD_LUFS_S: float = -6.0
"""Cap threshold. Above broadcast targets, below feedback-whistle saturation."""

DEFAULT_BREACH_WINDOW_MS: int = 300
"""Sustain window: 3 consecutive 100 ms measurements."""

DEFAULT_COOLDOWN_S: float = 10.0
"""Refuse re-trigger for 10 s after duck-restore complete."""

DEFAULT_ATTACK_MS: int = 200
DEFAULT_HOLD_S: float = 3.0
DEFAULT_RELEASE_MS: int = 1000
DEFAULT_DUCK_DB: float = -40.0

DEFAULT_SINK_NAME: str = "hapax-broadcast-master"
DEFAULT_MONITOR_SOURCE: str = "hapax-broadcast-master.monitor"

AWARENESS_STATE_PATH: Path = Path("/dev/shm/hapax-awareness/state.json")
REFUSAL_LOG_PATH: Path = Path("/dev/shm/hapax-refusals/log.jsonl")

SAMPLE_RATE_HZ: int = 44100
CHANNEL_COUNT: int = 2
SAMPLE_FORMAT: str = "s32le"
SAMPLE_BYTES_PER_FRAME: int = 4 * CHANNEL_COUNT


def _db_to_linear(db: float) -> float:
    return 10.0 ** (db / 20.0)


def _sine_ease(t: float) -> float:
    """Sine-eased in/out; t in [0, 1]; returns [0, 1]."""
    return (1.0 - math.cos(math.pi * t)) / 2.0


class LufsPanicCap:
    """Watches broadcast master loudness, ducks on sustained breach.

    Single-instance. Runs a parec subprocess for monitor capture and a
    measurement thread for LUFS-S evaluation. Duck-envelope is applied
    via wpctl on the master sink.

    State machine: idle → ducking → held → releasing → cooldown → idle.
    """

    STATES = ("idle", "ducking", "held", "releasing", "cooldown")

    def __init__(
        self,
        *,
        threshold_lufs_s: float = DEFAULT_THRESHOLD_LUFS_S,
        breach_window_ms: int = DEFAULT_BREACH_WINDOW_MS,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        attack_ms: int = DEFAULT_ATTACK_MS,
        hold_s: float = DEFAULT_HOLD_S,
        release_ms: int = DEFAULT_RELEASE_MS,
        duck_db: float = DEFAULT_DUCK_DB,
        sink_name: str = DEFAULT_SINK_NAME,
        monitor_source: str = DEFAULT_MONITOR_SOURCE,
        notify_callback: Callable[[str, str], None] | None = None,
        metrics_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        self._threshold = threshold_lufs_s
        self._breach_window_ms = breach_window_ms
        self._cooldown_s = cooldown_s
        self._attack_ms = attack_ms
        self._hold_s = hold_s
        self._release_ms = release_ms
        self._duck_db = duck_db
        self._sink_name = sink_name
        self._monitor_source = monitor_source
        self._notify = notify_callback
        self._metrics = metrics_callback

        self._breach_count_required = max(
            1, int(round(breach_window_ms / (MEASURE_INTERVAL_S * 1000)))
        )
        self._lufs_history: deque[float] = deque(maxlen=self._breach_count_required)

        self._state: str = "idle"
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._measure_thread: threading.Thread | None = None
        self._parec_proc: subprocess.Popen | None = None
        self._duck_thread: threading.Thread | None = None

        self._triggers_total: int = 0
        self._last_peak: float = float("-inf")

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    @property
    def triggers_total(self) -> int:
        return self._triggers_total

    @property
    def last_peak_lufs_s(self) -> float:
        return self._last_peak

    def start(self) -> None:
        if self._measure_thread is not None and self._measure_thread.is_alive():
            log.warning("LufsPanicCap already running")
            return
        self._stop_event.clear()
        self._measure_thread = threading.Thread(
            target=self._measure_loop,
            name="lufs-panic-cap-measure",
            daemon=True,
        )
        self._measure_thread.start()
        log.info(
            "LufsPanicCap started: threshold=%.1f LUFS-S, breach_ms=%d, duck_db=%.1f",
            self._threshold,
            self._breach_window_ms,
            self._duck_db,
        )

    def stop(self) -> None:
        self._stop_event.set()
        proc = self._parec_proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        if self._measure_thread is not None:
            self._measure_thread.join(timeout=3.0)
        if self._duck_thread is not None:
            self._duck_thread.join(timeout=10.0)

    def evaluate_window(self, lufs_s: float) -> bool:
        """Feed one LUFS-S measurement; return True iff this fires the duck.

        Public for unit tests — exercises the breach-history accumulator
        without spawning parec or threading.
        """
        if not math.isfinite(lufs_s):
            return False
        self._last_peak = max(self._last_peak, lufs_s)
        if self._metrics is not None:
            try:
                self._metrics("hapax_broadcast_master_lufs_short_term", lufs_s)
            except Exception:
                log.debug("metrics callback failed", exc_info=True)
        if self.state in ("ducking", "held", "releasing", "cooldown"):
            self._lufs_history.clear()
            return False
        self._lufs_history.append(lufs_s)
        if len(self._lufs_history) == self._breach_count_required and all(
            v > self._threshold for v in self._lufs_history
        ):
            self._lufs_history.clear()
            return True
        return False

    def _measure_loop(self) -> None:
        """Spawn parec, read frames, compute LUFS-S, trigger on breach."""
        try:
            import pyloudnorm as pyln
        except ImportError:
            log.error("pyloudnorm not available — LufsPanicCap disabled")
            return

        meter = pyln.Meter(rate=SAMPLE_RATE_HZ, block_size=LUFS_WINDOW_S)

        frames_per_window = int(SAMPLE_RATE_HZ * MEASURE_INTERVAL_S)
        bytes_per_window = frames_per_window * SAMPLE_BYTES_PER_FRAME

        rolling_window_frames = int(SAMPLE_RATE_HZ * LUFS_WINDOW_S)
        rolling_buffer = np.zeros((rolling_window_frames, CHANNEL_COUNT), dtype=np.float32)
        rolling_filled = 0

        cmd = [
            "parec",
            f"--device={self._monitor_source}",
            f"--rate={SAMPLE_RATE_HZ}",
            f"--channels={CHANNEL_COUNT}",
            f"--format={SAMPLE_FORMAT}",
            "--raw",
        ]
        try:
            self._parec_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log.error("parec not found — install pulseaudio-utils")
            return
        except Exception as exc:
            log.error("parec spawn failed: %s", exc)
            return

        assert self._parec_proc.stdout is not None
        stdout = self._parec_proc.stdout

        while not self._stop_event.is_set():
            chunk = stdout.read(bytes_per_window)
            if not chunk or len(chunk) < bytes_per_window:
                if self._stop_event.is_set():
                    break
                time.sleep(0.05)
                continue

            int32_samples = np.frombuffer(chunk, dtype="<i4").reshape(-1, CHANNEL_COUNT)
            float_samples = int32_samples.astype(np.float32) / float(2**31)

            rolling_buffer = np.roll(rolling_buffer, -frames_per_window, axis=0)
            rolling_buffer[-frames_per_window:] = float_samples
            rolling_filled = min(rolling_filled + frames_per_window, rolling_window_frames)

            if rolling_filled < rolling_window_frames:
                continue

            try:
                lufs_s = meter.integrated_loudness(rolling_buffer)
            except Exception:
                log.debug("LUFS measurement failed", exc_info=True)
                continue

            if self.evaluate_window(lufs_s):
                self._trigger_duck(peak_lufs_s=lufs_s)

    def _trigger_duck(self, *, peak_lufs_s: float) -> None:
        with self._state_lock:
            if self._state != "idle":
                return
            self._state = "ducking"
        self._triggers_total += 1
        log.warning(
            "LUFS panic-cap TRIGGERED: peak=%.2f LUFS-S, threshold=%.1f LUFS-S, "
            "ducking %.0f dB for %.1fs",
            peak_lufs_s,
            self._threshold,
            self._duck_db,
            self._hold_s,
        )

        self._publish_awareness(active=True, peak_lufs_s=peak_lufs_s)
        self._publish_refusal_log(peak_lufs_s=peak_lufs_s)

        if self._notify is not None:
            try:
                self._notify(
                    "high",
                    f"LUFS panic-cap triggered: {peak_lufs_s:.1f} LUFS-S "
                    f"(threshold {self._threshold:.1f}). Master ducked "
                    f"{self._duck_db:.0f}dB for {self._hold_s:.1f}s.",
                )
            except Exception:
                log.debug("notify callback failed", exc_info=True)

        if self._metrics is not None:
            try:
                self._metrics("hapax_lufs_panic_cap_triggers_total", 1.0)
            except Exception:
                log.debug("metrics callback failed", exc_info=True)

        self._duck_thread = threading.Thread(
            target=self._run_duck_envelope,
            name="lufs-panic-cap-envelope",
            daemon=True,
        )
        self._duck_thread.start()

    def _run_duck_envelope(self) -> None:
        try:
            pre_duck_linear = self._read_sink_volume()
            duck_linear = pre_duck_linear * _db_to_linear(self._duck_db)

            self._ramp_volume(
                start_linear=pre_duck_linear,
                end_linear=duck_linear,
                duration_ms=self._attack_ms,
            )
            with self._state_lock:
                self._state = "held"

            t0 = time.time()
            while time.time() - t0 < self._hold_s and not self._stop_event.is_set():
                time.sleep(0.05)

            with self._state_lock:
                self._state = "releasing"
            self._ramp_volume(
                start_linear=duck_linear,
                end_linear=pre_duck_linear,
                duration_ms=self._release_ms,
            )
            with self._state_lock:
                self._state = "cooldown"
            self._publish_awareness(active=False, peak_lufs_s=self._last_peak)

            t1 = time.time()
            while time.time() - t1 < self._cooldown_s and not self._stop_event.is_set():
                time.sleep(0.05)
        finally:
            with self._state_lock:
                self._state = "idle"

    def _read_sink_volume(self) -> float:
        try:
            result = subprocess.run(
                ["wpctl", "get-volume", self._sink_name],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            parts = result.stdout.strip().split()
            if len(parts) >= 2 and parts[0] == "Volume:":
                return float(parts[1])
        except Exception:
            log.debug("wpctl get-volume failed", exc_info=True)
        return 1.0

    def _set_sink_volume(self, linear: float) -> None:
        linear = max(0.0, min(linear, 1.5))
        try:
            subprocess.run(
                ["wpctl", "set-volume", self._sink_name, f"{linear:.4f}"],
                capture_output=True,
                timeout=2.0,
                check=False,
            )
        except Exception:
            log.debug("wpctl set-volume failed", exc_info=True)

    def _ramp_volume(
        self,
        *,
        start_linear: float,
        end_linear: float,
        duration_ms: int,
        steps: int = 16,
    ) -> None:
        if duration_ms <= 0 or steps <= 0:
            self._set_sink_volume(end_linear)
            return
        step_sleep_s = (duration_ms / 1000.0) / steps
        for i in range(1, steps + 1):
            if self._stop_event.is_set():
                break
            progress = _sine_ease(i / steps)
            linear = start_linear + (end_linear - start_linear) * progress
            self._set_sink_volume(linear)
            time.sleep(step_sleep_s)
        self._set_sink_volume(end_linear)

    def _publish_awareness(self, *, active: bool, peak_lufs_s: float) -> None:
        if not AWARENESS_STATE_PATH.parent.exists():
            return
        try:
            existing: dict = {}
            if AWARENESS_STATE_PATH.exists():
                try:
                    existing = json.loads(AWARENESS_STATE_PATH.read_text())
                except json.JSONDecodeError:
                    existing = {}
            existing["lufs_panic_cap"] = {
                "active": active,
                "peak_lufs_s": round(peak_lufs_s, 2) if math.isfinite(peak_lufs_s) else None,
                "triggered_at": time.time() if active else None,
                "duck_envelope_seconds": round(
                    (self._attack_ms + self._release_ms) / 1000.0 + self._hold_s,
                    2,
                ),
                "triggers_total": self._triggers_total,
            }
            tmp = AWARENESS_STATE_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(existing))
            tmp.replace(AWARENESS_STATE_PATH)
        except Exception:
            log.debug("awareness state write failed", exc_info=True)

    def _publish_refusal_log(self, *, peak_lufs_s: float) -> None:
        if not REFUSAL_LOG_PATH.parent.exists():
            return
        entry = {
            "ts": time.time(),
            "axiom": "broadcast_no_loopback",
            "surface": "studio-compositor:lufs-panic-cap",
            "reason": (
                f"Broadcast master peaked {peak_lufs_s:.2f} LUFS-S sustained "
                f"{self._breach_window_ms}ms — auto-ducked {self._duck_db:.0f}dB "
                f"for {self._hold_s:.1f}s"
            ),
        }
        try:
            # jsonl-rotation: exempt(domain rotation; refusal-brief rotator archives daily)
            with REFUSAL_LOG_PATH.open("a") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception:
            log.debug("refusal log write failed", exc_info=True)


def main() -> None:
    """systemd entry point for ``hapax-lufs-panic-cap.service``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    def notify(priority: str, message: str) -> None:
        try:
            from shared.notify import send_notification

            send_notification("LUFS panic-cap", message, priority=priority)
        except Exception:
            log.debug("notify dispatch failed", exc_info=True)

    metrics_emitter: Callable[[str, float], None] | None = None
    try:
        from prometheus_client import Counter, Gauge, start_http_server

        triggers = Counter(
            "hapax_lufs_panic_cap_triggers_total",
            "LUFS panic-cap auto-duck triggers since process start",
        )
        gauge = Gauge(
            "hapax_broadcast_master_lufs_short_term",
            "Broadcast master EBU R128 short-term loudness (LUFS-S, 3s window)",
        )

        def _emit(name: str, value: float) -> None:
            if name == "hapax_lufs_panic_cap_triggers_total":
                triggers.inc(value)
            elif name == "hapax_broadcast_master_lufs_short_term":
                gauge.set(value)

        metrics_emitter = _emit
        try:
            start_http_server(9484)
        except Exception:
            log.debug("prometheus http server start failed", exc_info=True)
    except ImportError:
        log.warning("prometheus_client unavailable — metrics disabled")

    cap = LufsPanicCap(notify_callback=notify, metrics_callback=metrics_emitter)
    cap.start()
    try:
        while not cap._stop_event.is_set():
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        cap.stop()


if __name__ == "__main__":
    main()

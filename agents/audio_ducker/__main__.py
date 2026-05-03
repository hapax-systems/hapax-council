"""Hapax audio ducker daemon — VAD-driven duck-gain controller.

Phase 4 of the unified audio architecture. Watches operator voice
(Rode mic on L-12 USB AUX4) and TTS chain envelopes; writes duck
gain values to `hapax-music-duck` and `hapax-tts-duck` PipeWire
mixer nodes via `pw-cli set-param`.

ARCHITECTURE
============

Two trigger sources, two duckers:

    Trigger A: operator voice (Rode mic on L-12 USB AUX4)
        ducks music -12 dB
        ducks TTS    -8 dB

    Trigger B: TTS chain envelope (`hapax-loudnorm.monitor`)
        ducks music -8 dB
        does NOT duck TTS (TTS doesn't duck itself)

When both triggers fire on the music ducker, the daemon takes the
DEEPEST duck (minimum gain).

DETECTION
=========

Per-source RMS envelope follower with hysteresis:
    - 50 ms RMS window
    - on threshold:  -45 dBFS  (hysteresis high)
    - off threshold: -55 dBFS  (hysteresis low)
    - 200 ms hold-open after last on-threshold sample
    - 50 ms attack ramp on duck engage
    - 400 ms release ramp on duck disengage

The thresholds are LOW because the trigger sources tap the L-12 USB
multichannel input pre-fader, where mic signals arrive at line level.
TTS monitor is post-loudnorm so it's around -18 dBFS during speech,
silent at idle.

FAIL-SAFE
=========

- On SIGTERM/SIGINT/exit: write Gain 1 = 1.0 to both mixers (music
  and TTS at full passthrough). Music + TTS never silenced by daemon
  death.
- systemd Restart=always keeps daemon alive on crashes.
- Health published to /dev/shm/hapax-audio-ducker/state.json every
  tick for external monitoring.

DEPENDENCIES (system)
=====================

- pw-cat (audio capture from sources)
- pw-cli (write filter-chain control values)
- pipewire (active session)

Constants live in `shared/audio_loudness.py` — never hand-tune values
in this file.
"""

from __future__ import annotations

import json
import logging
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from shared.audio_loudness import (
    DUCK_ATTACK_MS,
    DUCK_DEPTH_OPERATOR_VOICE_DB,
    DUCK_DEPTH_TTS_DB,
    DUCK_RELEASE_MS,
)
from shared.audio_working_mode_couplings import (
    current_audio_constraints,
    working_mode_changed_since,
)

log = logging.getLogger("audio_ducker")

# ── Source taps ───────────────────────────────────────────────────────

# L-12 multichannel USB capture: 14 channels at 48 kHz s32le.
# AUX4 (channel 5) = Rode wireless RX (per hapax-l12-evilpet-capture.conf
# operator-confirmed channel map).
L12_MULTICHANNEL_NODE = (
    "alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input"
)
L12_CHANNELS = 14
RODE_AUX_INDEX = 4  # AUX4 = CH5 = Rode

# TTS chain pre-limiter input. The sink is named `hapax-loudnorm-capture`
# (renamed from the legacy `hapax-loudnorm` in Phase 1.7 to avoid name
# conflict with the playback node). Its monitor reflects whatever the
# WirePlumber role.assistant → hapax-voice-fx → hapax-loudnorm-capture
# loopback chain feeds into it — i.e. live TTS audio whenever daimonion
# is speaking.
TTS_TAP_NODE = "hapax-loudnorm-capture.monitor"
TTS_TAP_CHANNELS = 2  # stereo

# Duck mixer node names.
MUSIC_DUCK_NODE = "hapax-music-duck"
TTS_DUCK_NODE = "hapax-tts-duck"

# Audio capture format.
SAMPLE_RATE = 48000
RMS_WINDOW_MS = 50
RMS_WINDOW_SAMPLES = int(SAMPLE_RATE * RMS_WINDOW_MS / 1000)

# VAD thresholds (dBFS).
TRIGGER_ON_DBFS = -45.0
TRIGGER_OFF_DBFS = -55.0
HOLD_OPEN_MS = 200

# Health output.
STATE_DIR = Path("/dev/shm/hapax-audio-ducker")
STATE_PATH = STATE_DIR / "state.json"
TICK_SLEEP_S = 0.02  # 20 ms scheduler tick
SOURCE_MAX_STALE_MS = 500.0
READBACK_INTERVAL_S = 0.25
GAIN_READBACK_TOLERANCE = 0.025

# ── Helpers ────────────────────────────────────────────────────────────


def db_to_lin(db: float) -> float:
    """Convert dB to linear gain factor."""
    return float(10.0 ** (db / 20.0))


def lin_to_db(lin: float) -> float:
    """Convert linear gain to dB. Floors at -120 dB."""
    if lin < 1e-6:
        return -120.0
    return float(20.0 * np.log10(lin))


@dataclass(frozen=True)
class MixerGainWriteResult:
    """Result of a PipeWire mixer write."""

    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class MixerGainReadback:
    """Actual `duck_l/r:Gain 1` values read back from PipeWire."""

    ok: bool
    left: float | None = None
    right: float | None = None
    error: str | None = None
    raw: str = ""

    @property
    def gain(self) -> float | None:
        if self.left is None or self.right is None:
            return None
        return (self.left + self.right) / 2.0

    @property
    def channels_match(self) -> bool:
        if self.left is None or self.right is None:
            return False
        return abs(self.left - self.right) <= GAIN_READBACK_TOLERANCE


def write_mixer_gain(node_name: str, gain_lin: float) -> MixerGainWriteResult:
    """Write `duck_l:Gain 1` AND `duck_r:Gain 1` on the named filter-chain
    node via a single pw-cli call.

    The duck conf uses two mono mixers (one per channel) for proper
    stereo passthrough — both must receive the same gain value. Sending
    both in one Props update keeps L/R atomic-ish (single message to
    PipeWire) so the operator never hears L/R drift during a duck event.
    """
    try:
        subprocess.run(
            [
                "pw-cli",
                "set-param",
                node_name,
                "Props",
                (
                    "{ params = ["
                    f' "duck_l:Gain 1" {gain_lin:.4f}'
                    f' "duck_r:Gain 1" {gain_lin:.4f}'
                    " ] }"
                ),
            ],
            check=True,
            capture_output=True,
            timeout=2.0,
        )
        return MixerGainWriteResult(ok=True)
    except subprocess.CalledProcessError as exc:
        error = exc.stderr.decode(errors="replace") if exc.stderr else str(exc)
        log.warning(
            "pw-cli set-param failed for %s gain=%.3f: %s",
            node_name,
            gain_lin,
            error,
        )
        return MixerGainWriteResult(ok=False, error=error)
    except subprocess.TimeoutExpired:
        log.warning("pw-cli set-param timed out for %s", node_name)
        return MixerGainWriteResult(ok=False, error="pw-cli set-param timed out")
    except FileNotFoundError as exc:
        log.warning("pw-cli set-param unavailable for %s: %s", node_name, exc)
        return MixerGainWriteResult(ok=False, error=str(exc))


def read_mixer_gain(node_name: str) -> MixerGainReadback:
    """Read actual `duck_l/r:Gain 1` from the PipeWire filter-chain node."""
    try:
        result = subprocess.run(
            ["pw-cli", "enum-params", node_name, "Props"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except FileNotFoundError as exc:
        return MixerGainReadback(ok=False, error=str(exc))
    except subprocess.TimeoutExpired:
        return MixerGainReadback(ok=False, error="pw-cli enum-params timed out")
    if result.returncode != 0:
        return MixerGainReadback(
            ok=False,
            error=result.stderr.strip() or f"pw-cli enum-params exited {result.returncode}",
            raw=result.stdout,
        )
    return _parse_mixer_gain_readback(result.stdout)


def _parse_mixer_gain_readback(text: str) -> MixerGainReadback:
    """Parse `pw-cli enum-params <node> Props` output for duck L/R gains."""
    values: dict[str, float] = {}
    pending: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith('String "duck_l:Gain 1"'):
            pending = "left"
            continue
        if line.startswith('String "duck_r:Gain 1"'):
            pending = "right"
            continue
        if pending is None or not line.startswith("Float "):
            continue
        try:
            values[pending] = float(line.split()[1])
        except (IndexError, ValueError):
            return MixerGainReadback(ok=False, error=f"malformed float line: {line}", raw=text)
        pending = None
    left = values.get("left")
    right = values.get("right")
    if left is None or right is None:
        return MixerGainReadback(
            ok=False,
            left=left,
            right=right,
            error="duck_l/r Gain 1 not present in PipeWire Props",
            raw=text,
        )
    return MixerGainReadback(ok=True, left=left, right=right, raw=text)


# ── Envelope follower ─────────────────────────────────────────────────


@dataclass
class EnvelopeState:
    """Hysteresis-based VAD state for a single trigger source."""

    name: str
    last_rms_dbfs: float = -120.0
    is_active: bool = False
    last_above_threshold_ms: float = 0.0  # monotonic, ms
    last_sample_ms: float | None = None
    last_error: str | None = None
    last_error_ms: float | None = None
    samples_lock: threading.Lock = field(default_factory=threading.Lock)
    pending_samples: bytes = b""

    def update(self, samples: np.ndarray, now_ms: float) -> None:
        """Compute RMS, update active state with hysteresis + hold-open."""
        if samples.size == 0:
            return
        # Float32 -1..1 expected; compute RMS in linear, convert to dB
        rms_lin = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
        rms_db = lin_to_db(rms_lin)
        self.last_rms_dbfs = rms_db
        self.last_sample_ms = now_ms
        self.last_error = None
        self.last_error_ms = None
        if rms_db >= TRIGGER_ON_DBFS:
            self.is_active = True
            self.last_above_threshold_ms = now_ms
        elif rms_db < TRIGGER_OFF_DBFS:
            # Below release threshold AND hold-open expired → off
            if (now_ms - self.last_above_threshold_ms) > HOLD_OPEN_MS:
                self.is_active = False
        # In between TRIGGER_OFF and TRIGGER_ON: latch existing state

    def mark_error(self, error: str, now_ms: float) -> None:
        self.last_error = error
        self.last_error_ms = now_ms
        self.is_active = False

    def sample_age_ms(self, now_ms: float) -> float | None:
        if self.last_sample_ms is None:
            return None
        return max(0.0, now_ms - self.last_sample_ms)

    def is_fresh(self, now_ms: float) -> bool:
        age = self.sample_age_ms(now_ms)
        return self.last_error is None and age is not None and age <= SOURCE_MAX_STALE_MS


# ── Capture readers ───────────────────────────────────────────────────


def _spawn_capture(
    target: str,
    channels: int,
    fmt: str,
    *,
    chunk_samples: int = RMS_WINDOW_SAMPLES,
) -> subprocess.Popen:
    """Spawn pw-cat in record mode pipelined to stdout."""
    return subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        [
            "pw-cat",
            "--record",
            "-",
            "--target",
            target,
            "--rate",
            str(SAMPLE_RATE),
            "--format",
            fmt,
            "--channels",
            str(channels),
            "--raw",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )


def _read_aligned(stream: object, want_bytes: int, frame_bytes: int) -> bytes:
    """Read one exact frame-aligned window from a raw audio stream.

    The caller passes a frame-aligned window size. Do not read past that
    window and trim the result: dropping even a few excess bytes rotates
    multichannel channel boundaries and can make a hot channel appear at
    the Rode AUX index.
    """
    if want_bytes % frame_bytes != 0:
        raise ValueError("want_bytes must be a multiple of frame_bytes")

    buf = bytearray()
    while len(buf) < want_bytes:
        chunk = stream.read(want_bytes - len(buf))  # type: ignore[attr-defined]
        if not chunk:
            return b""
        buf.extend(chunk)
    return bytes(buf)


def _read_rode_loop(state: EnvelopeState, stop: threading.Event) -> None:
    """Read L-12 multichannel input, isolate AUX4 (Rode), feed envelope."""
    proc = _spawn_capture(L12_MULTICHANNEL_NODE, L12_CHANNELS, "s32")
    bytes_per_frame = 4 * L12_CHANNELS  # s32 = 4 bytes/sample
    chunk_bytes = RMS_WINDOW_SAMPLES * bytes_per_frame
    log.info("Rode capture started (target=%s aux=%d)", L12_MULTICHANNEL_NODE, RODE_AUX_INDEX)
    try:
        while not stop.is_set():
            assert proc.stdout is not None
            buf = _read_aligned(proc.stdout, chunk_bytes, bytes_per_frame)
            if not buf:
                continue
            arr = np.frombuffer(buf, dtype=np.int32).reshape(-1, L12_CHANNELS)
            mono = arr[:, RODE_AUX_INDEX].astype(np.float64) / (2**31)
            state.update(mono, time.monotonic() * 1000.0)
    except Exception as exc:
        state.mark_error(f"{type(exc).__name__}: {exc}", time.monotonic() * 1000.0)
        log.exception("Rode capture loop crashed")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()


def _read_tts_loop(state: EnvelopeState, stop: threading.Event) -> None:
    """Read TTS chain monitor, sum L+R, feed envelope."""
    proc = _spawn_capture(TTS_TAP_NODE, TTS_TAP_CHANNELS, "s16")
    bytes_per_frame = 2 * TTS_TAP_CHANNELS  # s16 = 2 bytes/sample
    chunk_bytes = RMS_WINDOW_SAMPLES * bytes_per_frame
    log.info("TTS capture started (target=%s)", TTS_TAP_NODE)
    try:
        while not stop.is_set():
            assert proc.stdout is not None
            buf = _read_aligned(proc.stdout, chunk_bytes, bytes_per_frame)
            if not buf:
                continue
            arr = np.frombuffer(buf, dtype=np.int16).reshape(-1, TTS_TAP_CHANNELS)
            mono = arr.astype(np.float64).mean(axis=1) / (2**15)
            state.update(mono, time.monotonic() * 1000.0)
    except Exception as exc:
        state.mark_error(f"{type(exc).__name__}: {exc}", time.monotonic() * 1000.0)
        log.exception("TTS capture loop crashed")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()


# ── Duck-state computation ────────────────────────────────────────────


@dataclass
class DuckState:
    """Per-mixer current vs target gain (linear) with ramp."""

    node: str
    current_gain: float = 1.0
    target_gain: float = 1.0
    commanded_gain: float = 1.0
    actual_gain: float | None = 1.0
    actual_left_gain: float | None = 1.0
    actual_right_gain: float | None = 1.0
    last_write_error: str | None = None
    last_readback_error: str | None = None
    last_write_ts: float | None = None
    last_readback_ts: float | None = None
    fail_open_reason: str | None = None


UNITY = 1.0
MUSIC_DUCK_OPERATOR = db_to_lin(DUCK_DEPTH_OPERATOR_VOICE_DB)  # ≈ 0.251 (-12 dB)
MUSIC_DUCK_TTS = db_to_lin(DUCK_DEPTH_TTS_DB)  # ≈ 0.398 (-8 dB)
TTS_DUCK_OPERATOR = db_to_lin(DUCK_DEPTH_TTS_DB)  # TTS ducks -8 dB under operator


def compute_targets(
    rode_active: bool,
    tts_active: bool,
    *,
    allow_tts_into_broadcast: bool = True,
) -> tuple[float, float]:
    """Return (music_target_gain, tts_target_gain) given trigger states.

    Music: take the DEEPEST duck (min gain) when both Rode + TTS active.
    TTS:   only Rode triggers TTS duck (TTS doesn't duck itself).

    ``allow_tts_into_broadcast`` is the working-mode coupling: when
    fortress mode disables ``duck_role_assistant_into_broadcast``, the
    TTS trigger no longer drives the music duck (only operator voice
    does). Operator-voice ducking is unaffected — the operator IS the
    broadcast voice and always takes priority.
    """
    effective_tts = tts_active and allow_tts_into_broadcast
    if rode_active and effective_tts:
        music = min(MUSIC_DUCK_OPERATOR, MUSIC_DUCK_TTS)
    elif rode_active:
        music = MUSIC_DUCK_OPERATOR
    elif effective_tts:
        music = MUSIC_DUCK_TTS
    else:
        music = UNITY

    tts = TTS_DUCK_OPERATOR if rode_active else UNITY
    return music, tts


def ramp_gain(current: float, target: float, dt_ms: float) -> float:
    """Linear-domain ramp toward target. Faster on attack (down), slower
    on release (up). Returns new current value, clamped to [0, 1].
    """
    if abs(current - target) < 1e-4:
        return target
    if target < current:
        # Attacking: drop fast
        rate = (1.0 - 0.0) / DUCK_ATTACK_MS  # full-range sweep over attack window
    else:
        # Releasing: smooth recovery
        rate = (1.0 - 0.0) / DUCK_RELEASE_MS
    delta = rate * dt_ms
    if target > current:
        new = min(target, current + delta)
    else:
        new = max(target, current - delta)
    return max(0.0, min(1.0, new))


GainWriter = Callable[[str, float], MixerGainWriteResult]
GainReader = Callable[[str], MixerGainReadback]


def source_blockers(
    rode: EnvelopeState,
    tts: EnvelopeState,
    now_ms: float,
) -> list[str]:
    """Return source freshness/capture faults that force unity gain."""
    blockers: list[str] = []
    for source in (rode, tts):
        age = source.sample_age_ms(now_ms)
        if source.last_error is not None:
            blockers.append(f"{source.name}_capture_error:{source.last_error}")
        elif age is None:
            blockers.append(f"{source.name}_capture_missing")
        elif age > SOURCE_MAX_STALE_MS:
            blockers.append(f"{source.name}_capture_stale:{age:.0f}ms")
    return blockers


def trigger_cause_for(rode_active: bool, tts_active: bool, blockers: list[str]) -> str:
    if blockers:
        return "fail_open"
    if rode_active and tts_active:
        return "operator_voice+tts"
    if rode_active:
        return "operator_voice"
    if tts_active:
        return "tts"
    return "none"


def apply_gain_command(
    duck: DuckState,
    gain: float,
    now_s: float,
    *,
    writer: GainWriter = write_mixer_gain,
) -> str | None:
    result = writer(duck.node, gain)
    duck.last_write_ts = now_s
    if not result.ok:
        duck.last_write_error = result.error or "write_failed"
        return duck.last_write_error
    duck.current_gain = gain
    duck.commanded_gain = gain
    duck.last_write_error = None
    return None


def refresh_gain_readback(
    duck: DuckState,
    now_s: float,
    *,
    reader: GainReader = read_mixer_gain,
) -> str | None:
    readback = reader(duck.node)
    duck.last_readback_ts = now_s
    duck.actual_left_gain = readback.left
    duck.actual_right_gain = readback.right
    duck.actual_gain = readback.gain
    if not readback.ok:
        duck.last_readback_error = readback.error or "readback_failed"
        return duck.last_readback_error
    if not readback.channels_match:
        duck.last_readback_error = "readback_channel_mismatch"
        return duck.last_readback_error
    actual = readback.gain
    if actual is None:
        duck.last_readback_error = "readback_missing_gain"
        return duck.last_readback_error
    if abs(actual - duck.commanded_gain) > GAIN_READBACK_TOLERANCE:
        duck.last_readback_error = (
            f"readback_mismatch:commanded={duck.commanded_gain:.4f}:actual={actual:.4f}"
        )
        return duck.last_readback_error
    duck.last_readback_error = None
    return None


def fail_open_ducks(
    music: DuckState,
    ttsd: DuckState,
    reason: str,
    now_s: float,
    *,
    writer: GainWriter = write_mixer_gain,
    reader: GainReader = read_mixer_gain,
    refresh_readback: bool = True,
) -> None:
    """Restore unity gain and preserve the reason in both mixer states."""
    for duck in (music, ttsd):
        duck.fail_open_reason = reason
        wrote = False
        if abs(duck.commanded_gain - UNITY) > 1e-4:
            apply_gain_command(duck, UNITY, now_s, writer=writer)
            wrote = True
        if refresh_readback or wrote:
            refresh_gain_readback(duck, now_s, reader=reader)


# ── Health publisher ──────────────────────────────────────────────────


def _source_payload(source: EnvelopeState, now_ms: float) -> dict[str, Any]:
    age_ms = source.sample_age_ms(now_ms)
    fresh = source.is_fresh(now_ms)
    return {
        "rms_dbfs": source.last_rms_dbfs,
        "active": source.is_active,
        "effective_active": source.is_active and fresh,
        "fresh": fresh,
        "sample_age_ms": age_ms,
        "max_stale_ms": SOURCE_MAX_STALE_MS,
        "last_error": source.last_error,
        "last_error_age_ms": (
            max(0.0, now_ms - source.last_error_ms) if source.last_error_ms is not None else None
        ),
    }


def _duck_payload(duck: DuckState) -> dict[str, Any]:
    return {
        "node": duck.node,
        "target_gain": duck.target_gain,
        "current_gain": duck.current_gain,
        "commanded_gain": duck.commanded_gain,
        "commanded_db": lin_to_db(duck.commanded_gain),
        "actual_gain": duck.actual_gain,
        "actual_db": lin_to_db(duck.actual_gain) if duck.actual_gain is not None else None,
        "actual_left_gain": duck.actual_left_gain,
        "actual_right_gain": duck.actual_right_gain,
        "last_write_error": duck.last_write_error,
        "last_readback_error": duck.last_readback_error,
        "last_write_ts": duck.last_write_ts,
        "last_readback_ts": duck.last_readback_ts,
        "fail_open_reason": duck.fail_open_reason,
    }


def publish_state(
    rode: EnvelopeState,
    tts: EnvelopeState,
    music: DuckState,
    ttsd: DuckState,
    *,
    trigger_cause: str,
    blockers: list[str],
    now_s: float | None = None,
    now_ms: float | None = None,
    path: Path = STATE_PATH,
) -> None:
    """Atomic write of current state to /dev/shm for monitoring."""
    current_s = time.time() if now_s is None else now_s
    current_ms = time.monotonic() * 1000.0 if now_ms is None else now_ms
    effective_music_gain = (
        music.actual_gain if music.actual_gain is not None else music.commanded_gain
    )
    effective_tts_gain = ttsd.actual_gain if ttsd.actual_gain is not None else ttsd.commanded_gain
    duck_errors = [
        error
        for error in (
            music.last_write_error,
            music.last_readback_error,
            ttsd.last_write_error,
            ttsd.last_readback_error,
        )
        if error is not None
    ]
    payload = {
        "ts": current_s,
        "trigger_cause": trigger_cause,
        "fail_open": bool(blockers),
        "blockers": blockers,
        "errors": [*blockers, *duck_errors],
        "rode": _source_payload(rode, current_ms),
        "tts": _source_payload(tts, current_ms),
        "music_duck": _duck_payload(music),
        "tts_duck": _duck_payload(ttsd),
        "commanded_music_duck_gain": music.commanded_gain,
        "actual_music_duck_gain": music.actual_gain,
        "commanded_tts_duck_gain": ttsd.commanded_gain,
        "actual_tts_duck_gain": ttsd.actual_gain,
        # Legacy scalar aliases remain for older overlays; prefer actual readback when present.
        "music_duck_gain": effective_music_gain,
        "music_duck_db": lin_to_db(effective_music_gain),
        "tts_duck_gain": effective_tts_gain,
        "tts_duck_db": lin_to_db(effective_tts_gain),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.debug("state publish failed", exc_info=True)


# ── Main loop ──────────────────────────────────────────────────────────


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    rode_state = EnvelopeState(name="rode")
    tts_state = EnvelopeState(name="tts")
    music_duck = DuckState(node=MUSIC_DUCK_NODE)
    tts_duck = DuckState(node=TTS_DUCK_NODE)

    stop = threading.Event()

    def fail_safe(*_args: object) -> None:
        log.info("Shutdown signal — restoring unity gain on both duckers")
        write_mixer_gain(MUSIC_DUCK_NODE, UNITY)
        write_mixer_gain(TTS_DUCK_NODE, UNITY)
        stop.set()

    signal.signal(signal.SIGTERM, fail_safe)
    signal.signal(signal.SIGINT, fail_safe)

    # Initialize mixers to unity at startup (in case of stale state).
    apply_gain_command(music_duck, UNITY, time.time())
    apply_gain_command(tts_duck, UNITY, time.time())
    refresh_gain_readback(music_duck, time.time())
    refresh_gain_readback(tts_duck, time.time())

    threads = [
        threading.Thread(target=_read_rode_loop, args=(rode_state, stop), daemon=True),
        threading.Thread(target=_read_tts_loop, args=(tts_state, stop), daemon=True),
    ]
    for t in threads:
        t.start()

    last_tick = time.monotonic()
    last_readback = 0.0
    last_mode_mtime: float | None = None
    cached_constraints: dict[str, object] = current_audio_constraints()
    log.info("Audio ducker running")

    try:
        while not stop.is_set():
            now = time.monotonic()
            now_s = time.time()
            now_ms = now * 1000.0
            dt_ms = (now - last_tick) * 1000.0
            last_tick = now

            mode_changed, last_mode_mtime = working_mode_changed_since(last_mode_mtime)
            if mode_changed:
                cached_constraints = current_audio_constraints()
                log.info(
                    "audio ducker working-mode constraints refreshed: %s",
                    cached_constraints,
                )
            allow_tts_broadcast = bool(
                cached_constraints.get("duck_role_assistant_into_broadcast", True)
            )

            blockers = source_blockers(rode_state, tts_state, now_ms)
            if blockers:
                music_target, tts_target = UNITY, UNITY
            else:
                music_target, tts_target = compute_targets(
                    rode_state.is_active,
                    tts_state.is_active,
                    allow_tts_into_broadcast=allow_tts_broadcast,
                )
            music_duck.target_gain = music_target
            tts_duck.target_gain = tts_target

            new_music = ramp_gain(music_duck.current_gain, music_duck.target_gain, dt_ms)
            new_tts = ramp_gain(tts_duck.current_gain, tts_duck.target_gain, dt_ms)

            if abs(new_music - music_duck.current_gain) > 1e-3:
                error = apply_gain_command(music_duck, new_music, now_s)
                if error is not None:
                    blockers.append(f"music_write_error:{error}")
            if abs(new_tts - tts_duck.current_gain) > 1e-3:
                error = apply_gain_command(tts_duck, new_tts, now_s)
                if error is not None:
                    blockers.append(f"tts_write_error:{error}")

            readback_due = now - last_readback >= READBACK_INTERVAL_S
            if readback_due:
                last_readback = now
                error = refresh_gain_readback(music_duck, now_s)
                if error is not None:
                    blockers.append(f"music_readback_error:{error}")
                error = refresh_gain_readback(tts_duck, now_s)
                if error is not None:
                    blockers.append(f"tts_readback_error:{error}")

            if blockers:
                fail_open_ducks(
                    music_duck,
                    tts_duck,
                    ";".join(blockers),
                    now_s,
                    refresh_readback=False,
                )
            else:
                music_duck.fail_open_reason = None
                tts_duck.fail_open_reason = None

            trigger_cause = trigger_cause_for(rode_state.is_active, tts_state.is_active, blockers)
            publish_state(
                rode_state,
                tts_state,
                music_duck,
                tts_duck,
                trigger_cause=trigger_cause,
                blockers=blockers,
                now_s=now_s,
                now_ms=now_ms,
            )
            time.sleep(TICK_SLEEP_S)
    finally:
        fail_safe()

    return 0


if __name__ == "__main__":
    sys.exit(main())

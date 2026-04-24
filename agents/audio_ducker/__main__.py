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
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from shared.audio_loudness import (
    DUCK_ATTACK_MS,
    DUCK_DEPTH_OPERATOR_VOICE_DB,
    DUCK_DEPTH_TTS_DB,
    DUCK_RELEASE_MS,
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

# ── Helpers ────────────────────────────────────────────────────────────


def db_to_lin(db: float) -> float:
    """Convert dB to linear gain factor."""
    return float(10.0 ** (db / 20.0))


def lin_to_db(lin: float) -> float:
    """Convert linear gain to dB. Floors at -120 dB."""
    if lin < 1e-6:
        return -120.0
    return float(20.0 * np.log10(lin))


def write_mixer_gain(node_name: str, gain_lin: float) -> None:
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
    except subprocess.CalledProcessError as exc:
        log.warning(
            "pw-cli set-param failed for %s gain=%.3f: %s",
            node_name,
            gain_lin,
            exc.stderr.decode(errors="replace") if exc.stderr else exc,
        )
    except subprocess.TimeoutExpired:
        log.warning("pw-cli set-param timed out for %s", node_name)


# ── Envelope follower ─────────────────────────────────────────────────


@dataclass
class EnvelopeState:
    """Hysteresis-based VAD state for a single trigger source."""

    name: str
    last_rms_dbfs: float = -120.0
    is_active: bool = False
    last_above_threshold_ms: float = 0.0  # monotonic, ms
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
        if rms_db >= TRIGGER_ON_DBFS:
            self.is_active = True
            self.last_above_threshold_ms = now_ms
        elif rms_db < TRIGGER_OFF_DBFS:
            # Below release threshold AND hold-open expired → off
            if (now_ms - self.last_above_threshold_ms) > HOLD_OPEN_MS:
                self.is_active = False
        # In between TRIGGER_OFF and TRIGGER_ON: latch existing state


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
    """Read until we have an integer number of frames totaling >= want_bytes.

    pw-cat outputs PipeWire quanta (~1024 samples) per read, which may
    not align to our RMS window or even to channel-frame boundaries.
    Loop until we have at least ``want_bytes`` AND the total is a
    multiple of ``frame_bytes``. Returns ``b""`` on EOF.
    """
    buf = bytearray()
    while len(buf) < want_bytes:
        chunk = stream.read(want_bytes - len(buf) + frame_bytes)  # type: ignore[attr-defined]
        if not chunk:
            return b""
        buf.extend(chunk)
    # Trim trailing partial frame
    aligned = (len(buf) // frame_bytes) * frame_bytes
    return bytes(buf[:aligned])


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
    except Exception:
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
    except Exception:
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


UNITY = 1.0
MUSIC_DUCK_OPERATOR = db_to_lin(DUCK_DEPTH_OPERATOR_VOICE_DB)  # ≈ 0.251 (-12 dB)
MUSIC_DUCK_TTS = db_to_lin(DUCK_DEPTH_TTS_DB)  # ≈ 0.398 (-8 dB)
TTS_DUCK_OPERATOR = db_to_lin(DUCK_DEPTH_TTS_DB)  # TTS ducks -8 dB under operator


def compute_targets(rode_active: bool, tts_active: bool) -> tuple[float, float]:
    """Return (music_target_gain, tts_target_gain) given trigger states.

    Music: take the DEEPEST duck (min gain) when both Rode + TTS active.
    TTS:   only Rode triggers TTS duck (TTS doesn't duck itself).
    """
    if rode_active and tts_active:
        music = min(MUSIC_DUCK_OPERATOR, MUSIC_DUCK_TTS)
    elif rode_active:
        music = MUSIC_DUCK_OPERATOR
    elif tts_active:
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


# ── Health publisher ──────────────────────────────────────────────────


def publish_state(
    rode: EnvelopeState, tts: EnvelopeState, music: DuckState, ttsd: DuckState
) -> None:
    """Atomic write of current state to /dev/shm for monitoring."""
    payload = {
        "ts": time.time(),
        "rode": {"rms_dbfs": rode.last_rms_dbfs, "active": rode.is_active},
        "tts": {"rms_dbfs": tts.last_rms_dbfs, "active": tts.is_active},
        "music_duck_gain": music.current_gain,
        "music_duck_db": lin_to_db(music.current_gain),
        "tts_duck_gain": ttsd.current_gain,
        "tts_duck_db": lin_to_db(ttsd.current_gain),
    }
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(STATE_PATH)
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
    write_mixer_gain(MUSIC_DUCK_NODE, UNITY)
    write_mixer_gain(TTS_DUCK_NODE, UNITY)

    threads = [
        threading.Thread(target=_read_rode_loop, args=(rode_state, stop), daemon=True),
        threading.Thread(target=_read_tts_loop, args=(tts_state, stop), daemon=True),
    ]
    for t in threads:
        t.start()

    last_tick = time.monotonic()
    log.info("Audio ducker running")

    try:
        while not stop.is_set():
            now = time.monotonic()
            dt_ms = (now - last_tick) * 1000.0
            last_tick = now

            music_target, tts_target = compute_targets(rode_state.is_active, tts_state.is_active)
            music_duck.target_gain = music_target
            tts_duck.target_gain = tts_target

            new_music = ramp_gain(music_duck.current_gain, music_duck.target_gain, dt_ms)
            new_tts = ramp_gain(tts_duck.current_gain, tts_duck.target_gain, dt_ms)

            if abs(new_music - music_duck.current_gain) > 1e-3:
                write_mixer_gain(MUSIC_DUCK_NODE, new_music)
                music_duck.current_gain = new_music
            if abs(new_tts - tts_duck.current_gain) > 1e-3:
                write_mixer_gain(TTS_DUCK_NODE, new_tts)
                tts_duck.current_gain = new_tts

            publish_state(rode_state, tts_state, music_duck, tts_duck)
            time.sleep(TICK_SLEEP_S)
    finally:
        fail_safe()

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Hapax audio ducker daemon — VAD-driven duck-gain controller.

Phase 4 of the unified audio architecture, re-homed onto the mk5/S-4
baseline (segment-audio-hosting-readiness). Watches operator voice (the
live mk5 Rode → `hapax-mic-rode-capture`) and the broadcast TTS chain
envelope, plus a hosting-segment subscription; writes the music duck gain
to the mk5-native `hapax-music-duck-mk5` node via `pw-cli set-param`. Node
names resolve from the topology SSOT (fail-open). There is no software TTS
duck on mk5 (Hapax voice routes mk5 OUT3/4 → Torso S-4 → mk5 IN3/4, analog),
so the daemon owns the single music-bed duck.

ARCHITECTURE
============

Two trigger sources, two duckers:

    Trigger A: operator voice — PRE-WET mk5 Rode sidechain
        (`hapax-mic-rode-capture`, mk5 capture_AUX0: the dry mic,
        never the S-4 wet return — rebuild design §ducking)
        ducks music -12 dB
        ducks TTS    -8 dB

    Trigger B: TTS chain envelope (`hapax-loudnorm-capture.monitor`)
        ducks music -8 dB
        does NOT duck TTS (TTS doesn't duck itself)

Concurrent triggers COMPOSE IN dB DOMAIN (voice-p2-duck-handoff: the
shared/audio_duck_compose call-site swap): genuinely concurrent (hot)
triggers sum their attenuations, clamped at MAX_TOTAL_ATTEN_DB; a
trigger latched only by hold-open (a handoff tail) sustains its own
depth without stacking. Releases pass through a handoff hold
(DUCK_HANDOFF_HOLD_MS release hysteresis) so rapid operator↔TTS turn
alternation never pumps the bed. See `agents/audio_ducker/handoff.py`.

DETECTION
=========

Per-source RMS envelope follower with hysteresis:
    - 50 ms RMS window
    - on threshold:  -45 dBFS  (hysteresis high)
    - off threshold: -55 dBFS  (hysteresis low)
    - 200 ms hold-open after last on-threshold sample
    - 400 ms handoff hold before any release may begin
    - 10 ms attack ramp on duck engage
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

from agents.audio_ducker.handoff import (
    HandoffHold,
    compose_duck_target_db,
    music_duck_triggers,
)
from shared.audio_duck_compose import amplitude_from_db
from shared.audio_loudness import (
    DUCK_ATTACK_MS,
    DUCK_DEPTH_OPERATOR_VOICE_DB,
    DUCK_DEPTH_TTS_DB,
    DUCK_RELEASE_MS,
)
from shared.audio_node_resolver import resolve_audio_node
from shared.audio_working_mode_couplings import (
    current_audio_constraints,
    working_mode_changed_since,
)

log = logging.getLogger("audio_ducker")

# ── Source taps ───────────────────────────────────────────────────────

# Operator-mic VAD tap — the LIVE mk5 Rode. The L-12 → mk5 migration retired the
# Zoom L-12 14ch multichannel node this daemon used to read (AUX4 = Rode, line
# level pre-fader). The operator mic now lands on mk5 capture_AUX0 →
# hapax-mic-rode-capture, a 2ch FL/FR filter-chain (Rode mono duplicated).
# Resolved from the topology SSOT so the NEXT hardware migration is picked up
# instead of silently re-breaking this daemon; fallback fail-open to the literal.
RODE_CAPTURE_NODE = resolve_audio_node("mic-rode", "hapax-mic-rode-capture")
RODE_CHANNELS = 2

# TTS chain monitor. `hapax-loudnorm-capture` is the broadcast-bound TTS chain
# (role.broadcast → hapax-voice-fx → hapax-loudnorm-capture); its monitor
# reflects live TTS audio whenever Hapax is hosting on broadcast. This is the
# physical-truth "hosting TTS present" detector and stays live on mk5.
TTS_TAP_NODE = "hapax-loudnorm-capture.monitor"
TTS_TAP_CHANNELS = 2  # stereo

# Music duck gain node — the mk5-native dedicated ducker (config/audio-topology.yaml
# id music-duck-mk5, inserted hapax-music-loudnorm → hapax-music-duck-mk5 →
# hapax-livestream-tap). The daemon writes duck_l/duck_r "Gain 1" here. Resolved
# from SSOT; fail-open fallback (an absent node leaves the bed un-ducked, never
# silenced — the duck defaults to transparent passthrough).
MUSIC_DUCK_NODE = resolve_audio_node("music-duck-mk5", "hapax-music-duck-mk5")

# No SOFTWARE TTS duck on the mk5 graph: Hapax voice routes mk5 OUT3/4 → Torso
# S-4 → mk5 IN3/4 (analog), so there is no software gain node to duck. The
# L-12-era hapax-tts-duck node is dead. The daemon keeps a SINGLE duck owner
# (the music bed); TTS_DUCK_NODE=None disables the second-duck output path.
# Never-remove: the code path stays, guarded, for a future TTS-duck topology.
TTS_DUCK_NODE: str | None = None

# Audio capture format.
SAMPLE_RATE = 44100
RMS_WINDOW_MS = 50
RMS_WINDOW_SAMPLES = int(SAMPLE_RATE * RMS_WINDOW_MS / 1000)

# VAD thresholds (dBFS). PROVISIONAL for mk5: these were tuned for the retired
# L-12 PRE-FADER line-level tap. The live hapax-mic-rode-capture node is
# post-filter-chain (a different reference level), so the on/off points need a
# live dBFS readback at idle vs speech before the operator-VAD duck is trusted
# live (state.json publishes last_rms_dbfs for that tune). Alpha actuates.
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


def write_mixer_gain(node_name: str | None, gain_lin: float) -> MixerGainWriteResult:
    """Write `duck_l:Gain 1` AND `duck_r:Gain 1` on the named filter-chain
    node via a single pw-cli call.

    The duck conf uses two mono mixers (one per channel) for proper
    stereo passthrough — both must receive the same gain value. Sending
    both in one Props update keeps L/R atomic-ish (single message to
    PipeWire) so the operator never hears L/R drift during a duck event.

    ``node_name is None`` (e.g. the disabled mk5 TTS-duck path) is a no-op
    success — there is no node to write, and an absent duck must never be
    treated as a write failure (which would force fail-open on the music bed).
    """
    if node_name is None:
        return MixerGainWriteResult(ok=True)
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


def read_mixer_gain(node_name: str | None) -> MixerGainReadback:
    """Read actual `duck_l/r:Gain 1` from the PipeWire filter-chain node.

    ``node_name is None`` (disabled TTS-duck path) reports unity so the
    inert duck never produces a readback mismatch / blocker.
    """
    if node_name is None:
        return MixerGainReadback(ok=True, left=1.0, right=1.0)
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

    @property
    def is_hot(self) -> bool:
        """Instantaneously at/above the release threshold.

        Distinguishes a genuinely sounding source from one merely latched
        by hysteresis/hold-open (a handoff tail or syllable gap).
        Hysteresis (`is_active`) decides WHETHER a source ducks; hotness
        decides whether concurrent sources STACK in the dB-domain
        composition (see `agents/audio_ducker/handoff.py`).
        """
        return self.last_error is None and self.last_rms_dbfs >= TRIGGER_OFF_DBFS

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
    """Read the live mk5 operator-mic node (hapax-mic-rode-capture, 2ch FL/FR),
    fold to mono, feed the envelope.

    The retired L-12 path read a 14ch multichannel node and sliced AUX4; the mk5
    Rode lands as a 2ch filter-chain (mono source duplicated FL/FR), so there is
    no channel-isolation slice — just average the two channels.
    """
    proc = _spawn_capture(RODE_CAPTURE_NODE, RODE_CHANNELS, "s16")
    bytes_per_frame = 2 * RODE_CHANNELS  # s16 = 2 bytes/sample
    chunk_bytes = RMS_WINDOW_SAMPLES * bytes_per_frame
    log.info("Rode capture started (target=%s, %dch)", RODE_CAPTURE_NODE, RODE_CHANNELS)
    try:
        while not stop.is_set():
            assert proc.stdout is not None
            buf = _read_aligned(proc.stdout, chunk_bytes, bytes_per_frame)
            if not buf:
                continue
            arr = np.frombuffer(buf, dtype=np.int16).reshape(-1, RODE_CHANNELS)
            mono = arr.astype(np.float64).mean(axis=1) / (2**15)
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
    """Per-mixer current vs target gain (linear) with ramp.

    ``node`` is ``None`` for a disabled duck path (e.g. the mk5 TTS duck, which
    has no software gain node): all writes/readbacks no-op at unity.
    """

    node: str | None
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
    segment_active: bool = False,
    allow_tts_into_broadcast: bool = True,
) -> tuple[float, float]:
    """Return (music_target_gain, tts_target_gain) given trigger states.

    Music: concurrent triggers COMPOSE IN dB DOMAIN (sum of attenuations,
    clamped MAX_TOTAL_ATTEN_DB — the voice-p2-duck-handoff call-site swap
    of shared/audio_duck_compose; previously min() of linear gains). Three
    triggers engage the music bed:
      - operator voice (pre-wet Rode) → -12 dB (priority);
      - TTS present on the broadcast chain → -8 dB;
      - a live hosting SEGMENT (active-segment.json subscription) → -8 dB, held
        for the whole spoken span. A segment is the same content class as TTS, so
        it reuses the TTS depth — NO new dB and NO per-role table (no-presets).
    TTS: only Rode triggers the TTS duck (TTS doesn't duck itself).

    This boolean view treats every active trigger as hot (genuine
    concurrency). The daemon main loop passes the finer hot/latched
    envelope split to ``music_duck_triggers`` directly, so handoff tails
    sustain rather than stack — see `agents/audio_ducker/handoff.py`.

    ``allow_tts_into_broadcast`` is the working-mode coupling: when fortress mode
    disables ``duck_role_assistant_into_broadcast``, the TTS trigger no longer
    drives the music duck (only operator voice does). The hosting-segment hold is
    governed by the same coupling (a segment IS broadcast TTS content).
    Operator-voice ducking is unaffected — the operator IS the broadcast voice and
    always takes priority.
    """
    triggers = music_duck_triggers(
        rode_active,
        rode_active,
        tts_active,
        tts_active,
        segment_active=segment_active,
        allow_tts_into_broadcast=allow_tts_into_broadcast,
    )
    music = amplitude_from_db(compose_duck_target_db(triggers))
    tts = TTS_DUCK_OPERATOR if rode_active else UNITY
    return music, tts


# Hosting-segment subscription (AC#2 hosting-mode hold-open). programme_loop
# writes /dev/shm/hapax-compositor/active-segment.json at ~1 Hz while a paced
# hosting segment is live and UNLINKS it at segment end / when the active role
# isn't a segmented hosting role. So a FRESH file with a non-empty programme_id
# means "a hosting segment is currently live" — hold the music bed ducked for the
# whole span. This is a SUBSCRIPTION, not a hold timer: the hold lasts exactly as
# long as the producer keeps rewriting the file.
SEGMENT_STATE_PATH = Path("/dev/shm/hapax-compositor/active-segment.json")
# Staleness bound (a fail-open safety threshold, NOT a duck duration): >= 3x the
# 1 Hz producer cadence so a single skipped rewrite doesn't falsely release.
SEGMENT_FRESH_S = 3.0


def read_segment_active(
    path: Path = SEGMENT_STATE_PATH,
    *,
    now_s: float | None = None,
) -> bool:
    """True iff a paced hosting segment is currently live (hold the bed ducked).

    Release is producer-driven: the instant programme_loop unlinks the file at
    segment end, the next read returns False and the normal 400 ms release ramp
    recovers the bed. Fail-OPEN on any fault (missing / stale / corrupt /
    non-dict / no programme_id) → no hold, never a silenced bed.
    """
    current_s = time.time() if now_s is None else now_s
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False
    if current_s - mtime > SEGMENT_FRESH_S:
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    programme_id = data.get("programme_id")
    return isinstance(programme_id, str) and bool(programme_id)


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


GainWriter = Callable[[str | None, float], MixerGainWriteResult]
GainReader = Callable[[str | None], MixerGainReadback]


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
    handoff: HandoffHold | None = None,
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
        # Handoff anti-pump state (voice-p2-duck-handoff): bench/monitor
        # visibility into whether a release is currently being held.
        "duck_handoff": (
            None
            if handoff is None
            else {
                "holding": handoff.is_holding,
                "held_db": handoff.held_db,
                "hold_ms": handoff.hold_ms,
            }
        ),
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
    handoff = HandoffHold()

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
                # Fail-open drops the handoff hold too: a blocker forces
                # unity NOW, never after a hold window.
                handoff.reset()
                music_target, tts_target = UNITY, UNITY
            else:
                segment_active = read_segment_active(now_s=now_s)
                triggers = music_duck_triggers(
                    rode_state.is_active,
                    rode_state.is_hot,
                    tts_state.is_active,
                    tts_state.is_hot,
                    segment_active=segment_active,
                    allow_tts_into_broadcast=allow_tts_broadcast,
                )
                composed_db = compose_duck_target_db(triggers)
                music_target = amplitude_from_db(handoff.apply(composed_db, now_ms))
                tts_target = TTS_DUCK_OPERATOR if rode_state.is_active else UNITY
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
                handoff=handoff,
                now_s=now_s,
                now_ms=now_ms,
            )
            time.sleep(TICK_SLEEP_S)
    finally:
        fail_safe()

    return 0


if __name__ == "__main__":
    sys.exit(main())

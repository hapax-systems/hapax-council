"""Vinyl-into-Evil-Pet broadcast safety detector.

Reads the L-12 multitrack capture and correlates simultaneous activity
on AUX5 (Evil Pet return on CH6) and AUX8/9 (Korg Handytraxx vinyl L/R).
When sustained simultaneous activity exceeds the dwell threshold, emits a
high-priority ntfy notification + impingement so the operator can drop
the AUX-B send before YouTube ContentID fires.

Read-only: never modifies the broadcast graph.

Per `docs/governance/evil-pet-broadcast-source-policy.md`.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess  # noqa: S404 — pw-cat invocation is the only way to read PipeWire from Python
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from agents._notify import send_notification
from shared.impingement import Impingement, ImpingementType

log = logging.getLogger("audio_safety.vinyl_pet")

# ── Tunable constants (env-overridable) ──────────────────────────────────────

DEFAULT_L12_TARGET = (
    "alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input"
)
DEFAULT_RMS_THRESHOLD = 0.02  # both vinyl AND evilpet RMS above this = "active"
DEFAULT_DWELL_S = 2.0  # both must be active for this duration → fire
DEFAULT_COOLDOWN_S = 60.0  # min seconds between alerts
DEFAULT_FRAME_MS = 100  # capture frame size
DEFAULT_CHANNELS = 14
DEFAULT_RATE = 48000
DEFAULT_AUX_EVILPET = 5  # AUX5 = CH6 Evil Pet return
DEFAULT_AUX_VINYL_L = 8  # AUX8 = CH9 Handytraxx L
DEFAULT_AUX_VINYL_R = 9  # AUX9 = CH10 Handytraxx R

DEFAULT_IMPINGEMENTS_FILE = Path("/dev/shm/hapax-dmn/impingements.jsonl")

# ── Pure DSP / decision logic (testable) ─────────────────────────────────────


def channel_rms(frame: bytes, channels: int, channel_idx: int) -> float:
    """RMS energy of a single channel from interleaved int16 PCM, 0.0-1.0.

    Frame is interleaved: [ch0_s0, ch1_s0, ..., chN_s0, ch0_s1, ...].
    """
    if not frame:
        return 0.0
    arr = np.frombuffer(frame, dtype=np.int16)
    if arr.size % channels != 0:
        # incomplete frame — drop it
        return 0.0
    arr = arr.reshape(-1, channels)
    if channel_idx >= arr.shape[1]:
        return 0.0
    samples = arr[:, channel_idx].astype(np.float32) / 32768.0
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples**2)))


def is_simultaneous_activity(vinyl_rms: float, evilpet_rms: float, threshold: float) -> bool:
    """Both vinyl AND evilpet above the activity threshold."""
    return vinyl_rms >= threshold and evilpet_rms >= threshold


def should_fire(window: deque[bool], dwell_frames: int) -> bool:
    """Trigger condition: the entire dwell window is True.

    Requires the window to be at capacity AND every entry True. This means
    the simultaneous-activity condition has held continuously for the
    full dwell duration.
    """
    if len(window) < dwell_frames:
        return False
    return all(window)


# ── Detector state machine ──────────────────────────────────────────────────


@dataclass
class DetectorConfig:
    target: str = DEFAULT_L12_TARGET
    channels: int = DEFAULT_CHANNELS
    rate: int = DEFAULT_RATE
    frame_ms: int = DEFAULT_FRAME_MS
    rms_threshold: float = DEFAULT_RMS_THRESHOLD
    dwell_s: float = DEFAULT_DWELL_S
    cooldown_s: float = DEFAULT_COOLDOWN_S
    aux_evilpet: int = DEFAULT_AUX_EVILPET
    aux_vinyl_l: int = DEFAULT_AUX_VINYL_L
    aux_vinyl_r: int = DEFAULT_AUX_VINYL_R
    impingements_file: Path = DEFAULT_IMPINGEMENTS_FILE

    @classmethod
    def from_env(cls) -> DetectorConfig:
        return cls(
            target=os.environ.get("HAPAX_AUDIO_SAFETY_L12_TARGET", DEFAULT_L12_TARGET),
            channels=int(os.environ.get("HAPAX_AUDIO_SAFETY_CHANNELS", DEFAULT_CHANNELS)),
            rate=int(os.environ.get("HAPAX_AUDIO_SAFETY_RATE", DEFAULT_RATE)),
            frame_ms=int(os.environ.get("HAPAX_AUDIO_SAFETY_FRAME_MS", DEFAULT_FRAME_MS)),
            rms_threshold=float(
                os.environ.get("HAPAX_AUDIO_SAFETY_RMS_THRESHOLD", DEFAULT_RMS_THRESHOLD)
            ),
            dwell_s=float(os.environ.get("HAPAX_AUDIO_SAFETY_DWELL_S", DEFAULT_DWELL_S)),
            cooldown_s=float(os.environ.get("HAPAX_AUDIO_SAFETY_COOLDOWN_S", DEFAULT_COOLDOWN_S)),
            aux_evilpet=int(os.environ.get("HAPAX_AUDIO_SAFETY_AUX_EVILPET", DEFAULT_AUX_EVILPET)),
            aux_vinyl_l=int(os.environ.get("HAPAX_AUDIO_SAFETY_AUX_VINYL_L", DEFAULT_AUX_VINYL_L)),
            aux_vinyl_r=int(os.environ.get("HAPAX_AUDIO_SAFETY_AUX_VINYL_R", DEFAULT_AUX_VINYL_R)),
            impingements_file=Path(
                os.environ.get(
                    "HAPAX_AUDIO_SAFETY_IMPINGEMENTS_FILE", str(DEFAULT_IMPINGEMENTS_FILE)
                )
            ),
        )

    @property
    def dwell_frames(self) -> int:
        # frame_ms ms per frame → frames per dwell_s second
        return max(1, int(round(self.dwell_s * 1000.0 / self.frame_ms)))

    @property
    def frame_bytes(self) -> int:
        # int16 = 2 bytes per sample
        samples_per_frame = int(self.rate * self.frame_ms / 1000)
        return samples_per_frame * self.channels * 2


@dataclass
class DetectorState:
    window: deque[bool]
    # -inf so the first fire always passes the cooldown check regardless of
    # whether `now` is a real epoch timestamp or a small synthetic test value.
    last_fire_ts: float = float("-inf")

    @classmethod
    def fresh(cls, dwell_frames: int) -> DetectorState:
        return cls(window=deque(maxlen=dwell_frames))

    def observe(self, simultaneous: bool) -> None:
        self.window.append(simultaneous)

    def reset_window(self) -> None:
        self.window.clear()


# ── Side-effecting outputs ──────────────────────────────────────────────────


def _build_impingement(
    *, vinyl_l_rms: float, vinyl_r_rms: float, evilpet_rms: float, threshold: float, dwell_s: float
) -> Impingement:
    return Impingement(
        timestamp=time.time(),
        source="audio.safety.vinyl_pet",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=1.0,
        content={
            "alert": "vinyl is feeding Evil Pet → broadcast",
            "vinyl_l_rms": round(vinyl_l_rms, 4),
            "vinyl_r_rms": round(vinyl_r_rms, 4),
            "evilpet_rms": round(evilpet_rms, 4),
            "threshold": threshold,
            "dwell_s": dwell_s,
        },
        context={"policy": "docs/governance/evil-pet-broadcast-source-policy.md"},
    )


def fire_alert(
    *,
    config: DetectorConfig,
    vinyl_l_rms: float,
    vinyl_r_rms: float,
    evilpet_rms: float,
    notifier=send_notification,
) -> None:
    """Emit ntfy + impingement. Best-effort; never raises."""
    title = "Broadcast safety: vinyl in Evil Pet loop"
    message = (
        f"vinyl L={vinyl_l_rms:.3f} R={vinyl_r_rms:.3f}, "
        f"evilpet={evilpet_rms:.3f} ≥ {config.rms_threshold} for {config.dwell_s}s. "
        "Drop CH9/10 AUX-B sends or kill broadcast."
    )
    try:
        notifier(title, message, priority="high", tags=["warning", "microphone"])
    except Exception:
        log.warning("ntfy delivery failed", exc_info=True)

    imp = _build_impingement(
        vinyl_l_rms=vinyl_l_rms,
        vinyl_r_rms=vinyl_r_rms,
        evilpet_rms=evilpet_rms,
        threshold=config.rms_threshold,
        dwell_s=config.dwell_s,
    )
    try:
        config.impingements_file.parent.mkdir(parents=True, exist_ok=True)
        with config.impingements_file.open("a", encoding="utf-8") as f:
            f.write(imp.model_dump_json() + "\n")
    except OSError:
        log.warning("impingement write failed for %s", config.impingements_file, exc_info=True)


# ── pw-cat process management ────────────────────────────────────────────────


def spawn_pw_cat(config: DetectorConfig) -> subprocess.Popen[bytes]:
    """Launch pw-cat reading the L-12 multitrack source.

    Caller owns the process; must terminate on shutdown.
    """
    cmd = [
        "pw-cat",
        "--record",
        "--target",
        config.target,
        "--rate",
        str(config.rate),
        "--channels",
        str(config.channels),
        "--format",
        "s16",
        "--raw",
        "-",
    ]
    log.info("spawning: %s", " ".join(cmd))
    return subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
    )


def process_frame(
    *, frame: bytes, config: DetectorConfig, state: DetectorState, now: float
) -> tuple[bool, float, float, float]:
    """One detection step. Returns (fired, vinyl_l, vinyl_r, evilpet) RMS.

    Pure side-effect-free except for state.window mutation; firing is
    handled by the caller so the call site can be tested without ntfy.
    """
    vinyl_l = channel_rms(frame, config.channels, config.aux_vinyl_l)
    vinyl_r = channel_rms(frame, config.channels, config.aux_vinyl_r)
    evilpet = channel_rms(frame, config.channels, config.aux_evilpet)
    vinyl_max = max(vinyl_l, vinyl_r)
    simultaneous = is_simultaneous_activity(vinyl_max, evilpet, config.rms_threshold)
    state.observe(simultaneous)
    if not should_fire(state.window, config.dwell_frames):
        return (False, vinyl_l, vinyl_r, evilpet)
    if now - state.last_fire_ts < config.cooldown_s:
        return (False, vinyl_l, vinyl_r, evilpet)
    state.last_fire_ts = now
    state.reset_window()
    return (True, vinyl_l, vinyl_r, evilpet)


def run(config: DetectorConfig | None = None) -> int:
    """Long-running detection loop. Returns exit code on graceful stop."""
    cfg = config or DetectorConfig.from_env()
    state = DetectorState.fresh(cfg.dwell_frames)
    log.info(
        "vinyl-pet detector starting: target=%s threshold=%.3f dwell=%.1fs cooldown=%.1fs",
        cfg.target,
        cfg.rms_threshold,
        cfg.dwell_s,
        cfg.cooldown_s,
    )

    stop = {"requested": False}

    def _on_signal(signum: int, _frame) -> None:
        log.info("received signal %d; shutting down", signum)
        stop["requested"] = True

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    proc = spawn_pw_cat(cfg)
    try:
        assert proc.stdout is not None
        while not stop["requested"]:
            chunk = proc.stdout.read(cfg.frame_bytes)
            if not chunk:
                # pw-cat ended (device disappeared, etc.) — back off + restart
                log.warning("pw-cat stdout closed; restarting after 2s")
                proc.terminate()
                proc.wait(timeout=5)
                time.sleep(2)
                proc = spawn_pw_cat(cfg)
                state.reset_window()
                continue
            now = time.time()
            fired, vl, vr, ep = process_frame(frame=chunk, config=cfg, state=state, now=now)
            if fired:
                fire_alert(config=cfg, vinyl_l_rms=vl, vinyl_r_rms=vr, evilpet_rms=ep)
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            proc.kill()
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via __main__.py
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    sys.exit(run())

"""L-12 BROADCAST-V2 scene unloaded detector (audit A#6, Layer D).

The Zoom L-12's "BROADCAST-V2" scene is operator-side state — selecting it
on the device's hardware buttons routes the live mix into AUX5 (CH6
return = Evil Pet wet) so the broadcast carries the curated submix.
If the operator forgets to load BROADCAST-V2 and instead has the L-12 in
RECORDING/MONITOR/REHEARSAL scene, AUX5 falls silent regardless of
what the music sink is doing — broadcast egress goes dead while the
software stack still reports SAFE.

This probe samples ``alsa_input.usb-ZOOM_Corporation_L-12_*.multichannel-input``
channel 5 (AUX5 = Evil Pet return on CH6) RMS over a 5-second window
during music playback. If RMS stays below ``silence_threshold_dbfs``
(default -60 dBFS) for ``min_silence_s`` (default 5 minutes) while the
music sink is RUNNING, the probe:

  * emits an ``audio_l12_broadcast_scene_unloaded`` impingement event,
  * dispatches a high-priority ntfy to the operator,
  * persists state to ``/dev/shm/hapax-broadcast/l12-scene-state.json``.

Recovery is operator-only (physical button on the L-12 device) — there
is no software-side fix. The probe's job is detection + alert, not
repair.

Per audit finding A#6.
"""

from __future__ import annotations

import json
import logging
import math
import os
import subprocess  # noqa: S404 — pw-cat is the only PipeWire ingress from Python
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import numpy as np

from shared.audio_topology import TopologyDescriptor
from shared.audio_topology_inspector import (
    DEFAULT_L12_SCENE_DURATION_S,
    SceneAssertion,
    check_l12_broadcast_scene_active,
)

log = logging.getLogger("broadcast_audio_health.l12_scene_probe")


# ── Defaults (env-overridable for testing) ───────────────────────────────────

DEFAULT_L12_TARGET: Final[str] = (
    "alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input"
)
DEFAULT_AUX5_CHANNEL_INDEX: Final[int] = 4  # 0-based: AUX5 maps to channel 5 / index 4
DEFAULT_CHANNELS: Final[int] = 14
DEFAULT_RATE: Final[int] = 48000
DEFAULT_SAMPLE_WINDOW_S: Final[float] = 5.0
DEFAULT_SILENCE_THRESHOLD_DBFS: Final[float] = -60.0
DEFAULT_MIN_SILENCE_S: Final[float] = 300.0  # 5 minutes
DEFAULT_STATE_PATH: Final[Path] = Path("/dev/shm/hapax-broadcast/l12-scene-state.json")
DEFAULT_L12_SCENE_CHECK_STATE_PATH: Final[Path] = Path(
    "/dev/shm/hapax-broadcast/l12-scene-check-state.json"
)
DEFAULT_IMPINGEMENTS_FILE: Final[Path] = Path("/dev/shm/hapax-dmn/impingements.jsonl")
DEFAULT_MUSIC_SINK_NAME: Final[str] = "hapax-music-loudnorm"
RUNBOOK_ANCHOR: Final[str] = "docs/runbooks/audio-incidents.md#l12-scene-unloaded"

EVENT_NAME: Final[str] = "audio_l12_broadcast_scene_unloaded"
SceneCheckRunner = Callable[[TopologyDescriptor, float], SceneAssertion]


# ── Pure DSP helpers (testable without pw-cat) ───────────────────────────────


def channel_rms_dbfs(
    pcm_int16: bytes | np.ndarray,
    *,
    channels: int,
    channel_index: int,
) -> float:
    """RMS of one channel of interleaved int16 PCM, in dBFS.

    Returns ``-inf`` for completely silent buffers. Tolerates short
    buffers by truncating to a whole-frame multiple. Bytes input is
    converted via ``np.frombuffer``; ndarray input is treated as
    already-int16-shaped 1-D interleaved.
    """
    if isinstance(pcm_int16, bytes):
        if not pcm_int16:
            return float("-inf")
        arr = np.frombuffer(pcm_int16, dtype=np.int16)
    else:
        arr = pcm_int16
    if arr.size == 0:
        return float("-inf")
    truncate_to = (arr.size // channels) * channels
    if truncate_to == 0:
        return float("-inf")
    arr = arr[:truncate_to].reshape(-1, channels)
    if channel_index >= arr.shape[1]:
        return float("-inf")
    samples = arr[:, channel_index].astype(np.float32) / 32768.0
    if samples.size == 0:
        return float("-inf")
    rms = float(np.sqrt(np.mean(samples**2)))
    if rms <= 1e-12:
        return float("-inf")
    return 20.0 * math.log10(rms)


# ── Probe state machine (pure logic, exercised by tests) ─────────────────────


@dataclass
class L12SceneProbeConfig:
    """Tunable knobs for the probe."""

    target: str = DEFAULT_L12_TARGET
    channels: int = DEFAULT_CHANNELS
    rate: int = DEFAULT_RATE
    sample_window_s: float = DEFAULT_SAMPLE_WINDOW_S
    silence_threshold_dbfs: float = DEFAULT_SILENCE_THRESHOLD_DBFS
    min_silence_s: float = DEFAULT_MIN_SILENCE_S
    aux5_channel_index: int = DEFAULT_AUX5_CHANNEL_INDEX
    state_path: Path = field(default_factory=lambda: DEFAULT_STATE_PATH)
    impingements_file: Path = field(default_factory=lambda: DEFAULT_IMPINGEMENTS_FILE)
    music_sink_name: str = DEFAULT_MUSIC_SINK_NAME

    @classmethod
    def from_env(cls) -> L12SceneProbeConfig:
        return cls(
            target=os.environ.get("HAPAX_L12_SCENE_TARGET", DEFAULT_L12_TARGET),
            channels=int(os.environ.get("HAPAX_L12_SCENE_CHANNELS", DEFAULT_CHANNELS)),
            rate=int(os.environ.get("HAPAX_L12_SCENE_RATE", DEFAULT_RATE)),
            sample_window_s=float(
                os.environ.get("HAPAX_L12_SCENE_WINDOW_S", DEFAULT_SAMPLE_WINDOW_S)
            ),
            silence_threshold_dbfs=float(
                os.environ.get("HAPAX_L12_SCENE_SILENCE_DBFS", DEFAULT_SILENCE_THRESHOLD_DBFS)
            ),
            min_silence_s=float(
                os.environ.get("HAPAX_L12_SCENE_MIN_SILENCE_S", DEFAULT_MIN_SILENCE_S)
            ),
            aux5_channel_index=int(
                os.environ.get("HAPAX_L12_SCENE_AUX5_INDEX", DEFAULT_AUX5_CHANNEL_INDEX)
            ),
            state_path=Path(os.environ.get("HAPAX_L12_SCENE_STATE_PATH", str(DEFAULT_STATE_PATH))),
            impingements_file=Path(
                os.environ.get("HAPAX_L12_SCENE_IMPINGEMENTS", str(DEFAULT_IMPINGEMENTS_FILE))
            ),
            music_sink_name=os.environ.get("HAPAX_L12_SCENE_MUSIC_SINK", DEFAULT_MUSIC_SINK_NAME),
        )


@dataclass
class L12SceneProbeState:
    """Persisted between probe ticks via ``state_path``."""

    silent_since: float | None = None
    last_alert_at: float | None = None
    last_aux5_dbfs: float | None = None
    last_music_running: bool | None = None
    last_checked_at: float | None = None
    alert_active: bool = False

    @classmethod
    def from_dict(cls, raw: dict | None) -> L12SceneProbeState:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            silent_since=raw.get("silent_since"),
            last_alert_at=raw.get("last_alert_at"),
            last_aux5_dbfs=raw.get("last_aux5_dbfs"),
            last_music_running=raw.get("last_music_running"),
            last_checked_at=raw.get("last_checked_at"),
            alert_active=bool(raw.get("alert_active", False)),
        )

    def to_dict(self) -> dict:
        return {
            "silent_since": self.silent_since,
            "last_alert_at": self.last_alert_at,
            "last_aux5_dbfs": self.last_aux5_dbfs,
            "last_music_running": self.last_music_running,
            "last_checked_at": self.last_checked_at,
            "alert_active": bool(self.alert_active),
        }


@dataclass
class ProbeOutcome:
    """One probe tick's decision."""

    aux5_dbfs: float
    music_running: bool
    silent_for_s: float
    fired: bool
    state_changed: bool


@dataclass
class L12SceneCheckRotationState:
    """Persisted state for the 5-minute full scene assertion rotation."""

    last_checked_at: float | None = None
    last_ok: bool | None = None
    last_status: str = "never"
    last_alert_at: float | None = None

    @classmethod
    def from_dict(cls, raw: dict | None) -> L12SceneCheckRotationState:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            last_checked_at=raw.get("last_checked_at"),
            last_ok=raw.get("last_ok"),
            last_status=str(raw.get("last_status", "never")),
            last_alert_at=raw.get("last_alert_at"),
        )

    def to_dict(self) -> dict:
        return {
            "last_checked_at": self.last_checked_at,
            "last_ok": self.last_ok,
            "last_status": self.last_status,
            "last_alert_at": self.last_alert_at,
        }


@dataclass(frozen=True)
class L12SceneCheckRotationOutcome:
    """One full-scene-check rotation decision."""

    status: str
    due: bool
    ran: bool
    scene_ok: bool | None = None
    alerted: bool = False
    assertion: SceneAssertion | None = None


def evaluate_tick(
    *,
    aux5_dbfs: float,
    music_running: bool,
    now: float,
    state: L12SceneProbeState,
    config: L12SceneProbeConfig,
) -> ProbeOutcome:
    """Pure decision: should this tick fire the alert?

    - When music is NOT running, the silence-window state is reset; the
      probe only counts silence-during-music as evidence of an unloaded
      BROADCAST scene.
    - When music IS running and AUX5 is below threshold, accumulate
      silence: stamp ``silent_since`` on the first symptomatic tick,
      compute elapsed silence on subsequent ticks.
    - Fire the alert exactly once when silence exceeds ``min_silence_s``;
      stays in alert state until AUX5 returns above threshold (operator
      loaded BROADCAST). Re-arms the next time the sequence repeats.
    """
    is_silent = aux5_dbfs < config.silence_threshold_dbfs
    state_changed = False

    if not music_running:
        # No music = no signal expected on AUX5. Don't accumulate.
        if state.silent_since is not None or state.alert_active:
            state_changed = True
        state.silent_since = None
        state.alert_active = False
        elapsed = 0.0
    elif is_silent:
        if state.silent_since is None:
            state.silent_since = now
            state_changed = True
        elapsed = max(0.0, now - state.silent_since)
    else:
        # Signal present — clear any silence accumulation.
        if state.silent_since is not None or state.alert_active:
            state_changed = True
        state.silent_since = None
        state.alert_active = False
        elapsed = 0.0

    fired = False
    if (
        music_running
        and is_silent
        and state.silent_since is not None
        and (now - state.silent_since) >= config.min_silence_s
        and not state.alert_active
    ):
        fired = True
        state.alert_active = True
        state.last_alert_at = now
        state_changed = True

    state.last_aux5_dbfs = aux5_dbfs
    state.last_music_running = music_running
    state.last_checked_at = now

    return ProbeOutcome(
        aux5_dbfs=aux5_dbfs,
        music_running=music_running,
        silent_for_s=elapsed,
        fired=fired,
        state_changed=state_changed,
    )


# ── State persistence (atomic) ───────────────────────────────────────────────


def load_state(path: Path) -> L12SceneProbeState:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return L12SceneProbeState()
    return L12SceneProbeState.from_dict(raw)


def save_state(path: Path, state: L12SceneProbeState) -> None:
    payload = state.to_dict()
    payload["updated_at"] = (
        datetime.fromtimestamp(time.time(), tz=UTC).isoformat().replace("+00:00", "Z")
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.warning("l12 scene state write failed for %s", path, exc_info=True)


def load_scene_check_rotation_state(path: Path) -> L12SceneCheckRotationState:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return L12SceneCheckRotationState()
    return L12SceneCheckRotationState.from_dict(raw)


def save_scene_check_rotation_state(
    path: Path,
    state: L12SceneCheckRotationState,
) -> None:
    payload = state.to_dict()
    payload["updated_at"] = (
        datetime.fromtimestamp(time.time(), tz=UTC).isoformat().replace("+00:00", "Z")
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.warning("l12 scene check state write failed for %s", path, exc_info=True)


# ── Side-effecting outputs ───────────────────────────────────────────────────


def write_impingement(
    path: Path,
    *,
    aux5_dbfs: float,
    silent_for_s: float,
    config: L12SceneProbeConfig,
) -> None:
    """Best-effort impingement append. Never raises."""
    record = {
        "timestamp": time.time(),
        "source": "broadcast_audio_health.l12_scene_probe",
        "type": "absolute_threshold",
        "strength": 1.0,
        "content": {
            "alert": EVENT_NAME,
            "aux5_dbfs": round(aux5_dbfs, 2),
            "silent_for_s": round(silent_for_s, 1),
            "silence_threshold_dbfs": config.silence_threshold_dbfs,
            "min_silence_s": config.min_silence_s,
            "remediation": ("load BROADCAST-V2 scene on the L-12 hardware (operator-only)"),
            "runbook": RUNBOOK_ANCHOR,
        },
        "context": {"target": config.target},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        log.warning("impingement write failed for %s", path, exc_info=True)


def fire_ntfy_alert(
    *,
    aux5_dbfs: float,
    silent_for_s: float,
    config: L12SceneProbeConfig,
    notifier=None,
) -> None:
    """Best-effort ntfy notification. Falls back to logging only if missing."""
    if notifier is None:
        try:
            from agents._notify import send_notification

            notifier = send_notification
        except ImportError:
            log.warning("ntfy unavailable; alert not delivered")
            return
    title = "Broadcast: L-12 BROADCAST scene unloaded (expected BROADCAST-V2)"
    message = (
        f"AUX5 silent ({aux5_dbfs:.1f} dBFS) for {silent_for_s / 60.0:.1f} min "
        f"while music sink RUNNING. Load BROADCAST-V2 on the L-12 — broadcast "
        f"egress is dead until the scene is loaded (operator-only fix).\n"
        f"Runbook: {RUNBOOK_ANCHOR}"
    )
    try:
        notifier(title, message, priority="high", tags=["warning", "speaker"])
    except Exception:  # noqa: BLE001 — best-effort, never raise
        log.warning("ntfy delivery failed", exc_info=True)


def fire_l12_scene_check_ntfy_alert(
    assertion: SceneAssertion,
    *,
    notifier=None,
) -> None:
    """Best-effort ntfy for the full BROADCAST-V2 scene assertion."""
    if notifier is None:
        try:
            from agents._notify import send_notification

            notifier = send_notification
        except ImportError:
            log.warning("ntfy unavailable; scene check alert not delivered")
            return
    violations = "; ".join(assertion.violations[:3]) or "scene assertion failed"
    title = "Broadcast: L-12 BROADCAST-V2 scene NOT-OK"
    message = (
        f"{violations}\n"
        "Operator-only fix: press SCENE on the L-12 hardware, load BROADCAST-V2, "
        "then verify the OLED shows BROADCAST-V2.\n"
        f"Runbook: {RUNBOOK_ANCHOR}"
    )
    try:
        notifier(title, message, priority="high", tags=["warning", "speaker"])
    except Exception:  # noqa: BLE001 — best-effort, never raise
        log.warning("ntfy delivery failed", exc_info=True)


# ── Live probe orchestration (uses pw-cat + pactl) ───────────────────────────


def sample_aux5_rms_dbfs(
    config: L12SceneProbeConfig,
    *,
    pw_cat_runner=None,
) -> float:
    """Capture ``sample_window_s`` of audio and return AUX5 RMS in dBFS.

    ``pw_cat_runner`` is an injection point for tests; default invokes
    pw-cat as a subprocess. Returns ``-inf`` if the capture fails or
    the source is absent (no signal is treated as silent for the
    accumulation logic — that's the correct behaviour: an absent
    L-12 source is operationally identical to AUX5 cold).
    """
    if pw_cat_runner is None:
        pw_cat_runner = _default_pw_cat_runner
    try:
        pcm = pw_cat_runner(config)
    except Exception:  # noqa: BLE001 — best-effort, treat failures as silent
        log.warning("pw-cat capture failed", exc_info=True)
        return float("-inf")
    return channel_rms_dbfs(
        pcm,
        channels=config.channels,
        channel_index=config.aux5_channel_index,
    )


def _default_pw_cat_runner(config: L12SceneProbeConfig) -> bytes:
    """Run pw-cat for ``sample_window_s`` seconds and return the bytes."""
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
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        time.sleep(config.sample_window_s)
    finally:
        proc.terminate()
    try:
        out, _err = proc.communicate(timeout=2.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _err = proc.communicate()
    return out or b""


def is_music_sink_running(
    sink_name: str,
    *,
    pactl_runner=None,
) -> bool:
    """Inspect the music sink state via pactl.

    Returns True when ``pactl list sinks`` reports the sink as
    ``State: RUNNING`` (an active stream is bound and producing
    samples). Returns False on any error so the probe defers — it
    is not safe to alert the operator if the sink state cannot be
    inspected.
    """
    if pactl_runner is None:
        pactl_runner = _default_pactl_runner
    try:
        text = pactl_runner()
    except Exception:  # noqa: BLE001 — best-effort
        log.warning("pactl probe failed", exc_info=True)
        return False
    return _parse_sink_running(text, sink_name)


def _default_pactl_runner() -> str:
    proc = subprocess.run(  # noqa: S603 — fixed argv
        ["pactl", "list", "sinks"],
        capture_output=True,
        text=True,
        check=False,
        timeout=4.0,
    )
    return proc.stdout


def _parse_sink_running(text: str, sink_name: str) -> bool:
    """Find ``Name: <sink>`` then look at the next ``State:`` line.

    pactl outputs sinks as multi-line records; ``State:`` precedes
    ``Name:`` in the record. We collect the State seen most recently,
    then when we see Name: <sink_name> we know that's the State of
    interest. Order is fixed in pactl output.
    """
    last_state = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("State:"):
            last_state = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Name:"):
            value = stripped.split(":", 1)[1].strip()
            if value == sink_name:
                return last_state == "RUNNING"
    return False


def run_l12_scene_check_rotation(
    *,
    descriptor_path: Path,
    state_path: Path = DEFAULT_L12_SCENE_CHECK_STATE_PATH,
    interval_s: float = 300.0,
    duration_s: float = DEFAULT_L12_SCENE_DURATION_S,
    now: float | None = None,
    music_running: bool | None = None,
    checker: SceneCheckRunner | None = None,
    notifier=None,
) -> L12SceneCheckRotationOutcome:
    """Run the full scene assertion when the 5-minute rotation is due.

    The full assertion captures the L-12 multichannel source for >=30s.
    The health timer calls this only on the rotation cadence and only
    treats failures as alertable when music is running, because the
    signal-level proof requires programme audio to be present.
    """
    current = now if now is not None else time.time()
    state = load_scene_check_rotation_state(state_path)
    due = state.last_checked_at is None or current - state.last_checked_at >= interval_s
    if not due:
        return L12SceneCheckRotationOutcome(status="not_due", due=False, ran=False)

    state.last_checked_at = current
    if music_running is False:
        state.last_status = "skipped_music_not_running"
        save_scene_check_rotation_state(state_path, state)
        return L12SceneCheckRotationOutcome(
            status=state.last_status,
            due=True,
            ran=False,
            scene_ok=None,
        )

    runner = checker or _default_scene_check_runner
    try:
        descriptor = TopologyDescriptor.from_yaml(descriptor_path)
        assertion = runner(descriptor, duration_s)
    except Exception as exc:  # noqa: BLE001 - alert with evidence, do not crash service
        assertion = SceneAssertion(
            ok=False,
            evidence={"descriptor": str(descriptor_path)},
            violations=(f"l12-scene-check failed: {type(exc).__name__}: {exc}",),
        )

    previous_ok = state.last_ok
    state.last_ok = assertion.ok
    state.last_status = "ok" if assertion.ok else "not-ok"
    alerted = False
    if not assertion.ok and previous_ok is not False:
        state.last_alert_at = current
        fire_l12_scene_check_ntfy_alert(assertion, notifier=notifier)
        alerted = True
    save_scene_check_rotation_state(state_path, state)

    return L12SceneCheckRotationOutcome(
        status=state.last_status,
        due=True,
        ran=True,
        scene_ok=assertion.ok,
        alerted=alerted,
        assertion=assertion,
    )


def _default_scene_check_runner(
    descriptor: TopologyDescriptor,
    duration_s: float,
) -> SceneAssertion:
    return check_l12_broadcast_scene_active(descriptor, duration_s=duration_s)


# ── Main probe entry (called from broadcast_audio_health loop) ───────────────


def probe_l12_broadcast_scene(
    *,
    config: L12SceneProbeConfig | None = None,
    now: float | None = None,
    pw_cat_runner=None,
    pactl_runner=None,
    notifier=None,
) -> ProbeOutcome:
    """One probe tick. Reads state, samples, evaluates, persists, alerts.

    This is the function the broadcast-audio-health service loop calls
    on every iteration. Stateless from the caller's perspective —
    state lives in ``config.state_path`` between calls.

    Returns the ``ProbeOutcome`` so the caller can surface it in its
    own evidence/JSON envelope.
    """
    cfg = config or L12SceneProbeConfig.from_env()
    current = now if now is not None else time.time()
    state = load_state(cfg.state_path)

    aux5_dbfs = sample_aux5_rms_dbfs(cfg, pw_cat_runner=pw_cat_runner)
    music_running = is_music_sink_running(cfg.music_sink_name, pactl_runner=pactl_runner)

    outcome = evaluate_tick(
        aux5_dbfs=aux5_dbfs,
        music_running=music_running,
        now=current,
        state=state,
        config=cfg,
    )

    save_state(cfg.state_path, state)

    if outcome.fired:
        write_impingement(
            cfg.impingements_file,
            aux5_dbfs=outcome.aux5_dbfs,
            silent_for_s=outcome.silent_for_s,
            config=cfg,
        )
        fire_ntfy_alert(
            aux5_dbfs=outcome.aux5_dbfs,
            silent_for_s=outcome.silent_for_s,
            config=cfg,
            notifier=notifier,
        )

    return outcome


__all__ = [
    "DEFAULT_AUX5_CHANNEL_INDEX",
    "DEFAULT_L12_SCENE_CHECK_STATE_PATH",
    "DEFAULT_L12_TARGET",
    "DEFAULT_MIN_SILENCE_S",
    "DEFAULT_MUSIC_SINK_NAME",
    "DEFAULT_SILENCE_THRESHOLD_DBFS",
    "EVENT_NAME",
    "L12SceneCheckRotationOutcome",
    "L12SceneCheckRotationState",
    "L12SceneProbeConfig",
    "L12SceneProbeState",
    "ProbeOutcome",
    "RUNBOOK_ANCHOR",
    "channel_rms_dbfs",
    "evaluate_tick",
    "fire_l12_scene_check_ntfy_alert",
    "fire_ntfy_alert",
    "is_music_sink_running",
    "load_scene_check_rotation_state",
    "load_state",
    "probe_l12_broadcast_scene",
    "run_l12_scene_check_rotation",
    "sample_aux5_rms_dbfs",
    "save_scene_check_rotation_state",
    "save_state",
    "write_impingement",
]

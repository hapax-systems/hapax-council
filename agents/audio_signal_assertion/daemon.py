"""Signal-flow assertion daemon — main loop.

Long-running daemon: every ``probe_interval_s`` (default 30s), probes
each named broadcast stage's ``.monitor`` port via parecord, classifies
the captured PCM, updates a hysteresis state machine, writes a
:class:`agents.audio_signal_assertion.transitions.TransitionEvent` to
ntfy on transition into a bad steady-state at the OBS-bound stage,
publishes Prometheus textfile-collector gauges, and atomically writes
a JSON snapshot to ``/dev/shm/hapax-audio/signal-flow.json`` for
observability.

Run as a Type=notify systemd user service per the project README's
"daemon recommended for sustained probes" guidance — see
``systemd/units/hapax-audio-signal-assertion.service``.

Read-only invariant: the daemon never loads PipeWire modules, never
restarts services, never modifies confs, never auto-mutes. It is a
probe + alerter, not a circuit-breaker. False-positive auto-mute is
explicitly forbidden by the operator framing.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from agents.audio_signal_assertion.classifier import (
    BAD_STEADY_STATES,
    Classification,
    ClassifierConfig,
    ProbeMeasurement,
)
from agents.audio_signal_assertion.probes import (
    DEFAULT_DURATION_S,
    DEFAULT_STAGES,
    OBS_BOUND_STAGE,
    ProbeConfig,
    ProbeResult,
    capture_and_measure,
    discover_broadcast_stages,
)
from agents.audio_signal_assertion.transitions import (
    DEFAULT_CLIPPING_SUSTAIN_S,
    DEFAULT_NOISE_SUSTAIN_S,
    DEFAULT_RECOVERY_SUSTAIN_S,
    DEFAULT_SILENCE_SUSTAIN_S,
    TransitionDetector,
    TransitionEvent,
)

log = logging.getLogger(__name__)

DEFAULT_PROBE_INTERVAL_S: float = 30.0
DEFAULT_SNAPSHOT_PATH: Path = Path("/dev/shm/hapax-audio/signal-flow.json")
DEFAULT_LIVESTREAM_FLAG_PATH: Path = Path("/dev/shm/hapax-broadcast/livestream-active")
DEFAULT_TEXTFILE_BASENAME: str = "hapax_audio_signal_health.prom"
DEFAULT_RUNBOOK_ANCHOR: str = "docs/runbooks/audio-signal-assertion.md#bad-classification-at-stage"


@dataclass
class DaemonConfig:
    """Top-level config — env-overridable for operator-runtime tuning."""

    stages: tuple[str, ...] = DEFAULT_STAGES
    probe_interval_s: float = DEFAULT_PROBE_INTERVAL_S
    snapshot_path: Path = DEFAULT_SNAPSHOT_PATH
    livestream_flag_path: Path = DEFAULT_LIVESTREAM_FLAG_PATH
    discover_stages: bool = True
    enable_ntfy: bool = True
    runbook_anchor: str = DEFAULT_RUNBOOK_ANCHOR
    obs_bound_stage: str = OBS_BOUND_STAGE
    probe_duration_s: float = DEFAULT_DURATION_S
    clipping_sustain_s: float = DEFAULT_CLIPPING_SUSTAIN_S
    noise_sustain_s: float = DEFAULT_NOISE_SUSTAIN_S
    silence_sustain_s: float = DEFAULT_SILENCE_SUSTAIN_S
    recovery_sustain_s: float = DEFAULT_RECOVERY_SUSTAIN_S

    @classmethod
    def from_env(cls) -> DaemonConfig:
        config = cls()

        def _float(env_key: str, default: float) -> float:
            raw = os.environ.get(env_key)
            if not raw:
                return default
            try:
                return float(raw)
            except ValueError:
                log.warning("%s=%r not a float; using default %s", env_key, raw, default)
                return default

        def _bool(env_key: str, default: bool) -> bool:
            raw = os.environ.get(env_key)
            if raw is None:
                return default
            return raw.strip().lower() not in {"", "0", "false", "no", "off"}

        stages_raw = os.environ.get("HAPAX_AUDIO_SIGNAL_STAGES")
        if stages_raw:
            config.stages = tuple(s.strip() for s in stages_raw.split(",") if s.strip())
        config.probe_interval_s = _float(
            "HAPAX_AUDIO_SIGNAL_PROBE_INTERVAL_S",
            config.probe_interval_s,
        )
        config.probe_duration_s = _float(
            "HAPAX_AUDIO_SIGNAL_PROBE_DURATION_S",
            config.probe_duration_s,
        )
        config.discover_stages = _bool("HAPAX_AUDIO_SIGNAL_DISCOVER_STAGES", config.discover_stages)
        config.enable_ntfy = _bool("HAPAX_AUDIO_SIGNAL_ENABLE_NTFY", config.enable_ntfy)
        config.clipping_sustain_s = _float(
            "HAPAX_AUDIO_SIGNAL_CLIPPING_SUSTAIN_S",
            config.clipping_sustain_s,
        )
        config.noise_sustain_s = _float(
            "HAPAX_AUDIO_SIGNAL_NOISE_SUSTAIN_S",
            config.noise_sustain_s,
        )
        config.silence_sustain_s = _float(
            "HAPAX_AUDIO_SIGNAL_SILENCE_SUSTAIN_S",
            config.silence_sustain_s,
        )
        config.recovery_sustain_s = _float(
            "HAPAX_AUDIO_SIGNAL_RECOVERY_SUSTAIN_S",
            config.recovery_sustain_s,
        )
        snapshot_override = os.environ.get("HAPAX_AUDIO_SIGNAL_SNAPSHOT_PATH")
        if snapshot_override:
            config.snapshot_path = Path(snapshot_override)
        livestream_override = os.environ.get("HAPAX_AUDIO_SIGNAL_LIVESTREAM_FLAG_PATH")
        if livestream_override:
            config.livestream_flag_path = Path(livestream_override)
        return config


@dataclass
class DaemonState:
    """In-memory daemon state (test-introspectable)."""

    last_probes: dict[str, ProbeResult] = field(default_factory=dict)
    last_events: list[TransitionEvent] = field(default_factory=list)
    tick_count: int = 0


# ---------------------------------------------------------------------------
# Snapshot serialization
# ---------------------------------------------------------------------------


def _measurement_to_dict(m: ProbeMeasurement) -> dict[str, float | int]:
    return {
        "rms_dbfs": round(m.rms_dbfs, 3),
        "peak_dbfs": round(m.peak_dbfs, 3),
        "crest_factor": round(m.crest_factor, 3),
        "zero_crossing_rate": round(m.zero_crossing_rate, 6),
        "sample_count": int(m.sample_count),
    }


def _probe_to_dict(probe: ProbeResult) -> dict[str, object]:
    return {
        "stage": probe.stage,
        "classification": str(probe.classification),
        "captured_at": probe.captured_at,
        "duration_s": round(probe.duration_s, 3),
        "measurement": _measurement_to_dict(probe.measurement),
        "error": probe.error,
        "ok": probe.ok,
    }


def _event_to_dict(event: TransitionEvent) -> dict[str, object]:
    return {
        "stage": event.stage,
        "new_state": str(event.new_state),
        "previous_state": str(event.previous_state),
        "detected_at": event.detected_at,
        "sustained_for_s": round(event.sustained_for_s, 3),
        "upstream_context": [
            {"stage": stage, "classification": str(cls)} for stage, cls in event.upstream_context
        ],
    }


def write_snapshot(
    snapshot_path: Path,
    *,
    config: DaemonConfig,
    state: DaemonState,
    livestream_active: bool,
    now: float,
) -> None:
    """Atomically publish the daemon's current per-stage state.

    The snapshot is the operator-readable evidence file for the
    runbook and for any downstream broadcast-audio-health consumer
    that wants to attach signal-flow context to a degraded-state
    finding.
    """

    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checked_at": now,
        "tick_count": state.tick_count,
        "livestream_active": bool(livestream_active),
        "stages": [
            _probe_to_dict(state.last_probes[stage])
            for stage in config.stages
            if stage in state.last_probes
        ],
        "recent_events": [_event_to_dict(e) for e in state.last_events[-12:]],
    }
    tmp = snapshot_path.with_name(f"{snapshot_path.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(snapshot_path)


# ---------------------------------------------------------------------------
# Prometheus textfile-collector gauge writes
# ---------------------------------------------------------------------------


def emit_metrics(
    *,
    config: DaemonConfig,
    state: DaemonState,
    livestream_active: bool,
) -> None:
    """Write per-stage classification gauges to the textfile collector.

    Emits ``hapax_audio_signal_health{stage,classification}`` as
    a 5-row family per stage (one gauge per ``Classification`` value,
    1.0 for the active class, 0.0 for the others) so existing
    Prometheus query patterns can select on classification name.
    Also emits ``hapax_audio_signal_rms_dbfs``,
    ``hapax_audio_signal_peak_dbfs``, ``hapax_audio_signal_crest_factor``,
    and ``hapax_audio_signal_livestream_active`` for low-friction
    dashboard widgets.

    Errors writing the textfile are logged + swallowed — the daemon
    keeps running so probes continue. Workstation Prometheus may
    show the metric file as stale, which is the correct signal
    that the daemon's metric writer is unhealthy.
    """

    try:
        from shared.recovery_counter_textfile import write_gauge
    except ImportError:
        log.debug("recovery_counter_textfile unavailable; skipping metrics emit")
        return

    for stage_name in config.stages:
        probe = state.last_probes.get(stage_name)
        if probe is None:
            continue
        for classification in Classification:
            try:
                write_gauge(
                    metric_name="hapax_audio_signal_health",
                    labels={
                        "stage": stage_name,
                        "classification": str(classification),
                    },
                    help_text=(
                        "Per-stage signal-flow classification "
                        "(1.0 = active class, 0.0 = inactive). "
                        "Classes: silent, tone, music_voice, noise, clipping."
                    ),
                    value=1.0 if probe.classification == classification else 0.0,
                    file_basename=DEFAULT_TEXTFILE_BASENAME,
                )
            except Exception:
                log.debug(
                    "metrics: write_gauge failed for stage=%s class=%s",
                    stage_name,
                    classification,
                    exc_info=True,
                )

        for metric, value in (
            ("hapax_audio_signal_rms_dbfs", probe.measurement.rms_dbfs),
            ("hapax_audio_signal_peak_dbfs", probe.measurement.peak_dbfs),
            ("hapax_audio_signal_crest_factor", probe.measurement.crest_factor),
            (
                "hapax_audio_signal_zero_crossing_rate",
                probe.measurement.zero_crossing_rate,
            ),
        ):
            try:
                write_gauge(
                    metric_name=metric,
                    labels={"stage": stage_name},
                    help_text=f"{metric} from audio-signal-assertion daemon.",
                    value=float(value),
                    file_basename=DEFAULT_TEXTFILE_BASENAME,
                )
            except Exception:
                log.debug(
                    "metrics: write_gauge failed for %s stage=%s", metric, stage_name, exc_info=True
                )

    try:
        write_gauge(
            metric_name="hapax_audio_signal_livestream_active",
            labels={},
            help_text=(
                "1.0 when audio-signal-assertion treats the broadcast as "
                "live (silence-on-OBS gating active); 0.0 otherwise."
            ),
            value=1.0 if livestream_active else 0.0,
            file_basename=DEFAULT_TEXTFILE_BASENAME,
        )
    except Exception:
        log.debug("metrics: write_gauge failed for livestream_active", exc_info=True)


# ---------------------------------------------------------------------------
# Livestream gating
# ---------------------------------------------------------------------------


def is_livestream_active(path: Path, *, max_age_s: float = 60.0, now: float | None = None) -> bool:
    """Read the livestream-active flag.

    The flag file is touched by external producers (the studio
    compositor lifecycle) when broadcast egress is intended. Default
    layout: an existing flag file is "active"; missing or stale
    means "off-air". This matches the project's "/dev/shm/<surface>"
    flag-file convention used elsewhere.
    """

    current = now if now is not None else time.time()
    try:
        st = path.stat()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    age = current - st.st_mtime
    if age < 0:
        return True
    return age <= max_age_s


# ---------------------------------------------------------------------------
# Bad-state ntfy
# ---------------------------------------------------------------------------


def _format_event_message(event: TransitionEvent, anchor: str) -> str:
    upstream = ", ".join(f"{stage}={cls}" for stage, cls in event.upstream_context)
    if upstream:
        upstream_line = f"\nUpstream: {upstream}"
    else:
        upstream_line = ""
    return (
        f"{event.stage} → {event.new_state} (was {event.previous_state}) "
        f"sustained {event.sustained_for_s:.1f}s.{upstream_line}\n"
        f"Runbook: {anchor}"
    )


def _ntfy_event(event: TransitionEvent, *, anchor: str) -> None:
    """Page on transition into bad steady-state at the OBS-bound stage."""
    try:
        from shared.notify import send_notification
    except Exception:
        log.debug("notify import failed; skipping ntfy", exc_info=True)
        return
    title_class = str(event.new_state).replace("_", " ")
    title = f"Audio signal-flow: {event.stage} → {title_class}"
    body = _format_event_message(event, anchor)
    try:
        send_notification(
            title,
            body,
            priority="high" if event.new_state in BAD_STEADY_STATES else "default",
            tags=["warning", "audio-signal-flow"],
        )
    except Exception:
        log.warning("ntfy send_notification failed", exc_info=True)


# ---------------------------------------------------------------------------
# Tick orchestration
# ---------------------------------------------------------------------------


def run_tick(
    *,
    config: DaemonConfig,
    detector: TransitionDetector,
    state: DaemonState,
    probe_config: ProbeConfig,
    classifier_config: ClassifierConfig | None = None,
    now: float | None = None,
) -> list[TransitionEvent]:
    """Single tick: probe each stage, update detector, emit events.

    Pure with respect to detector + state — easy to test. Returns the
    list of events that fired this tick so callers can ntfy or assert.
    """

    current = now if now is not None else time.time()
    livestream_active = is_livestream_active(config.livestream_flag_path, now=current)
    fired: list[TransitionEvent] = []

    for stage_name in config.stages:
        probe = capture_and_measure(
            stage_name,
            config=probe_config,
            classifier_config=classifier_config,
            captured_at=current,
        )
        state.last_probes[stage_name] = probe
        is_obs_bound = stage_name == config.obs_bound_stage
        events = detector.record_probe(
            stage_name,
            probe.classification,
            probe.captured_at,
            duration_s=probe.duration_s,
            livestream_active=livestream_active and is_obs_bound,
        )
        for event in events:
            fired.append(event)
            state.last_events.append(event)
            if config.enable_ntfy and is_obs_bound:
                _ntfy_event(event, anchor=config.runbook_anchor)

    state.tick_count += 1
    write_snapshot(
        config.snapshot_path,
        config=config,
        state=state,
        livestream_active=livestream_active,
        now=current,
    )
    emit_metrics(
        config=config,
        state=state,
        livestream_active=livestream_active,
    )
    return fired


def run_forever(
    config: DaemonConfig,
    *,
    sleep_fn: object | None = None,
    notify_ready: object | None = None,
) -> int:
    """Production loop: probe, sleep, repeat. SIGTERM-safe.

    ``sleep_fn`` and ``notify_ready`` are injected for tests. Production
    callers leave them ``None``: ``time.sleep`` and the optional
    sd_notify ``READY=1`` / ``WATCHDOG=1`` writes are used.
    """

    sleeper = sleep_fn if sleep_fn is not None else time.sleep
    if notify_ready is not None:
        notify_fn = notify_ready
    else:
        notify_fn = _try_sd_notify

    stages = list(config.stages)
    if config.discover_stages:
        try:
            discovered = discover_broadcast_stages()
            if discovered:
                stages = list(discovered)
        except Exception:
            log.warning("stage discovery failed; using static %s", config.stages, exc_info=True)
    config.stages = tuple(stages)

    detector = TransitionDetector(
        stage_names=config.stages,
        clipping_sustain_s=config.clipping_sustain_s,
        noise_sustain_s=config.noise_sustain_s,
        silence_sustain_s=config.silence_sustain_s,
        recovery_sustain_s=config.recovery_sustain_s,
    )
    state = DaemonState()
    probe_config = ProbeConfig(duration_s=config.probe_duration_s)
    classifier_config = ClassifierConfig.from_env()

    stop = {"shutdown": False}

    def _signal_handler(signum: int, _frame: object) -> None:
        log.info("audio-signal-assertion: signal %d received, shutting down", signum)
        stop["shutdown"] = True

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    notify_fn("READY=1\nSTATUS=audio-signal-assertion: armed")

    while not stop["shutdown"]:
        tick_started = time.monotonic()
        try:
            run_tick(
                config=config,
                detector=detector,
                state=state,
                probe_config=probe_config,
                classifier_config=classifier_config,
            )
        except Exception:
            log.exception("audio-signal-assertion: tick failed (will retry)")
        notify_fn("WATCHDOG=1")

        elapsed = time.monotonic() - tick_started
        remaining = max(0.5, config.probe_interval_s - elapsed)
        # Sleep in short chunks so SIGTERM bounces out promptly.
        slept = 0.0
        while slept < remaining and not stop["shutdown"]:
            chunk = min(0.5, remaining - slept)
            sleeper(chunk)
            slept += chunk

    log.info("audio-signal-assertion: clean shutdown after %d ticks", state.tick_count)
    return 0


def _try_sd_notify(message: str) -> None:
    try:
        import sdnotify

        sdnotify.SystemdNotifier().notify(message)
    except Exception:
        log.debug("sdnotify unavailable; ignoring %r", message, exc_info=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audio-signal-assertion",
        description=__doc__,
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single probe tick and exit (debug / cron use).",
    )
    parser.add_argument(
        "--stages",
        type=str,
        default=None,
        help=("Comma-separated stage names override (default: env or static DEFAULT_STAGES)."),
    )
    parser.add_argument(
        "--snapshot-path",
        type=Path,
        default=None,
        help="Path for /dev/shm/hapax-audio/signal-flow.json override.",
    )
    parser.add_argument(
        "--probe-interval-s",
        type=float,
        default=None,
        help="Override the probe interval (default 30s).",
    )
    parser.add_argument(
        "--probe-duration-s",
        type=float,
        default=None,
        help="Override the per-probe capture duration (default 2s).",
    )
    parser.add_argument(
        "--no-ntfy",
        action="store_true",
        help="Disable ntfy on transitions (probes + metrics still fire).",
    )
    parser.add_argument(
        "--no-discover",
        action="store_true",
        help="Skip pactl-based stage discovery; use static stages only.",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print the snapshot to stdout after the (single) tick.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("HAPAX_AUDIO_SIGNAL_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    config = DaemonConfig.from_env()
    if args.stages:
        config.stages = tuple(s.strip() for s in args.stages.split(",") if s.strip())
    if args.snapshot_path:
        config.snapshot_path = args.snapshot_path
    if args.probe_interval_s is not None:
        config.probe_interval_s = args.probe_interval_s
    if args.probe_duration_s is not None:
        config.probe_duration_s = args.probe_duration_s
    if args.no_ntfy:
        config.enable_ntfy = False
    if args.no_discover:
        config.discover_stages = False

    if args.once:
        if config.discover_stages:
            try:
                discovered = discover_broadcast_stages()
                if discovered:
                    config.stages = discovered
            except Exception:
                log.warning("stage discovery failed", exc_info=True)
        detector = TransitionDetector(
            stage_names=config.stages,
            clipping_sustain_s=config.clipping_sustain_s,
            noise_sustain_s=config.noise_sustain_s,
            silence_sustain_s=config.silence_sustain_s,
            recovery_sustain_s=config.recovery_sustain_s,
        )
        state = DaemonState()
        probe_config = ProbeConfig(duration_s=config.probe_duration_s)
        run_tick(
            config=config,
            detector=detector,
            state=state,
            probe_config=probe_config,
            classifier_config=ClassifierConfig.from_env(),
        )
        if args.print:
            try:
                content = config.snapshot_path.read_text(encoding="utf-8")
            except OSError as exc:
                print(f"(snapshot unavailable: {exc})", file=sys.stderr)
                return 0
            print(content)
        return 0

    return run_forever(config)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_LIVESTREAM_FLAG_PATH",
    "DEFAULT_PROBE_INTERVAL_S",
    "DEFAULT_RUNBOOK_ANCHOR",
    "DEFAULT_SNAPSHOT_PATH",
    "DaemonConfig",
    "DaemonState",
    "emit_metrics",
    "is_livestream_active",
    "main",
    "run_forever",
    "run_tick",
    "write_snapshot",
]

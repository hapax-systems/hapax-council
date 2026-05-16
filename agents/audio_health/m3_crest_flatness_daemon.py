"""M3 Crest factor + ZCR + spectral flatness daemon.

Audio health monitor suite §3.4. Three complementary acoustic content
discriminators at 5s cadence:

- **Crest factor**: ratio of peak to RMS. Music/voice ~5+, white noise ~2.5-4.5,
  tone/drone <2.
- **Zero crossing rate (ZCR)**: fraction of consecutive samples that cross zero.
  Music <0.15, white noise ~0.5.
- **Spectral flatness**: Wiener entropy. Tonal content <0.3, noise >0.6.

Together these distinguish music/voice from format-conversion noise, feedback
oscillation, white noise, and DC drone without requiring ML classification.

Read-only invariant: never modifies PipeWire state, never mutes, never
restarts services.

Run via ``systemd/units/hapax-audio-health-crest-flatness.service``.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from agents.audio_health.m1_dimensions import compute_spectral_flatness
from agents.audio_health.probes import (
    OBS_BOUND_STAGE,
    ProbeConfig,
    capture_and_measure,
)
from agents.audio_health.service_loop import interruptible_sleep

log = logging.getLogger(__name__)

DEFAULT_STAGES: tuple[str, ...] = (
    "hapax-broadcast-master",
    "hapax-broadcast-normalized",
    "hapax-obs-broadcast-remap",
)

DEFAULT_PROBE_INTERVAL_S: float = 5.0
DEFAULT_CAPTURE_DURATION_S: float = 5.0
DEFAULT_BREACH_SUSTAIN_S: float = 10.0  # 2 consecutive 5s probes

DEFAULT_SNAPSHOT_PATH: Path = Path("/dev/shm/hapax-audio-health/crest-flatness.json")
DEFAULT_TEXTFILE_DIR: Path = Path("/var/lib/node_exporter/textfile_collector")
DEFAULT_TEXTFILE_BASENAME: str = "hapax_audio_health_crest_flatness.prom"


def compute_crest_factor(samples: np.ndarray) -> float:
    """Compute crest factor (peak / RMS ratio).

    Returns 0.0 for silent/empty input. Typical values:
    - Sine wave: ~1.414 (sqrt(2))
    - Music/voice: 5-15
    - White noise: ~3.0 (sqrt(3))
    - Square wave: 1.0
    """
    if samples.size < 2:
        return 0.0
    floats = samples.astype(np.float64, copy=False)
    rms = float(np.sqrt(np.mean(np.square(floats))))
    if rms < 1e-15:
        return 0.0
    peak = float(np.max(np.abs(floats)))
    return peak / rms


def compute_zcr(samples: np.ndarray) -> float:
    """Compute zero crossing rate.

    Fraction of consecutive samples that cross zero. Range [0.0, 1.0].
    """
    if samples.size < 2:
        return 0.0
    floats = samples.astype(np.float64, copy=False)
    crossings = int(np.sum(np.abs(np.diff(np.signbit(floats)))))
    return crossings / (len(floats) - 1)


@dataclass
class StageMeasurement:
    """Per-stage M3 measurement."""

    crest: float
    zcr: float
    spectral_flatness: float


@dataclass
class StageState:
    """Per-stage tracking state."""

    last_measurement: StageMeasurement | None = None
    prev_crest: float | None = None
    crest_drop_start: float | None = None
    flatness_breach_start: float | None = None
    crest_drop_count: int = 0
    crest_rise_count: int = 0
    flatness_noise_count: int = 0
    last_error: str | None = None
    analyzer_error_count: int = 0


@dataclass
class M3DaemonConfig:
    """Top-level config — env-overridable."""

    stages: tuple[str, ...] = DEFAULT_STAGES
    probe_interval_s: float = DEFAULT_PROBE_INTERVAL_S
    capture_duration_s: float = DEFAULT_CAPTURE_DURATION_S
    breach_sustain_s: float = DEFAULT_BREACH_SUSTAIN_S
    snapshot_path: Path = DEFAULT_SNAPSHOT_PATH
    enable_ntfy: bool = True
    # Thresholds
    crest_drop_threshold: float = 5.0  # drop from >5 to <5 = format noise
    crest_rise_threshold: float = 20.0  # rise from <10 to >20 = transient
    flatness_noise_threshold: float = 0.6  # sustained >0.6 = white noise

    @classmethod
    def from_env(cls) -> M3DaemonConfig:
        """Build from env vars."""

        def _fenv(key: str, default: float) -> float:
            raw = os.environ.get(f"HAPAX_AUDIO_HEALTH_CREST_FLATNESS_{key}")
            if raw is None:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        return cls(
            probe_interval_s=_fenv("PROBE_INTERVAL_S", DEFAULT_PROBE_INTERVAL_S),
            capture_duration_s=_fenv("CAPTURE_DURATION_S", DEFAULT_CAPTURE_DURATION_S),
            breach_sustain_s=_fenv("BREACH_SUSTAIN_S", DEFAULT_BREACH_SUSTAIN_S),
            crest_drop_threshold=_fenv("CREST_DROP_THRESHOLD", 5.0),
            crest_rise_threshold=_fenv("CREST_RISE_THRESHOLD", 20.0),
            flatness_noise_threshold=_fenv("FLATNESS_NOISE_THRESHOLD", 0.6),
        )


def _emit_textfile(
    stages: dict[str, StageState],
    config: M3DaemonConfig,
) -> None:
    """Write Prometheus textfile-collector gauge file."""
    lines: list[str] = []

    for metric, help_text, getter in [
        ("crest", "Crest factor (peak/RMS ratio)", lambda m: m.crest),
        ("zcr", "Zero crossing rate [0-1]", lambda m: m.zcr),
        (
            "spectral_flatness",
            "Spectral flatness (Wiener entropy) [0-1]",
            lambda m: m.spectral_flatness,
        ),
    ]:
        lines.append(f"# HELP hapax_audio_health_crest_flatness_{metric} {help_text}")
        lines.append(f"# TYPE hapax_audio_health_crest_flatness_{metric} gauge")
        for stage, state in stages.items():
            val = getter(state.last_measurement) if state.last_measurement else 0.0
            lines.append(f'hapax_audio_health_crest_flatness_{metric}{{stage="{stage}"}} {val:.4f}')

    for counter_name, counter_help, getter in [
        (
            "drop_below_5_count",
            "Crest factor sudden drops below 5 (format noise events)",
            lambda s: s.crest_drop_count,
        ),
        (
            "rise_above_20_count",
            "Crest factor sudden rises above 20 (transient events)",
            lambda s: s.crest_rise_count,
        ),
        (
            "flatness_noise_count",
            "Sustained spectral flatness >0.6 events (white noise)",
            lambda s: s.flatness_noise_count,
        ),
    ]:
        lines.append(f"# HELP hapax_audio_health_crest_flatness_{counter_name} {counter_help}")
        lines.append(f"# TYPE hapax_audio_health_crest_flatness_{counter_name} counter")
        for stage, state in stages.items():
            lines.append(
                f'hapax_audio_health_crest_flatness_{counter_name}{{stage="{stage}"}} {getter(state)}'
            )

    lines.extend(
        [
            "# HELP hapax_audio_health_crest_flatness_analyzer_error 1 if the last analyzer tick failed",
            "# TYPE hapax_audio_health_crest_flatness_analyzer_error gauge",
        ]
    )
    for stage, state in stages.items():
        lines.append(
            f'hapax_audio_health_crest_flatness_analyzer_error{{stage="{stage}"}} '
            f"{1.0 if state.last_error else 0.0}"
        )

    lines.extend(
        [
            "# HELP hapax_audio_health_crest_flatness_analyzer_error_count Total analyzer/probe failures",
            "# TYPE hapax_audio_health_crest_flatness_analyzer_error_count counter",
        ]
    )
    for stage, state in stages.items():
        lines.append(
            f'hapax_audio_health_crest_flatness_analyzer_error_count{{stage="{stage}"}} '
            f"{state.analyzer_error_count}"
        )

    try:
        textfile = DEFAULT_TEXTFILE_DIR / DEFAULT_TEXTFILE_BASENAME
        tmp = textfile.with_suffix(".tmp")
        textfile.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(textfile)
    except Exception:
        log.debug("textfile write failed", exc_info=True)


def _emit_snapshot(
    stages: dict[str, StageState],
    config: M3DaemonConfig,
    *,
    now: float,
) -> None:
    """Write atomic SHM snapshot."""
    payload = {
        "monitor": "crest-flatness",
        "timestamp": now,
        "stages": {},
    }
    for stage, state in stages.items():
        m = state.last_measurement
        payload["stages"][stage] = {
            "crest": m.crest if m else 0.0,
            "zcr": m.zcr if m else 0.0,
            "spectral_flatness": m.spectral_flatness if m else 0.0,
            "crest_drop_count": state.crest_drop_count,
            "crest_rise_count": state.crest_rise_count,
            "flatness_noise_count": state.flatness_noise_count,
            "analyzer_error": state.last_error,
            "analyzer_error_count": state.analyzer_error_count,
        }
    try:
        config.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = config.snapshot_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(config.snapshot_path)
    except Exception:
        log.debug("snapshot write failed", exc_info=True)


def _send_ntfy(stage: str, alert_type: str, detail: str) -> None:
    """Send desktop notification (best-effort)."""
    try:
        import subprocess

        urgency = "critical" if stage == OBS_BOUND_STAGE else "normal"
        subprocess.run(
            [
                "notify-send",
                f"--urgency={urgency}",
                "--app-name=LLM Stack",
                f"Audio: {alert_type}",
                f"{alert_type} at {stage}: {detail}",
            ],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        log.debug("notify-send failed", exc_info=True)


def _format_error(exc: BaseException | str | None) -> str:
    if exc is None:
        return "unknown analyzer failure"
    if isinstance(exc, BaseException):
        return f"{type(exc).__name__}: {exc}"
    return exc


def _mark_error(state: StageState, exc: BaseException | str | None) -> None:
    state.last_error = _format_error(exc)
    state.analyzer_error_count += 1


def _probe_stage(stage: str, state: StageState, config: M3DaemonConfig, *, now: float) -> None:
    """Run one M3 stage probe and record failures as health evidence."""

    try:
        probe_cfg = ProbeConfig(duration_s=config.capture_duration_s)
        result = capture_and_measure(f"{stage}.monitor", config=probe_cfg)
        if result is None:
            _mark_error(state, "probe returned None")
            return
        if not result.ok:
            _mark_error(state, result.error)
            return

        samples = result.samples_mono_float
        measurement = StageMeasurement(
            crest=compute_crest_factor(samples),
            zcr=compute_zcr(samples),
            spectral_flatness=compute_spectral_flatness(samples),
        )
        state.last_error = None

        # Crest drop detection (format-conversion noise entering)
        if state.prev_crest is not None and state.prev_crest > config.crest_drop_threshold:
            if measurement.crest < config.crest_drop_threshold:
                if state.crest_drop_start is None:
                    state.crest_drop_start = now
                elif (now - state.crest_drop_start) >= config.breach_sustain_s:
                    state.crest_drop_count += 1
                    if config.enable_ntfy:
                        _send_ntfy(
                            stage,
                            "Crest drop",
                            f"{state.prev_crest:.1f} → {measurement.crest:.1f}",
                        )
                    state.crest_drop_start = now
            else:
                state.crest_drop_start = None

        # Crest rise detection (transient / clipping)
        if state.prev_crest is not None and state.prev_crest < 10.0:
            if measurement.crest > config.crest_rise_threshold:
                state.crest_rise_count += 1
                if config.enable_ntfy:
                    _send_ntfy(
                        stage,
                        "Crest spike",
                        f"{state.prev_crest:.1f} → {measurement.crest:.1f}",
                    )

        # Spectral flatness sustained noise detection
        if measurement.spectral_flatness >= config.flatness_noise_threshold:
            if state.flatness_breach_start is None:
                state.flatness_breach_start = now
            elif (now - state.flatness_breach_start) >= config.breach_sustain_s:
                state.flatness_noise_count += 1
                if config.enable_ntfy:
                    _send_ntfy(
                        stage,
                        "White noise dominant",
                        f"flatness={measurement.spectral_flatness:.3f}",
                    )
                state.flatness_breach_start = now
        else:
            state.flatness_breach_start = None

        state.prev_crest = measurement.crest
        state.last_measurement = measurement
    except Exception as exc:
        _mark_error(state, exc)
        log.warning("probe tick failed for %s", stage, exc_info=True)


def run_daemon(config: M3DaemonConfig | None = None) -> None:
    """Main daemon loop."""
    cfg = config or M3DaemonConfig.from_env()

    try:
        import systemd.daemon  # type: ignore[import-untyped]

        systemd.daemon.notify("READY=1")
    except ImportError:
        pass

    shutdown = False

    def _sigterm(signum: int, frame: object) -> None:
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    states: dict[str, StageState] = {stage: StageState() for stage in cfg.stages}

    log.info(
        "M3 crest/flatness daemon started (interval=%.1fs, capture=%.1fs, stages=%s)",
        cfg.probe_interval_s,
        cfg.capture_duration_s,
        cfg.stages,
    )

    while not shutdown:
        now = time.time()

        for stage in cfg.stages:
            _probe_stage(stage, states[stage], cfg, now=now)

        _emit_textfile(states, cfg)
        _emit_snapshot(states, cfg, now=now)

        try:
            import systemd.daemon  # type: ignore[import-untyped]

            systemd.daemon.notify("WATCHDOG=1")
        except ImportError:
            pass

        elapsed = time.time() - now
        sleep_time = max(0.1, cfg.probe_interval_s - elapsed)
        interruptible_sleep(sleep_time, lambda: shutdown)

    log.info("M3 crest/flatness daemon shutting down")


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = M3DaemonConfig.from_env()

    enabled = os.environ.get("HAPAX_AUDIO_HEALTH_CREST_FLATNESS_ENABLED", "1")
    if enabled.strip().lower() in ("0", "false", "no", "off"):
        log.info("M3 daemon disabled via HAPAX_AUDIO_HEALTH_CREST_FLATNESS_ENABLED")
        sys.exit(0)

    run_daemon(config)


if __name__ == "__main__":
    main()

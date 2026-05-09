"""M2 LUFS-S rolling monitor daemon.

Audio health monitor suite §3.3. Continuous short-term (3s) LUFS-S
at each broadcast stage, emitting Prometheus textfile-collector gauges
and /dev/shm snapshots at 5s cadence. Detects:

- Out-of-band LUFS (clipping / silence) per stage
- Sustained breach (>3s) triggers ntfy

Read-only invariant: never modifies PipeWire state, never mutes,
never restarts services.

Run via ``systemd/units/hapax-audio-health-lufs-s.service``.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from agents.audio_health.m1_dimensions import compute_lufs_s
from agents.audio_health.probes import (
    OBS_BOUND_STAGE,
    ProbeConfig,
    capture_and_measure,
)
from agents.audio_health.service_loop import interruptible_sleep

log = logging.getLogger(__name__)

# Default stages to probe
DEFAULT_STAGES: tuple[str, ...] = (
    "hapax-broadcast-master",
    "hapax-obs-broadcast-remap",
)

# LUFS-S band thresholds per stage (env-overridable)
DEFAULT_BANDS: dict[str, tuple[float, float]] = {
    "hapax-broadcast-master": (-23.0, -16.0),
    "hapax-obs-broadcast-remap": (-22.0, -18.0),
}

# Probe cadence
DEFAULT_PROBE_INTERVAL_S: float = 5.0
DEFAULT_CAPTURE_DURATION_S: float = 3.0
DEFAULT_BREACH_SUSTAIN_S: float = 15.0  # 3 consecutive probes at 5s

# SHM + textfile paths
DEFAULT_SNAPSHOT_PATH: Path = Path("/dev/shm/hapax-audio-health/lufs-s.json")
DEFAULT_TEXTFILE_DIR: Path = Path("/var/lib/node_exporter/textfile_collector")
DEFAULT_TEXTFILE_BASENAME: str = "hapax_audio_health_lufs_s.prom"


@dataclass
class LufsBand:
    """Per-stage LUFS-S band."""

    low: float
    high: float


@dataclass
class StageState:
    """Per-stage tracking state."""

    last_lufs: float = -120.0
    breach_start: float | None = None
    breach_count: int = 0
    in_band: bool = True
    last_error: str | None = None
    analyzer_error_count: int = 0


@dataclass
class M2DaemonConfig:
    """Top-level config — env-overridable."""

    stages: tuple[str, ...] = DEFAULT_STAGES
    probe_interval_s: float = DEFAULT_PROBE_INTERVAL_S
    capture_duration_s: float = DEFAULT_CAPTURE_DURATION_S
    breach_sustain_s: float = DEFAULT_BREACH_SUSTAIN_S
    snapshot_path: Path = DEFAULT_SNAPSHOT_PATH
    enable_ntfy: bool = True
    bands: dict[str, LufsBand] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> M2DaemonConfig:
        """Build from env vars."""

        def _fenv(key: str, default: float) -> float:
            raw = os.environ.get(f"HAPAX_AUDIO_HEALTH_LUFS_S_{key}")
            if raw is None:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        bands: dict[str, LufsBand] = {}
        for stage, (lo, hi) in DEFAULT_BANDS.items():
            slug = stage.replace("-", "_").upper()
            bands[stage] = LufsBand(
                low=_fenv(f"BAND_{slug}_LOW", lo),
                high=_fenv(f"BAND_{slug}_HIGH", hi),
            )

        return cls(
            probe_interval_s=_fenv("PROBE_INTERVAL_S", DEFAULT_PROBE_INTERVAL_S),
            capture_duration_s=_fenv("CAPTURE_DURATION_S", DEFAULT_CAPTURE_DURATION_S),
            breach_sustain_s=_fenv("BREACH_SUSTAIN_S", DEFAULT_BREACH_SUSTAIN_S),
            bands=bands,
        )


def _emit_textfile(
    stages: dict[str, StageState],
    config: M2DaemonConfig,
) -> None:
    """Write Prometheus textfile-collector gauge file."""
    lines: list[str] = [
        "# HELP hapax_audio_health_lufs_s_value Short-term LUFS (3s EBU R128) per stage",
        "# TYPE hapax_audio_health_lufs_s_value gauge",
    ]
    for stage, state in stages.items():
        lines.append(f'hapax_audio_health_lufs_s_value{{stage="{stage}"}} {state.last_lufs:.2f}')

    lines.extend(
        [
            "# HELP hapax_audio_health_lufs_s_in_band 1 if LUFS in band, 0 if out",
            "# TYPE hapax_audio_health_lufs_s_in_band gauge",
        ]
    )
    for stage, state in stages.items():
        lines.append(
            f'hapax_audio_health_lufs_s_in_band{{stage="{stage}"}} {1.0 if state.in_band else 0.0}'
        )

    lines.extend(
        [
            "# HELP hapax_audio_health_lufs_s_breach_count Total out-of-band breach events",
            "# TYPE hapax_audio_health_lufs_s_breach_count counter",
        ]
    )
    for stage, state in stages.items():
        lines.append(
            f'hapax_audio_health_lufs_s_breach_count{{stage="{stage}"}} {state.breach_count}'
        )

    lines.extend(
        [
            "# HELP hapax_audio_health_lufs_s_analyzer_error 1 if the last analyzer tick failed",
            "# TYPE hapax_audio_health_lufs_s_analyzer_error gauge",
        ]
    )
    for stage, state in stages.items():
        lines.append(
            f'hapax_audio_health_lufs_s_analyzer_error{{stage="{stage}"}} '
            f"{1.0 if state.last_error else 0.0}"
        )

    lines.extend(
        [
            "# HELP hapax_audio_health_lufs_s_analyzer_error_count Total analyzer/probe failures",
            "# TYPE hapax_audio_health_lufs_s_analyzer_error_count counter",
        ]
    )
    for stage, state in stages.items():
        lines.append(
            f'hapax_audio_health_lufs_s_analyzer_error_count{{stage="{stage}"}} '
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
    config: M2DaemonConfig,
    *,
    now: float,
) -> None:
    """Write atomic SHM snapshot."""
    payload = {
        "monitor": "lufs-s",
        "timestamp": now,
        "stages": {
            stage: {
                "lufs_s": state.last_lufs,
                "in_band": state.in_band,
                "breach_count": state.breach_count,
                "analyzer_error": state.last_error,
                "analyzer_error_count": state.analyzer_error_count,
            }
            for stage, state in stages.items()
        },
    }
    try:
        config.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = config.snapshot_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(config.snapshot_path)
    except Exception:
        log.debug("snapshot write failed", exc_info=True)


def _send_ntfy(stage: str, lufs: float, band: LufsBand) -> None:
    """Send ntfy breach notification (best-effort)."""
    try:
        import subprocess

        direction = "above" if lufs > band.high else "below"
        msg = f"LUFS-S breach at {stage}: {lufs:.1f} dBFS ({direction} [{band.low}, {band.high}])"
        priority = "high" if stage == OBS_BOUND_STAGE else "default"
        subprocess.run(
            [
                "curl",
                "-s",
                "-d",
                msg,
                "-H",
                f"Priority: {priority}",
                "-H",
                "Tags: audio,lufs",
                "https://ntfy.sh/audio-health-lufs-s-breach",
            ],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        log.debug("ntfy send failed", exc_info=True)


def _format_error(exc: BaseException | str | None) -> str:
    if exc is None:
        return "unknown analyzer failure"
    if isinstance(exc, BaseException):
        return f"{type(exc).__name__}: {exc}"
    return exc


def _mark_error(state: StageState, exc: BaseException | str | None) -> None:
    state.last_error = _format_error(exc)
    state.analyzer_error_count += 1


def _probe_stage(stage: str, state: StageState, config: M2DaemonConfig, *, now: float) -> None:
    """Run one M2 stage probe and record failures as health evidence."""

    try:
        probe_cfg = ProbeConfig(duration_s=config.capture_duration_s)
        result = capture_and_measure(f"{stage}.monitor", config=probe_cfg)
        if result is None:
            _mark_error(state, "probe returned None")
            return
        if not result.ok:
            _mark_error(state, result.error)
            return

        lufs = compute_lufs_s(result.samples_mono_float, sample_rate=48000)
        state.last_error = None
        state.last_lufs = lufs

        band = config.bands.get(stage)
        if band is None:
            return

        state.in_band = band.low <= lufs <= band.high

        if not state.in_band:
            if state.breach_start is None:
                state.breach_start = now
            elif (now - state.breach_start) >= config.breach_sustain_s:
                state.breach_count += 1
                if config.enable_ntfy:
                    _send_ntfy(stage, lufs, band)
                state.breach_start = now
        else:
            state.breach_start = None
    except Exception as exc:
        _mark_error(state, exc)
        log.warning("probe tick failed for %s", stage, exc_info=True)


def run_daemon(config: M2DaemonConfig | None = None) -> None:
    """Main daemon loop."""
    cfg = config or M2DaemonConfig.from_env()

    # sd_notify READY
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
        "M2 LUFS-S daemon started (interval=%.1fs, capture=%.1fs, stages=%s)",
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

        # sd_notify watchdog
        try:
            import systemd.daemon  # type: ignore[import-untyped]

            systemd.daemon.notify("WATCHDOG=1")
        except ImportError:
            pass

        # Sleep until next probe
        elapsed = time.time() - now
        sleep_time = max(0.1, cfg.probe_interval_s - elapsed)
        interruptible_sleep(sleep_time, lambda: shutdown)

    log.info("M2 LUFS-S daemon shutting down")


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = M2DaemonConfig.from_env()

    enabled = os.environ.get("HAPAX_AUDIO_HEALTH_LUFS_S_ENABLED", "1")
    if enabled.strip().lower() in ("0", "false", "no", "off"):
        log.info("M2 LUFS-S daemon disabled via HAPAX_AUDIO_HEALTH_LUFS_S_ENABLED")
        sys.exit(0)

    run_daemon(config)


if __name__ == "__main__":
    main()

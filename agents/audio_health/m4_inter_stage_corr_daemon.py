"""M4 Inter-stage envelope correlation daemon.

Audio health monitor suite §3.5. Pearson correlation between consecutive
broadcast stage envelopes at 5s cadence. Detects signal loss or heavy
distortion between processing stages.

Stage pairs probed:
- broadcast-master ⇄ broadcast-normalized
- broadcast-normalized ⇄ obs-broadcast-remap

Downstream silence after upstream signal → signal lost. Low correlation
while both stages carry signal is diagnostic only: normalization, remap,
and capture-window skew can legitimately alter envelope shape without
dropping the broadcast signal.

Read-only invariant: never modifies PipeWire state.

Run via ``systemd/units/hapax-audio-health-inter-stage-corr.service``.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from agents.audio_health.m1_dimensions import compute_envelope_correlation
from agents.audio_health.probes import ProbeConfig, capture_and_measure
from agents.audio_health.service_loop import interruptible_sleep

log = logging.getLogger(__name__)

# Stage pairs to correlate
DEFAULT_STAGE_PAIRS: list[tuple[str, str]] = [
    ("hapax-broadcast-master", "hapax-broadcast-normalized"),
    ("hapax-broadcast-normalized", "hapax-obs-broadcast-remap"),
]

DEFAULT_PROBE_INTERVAL_S: float = 5.0
DEFAULT_CAPTURE_DURATION_S: float = 3.0
DEFAULT_CORRELATION_MIN: float = 0.3
DEFAULT_SILENCE_FLOOR_RMS: float = 1e-4  # skip correlation if both below this
DEFAULT_BREACH_SUSTAIN_S: float = 10.0
DEFAULT_SNAPSHOT_PATH: Path = Path("/dev/shm/hapax-audio-health/inter-stage-corr.json")
DEFAULT_TEXTFILE_DIR: Path = Path("/var/lib/node_exporter/textfile_collector")
DEFAULT_TEXTFILE_BASENAME: str = "hapax_audio_health_inter_stage_corr.prom"


@dataclass
class PairState:
    """Per-pair tracking state."""

    last_correlation: float | None = None
    breach_start: float | None = None
    breach_count: int = 0
    low_correlation_count: int = 0
    both_silent: bool = False
    last_error: str | None = None
    analyzer_error_count: int = 0


@dataclass
class M4DaemonConfig:
    """Top-level config — env-overridable."""

    stage_pairs: list[tuple[str, str]] = field(default_factory=lambda: list(DEFAULT_STAGE_PAIRS))
    probe_interval_s: float = DEFAULT_PROBE_INTERVAL_S
    capture_duration_s: float = DEFAULT_CAPTURE_DURATION_S
    correlation_min: float = DEFAULT_CORRELATION_MIN
    silence_floor_rms: float = DEFAULT_SILENCE_FLOOR_RMS
    breach_sustain_s: float = DEFAULT_BREACH_SUSTAIN_S
    snapshot_path: Path = DEFAULT_SNAPSHOT_PATH
    enable_ntfy: bool = True

    @classmethod
    def from_env(cls) -> M4DaemonConfig:
        """Build from env vars."""

        def _fenv(key: str, default: float) -> float:
            raw = os.environ.get(f"HAPAX_AUDIO_HEALTH_INTER_STAGE_CORR_{key}")
            if raw is None:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        def _benv(key: str, default: bool) -> bool:
            raw = os.environ.get(f"HAPAX_AUDIO_HEALTH_INTER_STAGE_CORR_{key}")
            if raw is None:
                return default
            return raw.strip().lower() not in {"0", "false", "no", "off", "disabled"}

        return cls(
            probe_interval_s=_fenv("PROBE_INTERVAL_S", DEFAULT_PROBE_INTERVAL_S),
            capture_duration_s=_fenv("CAPTURE_DURATION_S", DEFAULT_CAPTURE_DURATION_S),
            correlation_min=_fenv("CORRELATION_MIN", DEFAULT_CORRELATION_MIN),
            silence_floor_rms=_fenv("SILENCE_FLOOR_RMS", DEFAULT_SILENCE_FLOOR_RMS),
            breach_sustain_s=_fenv("BREACH_SUSTAIN_S", DEFAULT_BREACH_SUSTAIN_S),
            enable_ntfy=_benv("ENABLE_NTFY", True),
        )


def _pair_key(a: str, b: str) -> str:
    return f"{a}|{b}"


def _emit_textfile(pairs: dict[str, PairState]) -> None:
    """Write Prometheus textfile-collector gauge file."""
    lines = [
        "# HELP hapax_audio_health_inter_stage_corr Envelope correlation between stage pair",
        "# TYPE hapax_audio_health_inter_stage_corr gauge",
    ]
    for pair_name, state in pairs.items():
        val = state.last_correlation if state.last_correlation is not None else -1.0
        lines.append(f'hapax_audio_health_inter_stage_corr{{pair="{pair_name}"}} {val:.4f}')

    lines.extend(
        [
            "# HELP hapax_audio_health_inter_stage_corr_breach_count Signal-loss breach events",
            "# TYPE hapax_audio_health_inter_stage_corr_breach_count counter",
        ]
    )
    for pair_name, state in pairs.items():
        lines.append(
            f'hapax_audio_health_inter_stage_corr_breach_count{{pair="{pair_name}"}} '
            f"{state.breach_count}"
        )

    lines.extend(
        [
            "# HELP hapax_audio_health_inter_stage_corr_low_correlation_count "
            "Sustained low-correlation diagnostic events where both stages carried signal",
            "# TYPE hapax_audio_health_inter_stage_corr_low_correlation_count counter",
        ]
    )
    for pair_name, state in pairs.items():
        lines.append(
            f'hapax_audio_health_inter_stage_corr_low_correlation_count{{pair="{pair_name}"}} '
            f"{state.low_correlation_count}"
        )

    lines.extend(
        [
            "# HELP hapax_audio_health_inter_stage_corr_both_silent 1 if both stages silent",
            "# TYPE hapax_audio_health_inter_stage_corr_both_silent gauge",
        ]
    )
    for pair_name, state in pairs.items():
        lines.append(
            f'hapax_audio_health_inter_stage_corr_both_silent{{pair="{pair_name}"}} '
            f"{1.0 if state.both_silent else 0.0}"
        )

    lines.extend(
        [
            "# HELP hapax_audio_health_inter_stage_corr_analyzer_error 1 if the last analyzer tick failed",
            "# TYPE hapax_audio_health_inter_stage_corr_analyzer_error gauge",
        ]
    )
    for pair_name, state in pairs.items():
        lines.append(
            f'hapax_audio_health_inter_stage_corr_analyzer_error{{pair="{pair_name}"}} '
            f"{1.0 if state.last_error else 0.0}"
        )

    lines.extend(
        [
            "# HELP hapax_audio_health_inter_stage_corr_analyzer_error_count Total analyzer/probe failures",
            "# TYPE hapax_audio_health_inter_stage_corr_analyzer_error_count counter",
        ]
    )
    for pair_name, state in pairs.items():
        lines.append(
            f'hapax_audio_health_inter_stage_corr_analyzer_error_count{{pair="{pair_name}"}} '
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


def _emit_snapshot(pairs: dict[str, PairState], *, now: float, path: Path) -> None:
    """Write atomic SHM snapshot."""
    payload = {
        "monitor": "inter-stage-corr",
        "timestamp": now,
        "pairs": {
            name: {
                "correlation": s.last_correlation,
                "breach_count": s.breach_count,
                "low_correlation_count": s.low_correlation_count,
                "both_silent": s.both_silent,
                "analyzer_error": s.last_error,
                "analyzer_error_count": s.analyzer_error_count,
            }
            for name, s in pairs.items()
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        log.debug("snapshot write failed", exc_info=True)


def _send_ntfy(pair: str, correlation: float) -> None:
    """Send desktop signal-loss notification."""
    try:
        import subprocess

        subprocess.run(
            [
                "notify-send",
                "--urgency=critical",
                "--app-name=LLM Stack",
                "Audio: Signal Loss",
                f"Signal lost between {pair}: correlation={correlation:.3f}",
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


def _mark_error(state: PairState, exc: BaseException | str | None) -> None:
    state.last_error = _format_error(exc)
    state.analyzer_error_count += 1


def _is_downstream_signal_loss(rms_a: float, rms_b: float, config: M4DaemonConfig) -> bool:
    """Return whether the downstream stage is silent while upstream carries signal."""

    return rms_a >= config.silence_floor_rms and rms_b < config.silence_floor_rms


def _probe_pair(
    stage_a: str,
    stage_b: str,
    state: PairState,
    config: M4DaemonConfig,
    *,
    now: float,
) -> None:
    """Run one M4 pair probe and record failures as health evidence."""

    import numpy as np

    key = _pair_key(stage_a, stage_b)

    try:
        probe_cfg = ProbeConfig(duration_s=config.capture_duration_s)
        with ThreadPoolExecutor(max_workers=2) as pool:
            future_a = pool.submit(capture_and_measure, f"{stage_a}.monitor", config=probe_cfg)
            future_b = pool.submit(capture_and_measure, f"{stage_b}.monitor", config=probe_cfg)
            result_a = future_a.result()
            result_b = future_b.result()

        if result_a is None or result_b is None:
            _mark_error(state, "probe returned None")
            return
        if not result_a.ok:
            _mark_error(state, f"{stage_a}: {result_a.error}")
            return
        if not result_b.ok:
            _mark_error(state, f"{stage_b}: {result_b.error}")
            return

        samples_a = result_a.samples_mono_float
        samples_b = result_b.samples_mono_float

        rms_a = float(np.sqrt(np.mean(np.square(samples_a.astype(np.float64)))))
        rms_b = float(np.sqrt(np.mean(np.square(samples_b.astype(np.float64)))))

        if rms_a < config.silence_floor_rms and rms_b < config.silence_floor_rms:
            state.last_error = None
            state.both_silent = True
            state.last_correlation = None
            state.breach_start = None
            return

        state.last_error = None
        state.both_silent = False
        corr = compute_envelope_correlation(samples_a, samples_b)
        state.last_correlation = corr

        if corr < config.correlation_min:
            if state.breach_start is None:
                state.breach_start = now
            elif (now - state.breach_start) >= config.breach_sustain_s:
                if _is_downstream_signal_loss(rms_a, rms_b, config):
                    state.breach_count += 1
                    log.warning(
                        "Inter-stage downstream signal loss between %s: "
                        "corr=%.3f (rms_a=%.6f, rms_b=%.6f)",
                        key,
                        corr,
                        rms_a,
                        rms_b,
                    )
                    if config.enable_ntfy:
                        _send_ntfy(key, corr)
                else:
                    state.low_correlation_count += 1
                    log.info(
                        "Inter-stage low-correlation diagnostic between %s: "
                        "corr=%.3f (rms_a=%.6f, rms_b=%.6f)",
                        key,
                        corr,
                        rms_a,
                        rms_b,
                    )
                state.breach_start = now
        else:
            state.breach_start = None
    except Exception as exc:
        _mark_error(state, exc)
        log.warning("probe tick failed for %s", key, exc_info=True)


def run_daemon(config: M4DaemonConfig | None = None) -> None:
    """Main daemon loop."""
    cfg = config or M4DaemonConfig.from_env()

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

    pair_states: dict[str, PairState] = {_pair_key(a, b): PairState() for a, b in cfg.stage_pairs}

    log.info(
        "M4 inter-stage correlation daemon started (interval=%.1fs, pairs=%d)",
        cfg.probe_interval_s,
        len(cfg.stage_pairs),
    )

    while not shutdown:
        now = time.time()

        for stage_a, stage_b in cfg.stage_pairs:
            key = _pair_key(stage_a, stage_b)
            state = pair_states[key]
            _probe_pair(stage_a, stage_b, state, cfg, now=now)

        _emit_textfile(pair_states)
        _emit_snapshot(pair_states, now=now, path=cfg.snapshot_path)

        try:
            import systemd.daemon  # type: ignore[import-untyped]

            systemd.daemon.notify("WATCHDOG=1")
        except ImportError:
            pass

        elapsed = time.time() - now
        sleep_time = max(0.1, cfg.probe_interval_s - elapsed)
        interruptible_sleep(sleep_time, lambda: shutdown)

    log.info("M4 inter-stage correlation daemon shutting down")


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    enabled = os.environ.get("HAPAX_AUDIO_HEALTH_INTER_STAGE_CORR_ENABLED", "1")
    if enabled.strip().lower() in ("0", "false", "no", "off"):
        log.info("M4 daemon disabled")
        sys.exit(0)

    run_daemon()


if __name__ == "__main__":
    main()

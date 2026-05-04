"""Meta-monitor daemon for the audio-health suite.

Periodically checks each audio-health monitor's Prometheus textfile
mtime. If a monitor's textfile is missing or stale beyond its expected
freshness window, the meta-monitor emits ``hapax_audio_health_suite_up``
gauge = 0 and ntfys the operator.

This is the "is my observability layer running?" monitor. It does NOT
assess audio chain health — that's M1–M5's job.

Run as ``uv run python -m agents.audio_health_meta``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Default textfile collector directory — Prometheus node_exporter convention.
DEFAULT_TEXTFILE_DIR: Path = Path(
    os.environ.get(
        "HAPAX_PROM_TEXTFILE_DIR",
        "/var/lib/prometheus/node-exporter",
    )
)

# Monitored textfile basenames and their expected maximum age in seconds.
# Each audio-health monitor writes its own .prom textfile; the meta-monitor
# watches them all.
DEFAULT_MONITORS: dict[str, float] = {
    # H1 signal-flow assertion — 30s probe cycle, 90s freshness is generous.
    "hapax_audio_signal_health.prom": 90.0,
}

DEFAULT_PROBE_INTERVAL_S: float = 60.0
DEFAULT_SNAPSHOT_PATH: Path = Path("/dev/shm/hapax-audio-health/meta.json")
DEFAULT_META_TEXTFILE_BASENAME: str = "hapax_audio_health_meta.prom"


@dataclass
class MetaMonitorConfig:
    """Config — env-overridable."""

    textfile_dir: Path = DEFAULT_TEXTFILE_DIR
    monitors: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_MONITORS))
    probe_interval_s: float = DEFAULT_PROBE_INTERVAL_S
    snapshot_path: Path = DEFAULT_SNAPSHOT_PATH
    enable_ntfy: bool = True

    @classmethod
    def from_env(cls) -> MetaMonitorConfig:
        config = cls()
        textfile_dir = os.environ.get("HAPAX_PROM_TEXTFILE_DIR")
        if textfile_dir:
            config.textfile_dir = Path(textfile_dir)

        interval = os.environ.get("HAPAX_AUDIO_HEALTH_META_INTERVAL_S")
        if interval:
            try:
                config.probe_interval_s = float(interval)
            except ValueError:
                pass

        snapshot = os.environ.get("HAPAX_AUDIO_HEALTH_META_SNAPSHOT_PATH")
        if snapshot:
            config.snapshot_path = Path(snapshot)

        ntfy_raw = os.environ.get("HAPAX_AUDIO_HEALTH_META_ENABLE_NTFY")
        if ntfy_raw is not None:
            config.enable_ntfy = ntfy_raw.strip().lower() not in {"", "0", "false", "no", "off"}

        return config


@dataclass
class MonitorStatus:
    """Status of a single monitored textfile."""

    basename: str
    path: Path
    exists: bool
    mtime: float | None
    age_s: float | None
    max_age_s: float
    up: bool


def check_monitor(
    textfile_dir: Path,
    basename: str,
    max_age_s: float,
    now: float,
) -> MonitorStatus:
    """Check a single monitor's textfile freshness."""
    path = textfile_dir / basename
    try:
        st = path.stat()
        mtime = st.st_mtime
        age = now - mtime
        up = age <= max_age_s
    except FileNotFoundError:
        return MonitorStatus(
            basename=basename,
            path=path,
            exists=False,
            mtime=None,
            age_s=None,
            max_age_s=max_age_s,
            up=False,
        )
    except OSError:
        return MonitorStatus(
            basename=basename,
            path=path,
            exists=False,
            mtime=None,
            age_s=None,
            max_age_s=max_age_s,
            up=False,
        )

    return MonitorStatus(
        basename=basename,
        path=path,
        exists=True,
        mtime=mtime,
        age_s=age,
        max_age_s=max_age_s,
        up=up,
    )


def emit_meta_metrics(
    statuses: list[MonitorStatus],
    now: float,
) -> None:
    """Write suite-level gauges to the textfile collector."""
    try:
        from shared.recovery_counter_textfile import write_gauge
    except ImportError:
        log.debug("recovery_counter_textfile unavailable; skipping meta metrics")
        return

    for status in statuses:
        monitor_name = status.basename.removesuffix(".prom")
        try:
            write_gauge(
                metric_name="hapax_audio_health_suite_up",
                labels={"monitor": monitor_name},
                help_text=(
                    "1.0 if this audio-health monitor's textfile is fresh "
                    "(mtime within max_age_s); 0.0 if stale or missing."
                ),
                value=1.0 if status.up else 0.0,
                file_basename=DEFAULT_META_TEXTFILE_BASENAME,
            )
        except Exception:
            log.debug("write_gauge failed for %s", monitor_name, exc_info=True)

        freshness = status.age_s if status.age_s is not None else -1.0
        try:
            write_gauge(
                metric_name="hapax_audio_health_suite_freshness_seconds",
                labels={"monitor": monitor_name},
                help_text=(
                    "Seconds since the monitor's textfile was last written. "
                    "-1 if the file is missing."
                ),
                value=freshness,
                file_basename=DEFAULT_META_TEXTFILE_BASENAME,
            )
        except Exception:
            log.debug("write_gauge freshness failed for %s", monitor_name, exc_info=True)


def write_snapshot(
    snapshot_path: Path,
    statuses: list[MonitorStatus],
    now: float,
) -> None:
    """Atomically write a JSON snapshot for observability."""
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checked_at": now,
        "monitors": [
            {
                "basename": s.basename,
                "exists": s.exists,
                "mtime": s.mtime,
                "age_s": round(s.age_s, 3) if s.age_s is not None else None,
                "max_age_s": s.max_age_s,
                "up": s.up,
            }
            for s in statuses
        ],
        "all_up": all(s.up for s in statuses),
    }
    tmp = snapshot_path.with_name(f"{snapshot_path.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(snapshot_path)


def _ntfy_monitor_down(status: MonitorStatus) -> None:
    """Page on monitor-down."""
    try:
        from shared.notify import send_notification
    except Exception:
        log.debug("notify import failed; skipping ntfy", exc_info=True)
        return

    if status.exists:
        body = (
            f"Monitor textfile {status.basename} is stale: "
            f"age={status.age_s:.0f}s, max={status.max_age_s:.0f}s"
        )
    else:
        body = f"Monitor textfile {status.basename} is missing"

    try:
        send_notification(
            f"Audio health meta: {status.basename} DOWN",
            body,
            priority="high",
            tags=["warning", "audio-health-meta"],
        )
    except Exception:
        log.warning("ntfy failed for %s", status.basename, exc_info=True)


def _try_sd_notify(message: str) -> None:
    try:
        import sdnotify

        sdnotify.SystemdNotifier().notify(message)
    except Exception:
        log.debug("sdnotify unavailable; ignoring %r", message, exc_info=True)


def run_tick(
    config: MetaMonitorConfig,
    *,
    now: float | None = None,
    previous_up: dict[str, bool] | None = None,
) -> tuple[list[MonitorStatus], dict[str, bool]]:
    """Single tick: check all monitors, emit metrics, snapshot, ntfy on transitions."""
    current = now if now is not None else time.time()
    prev = previous_up or {}

    statuses: list[MonitorStatus] = []
    new_up: dict[str, bool] = {}

    for basename, max_age_s in config.monitors.items():
        status = check_monitor(config.textfile_dir, basename, max_age_s, current)
        statuses.append(status)
        new_up[basename] = status.up

        # Ntfy only on transition: was up (or first check) → now down.
        was_up = prev.get(basename, True)
        if was_up and not status.up and config.enable_ntfy:
            _ntfy_monitor_down(status)

    emit_meta_metrics(statuses, current)
    write_snapshot(config.snapshot_path, statuses, current)
    return statuses, new_up


def run_forever(
    config: MetaMonitorConfig,
    *,
    sleep_fn: object | None = None,
    notify_ready: object | None = None,
) -> int:
    """Production loop: check monitors, sleep, repeat."""
    sleeper = sleep_fn if sleep_fn is not None else time.sleep
    notify_fn = notify_ready if notify_ready is not None else _try_sd_notify

    stop = {"shutdown": False}

    def _signal_handler(signum: int, _frame: object) -> None:
        log.info("audio-health-meta: signal %d received, shutting down", signum)
        stop["shutdown"] = True

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    notify_fn("READY=1\nSTATUS=audio-health-meta: armed")

    previous_up: dict[str, bool] = {}
    tick_count = 0

    while not stop["shutdown"]:
        tick_started = time.monotonic()
        try:
            _, previous_up = run_tick(config, previous_up=previous_up)
            tick_count += 1
        except Exception:
            log.exception("audio-health-meta: tick failed (will retry)")
        notify_fn("WATCHDOG=1")

        elapsed = time.monotonic() - tick_started
        remaining = max(0.5, config.probe_interval_s - elapsed)
        slept = 0.0
        while slept < remaining and not stop["shutdown"]:
            chunk = min(0.5, remaining - slept)
            sleeper(chunk)
            slept += chunk

    log.info("audio-health-meta: clean shutdown after %d ticks", tick_count)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audio-health-meta",
        description="Meta-monitor for the audio-health suite.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single check tick and exit.",
    )
    parser.add_argument(
        "--probe-interval-s",
        type=float,
        default=None,
        help="Override the check interval (default 60s).",
    )
    parser.add_argument(
        "--no-ntfy",
        action="store_true",
        help="Disable ntfy on monitor-down.",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print the snapshot to stdout after the (single) tick.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("HAPAX_AUDIO_HEALTH_META_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    config = MetaMonitorConfig.from_env()
    if args.probe_interval_s is not None:
        config.probe_interval_s = args.probe_interval_s
    if args.no_ntfy:
        config.enable_ntfy = False

    if args.once:
        run_tick(config)
        if args.print:
            try:
                content = config.snapshot_path.read_text(encoding="utf-8")
            except OSError as exc:
                print(f"(snapshot unavailable: {exc})")
                return 0
            print(content)
        return 0

    return run_forever(config)


if __name__ == "__main__":
    raise SystemExit(main())

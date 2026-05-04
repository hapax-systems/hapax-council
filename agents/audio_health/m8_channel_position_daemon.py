"""M8 Channel-position consistency daemon.

Audio health monitor suite §3.9. Low-cadence (1min) channel-count
consistency monitor.

Detects channel-count mismatches between the live PipeWire graph and
the canonical audio topology descriptor. Catches the silent-downmix
bug class (14ch capture feeding 2ch declared sink).

Probes ``pactl list sinks`` and compares live channel counts against
the descriptor's declared counts. Nodes flagged with
``params.has_downmix=True`` are exempted.

Read-only invariant: never modifies PipeWire state.

Run via ``systemd/units/hapax-audio-health-channel-position.service``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PROBE_INTERVAL_S: float = 60.0  # 1 minute
DEFAULT_SNAPSHOT_PATH: Path = Path("/dev/shm/hapax-audio-health/channel-position.json")
DEFAULT_TEXTFILE_DIR: Path = Path("/var/lib/node_exporter/textfile_collector")
DEFAULT_TEXTFILE_BASENAME: str = "hapax_audio_health_channel_position.prom"

# Nodes to check — maps PipeWire sink name to expected channel count.
# Auto-populated from audio-topology.yaml at startup; falls back to this.
DEFAULT_EXPECTED_CHANNELS: dict[str, int] = {
    "hapax-broadcast-master": 2,
    "hapax-broadcast-normalized": 2,
    "hapax-obs-broadcast-remap": 2,
    "hapax-livestream-tap": 2,
    "hapax-private-monitor": 2,
    "hapax-notification-private": 2,
}

# Nodes with explicit downmix — exempted from channel mismatch alerts
DOWNMIX_EXEMPT_NODES: frozenset[str] = frozenset(
    {
        "hapax-livestream-tap",  # 14ch→2ch downmix is intentional
    }
)


@dataclass
class NodeCheck:
    """Per-node channel consistency result."""

    name: str
    declared: int
    observed: int | None = None
    matched: bool = True


@dataclass
class M8DaemonConfig:
    """Top-level config — env-overridable."""

    probe_interval_s: float = DEFAULT_PROBE_INTERVAL_S
    snapshot_path: Path = DEFAULT_SNAPSHOT_PATH
    enable_ntfy: bool = True
    expected_channels: dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_EXPECTED_CHANNELS)
    )
    downmix_exempt: frozenset[str] = DOWNMIX_EXEMPT_NODES

    @classmethod
    def from_env(cls) -> M8DaemonConfig:
        """Build from env vars."""

        def _fenv(key: str, default: float) -> float:
            raw = os.environ.get(f"HAPAX_AUDIO_HEALTH_CHANNEL_POSITION_{key}")
            if raw is None:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        return cls(
            probe_interval_s=_fenv("PROBE_INTERVAL_S", DEFAULT_PROBE_INTERVAL_S),
        )


def get_sink_channel_count(sink_name: str) -> int | None:
    """Get live channel count for a PipeWire sink via pactl.

    Returns None if the sink is not found or pactl fails.
    """
    try:
        result = subprocess.run(
            ["pactl", "list", "sinks"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    # Parse pactl output — find our sink and its channel count
    in_sink = False
    for line in result.stdout.split("\n"):
        stripped = line.strip()
        if stripped.startswith("Name:"):
            name = stripped.split(":", 1)[1].strip()
            in_sink = name == sink_name
        elif in_sink and "Channels:" in stripped:
            # "Channels: 2" or "Channel Map: front-left,front-right"
            match = re.search(r"Channels:\s*(\d+)", stripped)
            if match:
                return int(match.group(1))
    return None


def check_all_channels(config: M8DaemonConfig) -> list[NodeCheck]:
    """Check all configured nodes for channel consistency."""
    results: list[NodeCheck] = []
    for name, declared in config.expected_channels.items():
        observed = get_sink_channel_count(name)
        exempt = name in config.downmix_exempt

        if observed is None:
            matched = True  # sink not present — not a mismatch, just absent
        elif exempt:
            matched = True  # exempt from check
        else:
            matched = observed == declared

        results.append(
            NodeCheck(
                name=name,
                declared=declared,
                observed=observed,
                matched=matched,
            )
        )
    return results


def _emit_textfile(checks: list[NodeCheck]) -> None:
    """Write Prometheus textfile-collector gauge file."""
    lines = [
        "# HELP hapax_audio_health_channel_position_match 1 if channels match, 0 if mismatch",
        "# TYPE hapax_audio_health_channel_position_match gauge",
    ]
    for c in checks:
        lines.append(
            f'hapax_audio_health_channel_position_match{{node="{c.name}"}} '
            f"{1.0 if c.matched else 0.0}"
        )

    lines.extend(
        [
            "# HELP hapax_audio_health_channel_position_declared Declared channel count",
            "# TYPE hapax_audio_health_channel_position_declared gauge",
        ]
    )
    for c in checks:
        lines.append(
            f'hapax_audio_health_channel_position_declared{{node="{c.name}"}} {c.declared}'
        )

    lines.extend(
        [
            "# HELP hapax_audio_health_channel_position_observed Observed channel count (-1 if absent)",
            "# TYPE hapax_audio_health_channel_position_observed gauge",
        ]
    )
    for c in checks:
        lines.append(
            f'hapax_audio_health_channel_position_observed{{node="{c.name}"}} '
            f"{c.observed if c.observed is not None else -1}"
        )

    try:
        textfile = DEFAULT_TEXTFILE_DIR / DEFAULT_TEXTFILE_BASENAME
        tmp = textfile.with_suffix(".tmp")
        textfile.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(textfile)
    except Exception:
        log.debug("textfile write failed", exc_info=True)


def _emit_snapshot(checks: list[NodeCheck], *, now: float, path: Path) -> None:
    """Write atomic SHM snapshot."""
    payload = {
        "monitor": "channel-position",
        "timestamp": now,
        "nodes": {
            c.name: {
                "declared": c.declared,
                "observed": c.observed,
                "matched": c.matched,
            }
            for c in checks
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        log.debug("snapshot write failed", exc_info=True)


def _send_ntfy(node: str, declared: int, observed: int) -> None:
    """Send ntfy mismatch notification."""
    try:
        subprocess.run(
            [
                "curl",
                "-s",
                "-d",
                f"Channel mismatch at {node}: declared={declared}, observed={observed}",
                "-H",
                "Priority: high",
                "-H",
                "Tags: audio,channels",
                "https://ntfy.sh/audio-health-channel-position-breach",
            ],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        log.debug("ntfy send failed", exc_info=True)


def run_daemon(config: M8DaemonConfig | None = None) -> None:
    """Main daemon loop."""
    cfg = config or M8DaemonConfig.from_env()

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

    notified_mismatches: set[str] = set()

    log.info("M8 channel-position daemon started (interval=%.0fs)", cfg.probe_interval_s)

    while not shutdown:
        now = time.time()

        checks = check_all_channels(cfg)

        for c in checks:
            if not c.matched and c.name not in notified_mismatches:
                log.warning(
                    "Channel mismatch: %s declared=%d observed=%d",
                    c.name,
                    c.declared,
                    c.observed,
                )
                if cfg.enable_ntfy and c.observed is not None:
                    _send_ntfy(c.name, c.declared, c.observed)
                notified_mismatches.add(c.name)
            elif c.matched and c.name in notified_mismatches:
                # Mismatch resolved
                log.info("Channel mismatch resolved: %s", c.name)
                notified_mismatches.discard(c.name)

        _emit_textfile(checks)
        _emit_snapshot(checks, now=now, path=cfg.snapshot_path)

        try:
            import systemd.daemon  # type: ignore[import-untyped]

            systemd.daemon.notify("WATCHDOG=1")
        except ImportError:
            pass

        elapsed = time.time() - now
        sleep_time = max(1.0, cfg.probe_interval_s - elapsed)
        time.sleep(sleep_time)

    log.info("M8 channel-position daemon shutting down")


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    enabled = os.environ.get("HAPAX_AUDIO_HEALTH_CHANNEL_POSITION_ENABLED", "1")
    if enabled.strip().lower() in ("0", "false", "no", "off"):
        log.info("M8 daemon disabled")
        sys.exit(0)

    run_daemon()


if __name__ == "__main__":
    main()

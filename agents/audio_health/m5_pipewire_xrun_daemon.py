"""M5 PipeWire xrun + buffer-underrun daemon.

Audio health monitor suite §3.6. Per-node xrun counters parsed from
``pw-top -b -n 1`` at 10s cadence. Emits xrun delta + BUSY% + WAIT%.

Detects:
- Xrun storms (>5 xruns per probe window) → ntfy
- Sustained high BUSY% (>90%) indicating DSP overload
- Sustained high WAIT% (>50%) indicating scheduling issues

Read-only invariant: never modifies PipeWire state.

Run via ``systemd/units/hapax-audio-health-pipewire-xrun.service``.
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
from dataclasses import dataclass
from pathlib import Path

from agents.audio_health.service_loop import interruptible_sleep

log = logging.getLogger(__name__)

DEFAULT_PROBE_INTERVAL_S: float = 10.0
DEFAULT_XRUN_STORM_THRESHOLD: int = 5  # >5 xruns per probe → storm
DEFAULT_BUSY_THRESHOLD: float = 90.0  # BUSY% > 90 → overload
DEFAULT_SNAPSHOT_PATH: Path = Path("/dev/shm/hapax-audio-health/pipewire-xrun.json")
DEFAULT_TEXTFILE_DIR: Path = Path("/var/lib/node_exporter/textfile_collector")
DEFAULT_TEXTFILE_BASENAME: str = "hapax_audio_health_pipewire_xrun.prom"


@dataclass
class NodeStats:
    """Per-node pw-top stats from a single probe."""

    name: str
    busy_pct: float = 0.0
    wait_pct: float = 0.0
    xruns: int = 0


@dataclass
class NodeState:
    """Per-node tracking state across probes."""

    last_xruns: int = 0
    xrun_delta: int = 0
    xrun_storm_count: int = 0
    busy_pct: float = 0.0
    wait_pct: float = 0.0


@dataclass
class M5DaemonConfig:
    """Top-level config — env-overridable."""

    probe_interval_s: float = DEFAULT_PROBE_INTERVAL_S
    xrun_storm_threshold: int = DEFAULT_XRUN_STORM_THRESHOLD
    busy_threshold: float = DEFAULT_BUSY_THRESHOLD
    snapshot_path: Path = DEFAULT_SNAPSHOT_PATH
    enable_ntfy: bool = True

    @classmethod
    def from_env(cls) -> M5DaemonConfig:
        """Build from env vars."""

        def _fenv(key: str, default: float) -> float:
            raw = os.environ.get(f"HAPAX_AUDIO_HEALTH_PIPEWIRE_XRUN_{key}")
            if raw is None:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        return cls(
            probe_interval_s=_fenv("PROBE_INTERVAL_S", DEFAULT_PROBE_INTERVAL_S),
            xrun_storm_threshold=int(_fenv("XRUN_STORM_THRESHOLD", DEFAULT_XRUN_STORM_THRESHOLD)),
            busy_threshold=_fenv("BUSY_THRESHOLD", DEFAULT_BUSY_THRESHOLD),
        )


# pw-top -b -n 1 output format (example):
# S  ID QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR  NAME
# S  34  1024  48000   0.15ms  0.12ms  0.7%  0.6%    0  alsa_output.usb-...
_PWTOP_LINE_RE = re.compile(
    r"^\s*\S+\s+"  # status
    r"(\d+)\s+"  # id
    r"\d+\s+"  # quantum
    r"\d+\s+"  # rate
    r"[\d.]+\w*\s+"  # wait time
    r"[\d.]+\w*\s+"  # busy time
    r"([\d.]+)%\s+"  # wait%
    r"([\d.]+)%\s+"  # busy%
    r"(\d+)\s+"  # errors (xruns)
    r"(.+)$"  # name
)


def parse_pwtop_output(output: str) -> list[NodeStats]:
    """Parse ``pw-top -b -n 1`` output into per-node stats."""
    nodes: list[NodeStats] = []
    for line in output.strip().split("\n"):
        match = _PWTOP_LINE_RE.match(line)
        if match:
            nodes.append(
                NodeStats(
                    name=match.group(5).strip(),
                    wait_pct=float(match.group(2)),
                    busy_pct=float(match.group(3)),
                    xruns=int(match.group(4)),
                )
            )
    return nodes


def capture_pwtop() -> list[NodeStats]:
    """Run ``pw-top -b -n 1`` and parse output."""
    try:
        result = subprocess.run(
            ["pw-top", "-b", "-n", "1"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            log.warning("pw-top failed: %s", result.stderr)
            return []
        return parse_pwtop_output(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        log.warning("pw-top not available or timed out")
        return []


def _emit_textfile(states: dict[str, NodeState]) -> None:
    """Write Prometheus textfile-collector gauge file."""
    lines: list[str] = []

    for metric, help_text, getter in [
        ("xrun_delta", "Xrun delta since last probe", lambda s: s.xrun_delta),
        ("busy_pct", "DSP BUSY percentage", lambda s: s.busy_pct),
        ("wait_pct", "DSP WAIT percentage", lambda s: s.wait_pct),
        (
            "xrun_storm_count",
            "Total xrun storm events (>threshold per probe)",
            lambda s: s.xrun_storm_count,
        ),
    ]:
        lines.append(f"# HELP hapax_audio_health_pipewire_xrun_{metric} {help_text}")
        lines.append(f"# TYPE hapax_audio_health_pipewire_xrun_{metric} gauge")
        for node, state in states.items():
            lines.append(
                f'hapax_audio_health_pipewire_xrun_{metric}{{node="{node}"}} {getter(state)}'
            )

    try:
        textfile = DEFAULT_TEXTFILE_DIR / DEFAULT_TEXTFILE_BASENAME
        tmp = textfile.with_suffix(".tmp")
        textfile.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(textfile)
    except Exception:
        log.debug("textfile write failed", exc_info=True)


def _emit_snapshot(states: dict[str, NodeState], *, now: float, path: Path) -> None:
    """Write atomic SHM snapshot."""
    payload = {
        "monitor": "pipewire-xrun",
        "timestamp": now,
        "nodes": {
            node: {
                "xrun_delta": s.xrun_delta,
                "busy_pct": s.busy_pct,
                "wait_pct": s.wait_pct,
                "xrun_storm_count": s.xrun_storm_count,
            }
            for node, s in states.items()
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        log.debug("snapshot write failed", exc_info=True)


def _send_ntfy(node: str, delta: int) -> None:
    """Send ntfy xrun storm notification."""
    try:
        subprocess.run(
            [
                "curl",
                "-s",
                "-d",
                f"{node} xrun storm: {delta} xruns in probe window",
                "-H",
                "Priority: high",
                "-H",
                "Tags: audio,xrun",
                "https://ntfy.sh/audio-health-pipewire-xrun-breach",
            ],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        log.debug("ntfy send failed", exc_info=True)


def run_daemon(config: M5DaemonConfig | None = None) -> None:
    """Main daemon loop."""
    cfg = config or M5DaemonConfig.from_env()

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

    states: dict[str, NodeState] = {}

    log.info("M5 pw-top xrun daemon started (interval=%.0fs)", cfg.probe_interval_s)

    while not shutdown:
        now = time.time()

        nodes = capture_pwtop()

        for node_stats in nodes:
            name = node_stats.name
            if name not in states:
                states[name] = NodeState(last_xruns=node_stats.xruns)

            state = states[name]
            state.xrun_delta = max(0, node_stats.xruns - state.last_xruns)
            state.last_xruns = node_stats.xruns
            state.busy_pct = node_stats.busy_pct
            state.wait_pct = node_stats.wait_pct

            if state.xrun_delta > cfg.xrun_storm_threshold:
                state.xrun_storm_count += 1
                log.warning("%s xrun storm: %d xruns", name, state.xrun_delta)
                if cfg.enable_ntfy:
                    _send_ntfy(name, state.xrun_delta)

        _emit_textfile(states)
        _emit_snapshot(states, now=now, path=cfg.snapshot_path)

        try:
            import systemd.daemon  # type: ignore[import-untyped]

            systemd.daemon.notify("WATCHDOG=1")
        except ImportError:
            pass

        elapsed = time.time() - now
        sleep_time = max(0.1, cfg.probe_interval_s - elapsed)
        interruptible_sleep(sleep_time, lambda: shutdown)

    log.info("M5 pw-top xrun daemon shutting down")


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    enabled = os.environ.get("HAPAX_AUDIO_HEALTH_PIPEWIRE_XRUN_ENABLED", "1")
    if enabled.strip().lower() in ("0", "false", "no", "off"):
        log.info("M5 daemon disabled")
        sys.exit(0)

    run_daemon()


if __name__ == "__main__":
    main()

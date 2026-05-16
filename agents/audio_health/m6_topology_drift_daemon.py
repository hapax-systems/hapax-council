"""M6 Topology drift daemon — PipeWire module signature vs canonical descriptor.

Audio health monitor suite §3.7. Low-cadence (5min) topology monitor.

Detects:
- Uninvited modules appearing in the PipeWire graph
- Expected modules disappearing (silent regression)
- WirePlumber / PipeWire restart events suppress alerts for 30s

Probes ``pactl list modules short`` and compares against the canonical
audio topology descriptor (``config/audio-topology.yaml`` or
``shared/audio_topology_inspector.py``).

Read-only invariant: never loads/unloads modules, never restarts services.

Run via ``systemd/units/hapax-audio-health-topology-drift.service``.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from agents.audio_health.service_loop import interruptible_sleep

log = logging.getLogger(__name__)

# Topology-affecting module kinds to track
TOPOLOGY_MODULE_KINDS: frozenset[str] = frozenset(
    {
        "module-loopback",
        "module-null-sink",
        "module-pipe-source",
        "module-remap-sink",
        "module-remap-source",
        "module-combine-sink",
    }
)

DEFAULT_PROBE_INTERVAL_S: float = 300.0  # 5 minutes
DEFAULT_RESTART_SUPPRESS_S: float = 30.0  # suppress alerts post-restart
DEFAULT_SNAPSHOT_PATH: Path = Path("/dev/shm/hapax-audio-health/topology-drift.json")
DEFAULT_TEXTFILE_DIR: Path = Path("/var/lib/node_exporter/textfile_collector")
DEFAULT_TEXTFILE_BASENAME: str = "hapax_audio_health_topology_drift.prom"


@dataclass
class ModuleInfo:
    """Parsed module from pactl list modules short."""

    index: int
    name: str
    args: str


@dataclass
class M6DaemonConfig:
    """Top-level config — env-overridable."""

    probe_interval_s: float = DEFAULT_PROBE_INTERVAL_S
    restart_suppress_s: float = DEFAULT_RESTART_SUPPRESS_S
    snapshot_path: Path = DEFAULT_SNAPSHOT_PATH
    enable_ntfy: bool = True
    # Canonical expected modules (populated from topology descriptor or env)
    expected_module_count: int | None = None

    @classmethod
    def from_env(cls) -> M6DaemonConfig:
        """Build from env vars."""

        def _fenv(key: str, default: float) -> float:
            raw = os.environ.get(f"HAPAX_AUDIO_HEALTH_TOPOLOGY_DRIFT_{key}")
            if raw is None:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        expected = os.environ.get("HAPAX_AUDIO_HEALTH_TOPOLOGY_DRIFT_EXPECTED_MODULES")
        expected_count = int(expected) if expected and expected.isdigit() else None

        return cls(
            probe_interval_s=_fenv("PROBE_INTERVAL_S", DEFAULT_PROBE_INTERVAL_S),
            restart_suppress_s=_fenv("RESTART_SUPPRESS_S", DEFAULT_RESTART_SUPPRESS_S),
            expected_module_count=expected_count,
        )


def list_topology_modules() -> list[ModuleInfo]:
    """Parse topology-affecting modules from ``pactl list modules short``."""
    try:
        result = subprocess.run(
            ["pactl", "list", "modules", "short"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            log.warning("pactl list modules short failed: %s", result.stderr)
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        log.warning("pactl not available or timed out")
        return []

    modules: list[ModuleInfo] = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        try:
            idx = int(parts[0])
        except ValueError:
            continue
        name = parts[1]
        args = parts[2] if len(parts) > 2 else ""

        if name in TOPOLOGY_MODULE_KINDS:
            modules.append(ModuleInfo(index=idx, name=name, args=args))

    return modules


def compute_module_signature(modules: list[ModuleInfo]) -> str:
    """Compute a stable hash of the topology-affecting module set.

    Sorted by (name, args) to be independent of module load order.
    """
    entries = sorted(f"{m.name}:{m.args}" for m in modules)
    return "|".join(entries)


def check_recent_restart(suppress_s: float) -> bool:
    """Check if PipeWire or WirePlumber restarted recently.

    Returns True if restart occurred within ``suppress_s`` seconds.
    """
    try:
        for service in ("pipewire.service", "wireplumber.service"):
            result = subprocess.run(
                [
                    "systemctl",
                    "--user",
                    "show",
                    service,
                    "--property=ActiveEnterTimestampMonotonic",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if "=" in line:
                        usec_str = line.split("=", 1)[1].strip()
                        if usec_str.isdigit():
                            usec = int(usec_str)
                            age_s = (time.monotonic() * 1_000_000 - usec) / 1_000_000
                            if 0 < age_s < suppress_s:
                                log.info(
                                    "%s restarted %.1fs ago — suppressing",
                                    service,
                                    age_s,
                                )
                                return True
    except Exception:
        log.debug("restart check failed", exc_info=True)
    return False


@dataclass
class DriftState:
    """Tracking state for topology drift."""

    baseline_signature: str | None = None
    baseline_count: int = 0
    drift_events_appeared: int = 0
    drift_events_disappeared: int = 0
    last_drift_modules: list[str] = field(default_factory=list)


def _emit_textfile(state: DriftState, modules: list[ModuleInfo]) -> None:
    """Write Prometheus textfile-collector gauge file."""
    lines = [
        "# HELP hapax_audio_health_topology_modules_expected Expected topology module count",
        "# TYPE hapax_audio_health_topology_modules_expected gauge",
        f"hapax_audio_health_topology_modules_expected {state.baseline_count}",
        "# HELP hapax_audio_health_topology_modules_observed Observed topology module count",
        "# TYPE hapax_audio_health_topology_modules_observed gauge",
        f"hapax_audio_health_topology_modules_observed {len(modules)}",
        "# HELP hapax_audio_health_topology_drift Drift detected (0=aligned, 1=drift)",
        "# TYPE hapax_audio_health_topology_drift gauge",
        f"hapax_audio_health_topology_drift {1 if state.last_drift_modules else 0}",
        "# HELP hapax_audio_health_topology_drift_appeared_total Modules appeared unexpectedly",
        "# TYPE hapax_audio_health_topology_drift_appeared_total counter",
        f"hapax_audio_health_topology_drift_appeared_total {state.drift_events_appeared}",
        "# HELP hapax_audio_health_topology_drift_disappeared_total Modules disappeared",
        "# TYPE hapax_audio_health_topology_drift_disappeared_total counter",
        f"hapax_audio_health_topology_drift_disappeared_total {state.drift_events_disappeared}",
    ]
    try:
        textfile = DEFAULT_TEXTFILE_DIR / DEFAULT_TEXTFILE_BASENAME
        tmp = textfile.with_suffix(".tmp")
        textfile.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(textfile)
    except Exception:
        log.debug("textfile write failed", exc_info=True)


def _emit_snapshot(state: DriftState, modules: list[ModuleInfo], *, now: float, path: Path) -> None:
    """Write atomic SHM snapshot."""
    payload = {
        "monitor": "topology-drift",
        "timestamp": now,
        "expected_count": state.baseline_count,
        "observed_count": len(modules),
        "drift": bool(state.last_drift_modules),
        "drift_modules": state.last_drift_modules,
        "modules": [{"name": m.name, "args": m.args} for m in modules],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        log.debug("snapshot write failed", exc_info=True)


def _send_ntfy(direction: str, detail: str) -> None:
    """Send desktop notification."""
    try:
        subprocess.run(
            [
                "notify-send",
                "--urgency=normal",
                "--app-name=LLM Stack",
                "Audio: Topology Drift",
                f"Topology drift: module {direction} — {detail}",
            ],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        log.debug("notify-send failed", exc_info=True)


def run_daemon(config: M6DaemonConfig | None = None) -> None:
    """Main daemon loop."""
    cfg = config or M6DaemonConfig.from_env()

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

    state = DriftState()

    log.info("M6 topology drift daemon started (interval=%.0fs)", cfg.probe_interval_s)

    while not shutdown:
        now = time.time()

        modules = list_topology_modules()
        current_sig = compute_module_signature(modules)

        if state.baseline_signature is None:
            # First probe — establish baseline
            state.baseline_signature = current_sig
            state.baseline_count = len(modules)
            log.info("Baseline established: %d topology modules", state.baseline_count)
        else:
            if current_sig != state.baseline_signature:
                # Drift detected — check if suppressed
                if not check_recent_restart(cfg.restart_suppress_s):
                    # Determine appeared vs disappeared
                    baseline_entries = (
                        set(state.baseline_signature.split("|"))
                        if state.baseline_signature
                        else set()
                    )
                    current_entries = set(current_sig.split("|")) if current_sig else set()
                    appeared = current_entries - baseline_entries
                    disappeared = baseline_entries - current_entries

                    drift_details: list[str] = []
                    if appeared:
                        state.drift_events_appeared += len(appeared)
                        for a in appeared:
                            drift_details.append(f"+{a}")
                    if disappeared:
                        state.drift_events_disappeared += len(disappeared)
                        for d in disappeared:
                            drift_details.append(f"-{d}")

                    state.last_drift_modules = drift_details
                    log.warning("Topology drift detected: %s", drift_details)

                    if cfg.enable_ntfy and drift_details:
                        _send_ntfy(
                            "appeared" if appeared else "disappeared",
                            "; ".join(drift_details[:5]),
                        )
                else:
                    log.info("Drift detected but suppressed (recent restart)")
                    state.last_drift_modules = []
            else:
                state.last_drift_modules = []

        _emit_textfile(state, modules)
        _emit_snapshot(state, modules, now=now, path=cfg.snapshot_path)

        try:
            import systemd.daemon  # type: ignore[import-untyped]

            systemd.daemon.notify("WATCHDOG=1")
        except ImportError:
            pass

        elapsed = time.time() - now
        sleep_time = max(1.0, cfg.probe_interval_s - elapsed)
        interruptible_sleep(sleep_time, lambda: shutdown)

    log.info("M6 topology drift daemon shutting down")


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    enabled = os.environ.get("HAPAX_AUDIO_HEALTH_TOPOLOGY_DRIFT_ENABLED", "1")
    if enabled.strip().lower() in ("0", "false", "no", "off"):
        log.info("M6 daemon disabled")
        sys.exit(0)

    run_daemon()


if __name__ == "__main__":
    main()

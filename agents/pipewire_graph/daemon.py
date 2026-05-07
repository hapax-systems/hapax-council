"""Shadow-mode daemon for the audio graph SSOT.

The daemon has two loops:

* dry-run apply: compile the target graph and write a diff report to
  ``~/hapax-state/pipewire-graph/shadow-runs/{timestamp}.json``.
* egress observation: sample the OBS-bound monitor at 2 Hz and append
  health records to ``~/hapax-state/pipewire-graph/egress-health.jsonl``.

P2 is observe-only. This module never writes PipeWire or WirePlumber
configuration, never invokes ``pactl load-module``, and never enables or
starts the systemd unit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import signal
import socket
import sys
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.pipewire_graph.circuit_breaker import (
    DEFAULT_EGRESS_STAGE,
    EgressCircuitBreaker,
    EgressHealth,
    ShadowAlert,
    probe_egress_health,
)
from agents.pipewire_graph.lock import read_lock_status
from agents.pipewire_graph.metrics import PipewireGraphMetrics
from agents.pipewire_graph.safe_mute import SafeMuteRail
from shared.audio_graph import (
    AudioGraph,
    AudioGraphValidator,
    CompiledArtefacts,
    compile_descriptor,
)
from shared.notify import send_notification

log = logging.getLogger(__name__)

DEFAULT_STATE_ROOT = Path.home() / "hapax-state" / "pipewire-graph"
DEFAULT_PIPEWIRE_CONF_DIR = Path("~/.config/pipewire/pipewire.conf.d").expanduser()
DEFAULT_WIREPLUMBER_CONF_DIR = Path("~/.config/wireplumber/wireplumber.conf.d").expanduser()
DEFAULT_DRY_RUN_INTERVAL_S = 60.0
DEFAULT_METRICS_PORT = 9489


@dataclass(frozen=True)
class ShadowDaemonConfig:
    """Runtime configuration for the shadow daemon."""

    state_root: Path = DEFAULT_STATE_ROOT
    graph_descriptor_path: Path | None = None
    pipewire_conf_dir: Path = DEFAULT_PIPEWIRE_CONF_DIR
    wireplumber_conf_dir: Path = DEFAULT_WIREPLUMBER_CONF_DIR
    egress_stage: str = DEFAULT_EGRESS_STAGE
    dry_run_interval_s: float = DEFAULT_DRY_RUN_INTERVAL_S
    metrics_port: int = DEFAULT_METRICS_PORT
    metrics_addr: str = "127.0.0.1"
    enable_ntfy: bool = True
    run_once: bool = False

    @property
    def shadow_runs_dir(self) -> Path:
        return self.state_root / "shadow-runs"

    @property
    def egress_health_path(self) -> Path:
        return self.state_root / "egress-health.jsonl"

    @classmethod
    def from_env(cls) -> ShadowDaemonConfig:
        def _path(key: str) -> Path | None:
            raw = os.environ.get(key)
            return Path(raw).expanduser() if raw else None

        def _float(key: str, default: float) -> float:
            raw = os.environ.get(key)
            if not raw:
                return default
            try:
                return float(raw)
            except ValueError:
                log.warning("%s=%r is not a float; using %s", key, raw, default)
                return default

        def _int(key: str, default: int) -> int:
            raw = os.environ.get(key)
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError:
                log.warning("%s=%r is not an int; using %s", key, raw, default)
                return default

        def _bool(key: str, default: bool) -> bool:
            raw = os.environ.get(key)
            if raw is None:
                return default
            return raw.strip().lower() not in {"", "0", "false", "no", "off"}

        state_root = _path("HAPAX_PIPEWIRE_GRAPH_STATE_ROOT") or DEFAULT_STATE_ROOT
        return cls(
            state_root=state_root,
            graph_descriptor_path=_path("HAPAX_PIPEWIRE_GRAPH_DESCRIPTOR"),
            pipewire_conf_dir=_path("HAPAX_PIPEWIRE_GRAPH_PIPEWIRE_CONF_DIR")
            or DEFAULT_PIPEWIRE_CONF_DIR,
            wireplumber_conf_dir=_path("HAPAX_PIPEWIRE_GRAPH_WIREPLUMBER_CONF_DIR")
            or DEFAULT_WIREPLUMBER_CONF_DIR,
            egress_stage=os.environ.get("HAPAX_PIPEWIRE_GRAPH_EGRESS_STAGE", DEFAULT_EGRESS_STAGE),
            dry_run_interval_s=_float(
                "HAPAX_PIPEWIRE_GRAPH_DRY_RUN_INTERVAL_S",
                DEFAULT_DRY_RUN_INTERVAL_S,
            ),
            metrics_port=_int("HAPAX_PIPEWIRE_GRAPH_METRICS_PORT", DEFAULT_METRICS_PORT),
            metrics_addr=os.environ.get("HAPAX_PIPEWIRE_GRAPH_METRICS_ADDR", "127.0.0.1"),
            enable_ntfy=_bool("HAPAX_PIPEWIRE_GRAPH_ENABLE_NTFY", True),
            run_once=_bool("HAPAX_PIPEWIRE_GRAPH_RUN_ONCE", False),
        )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def _timestamp_for_path(now: datetime | None = None) -> str:
    dt = now or datetime.now(UTC)
    return dt.strftime("%Y%m%dT%H%M%S.%fZ")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _violation_to_dict(v: Any) -> dict[str, object]:
    return {
        "kind": str(getattr(v, "kind", "")),
        "severity": str(getattr(v, "severity", "")),
        "node_id": getattr(v, "node_id", None),
        "edge_idx": getattr(v, "edge_idx", None),
        "message": getattr(v, "message", ""),
    }


def _artefact_diff(root: Path, artefacts: dict[str, str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for rel_path, compiled_text in sorted(artefacts.items()):
        runtime_path = (root / rel_path).expanduser()
        compiled_sha = _sha256_text(compiled_text)
        runtime_sha = _sha256_file(runtime_path)
        if runtime_sha is None:
            state = "missing"
        elif runtime_sha == compiled_sha:
            state = "same"
        else:
            state = "different"
        rows.append(
            {
                "path": str(runtime_path),
                "state": state,
                "compiled_sha256": compiled_sha,
                "runtime_sha256": runtime_sha,
            }
        )
    return rows


def _compiled_summary(compiled: CompiledArtefacts) -> dict[str, object]:
    return {
        "pipewire_conf_count": len(compiled.pipewire_confs),
        "wireplumber_conf_count": len(compiled.wireplumber_confs),
        "pactl_load_count": len(compiled.pactl_loads),
        "post_apply_probe_count": len(compiled.post_apply_probes),
        "violation_count": len(compiled.pre_apply_violations),
        "blocking": any(
            str(getattr(v, "severity", "")).endswith("blocking")
            for v in compiled.pre_apply_violations
        ),
    }


def lock_status_payload() -> dict[str, object]:
    """Expose P3 applier-lock status without mutating the live graph."""

    return read_lock_status().to_dict()


def apply_dry_run(
    graph: AudioGraph,
    *,
    state_root: Path = DEFAULT_STATE_ROOT,
    pipewire_conf_dir: Path = DEFAULT_PIPEWIRE_CONF_DIR,
    wireplumber_conf_dir: Path = DEFAULT_WIREPLUMBER_CONF_DIR,
    now_utc: datetime | None = None,
) -> dict[str, object]:
    """Compile ``graph`` and write a shadow dry-run report.

    The only write is the JSON report under ``state_root``. Runtime conf
    files are read for diffing only.
    """

    now = now_utc or datetime.now(UTC)
    compiled = compile_descriptor(graph)
    blocked = bool(_compiled_summary(compiled)["blocking"])
    result = "blocked" if blocked else "ok"
    report_path = state_root / "shadow-runs" / f"{_timestamp_for_path(now)}.json"
    report: dict[str, object] = {
        "schema_version": 1,
        "mode": "shadow",
        "result": result,
        "written_at": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "target": {
            "schema_version": graph.schema_version,
            "node_count": len(graph.nodes),
            "link_count": len(graph.links),
            "loopback_count": len(graph.loopbacks),
        },
        "compile": {
            **_compiled_summary(compiled),
            "violations": [_violation_to_dict(v) for v in compiled.pre_apply_violations],
        },
        "diff": {
            "pipewire": _artefact_diff(pipewire_conf_dir, compiled.pipewire_confs),
            "wireplumber": _artefact_diff(wireplumber_conf_dir, compiled.wireplumber_confs),
        },
        "pactl_loads": [
            {
                "source": p.source,
                "sink": p.sink,
                "source_dont_move": p.source_dont_move,
                "sink_dont_move": p.sink_dont_move,
                "latency_msec": p.latency_msec,
                "description": p.description,
            }
            for p in compiled.pactl_loads
        ],
        "post_apply_probes": [
            {
                "name": p.name,
                "sink_to_inject": p.sink_to_inject,
                "source_to_capture": p.source_to_capture,
                "expected_outcome": p.expected_outcome,
            }
            for p in compiled.post_apply_probes
        ],
        "guardrails": {
            "live_pipewire_mutation": False,
            "pactl_load_module": False,
            "writes_outside_state_root": False,
            "applier_lock_required_for_live_apply": True,
            "applier_lock_status": lock_status_payload(),
        },
        "report_path": str(report_path),
    }
    _atomic_write_json(report_path, report)
    return report


class ShadowPipewireGraphDaemon:
    """Coordinator for P2 dry-run and observe-only breaker loops."""

    def __init__(
        self,
        config: ShadowDaemonConfig | None = None,
        *,
        metrics: PipewireGraphMetrics | None = None,
        safe_mute: SafeMuteRail | None = None,
    ) -> None:
        self.config = config or ShadowDaemonConfig.from_env()
        self.metrics = metrics or PipewireGraphMetrics()
        self.safe_mute = safe_mute or SafeMuteRail()
        self.stop_requested = False
        self.breaker = EgressCircuitBreaker(
            probe=lambda: probe_egress_health(stage=self.config.egress_stage),
            livestream_active=self._livestream_active,
            on_shadow_alert=self._on_shadow_alert,
        )

    def load_target_graph(self) -> AudioGraph:
        """Load the target graph from YAML, or decompose current confs read-only."""

        if self.config.graph_descriptor_path is not None:
            return AudioGraph.from_yaml(self.config.graph_descriptor_path)
        validator = AudioGraphValidator(
            pipewire_conf_dir=self.config.pipewire_conf_dir,
            wireplumber_conf_dir=self.config.wireplumber_conf_dir,
        )
        return validator.decompose_confs().graph

    def apply_dry_run(self, graph: AudioGraph | None = None) -> dict[str, object]:
        target = graph or self.load_target_graph()
        report = apply_dry_run(
            target,
            state_root=self.config.state_root,
            pipewire_conf_dir=self.config.pipewire_conf_dir,
            wireplumber_conf_dir=self.config.wireplumber_conf_dir,
        )
        self.metrics.record_dry_run(str(report["result"]))
        return report

    def observe_once(self, health: EgressHealth | None = None) -> EgressHealth:
        sample = health or self.breaker.probe_once()
        alert = self.breaker.observe(sample)
        payload = sample.to_dict(state=self.breaker.state)
        if alert is not None:
            payload["shadow_alert"] = alert.to_dict()
        _append_jsonl(self.config.egress_health_path, payload)
        self.metrics.observe_health(sample, self.breaker.state)
        return sample

    def run_forever(self) -> int:
        """Run until SIGTERM/SIGINT or ``run_once``."""

        logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
        self.config.state_root.mkdir(parents=True, exist_ok=True)
        self.config.shadow_runs_dir.mkdir(parents=True, exist_ok=True)
        self.safe_mute.load_shadow()
        self.metrics.start_http_server(self.config.metrics_port, addr=self.config.metrics_addr)
        _sd_notify("READY=1")
        log.info("hapax-pipewire-graph shadow daemon starting")

        last_dry_run = 0.0
        while not self.stop_requested:
            now = time.monotonic()
            if now - last_dry_run >= self.config.dry_run_interval_s:
                try:
                    self.apply_dry_run()
                except Exception:
                    log.exception("shadow dry-run failed")
                    self.metrics.record_dry_run("error")
                last_dry_run = now

            try:
                self.observe_once()
            except Exception:
                log.exception("egress observation failed")

            _sd_notify("WATCHDOG=1")
            if self.config.run_once:
                break
            time.sleep(0.5)

        _sd_notify("STOPPING=1")
        return 0

    def request_stop(self, *_args: object) -> None:
        self.stop_requested = True

    def _on_shadow_alert(self, alert: ShadowAlert) -> None:
        self.metrics.record_shadow_alert(alert.mode)
        if not self.config.enable_ntfy:
            return
        body = (
            f"{alert.message}\n"
            f"mode={alert.mode.value} rms={alert.health.rms_dbfs:.1f} dBFS "
            f"crest={alert.health.crest_factor:.2f} zcr={alert.health.zcr:.3f}\n"
            f"pre_event_samples={len(alert.pre_event_buffer)}"
        )
        try:
            send_notification(
                "PipeWire graph shadow breaker",
                body,
                priority="high",
                tags=["warning"],
                topic="audio-pipewire-graph",
            )
        except Exception:
            log.debug("shadow ntfy dispatch failed", exc_info=True)

    @staticmethod
    def _livestream_active() -> bool:
        """P2 defaults to active when no explicit flag exists.

        Silence alerts are useful during the 24 hour shadow window even
        if the existing broadcast-active flag is absent from a dev
        environment. Operators can disable ntfy through env.
        """

        flag = Path("/dev/shm/hapax-broadcast/livestream-active")
        if not flag.exists():
            return True
        try:
            return flag.read_text(encoding="utf-8").strip().lower() not in {
                "",
                "0",
                "false",
                "off",
            }
        except OSError:
            return True


def _sd_notify(message: str) -> bool:
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return False
    address: str | bytes = notify_socket
    if notify_socket.startswith("@"):
        address = "\0" + notify_socket[1:]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.connect(address)
        sock.sendall(message.encode("utf-8"))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="hapax-pipewire-graph shadow daemon")
    parser.add_argument("--once", action="store_true", help="run one dry-run/probe tick and exit")
    parser.add_argument("--state-root", type=Path, help="override state root")
    parser.add_argument("--descriptor", type=Path, help="AudioGraph YAML descriptor")
    parser.add_argument("--no-ntfy", action="store_true", help="disable shadow ntfy alerts")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = ShadowDaemonConfig.from_env()
    if args.once:
        config = replace(config, run_once=True)
    if args.state_root is not None:
        config = replace(config, state_root=args.state_root)
    if args.descriptor is not None:
        config = replace(config, graph_descriptor_path=args.descriptor)
    if args.no_ntfy:
        config = replace(config, enable_ntfy=False)
    daemon = ShadowPipewireGraphDaemon(config)
    signal.signal(signal.SIGTERM, daemon.request_stop)
    signal.signal(signal.SIGINT, daemon.request_stop)
    return daemon.run_forever()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


__all__ = [
    "DEFAULT_STATE_ROOT",
    "ShadowDaemonConfig",
    "ShadowPipewireGraphDaemon",
    "apply_dry_run",
    "lock_status_payload",
    "main",
]

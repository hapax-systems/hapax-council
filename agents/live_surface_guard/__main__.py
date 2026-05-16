"""Low-cadence live-surface guard daemon."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path

from shared.live_surface_truth import (
    LiveSurfaceAssessment,
    LiveSurfaceState,
    assess_live_surface,
    parse_prometheus_scalars,
    snapshot_from_prometheus,
)

from .model import (
    IncidentLedger,
    RemediationAction,
    RemediationController,
    action_for_assessment,
    emit_contract_textfile,
    sample_obs_decoder,
    surface_evidence,
)

DEFAULT_EXTRA_METRICS_FILES = (
    Path("/dev/shm/hapax-compositor/v4l2-bridge.prom"),
    Path("/dev/shm/hapax-visual/egress.prom"),
)


@dataclass
class RuntimeState:
    previous_obs_hash: str | None = None


def _read_obs_websocket_password(config_path: Path) -> str:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if data.get("server_enabled") is False:
        return ""
    if data.get("auth_required") is False:
        return ""
    password = data.get("server_password")
    return password if isinstance(password, str) else ""


def _default_obs_password() -> str:
    return (
        os.environ.get("HAPAX_OBS_WEBSOCKET_PASSWORD")
        or os.environ.get("OBS_WEBSOCKET_PASSWORD")
        or _read_obs_websocket_password(
            Path.home()
            / ".config"
            / "obs-studio"
            / "plugin_config"
            / "obs-websocket"
            / "config.json"
        )
    )


class CommandRemediationExecutor:
    def __init__(self, *, dry_run: bool = True) -> None:
        self._dry_run = dry_run

    def perform(self, action: RemediationAction) -> str:
        if self._dry_run:
            return f"dry_run:{action.value}"
        commands = {
            RemediationAction.OBS_CACHE_BUST_REBIND: [
                "systemctl",
                "--user",
                "restart",
                "hapax-obs-v4l2-source-reset.service",
            ],
            RemediationAction.BRIDGE_RECONNECT_OBS_REBIND: [
                "systemctl",
                "--user",
                "restart",
                "hapax-v4l2-bridge.service",
                "hapax-obs-v4l2-source-reset.service",
            ],
            RemediationAction.HLS_CACHE_BUST: [
                "systemctl",
                "--user",
                "restart",
                "hapax-hls-no-cache.service",
            ],
            RemediationAction.AUTO_PRIVATE_ESCALATE: [
                "systemctl",
                "--user",
                "stop",
                "hapax-hls-no-cache.service",
            ],
        }
        result = subprocess.run(commands[action], check=False, timeout=20)
        return "ok" if result.returncode == 0 else f"command_failed:{result.returncode}"

    def rollback(self, action: RemediationAction) -> str:
        if self._dry_run:
            return "dry_run"
        if action is RemediationAction.AUTO_PRIVATE_ESCALATE:
            return "manual_review_required"
        return "not_available"


def _load_metrics(args: argparse.Namespace) -> dict[str, float]:
    if args.metrics_file:
        text = Path(args.metrics_file).read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(args.metrics_url, timeout=2.0) as response:
            text = response.read().decode("utf-8", "replace")
    metrics = parse_prometheus_scalars(text)
    extra_files = args.extra_metrics_file
    if extra_files is None:
        extra_files = [] if args.metrics_file else list(DEFAULT_EXTRA_METRICS_FILES)
    for path in extra_files:
        _merge_metrics_file(metrics, path)
    return metrics


def _merge_metrics_file(metrics: dict[str, float], path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
        age_seconds = max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return
    extra = parse_prometheus_scalars(text)
    heartbeat = extra.get("hapax_v4l2_bridge_heartbeat_seconds_ago")
    if heartbeat is not None:
        extra["hapax_v4l2_bridge_heartbeat_seconds_ago"] = max(heartbeat, age_seconds)
    for name in (
        "hapax_imagination_output_last_frame_seconds_ago",
        "hapax_imagination_v4l2_last_frame_seconds_ago",
    ):
        if name in extra:
            extra[name] = max(extra[name], age_seconds)
    metrics.update(extra)


def _load_obs_state(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _apply_obs_state(snapshot, state: dict[str, object]):
    if not state:
        return snapshot
    return replace(
        snapshot,
        obs_source_active=_optional_bool(state.get("source_active")),
        obs_playing=_optional_bool(state.get("playing")),
        obs_screenshot_changed=_optional_bool(state.get("screenshot_changed")),
        obs_screenshot_flat=_optional_bool(state.get("screenshot_flat")),
        obs_screenshot_age_seconds=_optional_float(state.get("screenshot_age_seconds")),
        public_output_live=_optional_bool(state.get("public_output_live")),
    )


def _apply_obs_evidence(snapshot, evidence):
    return replace(
        snapshot,
        obs_source_active=evidence.source_active,
        obs_playing=evidence.playing,
        obs_screenshot_changed=evidence.screenshot_changed,
        obs_screenshot_flat=evidence.screenshot_flat,
        obs_screenshot_age_seconds=evidence.screenshot_age_seconds,
    )


def _sample_obs_websocket(args: argparse.Namespace, runtime_state: RuntimeState):
    try:
        import obsws_python

        client = obsws_python.ReqClient(
            host=args.obs_host,
            port=args.obs_port,
            password=args.obs_password,
            timeout=2,
        )
        evidence = sample_obs_decoder(
            client,
            args.obs_source_name,
            previous_hash=runtime_state.previous_obs_hash,
        )
        if evidence.screenshot_hash is not None:
            runtime_state.previous_obs_hash = evidence.screenshot_hash
        return evidence
    except Exception:
        return None


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "active"}
    return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _file_age_seconds(path: Path) -> float | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    return time.time() - stat.st_mtime


def _run_once(
    args: argparse.Namespace,
    *,
    controller: RemediationController,
    runtime_state: RuntimeState,
) -> int:
    try:
        metrics = _load_metrics(args)
    except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
        snapshot = snapshot_from_prometheus(
            {},
            service_active=False,
            bridge_active=not args.bridge_inactive,
        )
        assessment = LiveSurfaceAssessment(
            state=LiveSurfaceState.FAILED,
            reasons=(f"metrics_unavailable:{type(exc).__name__}",),
        )
        emit_contract_textfile(
            args.textfile_path,
            snapshot=snapshot,
            assessment=assessment,
            receipts_total=0,
        )
        IncidentLedger(args.ledger_path).append(
            "observation",
            surface_evidence(snapshot, assessment),
        )
        return 2
    hls_playlist_age_seconds = _file_age_seconds(args.hls_playlist) if args.require_hls else None
    snapshot = snapshot_from_prometheus(
        metrics,
        service_active=True,
        bridge_active=not args.bridge_inactive,
        hls_active=hls_playlist_age_seconds is not None,
        hls_playlist_age_seconds=hls_playlist_age_seconds,
    )
    if args.obs_state_file is not None:
        snapshot = _apply_obs_state(snapshot, _load_obs_state(args.obs_state_file))
    elif args.require_obs_decoder and not args.disable_obs_websocket_sampling:
        evidence = _sample_obs_websocket(args, runtime_state)
        if evidence is not None:
            snapshot = _apply_obs_evidence(snapshot, evidence)
    assessment = assess_live_surface(
        snapshot,
        max_egress_age_seconds=args.max_egress_age_seconds,
        require_hls=args.require_hls,
        require_rtmp=args.require_rtmp,
        require_obs_decoder=args.require_obs_decoder,
        require_public_output=args.require_public_output,
    )

    receipts_total = 0
    action = action_for_assessment(snapshot, assessment)
    if action is not None and args.enable_remediation:
        receipt = controller.run(
            action,
            before_snapshot=snapshot,
            before_assessment=assessment,
            collect_after=lambda: (snapshot, assessment),
        )
        receipts_total = receipt.attempt_number

    emit_contract_textfile(
        args.textfile_path,
        snapshot=snapshot,
        assessment=assessment,
        receipts_total=receipts_total,
    )
    IncidentLedger(args.ledger_path).append("observation", surface_evidence(snapshot, assessment))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics-url", default="http://127.0.0.1:9482/metrics")
    parser.add_argument("--metrics-file")
    parser.add_argument(
        "--extra-metrics-file",
        action="append",
        type=Path,
        default=None,
        help="additional Prometheus textfile to merge into the live-surface snapshot",
    )
    parser.add_argument("--obs-state-file", type=Path)
    parser.add_argument("--obs-source-name", default="StudioCompositor")
    parser.add_argument("--obs-host", default="localhost")
    parser.add_argument("--obs-port", type=int, default=4455)
    parser.add_argument("--obs-password", default=_default_obs_password())
    parser.add_argument("--disable-obs-websocket-sampling", action="store_true")
    parser.add_argument("--bridge-inactive", action="store_true")
    parser.add_argument("--require-hls", action="store_true")
    parser.add_argument(
        "--hls-playlist",
        type=Path,
        default=Path.home() / ".cache" / "hapax-compositor" / "hls" / "stream.m3u8",
    )
    parser.add_argument("--require-rtmp", action="store_true")
    parser.add_argument("--require-obs-decoder", dest="require_obs_decoder", action="store_true")
    parser.add_argument(
        "--no-require-obs-decoder", dest="require_obs_decoder", action="store_false"
    )
    parser.set_defaults(require_obs_decoder=True)
    parser.add_argument("--require-public-output", action="store_true")
    parser.add_argument("--max-egress-age-seconds", type=float, default=10.0)
    parser.add_argument("--poll-interval", type=float, default=15.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--enable-remediation", action="store_true")
    parser.add_argument("--enable-live-mutation", action="store_true")
    parser.add_argument(
        "--textfile-path",
        type=Path,
        default=Path.home()
        / ".local"
        / "share"
        / "node_exporter"
        / "textfile_collector"
        / "hapax-live-surface-guard.prom",
    )
    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=Path("/dev/shm/hapax-live-surface-guard/incidents.jsonl"),
    )
    args = parser.parse_args(argv)

    executor = CommandRemediationExecutor(
        dry_run=not (args.enable_remediation and args.enable_live_mutation)
    )
    controller = RemediationController(
        executor=executor,
        ledger=IncidentLedger(args.ledger_path),
    )
    runtime_state = RuntimeState()
    while True:
        rc = _run_once(args, controller=controller, runtime_state=runtime_state)
        if args.once:
            return rc
        time.sleep(max(1.0, args.poll_interval))


if __name__ == "__main__":
    sys.exit(main())

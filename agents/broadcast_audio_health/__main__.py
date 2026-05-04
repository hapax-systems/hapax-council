"""Entrypoint for the broadcast audio health producer."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from shared.broadcast_audio_health import (
    BroadcastAudioHealthPaths,
    BroadcastAudioHealthThresholds,
    resolve_broadcast_audio_health,
    write_broadcast_audio_health_state,
)

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish the canonical audio_safe_for_broadcast state."
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=None,
        help="Output path for the audio_safe_for_broadcast JSON envelope.",
    )
    parser.add_argument(
        "--topology-descriptor",
        type=Path,
        default=None,
        help="Audio topology descriptor path.",
    )
    parser.add_argument(
        "--audio-safety-state",
        type=Path,
        default=None,
        help="Runtime safety state from hapax-audio-safety.",
    )
    parser.add_argument(
        "--loudness-duration",
        type=int,
        default=5,
        help="Seconds to sample hapax-broadcast-normalized.monitor.",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print the state envelope after publishing.",
    )
    parser.add_argument(
        "--fail-on-unsafe",
        action="store_true",
        help="Exit non-zero when the resolved state is not safe.",
    )
    parser.add_argument(
        "--skip-l12-scene-probe",
        action="store_true",
        help=(
            "Audit-A#6: disable the L-12 BROADCAST-V2 scene probes "
            "(useful for tests + dev workstations without an L-12 attached)."
        ),
    )
    parser.add_argument(
        "--l12-scene-check-interval-s",
        type=float,
        default=300.0,
        help="Cadence for the full l12-scene-check rotation (default: 300s).",
    )
    parser.add_argument(
        "--l12-scene-check-duration-s",
        type=float,
        default=30.0,
        help="Capture duration for full L-12 scene assertions (default: 30s).",
    )
    parser.add_argument(
        "--l12-scene-check-state-path",
        type=Path,
        default=None,
        help="Persisted state for full L-12 scene-check rotation.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    paths = BroadcastAudioHealthPaths(
        state_path=args.state_path or BroadcastAudioHealthPaths.state_path,
        topology_descriptor=args.topology_descriptor
        or BroadcastAudioHealthPaths.topology_descriptor,
        audio_safety_state=args.audio_safety_state or BroadcastAudioHealthPaths.audio_safety_state,
    )
    thresholds = BroadcastAudioHealthThresholds(loudness_duration_s=args.loudness_duration)
    health = resolve_broadcast_audio_health(paths=paths, thresholds=thresholds)
    write_broadcast_audio_health_state(health, paths.state_path)

    if args.print:
        payload = {"audio_safe_for_broadcast": health.model_dump(mode="json")}
        print(json.dumps(payload, indent=2, sort_keys=True))

    if not args.skip_l12_scene_probe:
        # Audit A#6 / H5 P1: the existing 30s health timer drives
        # the lightweight AUX5 detector every tick, and the full
        # BROADCAST-V2 scene assertion on a 5-minute rotation.
        try:
            from agents.broadcast_audio_health.l12_broadcast_scene_probe import (
                DEFAULT_L12_SCENE_CHECK_STATE_PATH,
                DEFAULT_MUSIC_SINK_NAME,
                is_music_sink_running,
                probe_l12_broadcast_scene,
                run_l12_scene_check_rotation,
            )

            music_running = is_music_sink_running(DEFAULT_MUSIC_SINK_NAME)
            rotation = run_l12_scene_check_rotation(
                descriptor_path=paths.topology_descriptor,
                state_path=(args.l12_scene_check_state_path or DEFAULT_L12_SCENE_CHECK_STATE_PATH),
                interval_s=args.l12_scene_check_interval_s,
                duration_s=args.l12_scene_check_duration_s,
                music_running=music_running,
            )
            if rotation.ran:
                assertion = rotation.assertion
                log.info(
                    "l12-scene=%s rotation=full alerted=%s aux5_peak=%s aux10_11_peak=%s",
                    "ok" if rotation.scene_ok else "not-ok",
                    rotation.alerted,
                    assertion.evidence.get("aux5_peak_dbfs") if assertion else None,
                    assertion.evidence.get("aux10_11_peak_dbfs") if assertion else None,
                )
                return 1 if args.fail_on_unsafe and not health.safe else 0

            outcome = probe_l12_broadcast_scene()
            scene_status = "ok"
            if not outcome.music_running:
                scene_status = "skipped_music_not_running"
            elif outcome.fired:
                scene_status = "not-ok"
            log.info(
                "l12-scene=%s rotation=%s aux5_dbfs=%.2f "
                "music_running=%s silent_for_s=%.1f fired=%s",
                scene_status,
                rotation.status,
                outcome.aux5_dbfs,
                outcome.music_running,
                outcome.silent_for_s,
                outcome.fired,
            )
        except Exception:  # noqa: BLE001 — never let probe failure break the safety envelope
            log.warning("l12-scene probe failed", exc_info=True)

    if args.fail_on_unsafe and not health.safe:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

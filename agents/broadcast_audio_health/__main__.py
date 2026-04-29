"""Entrypoint for the broadcast audio health producer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shared.broadcast_audio_health import (
    BroadcastAudioHealthPaths,
    BroadcastAudioHealthThresholds,
    resolve_broadcast_audio_health,
    write_broadcast_audio_health_state,
)


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
    args = parser.parse_args(argv)

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

    if args.fail_on_unsafe and not health.safe:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

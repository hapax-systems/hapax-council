#!/usr/bin/env python3
"""Dry-run Phase 6 audio route policy generator discipline.

This bootstrap intentionally writes only the route-policy manifest. It does
not rewrite live PipeWire or WirePlumber confs, and it never reloads services.
Future generator parity work can add conf emission after golden output and
round-trip checks are in place.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from shared.audio_routing_policy import (
    DEFAULT_POLICY_PATH,
    audio_routing_manifest_json,
    load_audio_routing_policy,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    policy = load_audio_routing_policy(args.policy)
    manifest_text = audio_routing_manifest_json(policy)
    manifest_path = Path(policy.generated_output.manifest_path)

    if args.write_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(manifest_text, encoding="utf-8")

    if args.check:
        existing = manifest_path.read_text(encoding="utf-8")
        if existing != manifest_text:
            raise SystemExit(
                f"{manifest_path} is stale; rerun scripts/generate-pipewire-audio-confs.py "
                "--write-manifest"
            )

    if not args.write_manifest and not args.check:
        print(manifest_text, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

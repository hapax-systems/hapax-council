#!/usr/bin/env python3
"""Check audio current-capsule freshness against source artifacts.

Compares SHA-256 hashes of audio-authority source files against the recorded
hashes in config/audio-current-capsule.yaml. Fails if any source has changed
without the capsule being regenerated.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CAPSULE_PATH = REPO_ROOT / "config" / "audio-current-capsule.yaml"

TRACKED_SOURCES: list[str] = [
    "config/audio-topology.yaml",
    "config/audio-routing.yaml",
    "config/pipewire/generated/audio-routing-policy.manifest.json",
    "config/hapax/audio-forbidden-links.conf",
    "config/hapax/audio-link-map.conf",
]


def hash_file(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_capsule(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        return {}
    return data.get("source_hashes", {})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check audio capsule freshness")
    parser.add_argument(
        "--update", action="store_true", help="Update the capsule file with current hashes"
    )
    args = parser.parse_args(argv)

    current_hashes: dict[str, str] = {}
    for rel in TRACKED_SOURCES:
        current_hashes[rel] = hash_file(REPO_ROOT / rel)

    if args.update:
        capsule_data = {
            "schema_version": 1,
            "description": "Audio current-capsule freshness hashes. Auto-generated.",
            "source_hashes": current_hashes,
        }
        CAPSULE_PATH.write_text(yaml.dump(capsule_data, default_flow_style=False, sort_keys=False))
        print(f"Updated {CAPSULE_PATH.relative_to(REPO_ROOT)}")
        return 0

    recorded = load_capsule(CAPSULE_PATH)
    if not recorded:
        print(
            "WARNING: No capsule file found. Run with --update to create one.",
            file=sys.stderr,
        )
        return 0

    stale: list[str] = []
    for rel, current in current_hashes.items():
        expected = recorded.get(rel)
        if expected is None:
            stale.append(f"  {rel}: not tracked in capsule")
        elif current != expected:
            stale.append(f"  {rel}: hash drift ({expected} -> {current})")

    if stale:
        print("ERROR: Audio capsule is stale. Sources changed:", file=sys.stderr)
        for s in stale:
            print(s, file=sys.stderr)
        print(
            "\nRun: uv run python scripts/check-audio-current-capsule-staleness.py --update",
            file=sys.stderr,
        )
        return 1

    print(f"Audio capsule fresh: {len(current_hashes)} source(s) verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

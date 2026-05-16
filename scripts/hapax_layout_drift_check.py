#!/usr/bin/env python3
"""Check for drift between deployed and governed layout files.

Compares on-disk compositor layout files against their governed source
in the repository. Flags divergence: content mismatch, untracked files,
missing governed files.

Usage:
    uv run python scripts/hapax-layout-drift-check [--deployed DIR] [--governed DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GOVERNED = REPO_ROOT / "config" / "compositor-layouts"
DEFAULT_DEPLOYED = Path.home() / ".config" / "hapax-compositor" / "layouts"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_drift(governed_dir: Path, deployed_dir: Path) -> dict:
    results: dict = {
        "governed_dir": str(governed_dir),
        "deployed_dir": str(deployed_dir),
        "matching": [],
        "content_mismatch": [],
        "missing_from_deployed": [],
        "untracked_in_deployed": [],
    }

    governed_files = {f.name: f for f in governed_dir.glob("*.json") if f.is_file()}
    deployed_files = {f.name: f for f in deployed_dir.glob("*.json") if f.is_file()}

    for name, gov_path in sorted(governed_files.items()):
        if name not in deployed_files:
            results["missing_from_deployed"].append(name)
            continue
        dep_path = deployed_files[name]
        gov_hash = file_hash(gov_path)
        dep_hash = file_hash(dep_path)
        if gov_hash == dep_hash:
            results["matching"].append(name)
        else:
            results["content_mismatch"].append(
                {
                    "name": name,
                    "governed_hash": gov_hash[:12],
                    "deployed_hash": dep_hash[:12],
                }
            )

    for name in sorted(deployed_files.keys()):
        if name not in governed_files:
            results["untracked_in_deployed"].append(name)

    results["drift_detected"] = bool(
        results["content_mismatch"]
        or results["missing_from_deployed"]
        or results["untracked_in_deployed"]
    )

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Layout drift check")
    parser.add_argument("--governed", type=Path, default=DEFAULT_GOVERNED)
    parser.add_argument("--deployed", type=Path, default=DEFAULT_DEPLOYED)
    parser.add_argument("--json-output", action="store_true")
    args = parser.parse_args()

    if not args.governed.is_dir():
        print(f"Governed directory not found: {args.governed}", file=sys.stderr)
        sys.exit(1)
    if not args.deployed.is_dir():
        print(f"Deployed directory not found: {args.deployed}", file=sys.stderr)
        sys.exit(0)

    results = check_drift(args.governed, args.deployed)

    if args.json_output:
        print(json.dumps(results, indent=2))
    else:
        print(f"Governed: {results['governed_dir']}")
        print(f"Deployed: {results['deployed_dir']}")
        print(f"Matching: {len(results['matching'])}")
        if results["content_mismatch"]:
            print(f"Content mismatch: {len(results['content_mismatch'])}")
            for m in results["content_mismatch"]:
                print(f"  {m['name']}: governed={m['governed_hash']} deployed={m['deployed_hash']}")
        if results["missing_from_deployed"]:
            print(f"Missing from deployed: {results['missing_from_deployed']}")
        if results["untracked_in_deployed"]:
            print(f"Untracked in deployed: {results['untracked_in_deployed']}")

        if results["drift_detected"]:
            print("\nDRIFT DETECTED")
            sys.exit(1)
        else:
            print("\nNo drift")


if __name__ == "__main__":
    main()

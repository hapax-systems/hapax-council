#!/usr/bin/env python3
"""CI gate for audio SSOT industrial names.

Live PipeWire ``node.name`` strings are deployment compatibility handles.
The topology's ``industrial_name`` field is the operator-consultable SSOT
name used by docs, audits, and future graph tooling.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.audio_industrial_naming import industrial_audio_name_violations
from shared.audio_topology import TopologyDescriptor

DEFAULT_TOPOLOGY = REPO_ROOT / "config" / "audio-topology.yaml"


def check(topology_path: Path = DEFAULT_TOPOLOGY) -> tuple[int, str]:
    seen: dict[str, str] = {}
    violations: list[str] = []

    with topology_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    raw_nodes = raw.get("nodes", []) if isinstance(raw, dict) else []

    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            violations.append(f"<invalid-node>: {raw_node!r} (node entry is not a mapping)")
            continue
        node_id = str(raw_node.get("id") or "<missing-node-id>")
        name = raw_node.get("industrial_name")
        reasons = industrial_audio_name_violations(name)
        if reasons:
            violations.append(f"{node_id}: {name or '<missing>'} ({', '.join(reasons)})")
            continue

        assert name is not None
        previous = seen.get(name)
        if previous is not None:
            violations.append(f"{node_id}: {name} (duplicate of {previous})")
            continue
        seen[name] = node_id

    if violations:
        lines = [
            "check-audio-industrial-names: invalid audio industrial names detected",
            "",
            "Every config/audio-topology.yaml node must have a unique hierarchical industrial_name.",
            "Names must be lowercase dot-separated responsibilities such as chain.music.ducker.",
            "Do not use incident-era or ad-hoc tokens such as hapax, evilpet, or ytube.",
            "",
        ]
        lines.extend(f"  - {item}" for item in violations)
        return 1, "\n".join(lines)

    try:
        descriptor = TopologyDescriptor.from_yaml(topology_path)
    except Exception as exc:
        return (
            1,
            f"check-audio-industrial-names: topology descriptor failed schema validation\n{exc}",
        )

    return (
        0,
        f"OK - all {len(descriptor.nodes)} audio topology nodes have unique industrial names.",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reject missing, duplicate, or ad-hoc audio industrial names.",
    )
    parser.add_argument(
        "--topology",
        type=Path,
        default=DEFAULT_TOPOLOGY,
        help=f"Path to audio topology descriptor (default: {DEFAULT_TOPOLOGY})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    code, message = check(args.topology)
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Pre-commit + CI gate: audio yaml ↔ conf consistency.

Walks `config/audio-topology.yaml` and `config/pipewire/*.conf` and
flags drift in either direction:

  * **missing** — a `filter_chain` node declared in the topology
    yaml has no corresponding `hapax-<chain-id>.conf` on disk. This
    is always a hard error: the LADSPA chain has no place to land.

  * **orphan** — a conf file on disk has no corresponding `filter_chain`
    yaml node. This is normally a hard error, but legitimate exceptions
    exist (numbered modules `10-*`/`99-*`, voice-fx variants the yaml
    doesn't model yet, legacy l6 confs kept for rollback). The
    allowlist `config/audio-conf-allowlist.yaml` documents the known
    set; orphans not in the allowlist fail.

Exit codes:
  0 — yaml + confs consistent (or every drift is allowlisted).
  1 — missing or non-allowlisted orphan detected.
  2 — usage error (missing yaml, malformed allowlist).

Cc-task: ``audio-audit-F-precommit-yaml-conf-gate``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOPOLOGY = REPO_ROOT / "config" / "audio-topology.yaml"
DEFAULT_PIPEWIRE_DIR = REPO_ROOT / "config" / "pipewire"
DEFAULT_ALLOWLIST = REPO_ROOT / "config" / "audio-conf-allowlist.yaml"

#: Naming convention: yaml `<chain-id>` → conf `hapax-<chain-id>.conf`.
#: New chains MUST follow this convention; the gate enforces it.
CONF_PREFIX = "hapax-"
CONF_SUFFIX = ".conf"


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(f"check-audio-conf-consistency: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SystemExit(f"check-audio-conf-consistency: malformed yaml at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"check-audio-conf-consistency: yaml at {path} is not a mapping")
    return data


#: chain_kind values that emit a LADSPA conf. Stream-routing chains
#: (`chain_kind=None`, e.g. capture nodes that just `stream.capture.sink`)
#: don't have a conf and aren't expected to.
_LADSPA_CHAIN_KINDS: frozenset[str] = frozenset({"loudnorm", "duck", "usb-bias"})


def expected_confs_from_yaml(topology_path: Path) -> set[str]:
    """Return the set of conf basenames expected from yaml chain nodes.

    Convention: a `filter_chain` node with id `X` AND `chain_kind` in
    `{loudnorm, duck, usb-bias}` must have a `hapax-X.conf` on disk.
    Stream-routing filter_chain nodes (chain_kind=None) don't emit a
    conf — they're configured by inline `params:` in the yaml itself
    (e.g. `stream.capture.sink`, `playback_source`).

    Other node kinds (alsa_source, alsa_sink, loopback, tap) are
    never expected to have confs.
    """
    data = _load_yaml(topology_path)
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        return set()
    expected: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("kind") != "filter_chain":
            continue
        chain_kind = node.get("chain_kind")
        if chain_kind not in _LADSPA_CHAIN_KINDS:
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        expected.add(f"{CONF_PREFIX}{node_id}{CONF_SUFFIX}")
    return expected


def confs_on_disk(pipewire_dir: Path) -> set[str]:
    """Return the set of `*.conf` basenames in the pipewire dir."""
    if not pipewire_dir.is_dir():
        return set()
    return {p.name for p in pipewire_dir.iterdir() if p.is_file() and p.name.endswith(CONF_SUFFIX)}


def load_allowlist(path: Path) -> tuple[set[str], set[str]]:
    """Load the allowlist (returns (orphans, known_missing)).

    The allowlist is a yaml file with the shape:

        orphans:
          - 10-contact-mic.conf
          - voice-fx-loudnorm.conf
        known_missing:
          - hapax-tts-loudnorm.conf

    `orphans` are conf basenames on disk that the gate should accept
    as legitimately yaml-unbacked (e.g. legacy confs kept for rollback,
    voice-fx variants the yaml doesn't model yet).

    `known_missing` are conf basenames the gate should NOT flag as
    missing even though yaml declares the chain — these are tracked
    under separate audit follow-on tasks and the gate's job is only
    to catch NEW drift, not existing-known.

    Missing file → empty sets (the gate fires on everything).
    """
    if not path.exists():
        return set(), set()
    data = _load_yaml(path)
    orphans_raw = data.get("orphans") if isinstance(data.get("orphans"), list) else []
    missing_raw = data.get("known_missing") if isinstance(data.get("known_missing"), list) else []
    return (
        {str(item) for item in orphans_raw if isinstance(item, str)},
        {str(item) for item in missing_raw if isinstance(item, str)},
    )


def check(
    *,
    topology: Path = DEFAULT_TOPOLOGY,
    pipewire_dir: Path = DEFAULT_PIPEWIRE_DIR,
    allowlist: Path = DEFAULT_ALLOWLIST,
) -> tuple[int, str]:
    """Run the full gate. Returns ``(exit_code, message)``.

    Splits drift into:
      * ``missing`` — yaml chain has no conf on disk.
      * ``orphan_known`` — conf with no yaml backing, but allowlisted.
      * ``orphan_unknown`` — conf with no yaml backing, NOT allowlisted.

    ``missing`` and ``orphan_unknown`` are hard errors; ``orphan_known``
    is reported informationally.
    """
    expected = expected_confs_from_yaml(topology)
    on_disk = confs_on_disk(pipewire_dir)
    allowed_orphans, known_missing = load_allowlist(allowlist)

    raw_missing = expected - on_disk
    missing = sorted(raw_missing - known_missing)
    known_missing_actual = sorted(raw_missing & known_missing)
    orphans = sorted((on_disk - expected) - allowed_orphans)
    known_orphans = sorted((on_disk - expected) & allowed_orphans)

    if not missing and not orphans:
        msg = (
            f"OK — {len(expected)} yaml chains all have confs (or in known_missing: "
            f"{len(known_missing_actual)}); {len(known_orphans)} known orphans allowlisted."
        )
        return 0, msg

    lines: list[str] = ["check-audio-conf-consistency: drift detected", ""]
    if missing:
        lines.append(f"Missing confs ({len(missing)}) — yaml declares chain but conf is absent:")
        for name in missing:
            chain_id = name[len(CONF_PREFIX) : -len(CONF_SUFFIX)]
            lines.append(f"  - {name}  (yaml chain: {chain_id})")
        lines.append("")
        lines.append("Fix: create the missing conf, OR remove the yaml chain entry.")
        lines.append("")
    if orphans:
        lines.append(
            f"Orphan confs ({len(orphans)}) — on disk but no yaml chain AND not allowlisted:"
        )
        for name in orphans:
            lines.append(f"  - {name}")
        lines.append("")
        try:
            allowlist_display = str(allowlist.relative_to(REPO_ROOT))
        except ValueError:
            allowlist_display = str(allowlist)
        lines.append(
            "Fix: add a yaml chain entry for the conf, "
            f"OR add the basename to {allowlist_display} 'orphans:' list "
            "with a comment explaining why."
        )
        lines.append("")
    return 1, "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audio yaml ↔ conf consistency gate (pre-commit + CI).",
    )
    parser.add_argument(
        "--topology",
        type=Path,
        default=DEFAULT_TOPOLOGY,
        help=f"Path to audio-topology.yaml (default: {DEFAULT_TOPOLOGY})",
    )
    parser.add_argument(
        "--pipewire-dir",
        type=Path,
        default=DEFAULT_PIPEWIRE_DIR,
        help=f"Path to pipewire conf dir (default: {DEFAULT_PIPEWIRE_DIR})",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help=f"Path to orphan-allowlist yaml (default: {DEFAULT_ALLOWLIST})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    code, msg = check(
        topology=args.topology,
        pipewire_dir=args.pipewire_dir,
        allowlist=args.allowlist,
    )
    if code != 0:
        print(msg, file=sys.stderr)
    else:
        print(msg)
    return code


if __name__ == "__main__":
    sys.exit(main())

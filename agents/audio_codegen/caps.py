"""Audio source capability matrix CLI (audit F).

Read the canonical `config/audio-topology.yaml` and emit a matrix of
declared kinds × supported features so an operator triaging a live
audio incident has one diagnostic-first command instead of grep'ing
across YAML, systemd, and pw-link output.

Output modes:

  * **markdown** (default) — pipe into a runbook or paste into a PR.
  * **json** — for machine-readable consumption (operator dashboard,
    health probe, future Grafana table panel).

Output columns:

  * ``id`` — node identifier (kebab-case).
  * ``kind`` — declared `NodeKind` (`alsa_source`, `alsa_sink`,
    `filter_chain`, `loopback`, `tap`).
  * ``chain_kind`` — for filter-chain nodes, the typed template selector
    (`loudnorm`, `duck`, `usb-bias`, or empty).
  * ``edges_in`` / ``edges_out`` — count of edges where this node is
    target / source.
  * ``ducks`` — `Y` if the node id is a member of any ducking pair
    (matched by node id substring `"duck"` per the v3 chain-kind
    convention), else empty.
  * ``description`` — operator-readable label, truncated for table
    width.

Usage:

    uv run python -m agents.audio_codegen.caps              # markdown
    uv run python -m agents.audio_codegen.caps --json       # JSON
    uv run python -m agents.audio_codegen.caps --topology PATH

Cc-task: ``audio-audit-F-source-capability-matrix-cli``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from shared.audio_topology import TopologyDescriptor

DEFAULT_TOPOLOGY_PATH = Path("config/audio-topology.yaml")
#: Markdown column widths (description truncated for terminal width).
_DESC_MAX = 60


@dataclass(frozen=True)
class SourceCapability:
    """One row of the capability matrix.

    Frozen so dashboards can hash + cache rows.
    """

    id: str
    kind: str
    chain_kind: str
    edges_in: int
    edges_out: int
    ducks: bool
    description: str


def derive_capabilities(descriptor: TopologyDescriptor) -> list[SourceCapability]:
    """Project a `TopologyDescriptor` into capability rows.

    Pure function over the descriptor — no I/O, no live PipeWire
    state. Pairing live nodes with descriptor nodes is the
    `audio-topology verify` command's job; this matrix is the
    *declarative* shape, used to spot a node missing from yaml or a
    new chain that hasn't grown a typed template yet.
    """
    edges_in: dict[str, int] = {}
    edges_out: dict[str, int] = {}
    for edge in descriptor.edges:
        edges_in[edge.target] = edges_in.get(edge.target, 0) + 1
        edges_out[edge.source] = edges_out.get(edge.source, 0) + 1

    rows: list[SourceCapability] = []
    for node in descriptor.nodes:
        chain_kind_str = ""
        chain_kind = getattr(node, "chain_kind", None)
        if chain_kind is not None:
            chain_kind_str = str(chain_kind)
        rows.append(
            SourceCapability(
                id=node.id,
                kind=str(node.kind),
                chain_kind=chain_kind_str,
                edges_in=edges_in.get(node.id, 0),
                edges_out=edges_out.get(node.id, 0),
                ducks="duck" in node.id,
                description=node.description or "",
            )
        )
    return rows


def render_markdown(rows: Iterable[SourceCapability]) -> str:
    """Render rows as a GitHub-flavored markdown table."""
    rows_list = list(rows)
    header = "| id | kind | chain | in | out | ducks | description |"
    sep = "|---|---|---|---:|---:|:---:|---|"
    body_lines = [header, sep]
    for row in rows_list:
        desc = row.description
        if len(desc) > _DESC_MAX:
            desc = desc[: _DESC_MAX - 1].rstrip() + "…"
        # Escape pipes in descriptions to keep the column structure intact.
        desc = desc.replace("|", "\\|")
        ducks_cell = "Y" if row.ducks else ""
        body_lines.append(
            f"| {row.id} | {row.kind} | {row.chain_kind} | "
            f"{row.edges_in} | {row.edges_out} | {ducks_cell} | {desc} |"
        )
    return "\n".join(body_lines) + "\n"


def render_json(rows: Iterable[SourceCapability]) -> str:
    """Render rows as a JSON array of objects (sorted keys for stable diff)."""
    return json.dumps([asdict(row) for row in rows], sort_keys=True, indent=2) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print the audio source capability matrix from audio-topology.yaml.",
    )
    parser.add_argument(
        "--topology",
        type=Path,
        default=DEFAULT_TOPOLOGY_PATH,
        help=f"Path to audio-topology.yaml (default: {DEFAULT_TOPOLOGY_PATH})",
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of markdown.",
    )
    output_group.add_argument(
        "--markdown",
        action="store_true",
        help="Emit markdown (default).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        descriptor = TopologyDescriptor.from_yaml(args.topology)
    except FileNotFoundError:
        print(f"caps: topology descriptor not found: {args.topology}", file=sys.stderr)
        return 2
    rows = derive_capabilities(descriptor)
    if args.json:
        sys.stdout.write(render_json(rows))
    else:
        sys.stdout.write(render_markdown(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

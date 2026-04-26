"""Self-citation graph DOI minter — Phase 1 dry-run scaffold.

Per drop 5 §3 fresh-pattern #1: mint a Zenodo DOI for the DataCite
GraphQL query that resolves to Hapax's constellation graph. The query
string + its expected response shape together form a Zenodo deposit;
subsequent runs of the query produce version-DOIs under a stable
concept-DOI when the graph topology materially shifts.

Phase 1 (this module): scaffold + scan + material-change detector +
deposit-assembly preview. No actual Zenodo minting until ``--commit``
is implemented and operator authorizes per-run.

Phase 2 will wire actual concept-DOI mint + version-DOI mint on
material change + frontmatter writeback to the DataCite mirror.

Spec: ``agents/publication_bus/datacite_mirror.py`` (provides the
GraphQL snapshots) + drop-5 §3 fresh-pattern #1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)


DEFAULT_MIRROR_DIR = Path.home() / "hapax-state/datacite-mirror"
"""Where ``datacite_mirror.py`` writes per-day JSON snapshots."""

DEFAULT_GRAPH_DIR = Path.home() / "hapax-state/publications/self-citation-graph"
"""Where this module persists per-graph state.

- ``concept-doi.txt`` — minted on first run; stable across versions
- ``version-doi-history.jsonl`` — append-only history of version-DOIs
- ``last-fingerprint.txt`` — SHA-256 of last-deposited graph shape
"""

ZENODO_PASS_KEY = "zenodo/api-token"


def _latest_mirror_snapshot(mirror_dir: Path) -> Path | None:
    """Return the most recent DataCite mirror snapshot, or None if none."""
    if not mirror_dir.is_dir():
        return None
    snapshots = sorted(mirror_dir.glob("*.json"))
    return snapshots[-1] if snapshots else None


def graph_topology_fingerprint(snapshot_path: Path) -> str | None:
    """Compute a SHA-256 fingerprint of the graph's topology.

    Reads the raw GraphQL response, extracts the node-DOI set + the
    citation-count tuples, normalises ordering, and hashes. Two
    snapshots produce the same fingerprint when the topology is
    identical (DOIs + counts) — even if the query timestamp differs.
    """
    if not snapshot_path.is_file():
        return None
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("self_citation_graph: unparseable snapshot %s", snapshot_path)
        return None

    nodes = _extract_topology_nodes(data)
    if not nodes:
        return None
    canonical = json.dumps(sorted(nodes), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()


def _extract_topology_nodes(data: dict) -> list[tuple[str, int]]:
    """Pull (doi, citation_count) tuples from a DataCite GraphQL response."""
    nodes: list[tuple[str, int]] = []
    works = data.get("data", {}).get("works", {}).get("nodes", [])
    if not isinstance(works, list):
        return nodes
    for work in works:
        if not isinstance(work, dict):
            continue
        doi = work.get("doi")
        cites = work.get("citationCount", 0)
        if isinstance(doi, str) and isinstance(cites, int):
            nodes.append((doi, cites))
    return nodes


def material_change_detected(graph_dir: Path, current_fingerprint: str) -> bool:
    """Return True iff current fingerprint differs from last-deposited."""
    last_fp_file = graph_dir / "last-fingerprint.txt"
    if not last_fp_file.is_file():
        return True  # first run — always "changed" (will mint concept-DOI)
    try:
        last = last_fp_file.read_text(encoding="utf-8").strip()
    except OSError:
        return True
    return last != current_fingerprint


def assemble_deposit_metadata(
    *,
    snapshot_path: Path,
    fingerprint: str,
    is_first_version: bool,
) -> dict:
    """Build the Zenodo deposit metadata dict (Phase 1 — preview only)."""
    title = "Hapax constellation graph (DataCite GraphQL)"
    description = (
        "Self-citation graph derived from a parameterised DataCite GraphQL "
        "query against Hapax's authored works. Each version-DOI captures "
        "the graph topology at a specific snapshot; the concept-DOI is "
        "stable across versions. The graph evolution is itself the "
        "research artefact — refusal-as-data + infrastructure-as-argument."
    )
    return {
        "title": title,
        "description": description,
        "upload_type": "publication",
        "publication_type": "other",
        "keywords": [
            "constellation-graph",
            "self-citation",
            "datacite-graphql",
            "refusal-as-data",
            "infrastructure-as-argument",
        ],
        "snapshot_path": str(snapshot_path),
        "topology_fingerprint": fingerprint,
        "is_first_version": is_first_version,
    }


def render_dry_run_report(
    *,
    snapshot_path: Path | None,
    fingerprint: str | None,
    has_change: bool,
    metadata: dict | None,
) -> str:
    """Format the dry-run scan as an operator-readable report."""
    lines: list[str] = []
    lines.append("# Self-citation graph DOI dry-run")
    lines.append("")

    if snapshot_path is None:
        lines.append("(no DataCite mirror snapshot found — run hapax-datacite-mirror.timer first)")
        return "\n".join(lines)

    lines.append(f"Latest snapshot:    {snapshot_path}")
    lines.append(f"Topology fingerprint: {fingerprint}")
    lines.append(f"Material change:    {has_change}")
    lines.append("")

    if not has_change:
        lines.append("(no material change since last deposit; would skip mint)")
        return "\n".join(lines)

    if metadata is None:
        return "\n".join(lines)

    lines.append("## Would-mint Zenodo deposit")
    lines.append("")
    lines.append(f"- title:       {metadata['title']}")
    lines.append(f"- type:        {metadata['upload_type']}/{metadata['publication_type']}")
    lines.append(f"- first_version: {metadata['is_first_version']}")
    lines.append(f"- keywords:    {metadata['keywords']}")
    lines.append("")
    lines.append("Re-run with --commit to mint version-DOI + persist.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mirror-dir",
        type=Path,
        default=DEFAULT_MIRROR_DIR,
        help="DataCite mirror snapshots dir (default ~/hapax-state/datacite-mirror)",
    )
    parser.add_argument(
        "--graph-dir",
        type=Path,
        default=DEFAULT_GRAPH_DIR,
        help="Per-graph state dir (default ~/hapax-state/publications/self-citation-graph)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="EXPLICIT opt-in to mint Zenodo deposit (Phase 2 — not yet implemented)",
    )
    args = parser.parse_args(argv)

    snapshot = _latest_mirror_snapshot(args.mirror_dir)
    if snapshot is None:
        sys.stdout.write(
            render_dry_run_report(
                snapshot_path=None, fingerprint=None, has_change=False, metadata=None
            )
        )
        return 0

    fingerprint = graph_topology_fingerprint(snapshot)
    if fingerprint is None:
        sys.stdout.write(
            render_dry_run_report(
                snapshot_path=snapshot, fingerprint=None, has_change=False, metadata=None
            )
        )
        return 0

    has_change = material_change_detected(args.graph_dir, fingerprint)
    metadata = (
        assemble_deposit_metadata(
            snapshot_path=snapshot,
            fingerprint=fingerprint,
            is_first_version=not (args.graph_dir / "concept-doi.txt").is_file(),
        )
        if has_change
        else None
    )

    if args.commit:
        print(
            "# --commit recognised; minting loop is the Phase 2 sub-PR. "
            f"(snapshot={snapshot}, fingerprint={fingerprint[:12]}..., change={has_change})",
            file=sys.stderr,
        )
        _ = datetime.now(UTC)  # placeholder for future timestamp use
        return 0

    sys.stdout.write(
        render_dry_run_report(
            snapshot_path=snapshot,
            fingerprint=fingerprint,
            has_change=has_change,
            metadata=metadata,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

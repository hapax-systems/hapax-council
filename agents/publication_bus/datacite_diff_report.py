"""Persist DataCite mirror snapshot diffs into publication-bus state.

The mirror daemon writes daily GraphQL snapshots under
``~/hapax-state/datacite-mirror``. This module compares the two freshest
snapshots and stores JSON + Markdown diff artifacts under the existing
self-citation graph publication state directory:

``~/hapax-state/publications/self-citation-graph/diffs``.

It is intentionally local-state only. Public DOI minting remains the
explicit ``self_citation_graph_doi --commit`` path.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.publication_bus.datacite_mirror import DEFAULT_MIRROR_DIR, compute_diff

DEFAULT_GRAPH_DIFF_DIR = (
    Path.home() / "hapax-state" / "publications" / "self-citation-graph" / "diffs"
)
"""Canonical local publication-bus trail for DataCite graph diffs."""


def latest_snapshot_pair(mirror_dir: Path = DEFAULT_MIRROR_DIR) -> tuple[Path, Path] | None:
    """Return the previous/current snapshot paths, or ``None`` when unavailable."""
    if not mirror_dir.is_dir():
        return None
    snapshots = sorted(mirror_dir.glob("*.json"))
    if len(snapshots) < 2:
        return None
    return snapshots[-2], snapshots[-1]


def write_diff_artifacts(
    *,
    mirror_dir: Path = DEFAULT_MIRROR_DIR,
    output_dir: Path = DEFAULT_GRAPH_DIFF_DIR,
    generated_at: datetime | None = None,
) -> tuple[Path, Path] | None:
    """Write JSON + Markdown diff artifacts for the two freshest snapshots."""
    pair = latest_snapshot_pair(mirror_dir)
    if pair is None:
        return None
    previous_path, current_path = pair
    previous = _read_json(previous_path)
    current = _read_json(current_path)
    if previous is None or current is None:
        return None

    generated = generated_at or datetime.now(UTC)
    raw_diff = compute_diff(previous, current)
    report = _build_report(
        previous_path=previous_path,
        current_path=current_path,
        previous=previous,
        current=current,
        raw_diff=raw_diff,
        generated_at=generated,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / f"{current_path.stem}-diff"
    json_path = base.with_suffix(".json")
    markdown_path = base.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _build_report(
    *,
    previous_path: Path,
    current_path: Path,
    previous: dict[str, Any],
    current: dict[str, Any],
    raw_diff: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any]:
    added = sorted(raw_diff.get("added_dois") or [])
    removed = sorted(raw_diff.get("removed_dois") or [])
    citation_delta = {
        str(doi): int(delta)
        for doi, delta in sorted((raw_diff.get("citation_count_delta") or {}).items())
    }
    previous_nodes = _extract_nodes(previous)
    current_nodes = _extract_nodes(current)
    return {
        "generated_at": generated_at.isoformat(),
        "previous_snapshot": previous_path.name,
        "current_snapshot": current_path.name,
        "previous_work_count": len(previous_nodes),
        "current_work_count": len(current_nodes),
        "added_dois": added,
        "removed_dois": removed,
        "citation_count_delta": citation_delta,
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "citation_delta_count": len(citation_delta),
            "changed": bool(added or removed or citation_delta),
        },
    }


def _extract_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    person = (payload or {}).get("data", {}).get("person")
    if not isinstance(person, dict):
        return []
    works = person.get("works")
    if not isinstance(works, dict):
        return []
    nodes = works.get("nodes")
    return [node for node in nodes if isinstance(node, dict)] if isinstance(nodes, list) else []


def _render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# DataCite citation graph diff",
        "",
        f"Generated: {report['generated_at']}",
        f"Previous snapshot: {report['previous_snapshot']}",
        f"Current snapshot: {report['current_snapshot']}",
        "",
        "## Summary",
        "",
        f"- Previous work count: {report['previous_work_count']}",
        f"- Current work count: {report['current_work_count']}",
        f"- Added DOIs: {summary['added']}",
        f"- Removed DOIs: {summary['removed']}",
        f"- Citation-count deltas: {summary['citation_delta_count']}",
        f"- Changed: {summary['changed']}",
        "",
        "## Added DOIs",
        "",
    ]
    lines.extend(_bullet_lines(report["added_dois"]))
    lines.extend(["", "## Removed DOIs", ""])
    lines.extend(_bullet_lines(report["removed_dois"]))
    lines.extend(["", "## Citation-count Deltas", ""])
    deltas = report["citation_count_delta"]
    if deltas:
        lines.extend(f"- `{doi}`: {delta:+d}" for doi, delta in deltas.items())
    else:
        lines.append("- (none)")
    lines.append("")
    return "\n".join(lines)


def _bullet_lines(values: list[str]) -> list[str]:
    if not values:
        return ["- (none)"]
    return [f"- `{value}`" for value in values]


def main(argv: list[str] | None = None) -> int:
    """CLI entry for ``python -m agents.publication_bus.datacite_diff_report``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mirror-dir",
        type=Path,
        default=DEFAULT_MIRROR_DIR,
        help="DataCite mirror snapshots dir (default ~/hapax-state/datacite-mirror)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_GRAPH_DIFF_DIR,
        help=(
            "Diff artifact output dir "
            "(default ~/hapax-state/publications/self-citation-graph/diffs)"
        ),
    )
    args = parser.parse_args(argv)

    paths = write_diff_artifacts(mirror_dir=args.mirror_dir, output_dir=args.output_dir)
    if paths is None:
        print("no DataCite diff artifacts written; need at least two parseable snapshots")
        return 0
    json_path, markdown_path = paths
    print(f"wrote DataCite diff artifacts: {json_path} {markdown_path}")
    return 0


__all__ = [
    "DEFAULT_GRAPH_DIFF_DIR",
    "latest_snapshot_pair",
    "main",
    "write_diff_artifacts",
]


if __name__ == "__main__":
    raise SystemExit(main())

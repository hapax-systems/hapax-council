#!/usr/bin/env python3
"""LRR Phase 4 §3.7 data integrity lock — seal a research condition's data.

When the operator has accumulated the Phase 4 sample target for a
research condition, this script runs the three exports that lock
the collected data for post-hoc analysis:

1. **JSONL checksums** — sha256 on every ``reactor-log-YYYY-MM.jsonl``
   file under ``~/hapax-state/stream-archive/hls/**/`` that has at
   least one entry tagged with the target condition_id.

2. **Qdrant snapshot** — export all ``stream-reactions`` points with
   ``payload.condition_id == <target>`` to a tar.gz archive at
   ``~/hapax-state/research-registry/<condition_id>/qdrant-snapshot.tgz``
   with a top-level ``manifest.json`` documenting snapshot timestamp,
   point count, and Qdrant schema version.

3. **Langfuse score export** — query all scores with
   ``metadata.condition_id == <target>`` and dump one JSON line per
   score to ``~/hapax-state/research-registry/<condition_id>/langfuse-scores.jsonl``.
   This is the voice-grounding-DV half of the Condition A record.
   Omitting it would leave the voice channel analytically unreachable
   after the Phase 5 swap — Condition A and Condition A' would be
   compared only on stream-director reaction metrics.

All three checksums are recorded in
``~/hapax-state/research-registry/<condition_id>/data-checksums.txt``
as ``sha256  /absolute/path`` lines (one per file) so downstream
reviewers can verify end-to-end data integrity.

Exit codes::

    0  all three exports completed and checksums written
    1  argparse / environment error
    2  research-registry condition directory missing
    3  Qdrant unreachable or export failed
    4  Langfuse unreachable or export failed
    5  at least one JSONL file is missing sha256 readable state
    6  attempt to lock an already-locked condition without --force

Usage::

    scripts/lock-phase-a-condition.py <condition_id>
    scripts/lock-phase-a-condition.py <condition_id> --dry-run
    scripts/lock-phase-a-condition.py <condition_id> --force  # re-lock

Idempotence: the script refuses to overwrite an existing
``data-checksums.txt`` unless ``--force`` is passed. Dry-run prints
the actions it would take without writing any files.

Security: read-only against Qdrant and Langfuse. Writes only to the
condition's registry directory and to ``~/hapax-state/stream-archive/``
stats (glob walk).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_STATE_DIR = Path.home() / "hapax-state"
DEFAULT_REGISTRY_DIR = DEFAULT_STATE_DIR / "research-registry"
DEFAULT_STREAM_ARCHIVE_DIR = DEFAULT_STATE_DIR / "stream-archive"
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_QDRANT_COLLECTION = "stream-reactions"


@dataclass
class LockReport:
    condition_id: str
    started_at: str
    completed_at: str | None = None
    jsonl_files: list[dict[str, Any]] = field(default_factory=list)
    qdrant_path: str = ""
    qdrant_sha256: str = ""
    qdrant_point_count: int = 0
    langfuse_path: str = ""
    langfuse_sha256: str = ""
    langfuse_score_count: int = 0
    dry_run: bool = False
    errors: list[str] = field(default_factory=list)


def _sha256_file(path: Path) -> str:
    """Compute sha256 of a file's bytes. Streaming read so large files OK."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _jsonl_contains_condition(path: Path, condition_id: str) -> bool:
    """Scan a JSONL file for any entry tagged with the condition_id.

    Returns True on first match. Uses a cheap substring check first
    (avoids JSON parsing every line) then verifies with proper JSON
    parse if the substring is present.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if condition_id in line:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict) and entry.get("condition_id") == condition_id:
                        return True
        return False
    except OSError:
        return False


def collect_jsonl_checksums(
    condition_id: str,
    archive_root: Path,
) -> list[dict[str, Any]]:
    """Find every JSONL file under ``archive_root`` containing at least
    one entry tagged with ``condition_id`` and compute its sha256.
    """
    if not archive_root.exists():
        return []
    results: list[dict[str, Any]] = []
    for jsonl_path in sorted(archive_root.rglob("reactor-log-*.jsonl")):
        if not _jsonl_contains_condition(jsonl_path, condition_id):
            continue
        try:
            digest = _sha256_file(jsonl_path)
            size = jsonl_path.stat().st_size
        except OSError as exc:
            results.append(
                {
                    "path": str(jsonl_path),
                    "sha256": None,
                    "size_bytes": None,
                    "error": str(exc),
                }
            )
            continue
        results.append(
            {
                "path": str(jsonl_path),
                "sha256": digest,
                "size_bytes": size,
            }
        )
    return results


def export_qdrant_snapshot(
    condition_id: str,
    registry_condition_dir: Path,
    *,
    qdrant_url: str = DEFAULT_QDRANT_URL,
    collection: str = DEFAULT_QDRANT_COLLECTION,
    dry_run: bool = False,
) -> tuple[Path, str, int]:
    """Export Qdrant points filtered by condition_id to a tar.gz snapshot.

    Returns (archive_path, sha256, point_count). On dry-run, returns
    the expected path with empty sha256 + zero count.
    """
    archive_path = registry_condition_dir / "qdrant-snapshot.tgz"
    if dry_run:
        return archive_path, "", 0

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchValue
    except ImportError as exc:
        raise RuntimeError(f"qdrant-client not installed: {exc}") from exc

    client = QdrantClient(url=qdrant_url)
    filt = Filter(must=[FieldCondition(key="condition_id", match=MatchValue(value=condition_id))])

    # Scroll through all matching points with pagination.
    points: list[dict[str, Any]] = []
    offset = None
    while True:
        result, next_offset = client.scroll(
            collection_name=collection,
            scroll_filter=filt,
            limit=1024,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        for p in result:
            points.append(
                {
                    "id": p.id,
                    "payload": p.payload,
                    "vector": p.vector,
                }
            )
        if next_offset is None:
            break
        offset = next_offset

    manifest = {
        "condition_id": condition_id,
        "collection": collection,
        "exported_at": datetime.now(UTC).isoformat(),
        "point_count": len(points),
        "qdrant_url": qdrant_url,
    }

    registry_condition_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="qdrant-snapshot-") as tmpdir_s:
        tmpdir = Path(tmpdir_s)
        (tmpdir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        (tmpdir / "points.jsonl").write_text("\n".join(json.dumps(p, default=str) for p in points))

        with tarfile.open(archive_path, "w:gz") as tf:
            tf.add(tmpdir / "manifest.json", arcname="manifest.json")
            tf.add(tmpdir / "points.jsonl", arcname="points.jsonl")

    digest = _sha256_file(archive_path)
    return archive_path, digest, len(points)


def export_langfuse_scores(
    condition_id: str,
    registry_condition_dir: Path,
    *,
    dry_run: bool = False,
) -> tuple[Path, str, int]:
    """Export Langfuse scores filtered by metadata.condition_id.

    Returns (export_path, sha256, score_count). On dry-run, returns
    the expected path with empty sha256 + zero count.

    Langfuse's Python SDK's ``api.score.get`` interface is used to
    iterate with pagination. The exact API surface has varied across
    Langfuse versions; this function wraps any SDK exception as a
    RuntimeError to give the caller a single failure mode to handle.
    """
    export_path = registry_condition_dir / "langfuse-scores.jsonl"
    if dry_run:
        return export_path, "", 0

    try:
        from langfuse import Langfuse  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(f"langfuse SDK not installed: {exc}") from exc

    client = Langfuse()
    try:
        # Query API shape varies; wrap everything.
        page = 1
        count = 0
        registry_condition_dir.mkdir(parents=True, exist_ok=True)
        with export_path.open("w", encoding="utf-8") as f:
            while True:
                result = client.api.score.get(
                    name=None,
                    limit=100,
                    page=page,
                )
                items = getattr(result, "data", None) or []
                if not items:
                    break
                for score in items:
                    # Filter to scores whose metadata matches condition_id.
                    metadata = getattr(score, "metadata", None) or {}
                    if metadata.get("condition_id") != condition_id:
                        continue
                    f.write(
                        json.dumps(
                            {
                                "id": getattr(score, "id", None),
                                "trace_id": getattr(score, "trace_id", None),
                                "name": getattr(score, "name", None),
                                "value": getattr(score, "value", None),
                                "data_type": getattr(score, "data_type", None),
                                "comment": getattr(score, "comment", None),
                                "metadata": metadata,
                                "timestamp": str(getattr(score, "timestamp", None)),
                            },
                            default=str,
                        )
                        + "\n"
                    )
                    count += 1
                page += 1
                if len(items) < 100:
                    break
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Langfuse export failed: {exc}") from exc

    digest = _sha256_file(export_path)
    return export_path, digest, count


def write_checksums_file(
    registry_condition_dir: Path,
    report: LockReport,
) -> Path:
    """Write data-checksums.txt with one ``sha256  /path`` line per file."""
    lines: list[str] = []
    for jsonl in report.jsonl_files:
        if jsonl.get("sha256"):
            lines.append(f"{jsonl['sha256']}  {jsonl['path']}")
    if report.qdrant_sha256:
        lines.append(f"{report.qdrant_sha256}  {report.qdrant_path}")
    if report.langfuse_sha256:
        lines.append(f"{report.langfuse_sha256}  {report.langfuse_path}")
    checksums_path = registry_condition_dir / "data-checksums.txt"
    checksums_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = checksums_path.with_suffix(checksums_path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n" if lines else "")
    tmp.rename(checksums_path)
    return checksums_path


def lock_condition(args: argparse.Namespace) -> LockReport:
    report = LockReport(
        condition_id=args.condition_id,
        started_at=datetime.now(UTC).isoformat(),
        dry_run=args.dry_run,
    )

    registry_condition_dir = Path(args.registry_dir) / args.condition_id
    if not registry_condition_dir.exists():
        report.errors.append(f"registry condition directory missing: {registry_condition_dir}")
        return report

    checksums_path = registry_condition_dir / "data-checksums.txt"
    if checksums_path.exists() and not args.force and not args.dry_run:
        report.errors.append(
            f"data-checksums.txt already exists at {checksums_path}; pass --force to re-lock"
        )
        return report

    # Step 1 — JSONL checksums
    jsonl_files = collect_jsonl_checksums(args.condition_id, Path(args.stream_archive_dir) / "hls")
    report.jsonl_files = jsonl_files
    missing_hashes = [j for j in jsonl_files if not j.get("sha256")]
    if missing_hashes:
        report.errors.append(
            f"{len(missing_hashes)} JSONL files could not be hashed (see jsonl_files)"
        )

    # Step 2 — Qdrant snapshot
    try:
        qdrant_path, qdrant_sha, qdrant_count = export_qdrant_snapshot(
            args.condition_id,
            registry_condition_dir,
            qdrant_url=args.qdrant_url,
            collection=args.qdrant_collection,
            dry_run=args.dry_run,
        )
        report.qdrant_path = str(qdrant_path)
        report.qdrant_sha256 = qdrant_sha
        report.qdrant_point_count = qdrant_count
    except RuntimeError as exc:
        report.errors.append(f"Qdrant export failed: {exc}")

    # Step 3 — Langfuse score export
    try:
        lf_path, lf_sha, lf_count = export_langfuse_scores(
            args.condition_id, registry_condition_dir, dry_run=args.dry_run
        )
        report.langfuse_path = str(lf_path)
        report.langfuse_sha256 = lf_sha
        report.langfuse_score_count = lf_count
    except RuntimeError as exc:
        report.errors.append(f"Langfuse export failed: {exc}")

    # Step 4 — write checksums file (skipped on dry-run)
    if not args.dry_run and not report.errors:
        write_checksums_file(registry_condition_dir, report)

    report.completed_at = datetime.now(UTC).isoformat()
    return report


def _exit_code(report: LockReport) -> int:
    if not report.errors:
        return 0
    first = report.errors[0]
    if "condition directory missing" in first:
        return 2
    if "Qdrant" in first:
        return 3
    if "Langfuse" in first:
        return 4
    if "JSONL files could not be hashed" in first:
        return 5
    if "data-checksums.txt already exists" in first:
        return 6
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lock-phase-a-condition.py",
        description="LRR Phase 4 §3.7 data integrity lock: seal a research condition.",
    )
    p.add_argument("condition_id", help="Research condition_id to lock")
    p.add_argument(
        "--registry-dir",
        default=str(DEFAULT_REGISTRY_DIR),
        help=f"Research registry directory (default: {DEFAULT_REGISTRY_DIR})",
    )
    p.add_argument(
        "--stream-archive-dir",
        default=str(DEFAULT_STREAM_ARCHIVE_DIR),
        help=f"Stream archive directory (default: {DEFAULT_STREAM_ARCHIVE_DIR})",
    )
    p.add_argument(
        "--qdrant-url",
        default=DEFAULT_QDRANT_URL,
        help=f"Qdrant URL (default: {DEFAULT_QDRANT_URL})",
    )
    p.add_argument(
        "--qdrant-collection",
        default=DEFAULT_QDRANT_COLLECTION,
        help=f"Qdrant collection (default: {DEFAULT_QDRANT_COLLECTION})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute what would be done without writing any files",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing data-checksums.txt (re-lock)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit JSON report instead of human-readable output",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = lock_condition(args)

    if args.as_json:
        print(json.dumps(asdict(report), indent=2))
    else:
        status = "OK" if not report.errors else "FAIL"
        print(f"lock-phase-a-condition: {status} (condition={report.condition_id})")
        if args.dry_run:
            print("  (dry-run — no files written)")
        print(f"  JSONL files: {len(report.jsonl_files)}")
        if report.qdrant_path:
            print(f"  Qdrant snapshot: {report.qdrant_path} ({report.qdrant_point_count} points)")
        if report.langfuse_path:
            print(
                f"  Langfuse export: {report.langfuse_path} ({report.langfuse_score_count} scores)"
            )
        for err in report.errors:
            print(f"  ERR: {err}", file=sys.stderr)

    return _exit_code(report)


if __name__ == "__main__":
    sys.exit(main())

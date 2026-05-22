"""Daily semantic trace archiver.

Queries Chronicle for semantic_interpretation events and writes
a zstd-compressed JSONL snapshot to disk for longitudinal retention.

Usage:
    uv run python -m agents.semantic_trace_archiver
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import zstandard

from shared.chronicle import CHRONICLE_FILE, query

ARCHIVE_DIR = Path.home() / "hapax-state" / "semantic-traces"
RETENTION_DAYS = 90


def archive_day(
    *,
    chronicle_path: Path = CHRONICLE_FILE,
    archive_dir: Path = ARCHIVE_DIR,
    since: float | None = None,
    until: float | None = None,
) -> Path:
    now = time.time()
    if until is None:
        until = now
    if since is None:
        since = until - 86400

    events = query(
        since=since,
        until=until,
        evidence_class="semantic_interpretation",
        limit=50_000,
        path=chronicle_path,
    )

    archive_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.fromtimestamp(until, tz=UTC).strftime("%Y-%m-%d")
    out_path = archive_dir / f"{date_str}.jsonl.zst"

    lines = "\n".join(ev.to_json() for ev in reversed(events))
    compressed = zstandard.ZstdCompressor(level=3).compress(lines.encode("utf-8"))
    out_path.write_bytes(compressed)

    _rotate(archive_dir)
    return out_path


def _rotate(archive_dir: Path) -> None:
    cutoff = time.time() - (RETENTION_DAYS * 86400)
    for f in archive_dir.glob("*.jsonl.zst"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def main() -> None:
    out = archive_day()
    print(f"Archived to {out}")


if __name__ == "__main__":
    main()

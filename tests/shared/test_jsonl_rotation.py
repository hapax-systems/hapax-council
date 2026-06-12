from __future__ import annotations

import logging
from pathlib import Path

from shared.jsonl_rotation import iter_jsonl_lines_with_gzip_archives


def test_iter_jsonl_lines_with_gzip_archives_warns_and_continues(
    tmp_path: Path,
    caplog,
) -> None:
    path = tmp_path / "events.jsonl"
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    (archive_dir / "public-events.bad.jsonl.gz").write_text("not gzip", encoding="utf-8")
    path.write_text('{"event_id":"active"}\n', encoding="utf-8")
    logger = logging.getLogger("tests.jsonl_rotation")

    with caplog.at_level(logging.WARNING, logger=logger.name):
        lines = list(
            iter_jsonl_lines_with_gzip_archives(
                path,
                archive_glob="public-events.*.jsonl.gz",
                logger=logger,
            )
        )

    assert lines == ['{"event_id":"active"}\n']
    assert "jsonl archive read failed" in caplog.text


def test_iter_jsonl_lines_with_gzip_archives_reads_pending_rotating_slices(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    pending = tmp_path / "events.jsonl.20260612T010203Z.123.rotating"
    offset_sidecar = tmp_path / "events.jsonl.20260612T010203Z.123.rotating.archive-offset"
    pending.write_text('{"event_id":"pending"}\n', encoding="utf-8")
    offset_sidecar.write_text("22", encoding="utf-8")
    path.write_text('{"event_id":"active"}\n', encoding="utf-8")

    lines = list(
        iter_jsonl_lines_with_gzip_archives(
            path,
            archive_glob="public-events.*.jsonl.gz",
        )
    )

    assert lines == ['{"event_id":"pending"}\n', '{"event_id":"active"}\n']

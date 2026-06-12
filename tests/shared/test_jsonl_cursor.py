"""Tests for identity-aware JSONL byte cursor helpers."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest import mock

from shared.jsonl_cursor import read_jsonl_cursor, reconcile_jsonl_cursor, write_jsonl_cursor


def _state_path(cursor: Path) -> Path:
    return cursor.with_name(f"{cursor.name}.state.json")


def test_read_cursor_recovers_byte_offset_from_state_when_cursor_file_corrupt(tmp_path, caplog):
    cursor = tmp_path / "events.cursor"
    cursor.write_text("not-an-int", encoding="utf-8")
    _state_path(cursor).write_text(
        json.dumps({"cursor": 17, "st_dev": 1, "st_ino": 2, "st_size": 23}),
        encoding="utf-8",
    )
    logger = logging.getLogger("tests.jsonl_cursor")

    with caplog.at_level(logging.WARNING, logger=logger.name):
        resolved = read_jsonl_cursor(cursor, logger=logger, label="event")

    assert resolved == 17
    assert "recovered byte offset 17 from identity state" in caplog.text


def test_reconcile_resets_when_identity_changes_at_same_size(tmp_path, caplog):
    source = tmp_path / "events.jsonl"
    cursor = tmp_path / "events.cursor"
    source.write_text("abcd", encoding="utf-8")
    source_stat = source.stat()
    cursor.write_text(str(source_stat.st_size), encoding="utf-8")
    _state_path(cursor).write_text(
        json.dumps(
            {
                "cursor": source_stat.st_size,
                "st_dev": int(source_stat.st_dev),
                "st_ino": int(source_stat.st_ino) + 1,
                "st_size": int(source_stat.st_size),
            }
        ),
        encoding="utf-8",
    )

    logger = logging.getLogger("tests.jsonl_cursor")
    with caplog.at_level(logging.WARNING, logger=logger.name):
        resolved = reconcile_jsonl_cursor(
            cursor,
            source,
            source_stat.st_size,
            source_stat=source_stat,
            logger=logger,
            label="event",
        )

    assert resolved == 0
    assert cursor.read_text(encoding="utf-8") == "0"
    assert "cursor reset after rotation" in caplog.text


def test_reconcile_adopts_legacy_cursor_without_identity_state(tmp_path, caplog):
    source = tmp_path / "events.jsonl"
    cursor = tmp_path / "events.cursor"
    source.write_text("abcdef", encoding="utf-8")
    source_stat = source.stat()
    cursor.write_text(str(source_stat.st_size), encoding="utf-8")

    logger = logging.getLogger("tests.jsonl_cursor")
    with caplog.at_level(logging.WARNING, logger=logger.name):
        resolved = reconcile_jsonl_cursor(
            cursor,
            source,
            source_stat.st_size,
            source_stat=source_stat,
            logger=logger,
            label="event",
        )

    assert resolved == source_stat.st_size
    assert cursor.read_text(encoding="utf-8") == str(source_stat.st_size)
    state = json.loads(_state_path(cursor).read_text(encoding="utf-8"))
    assert state["st_ino"] == source_stat.st_ino
    assert "cursor adopted legacy identity" in caplog.text


def test_reconcile_resets_legacy_cursor_after_shrink_without_identity_state(tmp_path, caplog):
    source = tmp_path / "events.jsonl"
    cursor = tmp_path / "events.cursor"
    source.write_text("abc", encoding="utf-8")
    cursor.write_text("6", encoding="utf-8")

    logger = logging.getLogger("tests.jsonl_cursor")
    with caplog.at_level(logging.WARNING, logger=logger.name):
        resolved = reconcile_jsonl_cursor(
            cursor,
            source,
            6,
            source_stat=source.stat(),
            logger=logger,
            label="event",
        )

    assert resolved == 0
    assert cursor.read_text(encoding="utf-8") == "0"
    assert "cursor reset after legacy shrink without identity state" in caplog.text


def test_reconcile_logs_corrupt_state_and_adopts_in_range_cursor(tmp_path, caplog):
    source = tmp_path / "events.jsonl"
    cursor = tmp_path / "events.cursor"
    source.write_text("abcdef", encoding="utf-8")
    cursor.write_text("3", encoding="utf-8")
    _state_path(cursor).write_text("{broken", encoding="utf-8")

    logger = logging.getLogger("tests.jsonl_cursor")
    with caplog.at_level(logging.WARNING, logger=logger.name):
        resolved = reconcile_jsonl_cursor(
            cursor,
            source,
            3,
            source_stat=source.stat(),
            logger=logger,
            label="event",
        )

    assert resolved == 3
    assert cursor.read_text(encoding="utf-8") == "3"
    state = json.loads(_state_path(cursor).read_text(encoding="utf-8"))
    assert state["st_ino"] == source.stat().st_ino
    assert "cursor state unreadable" in caplog.text
    assert "cursor adopted unreadable identity state" in caplog.text


def test_write_cursor_logs_and_swallows_oserror(tmp_path, caplog):
    source = tmp_path / "events.jsonl"
    cursor = tmp_path / "events.cursor"
    source.write_text("abcd", encoding="utf-8")
    logger = logging.getLogger("tests.jsonl_cursor")

    with (
        mock.patch.object(Path, "write_text", side_effect=OSError("boom")),
        caplog.at_level(logging.WARNING, logger=logger.name),
    ):
        write_jsonl_cursor(cursor, 4, source_path=source, logger=logger)

    assert not cursor.exists()
    assert "cursor write failed" in caplog.text

"""Tests for identity-aware JSONL byte cursor helpers."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest import mock

from shared.jsonl_cursor import reconcile_jsonl_cursor, write_jsonl_cursor


def _state_path(cursor: Path) -> Path:
    return cursor.with_name(f"{cursor.name}.state.json")


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


def test_reconcile_resets_legacy_cursor_without_identity_state(tmp_path, caplog):
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

    assert resolved == 0
    assert cursor.read_text(encoding="utf-8") == "0"
    state = json.loads(_state_path(cursor).read_text(encoding="utf-8"))
    assert state["st_ino"] == source_stat.st_ino
    assert "cursor reset without identity state" in caplog.text


def test_reconcile_logs_corrupt_state_and_resets_cursor(tmp_path, caplog):
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

    assert resolved == 0
    assert cursor.read_text(encoding="utf-8") == "0"
    assert "cursor state unreadable" in caplog.text
    assert "cursor reset without identity state" in caplog.text


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

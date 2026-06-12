"""Cursor helpers for byte-offset JSONL bus consumers."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

type FileIdentity = tuple[int, int]


def jsonl_file_identity(source_stat: os.stat_result) -> FileIdentity:
    return (int(source_stat.st_dev), int(source_stat.st_ino))


def jsonl_byte_evidence_ref(
    source_path: Path, byte_offset: int, source_stat: os.stat_result
) -> str:
    st_dev, st_ino = jsonl_file_identity(source_stat)
    return f"{source_path}#dev={st_dev}:ino={st_ino}:byte={byte_offset}"


def read_jsonl_cursor(cursor_path: Path) -> int:
    try:
        return int(cursor_path.read_text().strip())
    except (OSError, ValueError):
        return 0


def _state_path(cursor_path: Path) -> Path:
    return cursor_path.with_name(f"{cursor_path.name}.state.json")


def _read_cursor_identity(
    cursor_path: Path,
    *,
    logger: logging.Logger | None = None,
) -> tuple[FileIdentity | None, bool]:
    state_path = _state_path(cursor_path)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        return (int(state["st_dev"]), int(state["st_ino"])), True
    except FileNotFoundError:
        return None, False
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        if logger is not None:
            logger.warning(
                "cursor state unreadable at %s; resetting to avoid stale cursor",
                state_path,
            )
        return None, False


def write_jsonl_cursor(
    cursor_path: Path,
    byte_offset: int,
    *,
    source_path: Path | None = None,
    source_stat: os.stat_result | None = None,
    logger: logging.Logger | None = None,
) -> None:
    try:
        cursor_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cursor_path.with_suffix(".tmp")
        tmp.write_text(str(byte_offset), encoding="utf-8")
        tmp.replace(cursor_path)
        if source_stat is None and source_path is not None:
            source_stat = source_path.stat()
        if source_stat is not None:
            state_path = _state_path(cursor_path)
            state_tmp = state_path.with_suffix(".tmp")
            state = {
                "cursor": byte_offset,
                "st_dev": int(source_stat.st_dev),
                "st_ino": int(source_stat.st_ino),
                "st_size": int(source_stat.st_size),
            }
            state_tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
            state_tmp.replace(state_path)
    except OSError:
        if logger is not None:
            logger.warning("cursor write failed at %s", cursor_path, exc_info=True)


def reconcile_jsonl_cursor(
    cursor_path: Path,
    source_path: Path,
    byte_offset: int,
    *,
    source_stat: os.stat_result,
    logger: logging.Logger,
    label: str,
) -> int:
    previous_identity, has_previous_identity = _read_cursor_identity(cursor_path, logger=logger)
    current_identity = jsonl_file_identity(source_stat)
    if not has_previous_identity and byte_offset > 0:
        logger.warning(
            "%s cursor reset without identity state: path=%s size=%d cursor=%d",
            label,
            source_path,
            source_stat.st_size,
            byte_offset,
        )
        write_jsonl_cursor(
            cursor_path,
            0,
            source_path=source_path,
            source_stat=source_stat,
            logger=logger,
        )
        return 0
    if previous_identity is not None and previous_identity != current_identity:
        logger.warning(
            "%s cursor reset after rotation: path=%s size=%d cursor=%d",
            label,
            source_path,
            source_stat.st_size,
            byte_offset,
        )
        write_jsonl_cursor(
            cursor_path,
            0,
            source_path=source_path,
            source_stat=source_stat,
            logger=logger,
        )
        return 0
    if byte_offset > source_stat.st_size:
        logger.warning(
            "%s cursor reset after shrink: path=%s size=%d cursor=%d",
            label,
            source_path,
            source_stat.st_size,
            byte_offset,
        )
        write_jsonl_cursor(
            cursor_path,
            0,
            source_path=source_path,
            source_stat=source_stat,
            logger=logger,
        )
        return 0
    return byte_offset

"""Cursor helpers for byte-offset JSONL bus consumers."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Literal

type FileIdentity = tuple[int, int]
type CursorIdentityStatus = Literal["present", "missing", "unreadable"]


def jsonl_file_identity(source_stat: os.stat_result) -> FileIdentity:
    return (int(source_stat.st_dev), int(source_stat.st_ino))


def jsonl_byte_evidence_ref(
    source_path: Path, byte_offset: int, source_stat: os.stat_result
) -> str:
    st_dev, st_ino = jsonl_file_identity(source_stat)
    return f"{source_path}#dev={st_dev}:ino={st_ino}:byte={byte_offset}"


def _read_cursor_from_state(cursor_path: Path) -> int | None:
    try:
        state = json.loads(_state_path(cursor_path).read_text(encoding="utf-8"))
        cursor = int(state["cursor"])
    except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return cursor if cursor >= 0 else None


def read_jsonl_cursor(
    cursor_path: Path,
    *,
    missing_default: int = 0,
    unreadable_default: int = 0,
    logger: logging.Logger | None = None,
    label: str = "jsonl",
) -> int:
    try:
        value = int(cursor_path.read_text(encoding="utf-8").strip())
        if value < 0:
            raise ValueError(f"negative cursor: {value}")
        return value
    except FileNotFoundError:
        return missing_default
    except (OSError, ValueError) as exc:
        state_cursor = _read_cursor_from_state(cursor_path)
        if state_cursor is not None:
            if logger is not None:
                logger.warning(
                    "%s cursor file unreadable at %s (%s); recovered byte offset %d "
                    "from identity state; operator action: inspect or replace the cursor "
                    "file if this repeats",
                    label,
                    cursor_path,
                    exc,
                    state_cursor,
                )
            return state_cursor
        if logger is not None:
            logger.warning(
                "%s cursor file unreadable at %s (%s); using fallback byte offset %d; "
                "operator action: inspect or replace the cursor file before restarting "
                "if replay would be unsafe",
                label,
                cursor_path,
                exc,
                unreadable_default,
            )
        return unreadable_default


def _state_path(cursor_path: Path) -> Path:
    return cursor_path.with_name(f"{cursor_path.name}.state.json")


def _read_cursor_identity(
    cursor_path: Path,
    *,
    logger: logging.Logger | None = None,
) -> tuple[FileIdentity | None, CursorIdentityStatus]:
    state_path = _state_path(cursor_path)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        return (int(state["st_dev"]), int(state["st_ino"])), "present"
    except FileNotFoundError:
        return None, "missing"
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        if logger is not None:
            logger.warning(
                "cursor state unreadable at %s; rewriting source identity from the current "
                "file when the offset is safe; operator action: inspect the state sidecar "
                "if this repeats",
                state_path,
            )
        return None, "unreadable"


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
    previous_identity, identity_status = _read_cursor_identity(cursor_path, logger=logger)
    current_identity = jsonl_file_identity(source_stat)
    if identity_status == "unreadable" and byte_offset > 0:
        if byte_offset > source_stat.st_size:
            logger.warning(
                "%s cursor reset after unreadable identity shrink: path=%s size=%d cursor=%d; "
                "operator action: confirm rotation or inspect the cursor sidecar if unexpected",
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
        write_jsonl_cursor(
            cursor_path,
            byte_offset,
            source_path=source_path,
            source_stat=source_stat,
            logger=logger,
        )
        logger.warning(
            "%s cursor adopted unreadable identity state: path=%s size=%d cursor=%d; "
            "operator action: inspect the cursor sidecar if this repeats",
            label,
            source_path,
            source_stat.st_size,
            byte_offset,
        )
        return byte_offset
    if identity_status == "missing" and byte_offset > 0:
        if byte_offset > source_stat.st_size:
            logger.warning(
                "%s cursor reset after legacy shrink without identity state: "
                "path=%s size=%d cursor=%d; operator action: confirm rotation or inspect "
                "the cursor file if unexpected",
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
        write_jsonl_cursor(
            cursor_path,
            byte_offset,
            source_path=source_path,
            source_stat=source_stat,
            logger=logger,
        )
        logger.warning(
            "%s cursor adopted legacy identity: path=%s size=%d cursor=%d; "
            "operator action: no manual action needed unless this repeats",
            label,
            source_path,
            source_stat.st_size,
            byte_offset,
        )
        return byte_offset
    if previous_identity is not None and previous_identity != current_identity:
        logger.warning(
            "%s cursor reset after rotation: path=%s size=%d cursor=%d; "
            "operator action: confirm rotation or inspect the source file if unexpected",
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
            "%s cursor reset after shrink: path=%s size=%d cursor=%d; "
            "operator action: confirm rotation or inspect the source file if unexpected",
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

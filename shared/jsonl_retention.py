"""Bounded JSONL retention helpers for state and witness ledgers."""

from __future__ import annotations

import fcntl
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def _exclusive_path_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _clean_lines(lines: Iterable[str]) -> list[str]:
    return [line.rstrip("\n") for line in lines if line.rstrip("\n")]


def _read_existing_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []


def _replace_lines(path: Path, lines: list[str]) -> None:
    tmp = path.with_name(f"{path.name}.tmp")
    payload = "\n".join(lines)
    if payload:
        payload += "\n"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def append_bounded_jsonl_lines(path: Path, lines: Iterable[str], *, max_lines: int) -> None:
    """Append lines while keeping only the newest ``max_lines`` JSONL rows."""

    if max_lines <= 0:
        raise ValueError("max_lines must be positive")
    incoming = _clean_lines(lines)
    if not incoming:
        return
    with _exclusive_path_lock(path):
        retained = [*_read_existing_lines(path), *incoming][-max_lines:]
        _replace_lines(path, retained)


def append_bounded_jsonl_line(path: Path, line: str, *, max_lines: int) -> None:
    """Append one line while keeping only the newest ``max_lines`` JSONL rows."""

    append_bounded_jsonl_lines(path, (line,), max_lines=max_lines)


def rewrite_bounded_jsonl_lines(path: Path, lines: Iterable[str], *, max_lines: int) -> None:
    """Rewrite a JSONL file with the provided lines capped to ``max_lines``."""

    if max_lines <= 0:
        raise ValueError("max_lines must be positive")
    with _exclusive_path_lock(path):
        _replace_lines(path, _clean_lines(lines)[-max_lines:])

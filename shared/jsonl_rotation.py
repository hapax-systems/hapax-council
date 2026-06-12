"""Small JSONL rotation/read helpers for domain-owned ledgers."""

from __future__ import annotations

import gzip
import logging
from collections.abc import Iterator
from pathlib import Path

DEFAULT_DOMAIN_JSONL_MAX_BYTES = 16 * 1024 * 1024
DEFAULT_DOMAIN_JSONL_KEEP_GENERATIONS = 4


def generation_path(path: Path, generation: int) -> Path:
    return path.with_name(f"{path.name}.{generation}")


def retained_jsonl_paths(path: Path, keep_generations: int) -> list[Path]:
    return [
        *(generation_path(path, generation) for generation in range(keep_generations, 0, -1)),
        path,
    ]


def maybe_rotate_jsonl(
    path: Path,
    *,
    max_bytes: int = DEFAULT_DOMAIN_JSONL_MAX_BYTES,
    keep_generations: int = DEFAULT_DOMAIN_JSONL_KEEP_GENERATIONS,
) -> None:
    if max_bytes <= 0 or keep_generations <= 0:
        return
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return
    if size < max_bytes:
        return

    generation_path(path, keep_generations).unlink(missing_ok=True)
    for generation in range(keep_generations - 1, 0, -1):
        source = generation_path(path, generation)
        if source.exists():
            source.replace(generation_path(path, generation + 1))
    path.replace(generation_path(path, 1))


def append_rotated_jsonl_line(
    path: Path,
    line: str,
    *,
    max_bytes: int = DEFAULT_DOMAIN_JSONL_MAX_BYTES,
    keep_generations: int = DEFAULT_DOMAIN_JSONL_KEEP_GENERATIONS,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    maybe_rotate_jsonl(path, max_bytes=max_bytes, keep_generations=keep_generations)
    # jsonl-rotation: exempt(domain rotation; readers scan retained generations)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line.rstrip("\n") + "\n")


def iter_retained_jsonl_lines(
    path: Path,
    *,
    keep_generations: int = DEFAULT_DOMAIN_JSONL_KEEP_GENERATIONS,
) -> Iterator[str]:
    for retained_path in retained_jsonl_paths(path, keep_generations):
        try:
            with retained_path.open(encoding="utf-8", errors="replace") as fh:
                yield from fh
        except FileNotFoundError:
            continue


def iter_jsonl_lines_with_gzip_archives(
    path: Path,
    *,
    archive_dir: Path | None = None,
    archive_glob: str,
    logger: logging.Logger | None = None,
) -> Iterator[str]:
    resolved_archive_dir = archive_dir or path.parent / "archive"
    for archive_path in sorted(resolved_archive_dir.glob(archive_glob)):
        try:
            with gzip.open(archive_path, "rt", encoding="utf-8") as fh:
                yield from fh
        except OSError as exc:
            if logger is not None:
                logger.warning("jsonl archive read failed: %s (%s)", archive_path, exc)
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            yield from fh
    except FileNotFoundError:
        return

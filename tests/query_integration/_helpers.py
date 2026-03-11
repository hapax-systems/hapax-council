"""Shared helpers for query integration tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from shared.ops_db import build_ops_db

TEST_DATA = Path(__file__).resolve().parent.parent.parent / "test-data"
POPULATED_PROFILES = TEST_DATA / "profiles-populated"
EMPTY_PROFILES = TEST_DATA / "profiles-empty"
POPULATED_DEV_STORY_DB = TEST_DATA / "dev-story-populated.db"
EMPTY_DEV_STORY_DB = TEST_DATA / "dev-story-empty.db"


def make_ops_db(profiles_dir: Path) -> sqlite3.Connection:
    """Build an in-memory ops SQLite database from profiles."""
    return build_ops_db(profiles_dir)


def open_dev_story_db(path: Path) -> sqlite3.Connection:
    """Open a dev-story database in read-only mode."""
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def skip_if_missing(path: Path, *, allow_empty: bool = False) -> None:
    """Raise pytest.skip if the path doesn't exist.

    If allow_empty is False (default), also skip if a directory contains
    only .gitkeep. Use allow_empty=True for empty-state tests where the
    directory existing but being empty is the intended test condition.
    """
    import pytest

    if not path.exists():
        pytest.skip(f"Test data not found: {path}")
    if not allow_empty and path.is_dir() and not any(p.name != ".gitkeep" for p in path.iterdir()):
        pytest.skip(f"Test data directory empty: {path}")

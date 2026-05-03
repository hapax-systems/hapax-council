"""Tests for the shared rail idempotency store.

cc-task: ``jr-patreon-rail-idempotency-pin`` (extracts pattern from #2322).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared._rail_idempotency import (
    IdempotencyError,
    IdempotencyStore,
    default_idempotency_db_path,
)


def test_store_first_insert_returns_true(tmp_path: Path) -> None:
    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    assert store.record_or_skip("evt_first") is True


def test_store_duplicate_returns_false(tmp_path: Path) -> None:
    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    assert store.record_or_skip("evt_a") is True
    assert store.record_or_skip("evt_a") is False


def test_store_distinct_ids_all_inserted(tmp_path: Path) -> None:
    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    for i in range(5):
        assert store.record_or_skip(f"evt_{i}") is True


def test_store_has_seen(tmp_path: Path) -> None:
    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    store.record_or_skip("evt_x")
    assert store.has_seen("evt_x") is True
    assert store.has_seen("evt_y") is False


def test_store_empty_event_id_raises(tmp_path: Path) -> None:
    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    with pytest.raises(IdempotencyError, match="non-empty string"):
        store.record_or_skip("")


@pytest.mark.parametrize("non_string", [None, 123, b"bytes", []])
def test_store_non_string_event_id_raises(tmp_path: Path, non_string: object) -> None:
    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    with pytest.raises(IdempotencyError, match="non-empty string"):
        store.record_or_skip(non_string)  # type: ignore[arg-type]


def test_store_persists_across_constructions(tmp_path: Path) -> None:
    db = tmp_path / "idem.db"
    a = IdempotencyStore(db_path=db)
    a.record_or_skip("evt_persist")

    b = IdempotencyStore(db_path=db)
    assert b.has_seen("evt_persist") is True
    assert b.record_or_skip("evt_persist") is False


def test_store_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c" / "idem.db"
    assert not nested.parent.exists()
    store = IdempotencyStore(db_path=nested)
    assert store.record_or_skip("evt_nested") is True
    assert nested.parent.is_dir()


def test_store_records_first_seen_iso(tmp_path: Path) -> None:
    """The first_seen_at timestamp is stored (forensic value)."""
    import sqlite3

    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    seen_at = datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC)
    store.record_or_skip("evt_with_ts", first_seen_at=seen_at)

    with sqlite3.connect(str(store.db_path)) as conn:
        row = conn.execute(
            "SELECT first_seen_at_iso FROM rail_webhook_events WHERE event_id = ?",
            ("evt_with_ts",),
        ).fetchone()
    assert row[0] == "2026-05-03T12:00:00+00:00"


@pytest.mark.parametrize(
    "rail",
    [
        "stripe-payment-link",
        "patreon",
        "ko-fi",
        "buy-me-a-coffee",
        "liberapay",
        "open-collective",
        "github-sponsors",
        "mercury",
        "modern-treasury",
        "treasury-prime",
    ],
)
def test_default_db_path_per_rail_namespace(
    rail: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each rail gets its own subdirectory under HAPAX_HOME."""
    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    p = default_idempotency_db_path(rail)
    assert p == tmp_path / rail / "idempotency.db"


def test_default_db_path_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HAPAX_HOME", raising=False)
    p = default_idempotency_db_path("test-rail")
    assert p == Path.home() / "hapax-state" / "test-rail" / "idempotency.db"


def test_module_carries_no_outbound_calls() -> None:
    """No outbound HTTP imports — sqlite is local disk only."""
    import ast

    import shared._rail_idempotency as mod

    src_tree = ast.parse(Path(mod.__file__).read_text())
    forbidden_modules = {"requests", "httpx", "aiohttp"}
    for node in ast.walk(src_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top not in forbidden_modules, f"forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            assert top not in forbidden_modules, f"forbidden import from: {node.module}"
            assert node.module != "urllib.request", "forbidden import: urllib.request"

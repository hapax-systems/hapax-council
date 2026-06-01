"""Tests for the coord-reform migration capability + ledger backfill (NEW-6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.case_migration import (
    MIGRATION_NAMESPACE,
    backfill_from_ledger,
    mint_capability,
)
from shared.coord_event_log import CoordEventLog


def _coord_log(tmp_path: Path) -> CoordEventLog:
    return CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )


def _write_ledger(path: Path) -> None:
    rows = [
        {
            "ts": "2026-05-31T00:00:00Z",
            "kind": "stage_transition",
            "role": "alpha",
            "task_id": "task-a",
            "authority_case": "CASE-X",
            "from_stage": "S6",
            "to_stage": "S7",
        },
        {
            "ts": "2026-05-31T00:00:01Z",
            "kind": "scope_widen",
            "role": "alpha",
            "task_id": "task-a",
            "added": ["shared/x.py"],
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_backfill_appends_legacy_rows(tmp_path: Path) -> None:
    log = _coord_log(tmp_path)
    ledger = tmp_path / "authority-case-ledger.jsonl"
    _write_ledger(ledger)

    cap = mint_capability(grantor="operator")
    appended = backfill_from_ledger(ledger, capability=cap, event_log=log)
    assert appended == 2

    events = log.replay().events
    assert {e.event_type for e in events} == {"legacy.stage_transition", "legacy.scope_widen"}
    assert {e.subject for e in events} == {"task-a"}
    assert any(e.authority_case == "CASE-X" for e in events)


def test_backfill_is_idempotent(tmp_path: Path) -> None:
    log = _coord_log(tmp_path)
    ledger = tmp_path / "authority-case-ledger.jsonl"
    _write_ledger(ledger)
    cap = mint_capability(grantor="operator")

    assert backfill_from_ledger(ledger, capability=cap, event_log=log) == 2
    # Re-running the same ledger appends nothing new (rows dedupe by content).
    assert backfill_from_ledger(ledger, capability=cap, event_log=log) == 0
    assert len(log.replay().events) == 2


def test_backfill_skips_blank_and_malformed_lines(tmp_path: Path) -> None:
    log = _coord_log(tmp_path)
    ledger = tmp_path / "authority-case-ledger.jsonl"
    ledger.write_text(
        '\n{"ts":"t","kind":"k","task_id":"task-z"}\n{not json}\n"a string row"\n',
        encoding="utf-8",
    )
    cap = mint_capability(grantor="operator")
    assert backfill_from_ledger(ledger, capability=cap, event_log=log) == 1


def test_backfill_missing_ledger_returns_zero(tmp_path: Path) -> None:
    cap = mint_capability(grantor="operator")
    assert (
        backfill_from_ledger(
            tmp_path / "absent.jsonl", capability=cap, event_log=_coord_log(tmp_path)
        )
        == 0
    )


def test_expired_capability_is_rejected(tmp_path: Path) -> None:
    log = _coord_log(tmp_path)
    ledger = tmp_path / "authority-case-ledger.jsonl"
    _write_ledger(ledger)
    cap = mint_capability(grantor="operator", ttl_seconds=-1.0)
    with pytest.raises(ValueError, match="expired"):
        backfill_from_ledger(ledger, capability=cap, event_log=log)
    assert log.replay().events == ()  # nothing written before the capability check


def test_wrong_namespace_is_rejected(tmp_path: Path) -> None:
    log = _coord_log(tmp_path)
    ledger = tmp_path / "authority-case-ledger.jsonl"
    _write_ledger(ledger)
    cap = mint_capability(grantor="operator", namespace="other")
    with pytest.raises(ValueError, match="namespace"):
        backfill_from_ledger(ledger, capability=cap, event_log=log)


def test_namespace_constant_matches_default() -> None:
    assert mint_capability(grantor="operator").namespace == MIGRATION_NAMESPACE

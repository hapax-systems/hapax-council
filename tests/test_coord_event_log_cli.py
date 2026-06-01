"""Tests for the coord_event_log daemon-writer CLI (reform unit K single writer).

The SBCL coordination kernel performs real ``coord.*`` commits by shelling out to
``python -m shared.coord_event_log append ...`` (collapse the Lisp/Python writer
split — one canonical writer). These tests pin that entrypoint: a durable append,
the JSON receipt contract, ``--origin`` stamping (the non-cli marker the kernel
sets), idempotent retries, and the exit codes the Lisp caller branches on
(0 => commit / make-receipt, non-zero => daemon-down fallback).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from shared.coord_event_log import main

BASE = [
    "--event-type",
    "coord.task.claim",
    "--actor",
    "eta",
    "--subject",
    "reform-coord-verbs-unit-k-20260601",
    "--origin",
    "coord-verb",
]


def _append(argv: list[str], capsys) -> tuple[int, dict | None, str]:
    rc = main(["append", *argv])
    captured = capsys.readouterr()
    receipt = json.loads(captured.out) if captured.out.strip() else None
    return rc, receipt, captured.err


def _ledger_args(tmp_path: Path) -> list[str]:
    return [
        "--db-path",
        str(tmp_path / "ledger.db"),
        "--jsonl-path",
        str(tmp_path / "ledger.jsonl"),
        "--spool-dir",
        str(tmp_path / "spool"),
    ]


def _rows(tmp_path: Path) -> list[dict]:
    con = sqlite3.connect(tmp_path / "ledger.db")
    try:
        cur = con.execute(
            "SELECT event_type, actor, subject, authority_case, parent_spec, payload_json "
            "FROM coord_events ORDER BY sequence"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    finally:
        con.close()


def test_append_writes_real_event(tmp_path: Path, capsys) -> None:
    rc, receipt, _ = _append(
        BASE + ["--payload", '{"lane":"eta"}', *_ledger_args(tmp_path)], capsys
    )
    assert rc == 0
    assert receipt is not None
    assert receipt["appended"] is True
    assert receipt["spooled"] is False
    assert receipt["sequence"] == 1
    assert receipt["duplicate"] is False
    assert receipt["errors"] == []

    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "coord.task.claim"
    assert rows[0]["actor"] == "eta"
    assert rows[0]["subject"] == "reform-coord-verbs-unit-k-20260601"
    payload = json.loads(rows[0]["payload_json"])
    assert payload["origin"] == "coord-verb"  # non-cli origin (AC2)
    assert payload["lane"] == "eta"


def test_origin_flag_wins_over_payload(tmp_path: Path, capsys) -> None:
    # --origin is the authoritative non-cli marker; it overrides any payload origin.
    rc, _, _ = _append(
        BASE
        + ["--payload", '{"verb":"coord.task.claim","origin":"ignored"}', *_ledger_args(tmp_path)],
        capsys,
    )
    assert rc == 0
    payload = json.loads(_rows(tmp_path)[0]["payload_json"])
    assert payload["origin"] == "coord-verb"
    assert payload["verb"] == "coord.task.claim"


def test_event_id_is_idempotent(tmp_path: Path, capsys) -> None:
    args = [*BASE, "--event-id", "coord-verb-fixedid", "--payload", "{}", *_ledger_args(tmp_path)]
    rc1, r1, _ = _append(args, capsys)
    rc2, r2, _ = _append(args, capsys)
    assert rc1 == 0 and r1 is not None and r1["duplicate"] is False and r1["appended"] is True
    assert rc2 == 0 and r2 is not None and r2["duplicate"] is True
    assert len(_rows(tmp_path)) == 1  # the retry is a tolerated no-op, not a second row


def test_authority_case_and_parent_spec_recorded(tmp_path: Path, capsys) -> None:
    rc, _, _ = _append(
        BASE
        + [
            "--authority-case",
            "CASE-SBCL-CLOG-COORD-001",
            "--parent-spec",
            "coordination-reform-master-design.md",
            "--payload",
            "{}",
            *_ledger_args(tmp_path),
        ],
        capsys,
    )
    assert rc == 0
    row = _rows(tmp_path)[0]
    assert row["authority_case"] == "CASE-SBCL-CLOG-COORD-001"
    assert row["parent_spec"] == "coordination-reform-master-design.md"


def test_non_object_payload_is_rejected(tmp_path: Path, capsys) -> None:
    rc, receipt, err = _append(BASE + ["--payload", "[1,2,3]", *_ledger_args(tmp_path)], capsys)
    assert rc == 2  # the Lisp caller treats non-zero as "fall back to daemon-down path"
    assert receipt is None
    assert "invalid_event" in err
    assert not (tmp_path / "ledger.db").exists()


def test_malformed_json_payload_is_rejected(tmp_path: Path, capsys) -> None:
    rc, _, err = _append(BASE + ["--payload", "not-json", *_ledger_args(tmp_path)], capsys)
    assert rc == 2
    assert "invalid_event" in err


def test_default_event_log_honors_hapax_coord_dir(tmp_path: Path, capsys, monkeypatch) -> None:
    # With no explicit path args the CLI uses default_event_log(), which redirects
    # under HAPAX_COORD_DIR — the isolation seam the live verb relies on to target
    # the real ~/.cache/hapax/coord ledger in production.
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path))
    rc, receipt, _ = _append([*BASE, "--payload", "{}"], capsys)
    assert rc == 0
    assert receipt is not None
    assert Path(receipt["db_path"]) == tmp_path / "ledger.db"
    assert (tmp_path / "ledger.db").exists()


def test_jsonl_mirror_written(tmp_path: Path, capsys) -> None:
    rc, _, _ = _append(BASE + ["--payload", "{}", *_ledger_args(tmp_path)], capsys)
    assert rc == 0
    lines = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    mirror = json.loads(lines[0])
    assert mirror["event_type"] == "coord.task.claim"
    assert mirror["payload"]["origin"] == "coord-verb"

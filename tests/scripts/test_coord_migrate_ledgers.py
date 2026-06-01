"""Tests for scripts/coord-migrate-ledgers CLI."""

from __future__ import annotations

import importlib.util
import json
import shutil
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "coord-migrate-ledgers"
_loader = SourceFileLoader("coord_migrate_ledgers", str(_SCRIPT))
_spec = importlib.util.spec_from_loader("coord_migrate_ledgers", _loader)
assert _spec is not None
mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(mod)


def _make_ledger(root: Path, slot: str) -> Path:
    directory = root / f"hapax-council--{slot}" / "evidence"
    directory.mkdir(parents=True)
    path = directory / "authority-case-ledger.jsonl"
    path.write_text(
        json.dumps(
            {
                "ts": "2026-05-31T00:00:00Z",
                "kind": "stage_transition",
                "task_id": f"task-{slot}",
                "authority_case": "CASE-Y",
                "from_stage": "S6",
                "to_stage": "S7",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_migrate_discovers_and_backfills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    root = tmp_path / "root"
    _make_ledger(root, "a")
    _make_ledger(root, "b")

    assert mod.main(["--root", str(root)]) == 0
    from shared.coord_event_log import default_event_log

    subjects = {e.subject for e in default_event_log().replay().events}
    assert {"task-a", "task-b"} <= subjects


def test_migrate_no_ledgers_returns_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    # pytest's tmp_path is repo-resident and retained across runs, so defend the
    # "no ledgers" precondition against a prior run's leftover discovery tree.
    empty = tmp_path / "no-ledgers-here"
    shutil.rmtree(empty, ignore_errors=True)
    assert mod._discover(empty) == []
    assert mod.main(["--root", str(empty)]) == 1


def test_migrate_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    root = tmp_path / "root"
    _make_ledger(root, "a")

    assert mod.main(["--root", str(root), "--dry-run"]) == 0
    assert "dry-run" in capsys.readouterr().out
    from shared.coord_event_log import default_event_log

    assert default_event_log().replay().events == ()

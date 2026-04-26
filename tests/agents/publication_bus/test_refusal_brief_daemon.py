"""Tests for ``agents.publication_bus.refusal_brief_daemon``.

Phase 2 dry-run scanner pairs with the cred-arrival of
``zenodo/api-token``. Tests cover scan output, dry-run reporting,
--commit gate (token absence + presence stub).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agents.publication_bus.refusal_brief_daemon import (
    main,
    render_dry_run_report,
    scan_all_refused,
)
from agents.publication_bus.refusal_brief_publisher import RefusedTaskSummary


def _seed_refused(path: Path, slug: str, *, automation_status: str = "REFUSED") -> None:
    fm = {
        "type": "cc-task",
        "task_id": slug,
        "title": f"REFUSED: {slug}",
        "automation_status": automation_status,
        "refusal_reason": "single_user axiom prohibits this surface",
    }
    path.write_text(f"---\n{yaml.safe_dump(fm)}---\n# body\n", encoding="utf-8")


def test_scan_all_refused_walks_active_and_closed(tmp_path: Path):
    active = tmp_path / "active"
    closed = tmp_path / "closed"
    active.mkdir()
    closed.mkdir()
    _seed_refused(active / "a.md", "a")
    _seed_refused(closed / "b.md", "b")
    _seed_refused(active / "c.md", "c", automation_status="OFFERED")  # skipped

    summaries = scan_all_refused(tmp_path)
    assert {s.task_id for s in summaries} == {"a", "b"}


def test_scan_returns_empty_for_missing_vault(tmp_path: Path):
    # Non-existent base — daemon should not crash
    summaries = scan_all_refused(tmp_path / "nonexistent")
    assert summaries == []


def test_render_report_with_zero_summaries():
    report = render_dry_run_report([])
    assert "Scan found:       0" in report
    assert "no refused cc-tasks found" in report


def test_render_report_with_summaries():
    s = RefusedTaskSummary(
        task_id="leverage-twitter",
        title="REFUSED: leverage Twitter",
        refusal_reason="single_user + ToS-prohibits-bots",
        file_path=Path("/tmp/x.md"),
    )
    report = render_dry_run_report([s])
    assert "Scan found:       1" in report
    assert "leverage-twitter" in report
    assert "single_user" in report
    assert "Re-run with --commit" in report


def test_main_dry_run_default(tmp_path: Path, capsys):
    active = tmp_path / "active"
    active.mkdir()
    _seed_refused(active / "a.md", "a")
    rc = main(["--vault-base", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Refusal Brief Zenodo-deposit dry-run" in captured.out


def test_main_commit_without_token_aborts(tmp_path: Path, capsys, monkeypatch):
    from agents.publication_bus import refusal_brief_daemon as m

    monkeypatch.setattr(m, "_read_pass_value", lambda _k: None)
    rc = m.main(["--vault-base", str(tmp_path), "--commit"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "ABORT" in captured.err
    assert "zenodo/api-token" in captured.err


def test_main_commit_with_token_acknowledges_unimplemented(tmp_path: Path, capsys, monkeypatch):
    from agents.publication_bus import refusal_brief_daemon as m

    monkeypatch.setattr(m, "_read_pass_value", lambda _k: "fake-token")
    rc = m.main(["--vault-base", str(tmp_path), "--commit"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "not yet implemented" in captured.err

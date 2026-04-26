"""Tests for ``agents.marketing.refusal_annex_bridgy_daemon``."""

from __future__ import annotations

from pathlib import Path

from agents.marketing.refusal_annex_bridgy_daemon import (
    AnnexFanoutTarget,
    main,
    render_dry_run_report,
    scan_refusal_annexes,
)


def test_scan_finds_annex_markdowns(tmp_path: Path):
    (tmp_path / "refusal-annex-bandcamp.md").write_text("x", encoding="utf-8")
    (tmp_path / "refusal-annex-discogs.md").write_text("x", encoding="utf-8")
    # Non-annex file should not be picked up
    (tmp_path / "other.md").write_text("x", encoding="utf-8")
    targets = scan_refusal_annexes(tmp_path)
    assert {t.slug for t in targets} == {"bandcamp", "discogs"}


def test_scan_returns_empty_for_missing_dir(tmp_path: Path):
    targets = scan_refusal_annexes(tmp_path / "absent")
    assert targets == []


def test_scan_returns_empty_for_dir_with_no_annexes(tmp_path: Path):
    (tmp_path / "unrelated.txt").write_text("x", encoding="utf-8")
    targets = scan_refusal_annexes(tmp_path)
    assert targets == []


def test_target_carries_weblog_url(tmp_path: Path):
    (tmp_path / "refusal-annex-stripe-kyc.md").write_text("x", encoding="utf-8")
    targets = scan_refusal_annexes(tmp_path)
    assert len(targets) == 1
    assert "hapax.weblog.lol" in targets[0].weblog_url
    assert targets[0].weblog_url.endswith("/stripe-kyc")


def test_render_with_targets():
    target = AnnexFanoutTarget(
        slug="bandcamp",
        source_path=Path("/tmp/refusal-annex-bandcamp.md"),
        weblog_url="https://hapax.weblog.lol/refusal-annex/bandcamp",
    )
    report = render_dry_run_report([target])
    assert "Scan found:       1" in report
    assert "bandcamp" in report
    assert "Re-run with --commit" in report


def test_render_with_zero_targets():
    report = render_dry_run_report([])
    assert "Scan found:       0" in report
    assert "no refusal-annex" in report


def test_main_dry_run(tmp_path: Path, capsys):
    (tmp_path / "refusal-annex-x.md").write_text("x", encoding="utf-8")
    rc = main(["--publications-dir", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "dry-run" in captured.out
    assert "refusal-annex-x" in captured.out


def test_main_commit_acknowledges_unimplemented(tmp_path: Path, capsys):
    rc = main(["--publications-dir", str(tmp_path), "--commit"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Phase 2.5 sub-PR" in captured.err


def test_skips_files_without_slug(tmp_path: Path):
    """Edge case: empty slug after prefix removal."""
    # "refusal-annex-.md" has slug == ""
    (tmp_path / "refusal-annex-.md").write_text("x", encoding="utf-8")
    targets = scan_refusal_annexes(tmp_path)
    assert targets == []

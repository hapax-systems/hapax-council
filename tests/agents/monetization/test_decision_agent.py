"""Tests for the monetization decision agent."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from agents.monetization.decision_agent import (
    ValueBraidEntry,
    build_recommendation,
    deposit_to_inbox,
    load_value_braid_entries,
    run,
)
from shared.preprint_artifact import ApprovalState


def _write_braid_entry(braid_dir: Path, slug: str, monetary_value: float) -> None:
    (braid_dir / f"{slug}.json").write_text(
        json.dumps({"slug": slug, "title": f"Test {slug}", "monetary_value": monetary_value})
    )


def test_load_value_braid_entries_from_dir(tmp_path: Path) -> None:
    _write_braid_entry(tmp_path, "entry-a", 0.8)
    _write_braid_entry(tmp_path, "entry-b", 0.2)
    entries = load_value_braid_entries(tmp_path)
    assert len(entries) == 2
    assert entries[0].slug == "entry-a"
    assert entries[0].monetary_value == 0.8


def test_load_value_braid_entries_missing_dir(tmp_path: Path) -> None:
    entries = load_value_braid_entries(tmp_path / "nonexistent")
    assert entries == []


def test_load_value_braid_entries_skips_malformed(tmp_path: Path) -> None:
    _write_braid_entry(tmp_path, "good", 0.5)
    (tmp_path / "bad.json").write_text("not valid json{{{")
    entries = load_value_braid_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0].slug == "good"


def test_build_recommendation_creates_draft_artifact() -> None:
    entry = ValueBraidEntry(slug="test", title="Test Title", monetary_value=0.9)
    artifact = build_recommendation(entry, ["github-sponsors", "ko-fi"])
    assert artifact.slug == "monetization-rec-test"
    assert artifact.title == "Test Title"
    assert artifact.surfaces_targeted == ["github-sponsors", "ko-fi"]
    assert artifact.approval == ApprovalState.DRAFT


def test_build_recommendation_uses_slug_as_title_fallback() -> None:
    entry = ValueBraidEntry(slug="fallback-test", monetary_value=0.7)
    artifact = build_recommendation(entry, ["github-sponsors"])
    assert artifact.title == "fallback-test"


def test_deposit_to_inbox_writes_json(tmp_path: Path) -> None:
    entry = ValueBraidEntry(slug="deposit-test", title="Deposit", monetary_value=0.8)
    artifact = build_recommendation(entry, ["github-sponsors"])
    dest = deposit_to_inbox(artifact, tmp_path)
    assert dest.exists()
    loaded = json.loads(dest.read_text())
    assert loaded["slug"] == "monetization-rec-deposit-test"
    assert loaded["approval"] == "draft"


def test_deposit_creates_inbox_dir(tmp_path: Path) -> None:
    inbox = tmp_path / "nested" / "inbox"
    entry = ValueBraidEntry(slug="mkdir-test", title="Mkdir", monetary_value=0.5)
    artifact = build_recommendation(entry, ["ko-fi"])
    dest = deposit_to_inbox(artifact, inbox)
    assert dest.exists()


def test_run_filters_below_min_score(tmp_path: Path) -> None:
    braid_dir = tmp_path / "braid"
    braid_dir.mkdir()
    inbox_dir = tmp_path / "inbox"
    _write_braid_entry(braid_dir, "low", 0.1)
    _write_braid_entry(braid_dir, "high", 0.9)

    with patch(
        "agents.monetization.decision_agent.select_revenue_surfaces",
        return_value=["github-sponsors"],
    ):
        results = run(braid_dir=braid_dir, inbox_dir=inbox_dir, min_score=0.4)

    assert len(results) == 1
    assert results[0].slug == "high"


def test_run_dry_run_does_not_deposit(tmp_path: Path) -> None:
    braid_dir = tmp_path / "braid"
    braid_dir.mkdir()
    inbox_dir = tmp_path / "inbox"
    _write_braid_entry(braid_dir, "dry", 0.8)

    with patch(
        "agents.monetization.decision_agent.select_revenue_surfaces",
        return_value=["github-sponsors"],
    ):
        results = run(braid_dir=braid_dir, inbox_dir=inbox_dir, dry_run=True)

    assert len(results) == 1
    assert results[0].deposited_at is None
    assert not inbox_dir.exists()


def test_run_skips_entries_with_no_ready_surfaces(tmp_path: Path) -> None:
    braid_dir = tmp_path / "braid"
    braid_dir.mkdir()
    inbox_dir = tmp_path / "inbox"
    _write_braid_entry(braid_dir, "no-surfaces", 0.9)

    with patch(
        "agents.monetization.decision_agent.select_revenue_surfaces",
        return_value=[],
    ):
        results = run(braid_dir=braid_dir, inbox_dir=inbox_dir)

    assert results == []


def test_agent_never_calls_publish():
    """ISAP constraint: agent must not call Publisher.publish() directly."""
    import ast
    from pathlib import Path

    source = Path("agents/monetization/decision_agent.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "publish":
            if isinstance(node.value, ast.Name):
                msg = f"Found .publish() call on {node.value.id} at line {node.lineno}"
                raise AssertionError(msg)

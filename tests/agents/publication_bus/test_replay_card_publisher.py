"""Tests for the replay card marketplace publisher."""

from __future__ import annotations

import json
from pathlib import Path

from agents.publication_bus.replay_card_publisher import (
    ReplayCardPublisher,
    validate_card,
)
from shared.replay_demo_card import ReplayDemoCard


def _make_card(**overrides) -> ReplayDemoCard:
    defaults = dict(
        event_id="evt-001",
        public_url="https://example.com/replay/001",
        replay_title="Test Replay",
        chapter_label="Chapter 1",
        chapter_timecode="00:05:30",
        frame_uri="/frames/001.jpg",
        frame_kind="thumbnail",
        provenance_token="prov-abc123",
        provenance_evidence_refs=("evidence:archive:001",),
        rights_class="operator_original",
        privacy_class="public_safe",
        n1_explanation="This replay demonstrates the n=1 epistemic lab in action.",
        suggested_audience="grant reviewers",
        programme_id="prog-001",
        broadcast_id="bc-001",
    )
    defaults.update(overrides)
    return ReplayDemoCard(**defaults)


def test_validate_card_passes_complete_card() -> None:
    card = _make_card()
    assert validate_card(card) == []


def test_validate_card_catches_missing_event_id() -> None:
    card = _make_card(event_id="")
    blockers = validate_card(card)
    assert "event_id:missing" in blockers


def test_validate_card_catches_missing_provenance() -> None:
    card = _make_card(provenance_token=None, provenance_evidence_refs=())
    blockers = validate_card(card)
    assert "provenance:missing" in blockers


def test_validate_card_accepts_provenance_evidence_refs_alone() -> None:
    card = _make_card(provenance_token=None, provenance_evidence_refs=("evidence:a",))
    assert validate_card(card) == []


def test_validate_card_catches_missing_n1_explanation() -> None:
    card = _make_card(n1_explanation="")
    blockers = validate_card(card)
    assert "n1_explanation:missing" in blockers


def test_publish_card_refuses_incomplete_card(tmp_path: Path) -> None:
    publisher = ReplayCardPublisher(output_dir=tmp_path)
    card = _make_card(event_id="", provenance_token=None, provenance_evidence_refs=())
    result = publisher.publish_card(card, "catalog")
    assert result.refused is True
    assert "event_id:missing" in result.detail
    assert "provenance:missing" in result.detail


def test_publish_card_writes_manifest(tmp_path: Path) -> None:
    publisher = ReplayCardPublisher(output_dir=tmp_path)
    card = _make_card()
    result = publisher.publish_card(card, "catalog")
    assert result.ok is True
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    manifest = json.loads(files[0].read_text())
    assert manifest["event_id"] == "evt-001"
    assert manifest["surface"] == "catalog"
    assert manifest["rights_class"] == "operator_original"
    assert manifest["n1_explanation"] != ""


def test_publish_card_refuses_non_allowlisted_surface(tmp_path: Path) -> None:
    publisher = ReplayCardPublisher(output_dir=tmp_path)
    card = _make_card()
    result = publisher.publish_card(card, "private-vip-access")
    assert result.refused is True


def test_publish_card_emits_to_all_allowed_surfaces(tmp_path: Path) -> None:
    publisher = ReplayCardPublisher(output_dir=tmp_path)
    card = _make_card()
    for surface in ("catalog", "demo", "grant", "residency", "marketplace"):
        result = publisher.publish_card(card, surface)
        assert result.ok is True, f"Failed for surface: {surface}"
    assert len(list(tmp_path.glob("*.json"))) == 5

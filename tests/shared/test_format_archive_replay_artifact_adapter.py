"""Tests for shared.format_archive_replay_artifact_adapter."""

from __future__ import annotations

from shared.format_archive_replay_artifact_adapter import (
    ArtifactStatus,
    PrivacyClass,
    ProgrammeRunRef,
    RightsClass,
    adapt_programme_run,
)

PROVENANCE = "a" * 32


def _make_run(
    *,
    run_id: str = "run-001",
    rights: RightsClass = RightsClass.OPERATOR_OWNED,
    privacy: PrivacyClass = PrivacyClass.FULLY_PUBLIC,
    provenance: str | None = PROVENANCE,
    public_event_link: str | None = "urn:hapax:event:test",
    grounding_question: str | None = None,
) -> ProgrammeRunRef:
    return ProgrammeRunRef(
        run_id=run_id,
        programme_id="prog-test",
        broadcast_id="broadcast-01",
        event_refs=("ev-1",),
        chapter_refs=("ch-1", "ch-2"),
        frame_refs=("frame-1",),
        archive_refs=("archive-1",),
        grounding_question=grounding_question,
        rights_class=rights,
        privacy_class=privacy,
        provenance_token=provenance,
        public_event_link=public_event_link,
    )


def test_eligible_run_produces_candidates() -> None:
    result = adapt_programme_run(_make_run())
    assert result.replay_card is not None
    assert result.replay_card.status == ArtifactStatus.CANDIDATE
    assert result.zine_logbook is not None
    assert result.zine_logbook.status == ArtifactStatus.CANDIDATE
    assert not result.blocked_reasons


def test_uncleared_rights_blocks() -> None:
    result = adapt_programme_run(_make_run(rights=RightsClass.UNCLEARED))
    assert result.replay_card is not None
    assert result.replay_card.status == ArtifactStatus.BLOCKED
    assert "rights_class" in result.replay_card.blocked_reason


def test_unanonymized_privacy_blocks() -> None:
    result = adapt_programme_run(_make_run(privacy=PrivacyClass.UNANONYMIZED))
    assert result.zine_logbook is not None
    assert result.zine_logbook.status == ArtifactStatus.BLOCKED


def test_missing_provenance_blocks() -> None:
    result = adapt_programme_run(_make_run(provenance=None))
    assert "missing_provenance_token" in result.blocked_reasons


def test_missing_public_event_link_blocks() -> None:
    result = adapt_programme_run(_make_run(public_event_link=None))
    assert "missing_public_event_link" in result.blocked_reasons


def test_grounding_question_in_replay_title() -> None:
    result = adapt_programme_run(_make_run(grounding_question="What is enactivism?"))
    assert result.replay_card is not None
    assert "enactivism" in result.replay_card.title


def test_zine_logbook_populates_structure() -> None:
    result = adapt_programme_run(_make_run())
    assert result.zine_logbook is not None
    assert result.zine_logbook.tier_sheets == ("ch-1", "ch-2")
    assert result.zine_logbook.condition_stills == ("frame-1",)
    assert PROVENANCE in result.zine_logbook.provenance_pages


def test_multiple_blockers_accumulated() -> None:
    result = adapt_programme_run(
        _make_run(rights=RightsClass.UNCLEARED, provenance=None, public_event_link=None)
    )
    assert len(result.blocked_reasons) == 3

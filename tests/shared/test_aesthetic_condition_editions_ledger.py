"""Tests for the aesthetic condition editions ledger.

cc-task: aesthetic-condition-editions-ledger.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.aesthetic_condition_editions_ledger import (
    AestheticConditionEditionsLedger,
    CapturePublicEventInput,
    EditionBlocker,
    EditionKind,
    EditionMetadata,
    PrivacyClass,
    RightsClass,
    SourceSubstrate,
    SurfaceLane,
    auto_capture_edition_from_input,
    evaluate_edition_eligibility_from_input,
)

_PROVENANCE_TOKEN = "a" * 32  # any 32+ hex chars satisfies the pattern


def _metadata(**overrides) -> EditionMetadata:
    payload = {
        "edition_id": "edition-research-001",
        "kind": EditionKind.STILL,
        "condition_id": "rc-curiosity-2026-05-02",
        "timestamp": datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        "broadcast_id": "broadcast-2026-05-02-001",
        "programme_id": "programme-2026-05-02-001",
        "surface_lane": SurfaceLane.OVERHEAD,
        "frame_ref": "frame:hls/segment-12345.ts#frame-42",
        "rights_class": RightsClass.OPERATOR_OWNED,
        "privacy_class": PrivacyClass.FULLY_PUBLIC,
        "provenance_token": _PROVENANCE_TOKEN,
        "source_substrates": (SourceSubstrate.LIVESTREAM_ARCHIVE,),
        "public_event_link": "public-event:replay:abc123",
    }
    payload.update(overrides)
    return EditionMetadata(**payload)


def _candidate(**overrides) -> CapturePublicEventInput:
    payload = {
        "public_event_id": "abc123",
        "public_event_link": "public-event:replay:abc123",
        "broadcast_id": "broadcast-2026-05-02-001",
        "programme_id": "programme-2026-05-02-001",
        "condition_id": "rc-curiosity-2026-05-02",
        "surface_lane": SurfaceLane.OVERHEAD,
        "frame_ref": "frame:hls/segment-12345.ts#frame-42",
        "rights_class": RightsClass.OPERATOR_OWNED,
        "privacy_class": PrivacyClass.FULLY_PUBLIC,
        "provenance_token": _PROVENANCE_TOKEN,
        "source_substrates": (SourceSubstrate.LIVESTREAM_ARCHIVE,),
        "captured_at": datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        "suggested_kind": EditionKind.STILL,
    }
    payload.update(overrides)
    return CapturePublicEventInput(**payload)


def test_minimal_edition_metadata_constructs():
    m = _metadata()
    assert m.edition_id == "edition-research-001"
    assert m.kind is EditionKind.STILL
    assert m.privacy_class is PrivacyClass.FULLY_PUBLIC


def test_all_seven_edition_kinds_constructible():
    for kind in EditionKind:
        m = _metadata(kind=kind, edition_id=f"edition-{kind.value}".replace("_", "-"))
        assert m.kind is kind


def test_required_field_set_matches_acceptance():
    m = _metadata()
    # Pydantic v2.11 deprecated instance access of ``model_fields``; use the
    # class attribute so V3 doesn't break the assertion.
    fields = set(type(m).model_fields.keys())
    expected = {
        "edition_id",
        "kind",
        "condition_id",
        "timestamp",
        "broadcast_id",
        "programme_id",
        "surface_lane",
        "frame_ref",
        "rights_class",
        "privacy_class",
        "provenance_token",
        "source_substrates",
        "public_event_link",
    }
    assert expected.issubset(fields)


def test_uncleared_rights_blocks_creation():
    with pytest.raises(Exception, match="uncleared_rights"):
        _metadata(rights_class=RightsClass.UNCLEARED)


def test_third_party_rights_risky_blocks_creation():
    with pytest.raises(Exception, match="third_party_rights_risky"):
        _metadata(rights_class=RightsClass.THIRD_PARTY_RIGHTS_RISKY)


def test_album_cover_without_explicit_rights_blocks_creation():
    with pytest.raises(Exception, match="album_cover_no_explicit_rights"):
        _metadata(rights_class=RightsClass.ALBUM_COVER_NO_EXPLICIT_RIGHTS)


def test_raw_private_frame_blocks_creation():
    with pytest.raises(Exception, match="raw_private_frame"):
        _metadata(privacy_class=PrivacyClass.RAW_PRIVATE_FRAME)


def test_unanonymized_private_blocks_creation():
    with pytest.raises(Exception, match="unanonymized_private"):
        _metadata(privacy_class=PrivacyClass.UNANONYMIZED_PRIVATE)


def test_missing_provenance_token_rejected_by_pattern():
    with pytest.raises(Exception):
        _metadata(provenance_token="")


def test_missing_public_event_link_rejected():
    with pytest.raises(Exception):
        _metadata(public_event_link="")


def test_missing_source_substrates_rejected():
    with pytest.raises(Exception):
        _metadata(source_substrates=())


def test_dry_run_eligibility_passes_clean_candidate():
    verdict = evaluate_edition_eligibility_from_input(_candidate())
    assert verdict.allowed is True
    assert verdict.blockers == ()


def test_dry_run_eligibility_blocks_uncleared_rights():
    verdict = evaluate_edition_eligibility_from_input(
        _candidate(rights_class=RightsClass.UNCLEARED)
    )
    assert verdict.allowed is False
    assert EditionBlocker.UNCLEARED_RIGHTS in verdict.blockers


def test_dry_run_eligibility_blocks_missing_provenance_token():
    verdict = evaluate_edition_eligibility_from_input(_candidate(provenance_token=None))
    assert verdict.allowed is False
    assert EditionBlocker.MISSING_PROVENANCE_TOKEN in verdict.blockers


def test_dry_run_eligibility_blocks_missing_substrates():
    verdict = evaluate_edition_eligibility_from_input(_candidate(source_substrates=()))
    assert verdict.allowed is False
    assert EditionBlocker.MISSING_SOURCE_SUBSTRATES in verdict.blockers


def test_auto_capture_creates_edition_for_clean_candidate():
    edition = auto_capture_edition_from_input(_candidate())
    assert isinstance(edition, EditionMetadata)
    assert edition.kind is EditionKind.STILL
    assert edition.condition_id == "rc-curiosity-2026-05-02"


def test_auto_capture_refuses_missing_provenance():
    with pytest.raises(Exception, match="provenance_token"):
        auto_capture_edition_from_input(_candidate(provenance_token=None))


def test_auto_capture_refuses_uncleared_rights():
    with pytest.raises(Exception, match="uncleared_rights"):
        auto_capture_edition_from_input(_candidate(rights_class=RightsClass.UNCLEARED))


def test_auto_capture_refuses_raw_private_frame():
    with pytest.raises(Exception, match="raw_private_frame"):
        auto_capture_edition_from_input(_candidate(privacy_class=PrivacyClass.RAW_PRIVATE_FRAME))


def test_ledger_groups_by_kind():
    ledger = AestheticConditionEditionsLedger(
        generated_at=datetime.now(tz=UTC),
        editions=(
            _metadata(edition_id="edition-still-1"),
            _metadata(edition_id="edition-loop-1", kind=EditionKind.LOOP),
            _metadata(edition_id="edition-still-2"),
        ),
    )
    stills = ledger.by_kind(EditionKind.STILL)
    assert len(stills) == 2
    loops = ledger.by_kind(EditionKind.LOOP)
    assert len(loops) == 1


def test_ledger_groups_by_rights():
    ledger = AestheticConditionEditionsLedger(
        generated_at=datetime.now(tz=UTC),
        editions=(
            _metadata(edition_id="edition-op-1"),
            _metadata(edition_id="edition-pd-1", rights_class=RightsClass.PUBLIC_DOMAIN),
        ),
    )
    operator_owned = ledger.by_rights(RightsClass.OPERATOR_OWNED)
    public_domain = ledger.by_rights(RightsClass.PUBLIC_DOMAIN)
    assert len(operator_owned) == 1
    assert len(public_domain) == 1


def test_ledger_groups_by_condition():
    ledger = AestheticConditionEditionsLedger(
        generated_at=datetime.now(tz=UTC),
        editions=(
            _metadata(edition_id="edition-c1-1", condition_id="rc-curiosity"),
            _metadata(edition_id="edition-c2-1", condition_id="rc-coherence"),
            _metadata(edition_id="edition-c1-2", condition_id="rc-curiosity"),
        ),
    )
    curiosity = ledger.by_condition("rc-curiosity")
    coherence = ledger.by_condition("rc-coherence")
    assert len(curiosity) == 2
    assert len(coherence) == 1

"""Tests for the condition edition provenance ledger v2."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.condition_edition_provenance_ledger import (
    ProvenanceBlocker,
    ProvenanceLedger,
    ProvenanceRecord,
    ReleaseState,
    evaluate_blockers,
)


def _make_record(**overrides) -> ProvenanceRecord:
    defaults = dict(
        edition_id="ed-001",
        condition_id="cond-intensity-high",
        timestamp=datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC),
        surface_lane="reverie",
        frame_ref="frame:reverie:run12:f0042",
        archive_ref="archive:hls:2026-05-20:seg-042",
        public_event_ref="rvpe:visual:run12:intensity-pulse",
        replay_manifest_ref="manifest:replay:run12",
        rights_class="operator_owned",
        privacy_class="fully_public",
        release_state=ReleaseState.RELEASED,
        provenance_token="abc123def456",
        source_condition_description="High intensity moment during shader pulse",
    )
    defaults.update(overrides)
    return ProvenanceRecord(**defaults)


def test_valid_released_record_passes() -> None:
    record = _make_record()
    assert record.release_state is ReleaseState.RELEASED
    assert record.blockers == ()


def test_blocked_rights_produces_blocker() -> None:
    record = _make_record(
        rights_class="third_party_rights_risky",
        release_state=ReleaseState.BLOCKED,
    )
    blockers = evaluate_blockers(record)
    assert ProvenanceBlocker.THIRD_PARTY_MEDIA in blockers


def test_raw_private_frame_produces_blocker() -> None:
    record = _make_record(
        privacy_class="raw_private_frame",
        release_state=ReleaseState.BLOCKED,
    )
    blockers = evaluate_blockers(record)
    assert ProvenanceBlocker.RAW_PRIVATE_FRAME in blockers


def test_missing_public_event_produces_blocker() -> None:
    record = _make_record(
        public_event_ref=None,
        release_state=ReleaseState.PRIVATE_ONLY,
    )
    blockers = evaluate_blockers(record)
    assert ProvenanceBlocker.MISSING_PUBLIC_EVENT_PROOF in blockers


def test_album_cover_uncertainty_produces_blocker() -> None:
    record = _make_record(
        rights_class="album_cover_no_explicit_rights",
        release_state=ReleaseState.BLOCKED,
    )
    blockers = evaluate_blockers(record)
    assert ProvenanceBlocker.ALBUM_COVER_UNCERTAINTY in blockers


def test_released_with_blockers_raises() -> None:
    with pytest.raises(ValueError, match="blockers remain"):
        _make_record(
            rights_class="uncleared",
            release_state=ReleaseState.RELEASED,
        )


def test_licensed_with_blockers_raises() -> None:
    with pytest.raises(ValueError, match="blockers remain"):
        _make_record(
            privacy_class="raw_private_frame",
            release_state=ReleaseState.LICENSED,
        )


def test_draft_with_blockers_allowed() -> None:
    record = _make_record(
        public_event_ref=None,
        release_state=ReleaseState.DRAFT,
    )
    assert record.release_state is ReleaseState.DRAFT


def test_ledger_releasable_filter() -> None:
    ledger = ProvenanceLedger(
        generated_at=datetime.now(UTC),
        records=(
            _make_record(edition_id="ed-released", release_state=ReleaseState.RELEASED),
            _make_record(edition_id="ed-licensed", release_state=ReleaseState.LICENSED),
            _make_record(
                edition_id="ed-draft",
                release_state=ReleaseState.DRAFT,
                public_event_ref=None,
            ),
        ),
    )
    assert len(ledger.releasable()) == 2
    assert len(ledger.blocked()) == 0


def test_ledger_for_marketplace_requires_public_event() -> None:
    ledger = ProvenanceLedger(
        generated_at=datetime.now(UTC),
        records=(
            _make_record(edition_id="ed-with-event", public_event_ref="rvpe:test"),
            _make_record(
                edition_id="ed-no-event",
                public_event_ref=None,
                release_state=ReleaseState.DRAFT,
            ),
        ),
    )
    marketplace = ledger.for_marketplace()
    assert len(marketplace) == 1
    assert marketplace[0].edition_id == "ed-with-event"


def test_ledger_for_demo_kit_excludes_blocked_and_withdrawn() -> None:
    ledger = ProvenanceLedger(
        generated_at=datetime.now(UTC),
        records=(
            _make_record(edition_id="ed-released", release_state=ReleaseState.RELEASED),
            _make_record(
                edition_id="ed-draft",
                release_state=ReleaseState.DRAFT,
                public_event_ref=None,
            ),
            _make_record(
                edition_id="ed-blocked",
                release_state=ReleaseState.BLOCKED,
                rights_class="uncleared",
            ),
            _make_record(
                edition_id="ed-withdrawn",
                release_state=ReleaseState.WITHDRAWN,
                public_event_ref=None,
            ),
        ),
    )
    demo = ledger.for_demo_kit()
    assert len(demo) == 2
    ids = {r.edition_id for r in demo}
    assert ids == {"ed-released", "ed-draft"}


def test_all_release_states_supported() -> None:
    for state in ReleaseState:
        if state in (ReleaseState.RELEASED, ReleaseState.LICENSED):
            record = _make_record(release_state=state)
        else:
            record = _make_record(release_state=state, public_event_ref=None)
        assert record.release_state is state

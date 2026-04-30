"""Archive replay public-event adapter tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.archive_replay_public_events import (
    ARCHIVE_CAPTURE_KIND,
    CURSOR_OWNER,
    IDEMPOTENCY_OWNER,
    PUBLIC_REPLAY_PUBLICATION_KIND,
    ArchiveReplayPublicEventError,
    adapt_hls_sidecar_to_replay_public_event,
    archive_replay_public_event_id,
    load_archive_replay_public_event_fixtures,
)
from shared.stream_archive import SegmentSidecar
from shared.temporal_span_registry import load_temporal_span_registry_fixtures

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "archive-replay-public-event.schema.json"
FIXTURES = REPO_ROOT / "config" / "archive-replay-public-event-fixtures.json"


def _payload() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(FIXTURES.read_text(encoding="utf-8")))


def _schema() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(SCHEMA.read_text(encoding="utf-8")))


def _registry():
    return load_temporal_span_registry_fixtures().registry()


def _fixtures():
    return load_archive_replay_public_event_fixtures(registry=_registry())


def test_schema_validates_fixture_file_and_pins_owners() -> None:
    schema = _schema()
    payload = _payload()

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)
    assert schema["x-cursor_owner"] == CURSOR_OWNER
    assert schema["x-idempotency_owner"] == IDEMPOTENCY_OWNER
    assert set(schema["x-required_fixture_cases"]) == {
        fixture["case"] for fixture in payload["fixtures"]
    }


def test_loader_validates_all_fixture_expectations() -> None:
    fixtures = _fixtures()

    assert set(fixtures.by_case()) == set(_schema()["x-required_fixture_cases"])


def test_clean_sidecar_maps_to_research_vehicle_public_event() -> None:
    fixture = _fixtures().by_case()["clean_public_replay_link"]
    sidecar = SegmentSidecar.from_dict(fixture.sidecar)
    decision = adapt_hls_sidecar_to_replay_public_event(
        sidecar,
        fixture.evidence,
        registry=_registry(),
        generated_at="2026-04-30T04:20:00Z",
        now="2026-04-30T04:20:00Z",
    )

    assert decision.status == "emitted"
    assert decision.archive_capture_kind == ARCHIVE_CAPTURE_KIND
    assert decision.public_replay_publication_kind == PUBLIC_REPLAY_PUBLICATION_KIND
    assert decision.archive_capture_claim_allowed is True
    assert decision.public_replay_link_claim_allowed is True
    assert decision.unavailable_reasons == ()
    assert decision.public_event is not None

    event = decision.public_event
    assert event.event_id == archive_replay_public_event_id(sidecar, fixture.evidence)
    assert event.event_type == "archive.segment"
    assert event.state_kind == "archive_artifact"
    assert event.source.substrate_id == "archive_replay"
    assert event.source.task_anchor == "archive-replay-public-event-link-adapter"
    assert event.public_url == "https://example.invalid/replay/segment00042"
    assert event.surface_policy.allowed_surfaces == ["archive", "replay"]
    assert event.surface_policy.claim_live is False
    assert event.surface_policy.claim_archive is True
    assert event.surface_policy.claim_monetizable is False
    assert event.surface_policy.requires_egress_public_claim is True
    assert event.surface_policy.requires_audio_safe is True
    assert event.surface_policy.requires_provenance is True
    for ref in (
        "span:archive.hls.segment00042",
        "span:audio.broadcast.window.0042",
        "span:replay.chapter.opening.0042",
        "egress:public-claim:fixture-pass",
        "provenance:archive-replay:segment00042",
    ):
        assert ref in event.provenance.evidence_refs


def test_claim_bearing_public_replay_requires_temporal_span_refs() -> None:
    fixture = _fixtures().by_case()["missing_temporal_span_refs"]
    decision = adapt_hls_sidecar_to_replay_public_event(
        fixture.sidecar,
        fixture.evidence,
        registry=_registry(),
        generated_at="2026-04-30T04:20:00Z",
        now="2026-04-30T04:20:00Z",
    )

    assert decision.status == "refused"
    assert decision.public_event is None
    assert decision.public_replay_link_claim_allowed is False
    assert "empty_span_refs" in decision.unavailable_reasons
    assert "temporal_span_gate_blocked_no_span_refs" in decision.unavailable_reasons


def test_private_or_rights_blocked_spans_cannot_ground_public_replay() -> None:
    fixture = _fixtures().by_case()["private_temporal_span_ref"]
    decision = adapt_hls_sidecar_to_replay_public_event(
        fixture.sidecar,
        fixture.evidence,
        registry=_registry(),
        generated_at="2026-04-30T04:20:00Z",
        now="2026-04-30T04:20:00Z",
    )

    assert decision.status == "refused"
    assert decision.public_event is None
    assert "private_or_rights_blocked_span_refs" in decision.unavailable_reasons
    assert "temporal_span_gate_blocked_private_or_rights" in decision.unavailable_reasons


def test_rights_privacy_and_provenance_fail_closed() -> None:
    fixture = _fixtures().by_case()["rights_privacy_blocked"]
    decision = adapt_hls_sidecar_to_replay_public_event(
        fixture.sidecar,
        fixture.evidence,
        registry=_registry(),
        generated_at="2026-04-30T04:20:00Z",
        now="2026-04-30T04:20:00Z",
    )

    assert decision.status == "refused"
    assert decision.public_event is None
    for reason in (
        "missing_provenance",
        "missing_provenance_evidence_refs",
        "rights_blocked",
        "privacy_blocked",
    ):
        assert reason in decision.unavailable_reasons


def test_egress_audio_gate_and_freshness_fail_closed() -> None:
    fixture = _fixtures().by_case()["egress_blocked"]
    decision = adapt_hls_sidecar_to_replay_public_event(
        fixture.sidecar,
        fixture.evidence,
        registry=_registry(),
        generated_at="2026-04-30T04:20:00Z",
        now="2026-04-30T04:20:00Z",
    )

    assert decision.status == "refused"
    assert decision.public_event is None
    for reason in (
        "egress_blocked",
        "egress_evidence_missing",
        "audio_blocked",
        "public_event_gate_stale",
        "source_stale",
    ):
        assert reason in decision.unavailable_reasons


def test_archive_capture_remains_separate_when_no_public_link_exists() -> None:
    fixture = _fixtures().by_case()["capture_only_no_public_url"]
    decision = adapt_hls_sidecar_to_replay_public_event(
        fixture.sidecar,
        fixture.evidence,
        registry=_registry(),
        generated_at="2026-04-30T04:20:00Z",
        now="2026-04-30T04:20:00Z",
    )

    assert decision.status == "held"
    assert decision.archive_capture_claim_allowed is True
    assert decision.public_replay_link_claim_allowed is False
    assert decision.public_event is None
    assert decision.unavailable_reasons == ("public_replay_url_missing",)
    assert decision.archive_capture_kind != decision.public_replay_publication_kind


def test_fixture_loader_rejects_missing_expected_case(tmp_path: Path) -> None:
    payload = copy.deepcopy(_payload())
    payload["fixtures"] = [
        fixture for fixture in payload["fixtures"] if fixture["case"] != "egress_blocked"
    ]
    path = tmp_path / "bad-archive-replay-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ArchiveReplayPublicEventError, match="fixture cases drifted"):
        load_archive_replay_public_event_fixtures(path, registry=_registry())

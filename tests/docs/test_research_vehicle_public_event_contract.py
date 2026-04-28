"""Regression pins for the research vehicle public event contract seed."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-04-28-research-vehicle-public-event-contract-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "research-vehicle-public-event.schema.json"


def _spec_body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _spec_body()

    for heading in (
        "## `ResearchVehiclePublicEvent` Schema Seed",
        "## Event Type Vocabulary",
        "## Derived Public Claim Policy",
        "## Archive And Monetization Policy",
        "## Aperture Surface Map",
        "## Caption And Cuepoint Rules",
        "## Failure Behavior",
        "## Existing Task Mapping",
        "## Child Task Recommendations",
    ):
        assert heading in body


def test_schema_has_required_public_event_fields() -> None:
    schema = _schema()
    required = set(schema["required"])
    properties = schema["properties"]

    for field in (
        "event_id",
        "event_type",
        "occurred_at",
        "broadcast_id",
        "programme_id",
        "condition_id",
        "source",
        "salience",
        "state_kind",
        "rights_class",
        "privacy_class",
        "provenance",
        "public_url",
        "frame_ref",
        "chapter_ref",
        "attribution_refs",
        "surface_policy",
    ):
        assert field in required
        assert field in properties

    surface_policy = properties["surface_policy"]
    policy_required = set(surface_policy["required"])
    for field in (
        "claim_live",
        "claim_archive",
        "claim_monetizable",
        "requires_egress_public_claim",
        "requires_audio_safe",
        "requires_provenance",
        "requires_human_review",
        "fallback_action",
    ):
        assert field in policy_required


def test_schema_covers_expected_event_types_and_surfaces() -> None:
    schema = _schema()
    properties = schema["properties"]

    assert set(properties["event_type"]["enum"]) >= {
        "broadcast.boundary",
        "programme.boundary",
        "chronicle.high_salience",
        "aesthetic.frame_capture",
        "caption.segment",
        "cuepoint.candidate",
        "chapter.marker",
        "shorts.candidate",
        "shorts.upload",
        "metadata.update",
        "channel_section.candidate",
        "arena_block.candidate",
        "omg.statuslog",
        "omg.weblog",
        "publication.artifact",
        "monetization.review",
        "fanout.decision",
    }

    assert set(schema["$defs"]["surface"]["enum"]) >= {
        "youtube_description",
        "youtube_cuepoints",
        "youtube_chapters",
        "youtube_captions",
        "youtube_shorts",
        "youtube_channel_sections",
        "arena",
        "omg_statuslog",
        "omg_weblog",
        "mastodon",
        "bluesky",
        "discord",
        "archive",
        "monetization",
    }


def test_example_event_is_parseable_and_conservative() -> None:
    body = _spec_body()
    schema = _schema()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example ResearchVehiclePublicEvent JSON block missing"

    event = json.loads(match.group("payload"))
    known_surfaces = set(schema["$defs"]["surface"]["enum"])

    assert event["schema_version"] == 1
    assert re.match(schema["properties"]["event_id"]["pattern"], event["event_id"])
    assert event["event_type"] == "programme.boundary"
    assert event["state_kind"] == "programme_state"
    assert event["source"]["substrate_id"] == "programme_cuepoints"
    assert set(event["surface_policy"]["allowed_surfaces"]) <= known_surfaces
    assert set(event["surface_policy"]["denied_surfaces"]) <= known_surfaces
    assert event["surface_policy"]["claim_live"] is False
    assert event["surface_policy"]["claim_archive"] is True
    assert event["surface_policy"]["claim_monetizable"] is False
    assert event["surface_policy"]["requires_egress_public_claim"] is True
    assert event["surface_policy"]["requires_audio_safe"] is True
    assert event["surface_policy"]["requires_provenance"] is True
    assert event["surface_policy"]["fallback_action"] == "chapter_only"


def test_public_claim_archive_and_monetization_derivations_are_pinned() -> None:
    body = _spec_body()

    for phrase in (
        "LivestreamEgressState.public_claim_allowed",
        "ContentSubstrate.integration_status",
        "ContentSubstrate.public_claim_permissions.claim_live",
        "BroadcastAudioSafety.audio_safe_for_broadcast.safe",
        "claim_archive",
        "claim_monetizable",
        "safe to broadcast",
        "safe to archive",
        "safe to promote",
        "safe to monetize",
    ):
        assert phrase in body


def test_surface_mapping_and_child_splits_include_required_public_apertures() -> None:
    body = _spec_body()

    for surface_or_task in (
        "YouTube live title/description",
        "YouTube live cuepoints",
        "YouTube VOD chapters",
        "YouTube captions",
        "YouTube channel sections",
        "YouTube Shorts",
        "Are.na",
        "OMG statuslog",
        "OMG weblog",
        "Mastodon/Bluesky/Discord",
        "ytb-009-production-wire",
        "ytb-004-programme-boundary-cuepoints",
        "ytb-010-cross-surface-federation",
        "ytb-011-channel-sections-manager",
        "ytb-012-shorts-extraction-pipeline",
        "youtube-research-translation-ledger",
        "cross-surface-event-contract",
        "monetization-readiness-ledger",
    ):
        assert surface_or_task in body

    for child_task in (
        "youtube-public-event-adapter",
        "youtube-caption-event-adapter",
        "youtube-cuepoint-chapter-event-adapter",
        "cross-surface-public-event-router",
        "arena-block-public-event-adapter",
        "omg-statuslog-public-event-adapter",
        "omg-weblog-public-event-adapter",
        "monetization-event-evidence-ledger",
        "shorts-public-event-adapter",
    ):
        assert child_task in body


def test_failure_behavior_is_fail_closed_and_named() -> None:
    body = _spec_body()

    for reason in (
        "missing_provenance",
        "rights_blocked",
        "privacy_blocked",
        "source_stale",
        "egress_blocked",
        "audio_blocked",
        "missing_surface_reference",
        "rate_limited",
        "cuepoint_failed",
        "shorts_blocked",
        "policy_conflict",
    ):
        assert reason in body

    assert "Most restrictive policy wins" in body

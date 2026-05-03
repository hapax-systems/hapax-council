from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "audits"
    / "2026-04-30-youtube-research-translation-ledger.json"
)
DOC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "audits"
    / "2026-04-30-youtube-research-translation-ledger.md"
)
SCHEMA = REPO_ROOT / "schemas" / "youtube-research-translation-ledger.schema.json"


def _ledger() -> dict[str, object]:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _rows() -> dict[str, dict[str, object]]:
    ledger = _ledger()
    return {str(row["surface_id"]): row for row in ledger["surface_rows"]}  # type: ignore[index]


def test_youtube_research_translation_ledger_schema_validates() -> None:
    schema = _schema()
    ledger = _ledger()

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(ledger)


def test_youtube_surface_rows_cover_required_translation_surfaces() -> None:
    rows = _rows()

    assert set(rows) >= {
        "youtube_live_metadata",
        "youtube_live_captions",
        "youtube_live_cuepoints",
        "youtube_vod_chapters",
        "youtube_channel_sections",
        "youtube_shorts",
        "youtube_archive_links",
        "youtube_cross_surface_fanout",
        "youtube_quota_posture",
        "youtube_advertiser_suitability",
    }


def test_publication_surfaces_fail_closed_on_public_and_monetization_claims() -> None:
    ledger = _ledger()

    for row in ledger["surface_rows"]:  # type: ignore[index]
        if not row["publication_surface"]:
            continue
        policy = row["claim_policy"]
        refs = set(row["evidence_requirements"]["required_refs"])

        assert policy["default_public_claim_allowed"] is False
        assert policy["default_monetization_claim_allowed"] is False
        assert "ResearchVehiclePublicEvent" in refs
        assert "LivestreamEgressState.public_claim_allowed" in refs
        assert "ContentSubstrate.public_claim_permissions" in refs
        assert "rights_provenance_token" in refs
        assert "privacy_class_public_safe" in refs


def test_metadata_cannot_claim_unavailable_producers() -> None:
    metadata = _rows()["youtube_live_metadata"]
    forbidden = set(metadata["claim_policy"]["forbidden_claims"])

    assert forbidden >= {
        "public_live_captions_without_caption_stream",
        "programme_boundary_live_cuepoints_without_live_smoke",
        "archive_replay_without_archive_public_url",
        "dynamic_channel_sections_without_section_manager",
        "shorts_extraction_or_upload_without_pipeline",
        "cross_surface_fanout_without_public_event_adapter",
        "monetizable_without_monetization_readiness",
    }
    assert metadata["claim_policy"]["requires_human_review"] is True


def test_surface_specific_fail_closed_postures_are_pinned() -> None:
    rows = _rows()

    captions = rows["youtube_live_captions"]
    # Producer (ytb-009-production-wire, PR #1901) and substrate adapter
    # (caption-substrate-adapter) shipped — surface stays in dry_run until
    # live smoke produces fresh, AV-aligned candidates per the adapter.
    assert captions["current_status"] == "dry_run"
    assert captions["fallback"]["mode"] == "dry_run"
    blockers = captions["evidence_requirements"]["public_blockers"]
    assert "producer_absent" in blockers
    assert "av_offset_unavailable" in blockers
    assert "adapter_rejection_stale" in blockers
    assert (
        "caption_substrate_adapter_candidate" in captions["evidence_requirements"]["required_refs"]
    )

    cuepoints = rows["youtube_live_cuepoints"]
    assert cuepoints["current_status"] == "legacy_live_unverified"
    assert cuepoints["fallback"]["mode"] == "chapter_only"
    assert (
        "operator_supervised_live_player_smoke"
        in cuepoints["evidence_requirements"]["required_refs"]
    )

    shorts = rows["youtube_shorts"]
    assert shorts["quota_policy"]["endpoint"] == "videos.insert"
    assert shorts["quota_policy"]["units_per_call"] == 100
    assert "shorts_upload" in shorts["claim_policy"]["forbidden_claims"]


def test_quota_and_suitability_sources_are_currently_explicit() -> None:
    ledger = _ledger()
    sources = {source["source_id"]: source for source in ledger["official_sources"]}  # type: ignore[index]

    assert sources["youtube_data_api:quota_calculator"]["url"].endswith("/determine_quota_cost")
    assert any(
        "10000 units" in fact for fact in sources["youtube_data_api:quota_calculator"]["key_facts"]
    )
    assert any(
        "captions.insert at 400" in fact
        for fact in sources["youtube_data_api:quota_calculator"]["key_facts"]
    )
    assert any(
        "videos.insert at 100" in fact
        for fact in sources["youtube_data_api:quota_calculator"]["key_facts"]
    )
    assert any(
        "maximum of 10 shelves" in fact
        for fact in sources["youtube_data_api:channel_sections_insert"]["key_facts"]
    )
    assert any(
        "actively streaming" in fact
        for fact in sources["youtube_live_api:live_broadcasts_cuepoint"]["key_facts"]
    )

    suitability = _rows()["youtube_advertiser_suitability"]
    assert suitability["claim_policy"]["default_monetization_claim_allowed"] is False
    assert "safe_to_monetize" in suitability["claim_policy"]["forbidden_claims"]


def test_child_task_splits_keep_youtube_work_bounded() -> None:
    ledger = _ledger()
    task_ids = {task["task_id"] for task in ledger["child_task_splits"]}  # type: ignore[index]

    assert task_ids >= {
        "ytb-009-production-wire",
        "ytb-004-programme-boundary-cuepoints",
        "ytb-011-channel-sections-manager",
        "ytb-012-shorts-extraction-pipeline",
        "youtube-packaging-claim-policy",
        "youtube-public-event-adapter",
    }


def test_markdown_explainer_points_to_machine_readable_contracts() -> None:
    body = DOC.read_text(encoding="utf-8")

    for phrase in (
        "2026-04-30-youtube-research-translation-ledger.json",
        "youtube-research-translation-ledger.schema.json",
        "Most restrictive policy wins",
        "No live YouTube writes",
        "ResearchVehiclePublicEvent",
        "LivestreamEgressState.public_claim_allowed",
        "ContentSubstrate.public_claim_permissions",
    ):
        assert phrase in body

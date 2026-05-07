from __future__ import annotations

from shared.segment_source_inquiry import (
    SOURCE_PACKET_INQUIRY_AUTHORITY,
    SOURCE_PACKET_INQUIRY_DOCTRINE,
    build_source_packet_inquiry_blackboard,
    render_source_packet_inquiry_seed,
    source_packet_inquiry_hash,
    source_packet_inquiry_summary,
)


def test_source_packet_inquiry_blackboard_is_advisory_and_open_ended() -> None:
    blackboard = build_source_packet_inquiry_blackboard(
        target_segments=3,
        existing_manifest_programmes=["prog-a.json"],
        budget_s=120.0,
    )

    assert blackboard["authority"] == SOURCE_PACKET_INQUIRY_AUTHORITY
    assert blackboard["doctrine"] == SOURCE_PACKET_INQUIRY_DOCTRINE
    assert blackboard["lead_policy"]["fixed_pass_count"] is False
    assert blackboard["lead_policy"]["no_forced_segment_production"] is True
    assert "no_candidate_witness_required" in blackboard["lead_policy"]["may_follow_leads_until"]
    assert "blackboard_is_not_script_authority" in blackboard["authority_boundaries"]
    assert "blackboard_is_not_layout_or_runtime_authority" in blackboard["authority_boundaries"]
    assert blackboard["source_packet_inquiry_sha256"] == source_packet_inquiry_hash(blackboard)
    assert blackboard["source_packet_inquiry_ref"].startswith("source_packet_inquiry:")


def test_source_packet_inquiry_decisions_require_receipts_without_transferring_authority() -> None:
    blackboard = build_source_packet_inquiry_blackboard(target_segments=1)
    decisions = blackboard["recruitment_decisions"]
    requirements = blackboard["source_packet_requirements"]

    assert decisions
    assert any(item["source_acquisition_required"] is True for item in decisions)
    for decision in decisions:
        assert "provider_id" in decision["required_receipt_fields"]
        assert "raw_source_hashes" in decision["required_receipt_fields"]
        assert "sources_do_not_become_runtime_authority" in decision["authority_boundaries"]
    for requirement in requirements:
        assert "required_receipt_fields" in requirement
        assert "authority_boundary" in requirement


def test_source_packet_inquiry_seed_render_rejects_topic_and_runtime_authority() -> None:
    blackboard = build_source_packet_inquiry_blackboard(target_segments=2)
    rendered = render_source_packet_inquiry_seed(blackboard)

    assert "SOURCE-PACKET INQUIRY BLACKBOARD" in rendered
    assert "forms are generated; authority is gated" in rendered
    assert "not topic, script, layout, cue, runtime, or release authority" in rendered
    assert "fixed pass counts" in rendered
    assert "forced segment production" in rendered


def test_source_packet_inquiry_summary_is_status_safe() -> None:
    blackboard = build_source_packet_inquiry_blackboard(target_segments=2)
    summary = source_packet_inquiry_summary(blackboard)

    assert summary["source_packet_inquiry_sha256"] == blackboard["source_packet_inquiry_sha256"]
    assert summary["knowledge_gap_count"] == 3
    assert summary["recruitment_decision_count"] == 3
    assert summary["fixed_pass_count"] is False
    assert summary["no_forced_segment_production"] is True

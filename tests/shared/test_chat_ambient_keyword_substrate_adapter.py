"""Tests for the chat ambient / keyword substrate adapter."""

from __future__ import annotations

from shared.chat_ambient_keyword_substrate_adapter import (
    CHAT_AMBIENT_SUBSTRATE_ID,
    CHAT_KEYWORD_SUBSTRATE_ID,
    DEFAULT_FRESHNESS_TTL_S,
    PRODUCER,
    TASK_ANCHOR,
    project_chat_ambient_keyword_substrate,
)

NOW = 1_717_000_000.0


def _aggregate(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "window_seconds": 60.0,
        "window_end_ts": NOW - 8.0,
        "message_count_60s": 18,
        "message_rate_per_min": 18.0,
        "unique_authors_60s": 6,
        "audience_engagement": 0.72,
        "t4_plus_rate_per_min": 10.0,
        "unique_t4_plus_authors_60s": 4,
        "t5_rate_per_min": 3.0,
        "t6_rate_per_min": 1.0,
        "keyword_class_counts": {
            "research": 5,
            "citation": 2,
        },
        "aggregate_only_privacy_proof": True,
        "privacy_filter_status": "aggregate_only",
        "egress_public_claim": True,
        "health_evidence_refs": ["livestream-health-group:chat_aggregate:fresh"],
        "provenance_token": "chat-aggregate-window-001",
        "source_ref": "substrate:chat_signals_aggregate",
        "producer": "agents.studio_compositor.chat_signals",
    }
    payload.update(overrides)
    return payload


def test_raw_author_handle_and_text_fields_are_rejected_before_output() -> None:
    payload = _aggregate(
        author_handle="viewer_alice",
        raw_handle="@viewer_alice",
        per_viewer_text="this must never be copied",
    )

    candidates, rejections = project_chat_ambient_keyword_substrate(payload, now=NOW)

    assert candidates == []
    assert len(rejections) == 1
    rejection = rejections[0]
    assert rejection.reason == "raw_private_field"
    assert set(rejection.rejected_fields) == {"author_handle", "per_viewer_text", "raw_handle"}
    assert "viewer_alice" not in rejection.detail
    assert "this must never be copied" not in rejection.detail


def test_aggregate_only_fixture_projects_explicit_ambient_and_keyword_refs() -> None:
    candidates, rejections = project_chat_ambient_keyword_substrate(_aggregate(), now=NOW)

    assert rejections == []
    assert {candidate.substrate_id for candidate in candidates} == {
        CHAT_AMBIENT_SUBSTRATE_ID,
        CHAT_KEYWORD_SUBSTRATE_ID,
    }
    assert {candidate.render_target for candidate in candidates} == {
        "chat_ambient",
        "chat_keyword_ward",
    }

    for candidate in candidates:
        event = candidate.event
        assert candidate.projection_status == "candidate"
        assert event.source.producer == PRODUCER
        assert event.source.task_anchor == TASK_ANCHOR
        assert event.source.substrate_id == candidate.substrate_id
        assert event.privacy_class == "aggregate_only"
        assert event.rights_class == "platform_embedded"
        assert event.provenance.token == "chat-aggregate-window-001"
        evidence = "|".join(event.provenance.evidence_refs)
        assert f"substrate:{candidate.substrate_id}" in evidence
        assert "keyword_class_counts:citation=2,research=5" in evidence
        assert "egress_public_claim:True" in evidence
        assert "viewer_alice" not in event.to_json_line()


def test_missing_provenance_or_health_keeps_records_dry_run_and_non_claiming() -> None:
    candidates, rejections = project_chat_ambient_keyword_substrate(
        _aggregate(
            health_evidence_refs=[],
            provenance_token=None,
        ),
        now=NOW,
    )

    assert rejections == []
    assert len(candidates) == 2
    for candidate in candidates:
        assert candidate.projection_status == "dry_run"
        assert "missing_chat_aggregate_health_evidence" in candidate.dry_run_reasons
        assert "missing_provenance_token" in candidate.dry_run_reasons
        assert candidate.public_live_claim_allowed is False
        assert candidate.viewer_visible_claim_allowed is False
        assert candidate.publication_claim_allowed is False
        assert candidate.monetization_claim_allowed is False
        policy = candidate.event.surface_policy
        assert policy.claim_live is False
        assert policy.claim_archive is False
        assert policy.claim_monetizable is False
        assert policy.fallback_action == "dry_run"
        assert policy.dry_run_reason is not None


def test_stale_aggregate_window_blocks_public_claims_with_dry_run_reason() -> None:
    stale_window_end = NOW - DEFAULT_FRESHNESS_TTL_S - 3.0

    candidates, rejections = project_chat_ambient_keyword_substrate(
        _aggregate(window_end_ts=stale_window_end),
        now=NOW,
    )

    assert rejections == []
    assert len(candidates) == 2
    for candidate in candidates:
        assert candidate.projection_status == "dry_run"
        assert any(
            reason.startswith("stale_aggregate_window") for reason in candidate.dry_run_reasons
        )
        assert candidate.public_live_claim_allowed is False
        assert candidate.viewer_visible_claim_allowed is False
        assert candidate.publication_claim_allowed is False
        assert candidate.event.surface_policy.claim_live is False
        assert candidate.event.surface_policy.claim_archive is False


def test_privacy_filter_failure_blocks_public_and_viewer_visible_claims() -> None:
    candidates, rejections = project_chat_ambient_keyword_substrate(
        _aggregate(
            aggregate_only_privacy_proof=False,
            privacy_filter_status="failed",
        ),
        now=NOW,
    )

    assert rejections == []
    for candidate in candidates:
        assert candidate.projection_status == "dry_run"
        assert "missing_aggregate_only_privacy_proof" in candidate.dry_run_reasons
        assert "privacy_filter_status:failed" in candidate.dry_run_reasons
        assert candidate.public_live_claim_allowed is False
        assert candidate.viewer_visible_claim_allowed is False
        assert candidate.publication_claim_allowed is False
        assert candidate.monetization_claim_allowed is False
        assert candidate.event.privacy_class == "aggregate_only"
        assert candidate.event.surface_policy.redaction_policy == "aggregate_only"


def test_missing_egress_evidence_keeps_viewer_publication_and_live_claims_false() -> None:
    candidates, rejections = project_chat_ambient_keyword_substrate(
        _aggregate(egress_public_claim=False),
        now=NOW,
    )

    assert rejections == []
    for candidate in candidates:
        assert candidate.projection_status == "dry_run"
        assert "missing_public_egress_evidence" in candidate.dry_run_reasons
        assert candidate.public_live_claim_allowed is False
        assert candidate.viewer_visible_claim_allowed is False
        assert candidate.publication_claim_allowed is False
        assert candidate.monetization_claim_allowed is False


def test_producer_absent_returns_noop_rejection() -> None:
    candidates, rejections = project_chat_ambient_keyword_substrate(None, now=NOW)

    assert candidates == []
    assert len(rejections) == 1
    assert rejections[0].reason == "producer_absent"
    assert "absent" in rejections[0].detail


def test_schema_is_closed_for_unknown_fields() -> None:
    candidates, rejections = project_chat_ambient_keyword_substrate(
        _aggregate(raw_author_rows_count=3),
        now=NOW,
    )

    assert candidates == []
    assert len(rejections) == 1
    assert rejections[0].reason == "invalid_aggregate"
    assert rejections[0].rejected_fields == ("raw_author_rows_count",)

"""Regression pins for the autonomous grounding value stream registry."""

from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-04-29-autonomous-grounding-value-stream-registry-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "autonomous-grounding-value-stream.schema.json"
REGISTRY = REPO_ROOT / "config" / "autonomous-grounding-value-streams.json"
TASK_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"

REQUIRED_STREAM_FIELDS = {
    "stream_id",
    "category",
    "automation_class",
    "n1_value_claim",
    "evidence_owner",
    "revenue_path",
    "prerequisites",
    "public_claim_policy",
    "privacy_rights_posture",
    "operator_boundary",
    "status",
    "next_packet",
}

EXPECTED_STREAMS = {
    "livestream_public_aperture",
    "vod_archive_replay_shorts_chapters",
    "cross_surface_publication_bus",
    "direct_no_perk_support_rails",
    "commercial_license_agent_payment_rail",
    "product_tool_ip_artifact_packs",
    "research_artifacts_datasets_papers_identifiers",
    "grants_fellowships_credits_institutional_patronage",
    "aesthetic_media_condition_editions",
    "studio_operator_adjacent_value",
    "consulting_by_artifact",
    "refusal_conversions",
}

EXPECTED_CATEGORIES = {
    "live_aperture",
    "archive_replay",
    "publication_bus",
    "support_rail",
    "commercial_license",
    "artifact_product",
    "research_artifact",
    "institutional_grant",
    "aesthetic_edition",
    "studio_adjacent",
    "refusal_conversion",
}


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _registry() -> dict[str, object]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _operator_task_root_available() -> bool:
    return os.environ.get("GITHUB_ACTIONS") != "true" and TASK_ROOT.is_dir()


def _streams_by_id() -> dict[str, dict[str, object]]:
    records = _registry()["streams"]
    return {record["stream_id"]: record for record in records}


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Machine-Readable Registry",
        "## Automation Doctrine",
        "## Seeded Streams",
        "## Evidence Ownership",
        "## Public Claim Policy",
        "## Privacy Rights And Operator Boundary",
        "## Downstream Packet Mapping",
        "## Refusal Conversions",
        "## Downstream Consumers",
    ):
        assert heading in body


def test_schema_requires_acceptance_criteria_fields() -> None:
    schema = _schema()
    value_stream = schema["$defs"]["value_stream"]
    required = set(value_stream["required"])
    properties = value_stream["properties"]

    for field in REQUIRED_STREAM_FIELDS:
        assert field in required
        assert field in properties

    assert (
        schema["properties"]["global_policy"]["properties"]["single_operator_only"]["const"] is True
    )
    assert (
        schema["properties"]["global_policy"]["properties"]["recurring_operator_labor_allowed"][
            "const"
        ]
        is False
    )
    assert (
        schema["$defs"]["operator_boundary"]["properties"]["recurring_operator_labor_allowed"][
            "const"
        ]
        is False
    )


def test_schema_and_registry_seed_all_synthesis_streams() -> None:
    schema = _schema()
    streams = _streams_by_id()

    assert set(schema["$defs"]["stream_id"]["enum"]) == EXPECTED_STREAMS
    assert set(streams) == EXPECTED_STREAMS
    assert {stream["category"] for stream in streams.values()} == EXPECTED_CATEGORIES

    body = _body()
    for stream_id in EXPECTED_STREAMS:
        assert f"`{stream_id}`" in body


def test_registry_marks_each_stream_with_train_status_and_automation_class() -> None:
    streams = _streams_by_id()
    statuses = {stream["status"] for stream in streams.values()}
    automation_classes = {stream["automation_class"] for stream in streams.values()}

    assert statuses == {"offered", "blocked", "guarded", "refusal_artifact"}
    assert automation_classes == {
        "AUTO",
        "BOOTSTRAP",
        "LEGAL_ATTEST",
        "GUARDED",
        "REFUSAL_ARTIFACT",
    }

    assert streams["refusal_conversions"]["status"] == "refusal_artifact"
    assert streams["refusal_conversions"]["automation_class"] == "REFUSAL_ARTIFACT"


def test_global_and_per_stream_operator_boundary_ban_recurring_labor() -> None:
    registry = _registry()
    global_policy = registry["global_policy"]
    allowed_global_actions = set(global_policy["allowed_operator_actions"])

    assert global_policy["single_operator_only"] is True
    assert global_policy["recurring_operator_labor_allowed"] is False
    assert global_policy["supporter_perks_allowed"] is False
    assert global_policy["supporter_identity_persistence_allowed"] is False
    assert allowed_global_actions == {"bootstrap", "legal_attestation"}

    for stream in registry["streams"]:
        boundary = stream["operator_boundary"]
        allowed_actions = set(boundary["allowed_operator_actions"])

        assert boundary["recurring_operator_labor_allowed"] is False, stream["stream_id"]
        assert allowed_actions <= allowed_global_actions, stream["stream_id"]
        assert boundary["boundary_note"], stream["stream_id"]


def test_each_stream_declares_evidence_revenue_claims_privacy_and_guardrails() -> None:
    for stream in _registry()["streams"]:
        assert set(REQUIRED_STREAM_FIELDS) <= set(stream), stream["stream_id"]
        assert stream["n1_value_claim"], stream["stream_id"]
        assert stream["evidence_owner"]["owner_id"], stream["stream_id"]
        assert stream["evidence_owner"]["evidence_refs"], stream["stream_id"]
        assert stream["evidence_owner"]["proof_required"], stream["stream_id"]
        assert stream["revenue_path"]["money_forms"], stream["stream_id"]
        assert stream["revenue_path"]["route_policy"], stream["stream_id"]
        assert stream["prerequisites"], stream["stream_id"]
        assert stream["public_claim_policy"]["allowed_claims"], stream["stream_id"]
        assert stream["public_claim_policy"]["forbidden_claims"], stream["stream_id"]
        assert stream["public_claim_policy"]["claim_gate_refs"], stream["stream_id"]
        assert stream["privacy_rights_posture"]["fail_closed_reasons"], stream["stream_id"]
        assert stream["guardrails"], stream["stream_id"]
        assert stream["train_position"]["wsjf"] > 0, stream["stream_id"]


def test_downstream_next_packets_point_to_exact_task_notes() -> None:
    for stream in _registry()["streams"]:
        packet = stream["next_packet"]
        task_note = Path(packet["task_note"])

        assert not task_note.is_absolute(), stream["stream_id"]
        assert task_note.parts[0] in {"active", "closed"}, stream["stream_id"]
        assert task_note.suffix == ".md", stream["stream_id"]
        assert packet["state"] in {
            "active",
            "offered",
            "blocked",
            "closed",
            "refusal_artifact",
        }
        assert packet["reason"], stream["stream_id"]

        note_path = TASK_ROOT / task_note
        if _operator_task_root_available():
            assert note_path.is_file(), stream["stream_id"]
            task_body = note_path.read_text(encoding="utf-8")
            assert f"task_id: {packet['task_id']}" in task_body, stream["stream_id"]


def test_refusal_conversions_preserve_forbidden_generic_business_shapes() -> None:
    registry = _registry()
    forbidden_shapes = set(registry["global_policy"]["forbidden_revenue_shapes"])

    assert forbidden_shapes == {
        "patreon_perk_ladder",
        "github_sponsors_funding_file",
        "stripe_payment_links",
        "discord_community_business",
        "consulting_as_service",
        "paid_subscriber_access_model",
        "supporter_request_queue",
        "sponsor_ad_read_obligation",
    }

    conversions = [
        conversion for stream in registry["streams"] for conversion in stream["refusal_conversions"]
    ]
    generic_forms = {conversion["generic_form"] for conversion in conversions}

    assert {
        "Patreon",
        "GitHub Sponsors funding file",
        "Stripe Payment Links",
        "Discord community subscriptions",
        "Paid subscriber access model",
        "Sponsor ad reads",
        "Consulting service",
    } <= generic_forms

    for conversion in conversions:
        assert conversion["decision"] in {"refused", "guarded", "converted"}
        assert conversion["buildable_conversion"]


def test_no_stream_uses_supporter_or_client_relationship_as_revenue_path() -> None:
    registry_text = REGISTRY.read_text(encoding="utf-8").lower()

    for forbidden in (
        "supporter list",
        "leaderboard",
        "client accounts",
        "retainers",
        "customer success",
        "request queue",
    ):
        # The phrases may appear only as forbidden claims or guardrails, never
        # as positive money forms.
        assert '"money_forms":' in registry_text
        money_form_sections = registry_text.split('"money_forms":')
        for section in money_form_sections[1:]:
            before_route_policy = section.split('"route_policy":', 1)[0]
            assert forbidden not in before_route_policy

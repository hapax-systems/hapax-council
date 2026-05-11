"""Regression pins for the support surface registry contract."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-04-29-support-surface-registry-design.md"
)
HSEA_SPEC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-04-15-hsea-phase-9-revenue-preparation-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "support-surface-registry.schema.json"
REGISTRY = REPO_ROOT / "config" / "support-surface-registry.json"


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _registry() -> dict[str, object]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = SPEC.read_text(encoding="utf-8")

    for heading in (
        "## Purpose",
        "## Source Authority",
        "## Surface Decisions",
        "## No-Perk Support Doctrine",
        "## Aggregate-Only Receipts",
        "## Readiness Gates",
        "## Superseded HSEA Assumptions",
        "## Downstream Consumers",
    ):
        assert heading in body


def test_schema_top_level_fields_are_train_readable() -> None:
    schema = _schema()
    required = set(schema["required"])
    properties = schema["properties"]

    for field in (
        "schema_version",
        "registry_id",
        "declared_at",
        "source_refs",
        "no_perk_support_doctrine",
        "aggregate_receipt_policy",
        "surfaces",
    ):
        assert field in required
        assert field in properties


def test_required_surfaces_and_refusals_are_pinned_in_schema() -> None:
    schema = _schema()

    assert set(schema["x-required_surface_ids"]) == {
        "youtube_ads",
        "youtube_supers",
        "youtube_super_thanks",
        "youtube_memberships_no_perk",
        "liberapay_recurring",
        "lightning_invoice_receive",
        "nostr_zaps",
        "kofi_tips_guarded",
        "github_sponsors",
        "patreon",
        "substack_paid_subscription",
        "discord_community_subscriptions",
        "stripe_payment_links",
        "consulting_as_service",
        "sponsor_support_copy",
    }
    assert set(schema["x-required_refusal_conversion_surface_ids"]) == {
        "patreon",
        "substack_paid_subscription",
        "discord_community_subscriptions",
        "stripe_payment_links",
        "consulting_as_service",
    }


def test_no_perk_doctrine_and_receipt_policy_are_structural() -> None:
    schema = _schema()
    doctrine = schema["$defs"]["no_perk_support_doctrine"]["properties"]
    receipts = schema["$defs"]["aggregate_receipt_policy"]["properties"]

    for field in (
        "support_buys_access",
        "support_buys_requests",
        "support_buys_private_advice",
        "support_buys_priority",
        "support_buys_shoutouts",
        "support_buys_guarantees",
        "support_buys_client_service",
        "support_buys_deliverables",
        "support_buys_control",
    ):
        assert doctrine[field]["const"] is False
    assert doctrine["work_continues_regardless"]["const"] is True
    assert receipts["public_state_aggregate_only"]["const"] is True
    assert receipts["per_receipt_public_state_allowed"]["const"] is False
    assert receipts["identity_retention_allowed"]["const"] is False
    assert receipts["comment_text_retention_allowed"]["const"] is False


def test_registry_records_source_refusal_authority() -> None:
    registry = _registry()
    source_refs = set(registry["source_refs"])

    for ref in (
        "docs/refusal-briefs/leverage-patreon.md",
        "docs/refusal-briefs/sponsorships-multi-user-pattern.md",
        "docs/refusal-briefs/leverage-stripe-kyc.md",
        "docs/refusal-briefs/leverage-consulting-methodology-as-service.md",
        "docs/refusal-briefs/leverage-discord-community.md",
    ):
        assert ref in source_refs


def test_registry_classifies_acceptance_criteria_surfaces() -> None:
    surfaces = {surface["surface_id"]: surface for surface in _registry()["surfaces"]}

    for surface_id in (
        "youtube_ads",
        "youtube_supers",
        "youtube_super_thanks",
        "youtube_memberships_no_perk",
        "liberapay_recurring",
        "lightning_invoice_receive",
        "nostr_zaps",
        "kofi_tips_guarded",
        "github_sponsors",
        "sponsor_support_copy",
    ):
        assert surfaces[surface_id]["decision"] in {"allowed", "guarded"}
        assert surfaces[surface_id]["no_perk_required"] is True
        assert surfaces[surface_id]["aggregate_only_receipts"] is True

    for surface_id in (
        "patreon",
        "substack_paid_subscription",
        "discord_community_subscriptions",
        "stripe_payment_links",
        "consulting_as_service",
    ):
        surface = surfaces[surface_id]
        assert surface["decision"] == "refusal_conversion"
        assert surface["automation_class"] == "REFUSAL_ARTIFACT"
        assert surface["buildable_conversion"]


def test_hsea_phase_9_copy_expectations_are_superseded() -> None:
    body = HSEA_SPEC.read_text(encoding="utf-8")

    assert "Supersession 2026-04-29" in body
    assert "GitHub Sponsors profile copy" in body
    assert "refused conversion artifacts only" in body
    assert "public consulting-as-service artifacts remain refused" in body
    assert "no-perk support copy staged" in body

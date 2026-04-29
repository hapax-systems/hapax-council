"""Regression pins for the content format source-pool rights ledger."""

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
    / "2026-04-29-content-format-source-pool-rights-ledger-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "content-format-source-pool-rights-ledger.schema.json"
LEDGER = REPO_ROOT / "config" / "content-format-source-pool-rights-ledger.json"

EXPECTED_RIGHTS_CLASSES = {
    "owned",
    "public_domain",
    "cc_compatible",
    "licensed",
    "platform_embed_only",
    "fair_use_candidate",
    "forbidden",
    "unknown",
}

EXPECTED_POSTURES = {
    "link_along",
    "metadata_first",
    "owned_cleared",
    "archive_only",
    "refusal_artifact",
}

EXPECTED_FORMATS = {
    "tier_list",
    "react_commentary",
    "ranking",
    "comparison",
    "review",
    "watch_along",
    "explainer",
    "rundown",
    "debate",
    "bracket",
    "what_is_this",
    "refusal_breakdown",
    "evidence_audit",
}

EXPECTED_CONSUMERS = {
    "scheduler",
    "run_store",
    "public_adapter",
    "conversion_broker",
    "monetization_ledger",
}

SOURCE_METADATA_FIELDS = {
    "source_url",
    "title",
    "creator",
    "rightsholder",
    "platform",
    "license",
    "permission",
    "acquisition_method",
    "capture_method",
    "date_checked",
}


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _ledger() -> dict[str, object]:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _sources_by_id() -> dict[str, dict[str, object]]:
    return {source["source_id"]: source for source in _ledger()["source_pool"]}


def _formats_by_id() -> dict[str, dict[str, object]]:
    return {policy["format_id"]: policy for policy in _ledger()["format_policies"]}


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Machine-Readable Ledger",
        "## Rights Classes",
        "## Source Pool Records",
        "## Public Private Eligibility",
        "## Third Party AV Default",
        "## Bayesian Rights Priors",
        "## WCS Evidence And Downstream Consumers",
        "## Format Posture Matrix",
        "## Acceptance Pin",
    ):
        assert heading in body


def test_schema_defines_required_rights_classes_postures_and_records() -> None:
    schema = _schema()

    assert set(schema["$defs"]["rights_class"]["enum"]) == EXPECTED_RIGHTS_CLASSES
    assert set(schema["$defs"]["source_posture"]["enum"]) == EXPECTED_POSTURES
    assert set(schema["$defs"]["format_id"]["enum"]) == EXPECTED_FORMATS
    assert set(schema["$defs"]["downstream_consumer"]["enum"]) == EXPECTED_CONSUMERS

    source_required = set(schema["$defs"]["source_pool_record"]["required"])
    for field in {
        "rights_class",
        "media_profile",
        "eligibility",
        "postures",
        "wcs_substrate_refs",
        "evidence_refs",
        "bayesian_priors",
        "downstream_consumers",
    } | SOURCE_METADATA_FIELDS:
        assert field in source_required

    policy = schema["properties"]["global_policy"]["properties"]
    assert policy["single_operator_only"]["const"] is True
    assert policy["unknown_rights_fail_closed"]["const"] is True
    assert policy["third_party_av_non_autonomous_public_default"]["const"] is True
    assert policy["explicit_clearance_required_for_third_party_av_public"]["const"] is True
    assert policy["absolute_local_paths_allowed"]["const"] is False


def test_seeded_ledger_has_complete_definitions_and_no_workstation_paths() -> None:
    ledger = _ledger()
    body = _body()
    ledger_text = LEDGER.read_text(encoding="utf-8")

    assert ledger["schema_version"] == 1
    assert re.match(r"^[a-z][a-z0-9_:-]*$", ledger["ledger_id"])
    assert "/home/" not in ledger_text

    rights = {record["rights_class"] for record in ledger["rights_class_definitions"]}
    postures = {record["posture"] for record in ledger["source_posture_definitions"]}

    assert rights == EXPECTED_RIGHTS_CLASSES
    assert postures == EXPECTED_POSTURES

    for rights_class in EXPECTED_RIGHTS_CLASSES:
        assert f"`{rights_class}`" in body
    for posture in EXPECTED_POSTURES:
        assert f"`{posture}`" in body


def test_every_source_records_rights_provenance_wcs_evidence_and_priors() -> None:
    for source_id, source in _sources_by_id().items():
        for field in SOURCE_METADATA_FIELDS:
            assert source[field], source_id

        assert re.match(r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$", source["date_checked"])
        assert source["rights_class"] in EXPECTED_RIGHTS_CLASSES, source_id
        assert set(source["postures"]) <= EXPECTED_POSTURES, source_id
        assert set(source["downstream_consumers"]) == EXPECTED_CONSUMERS, source_id
        assert source["wcs_substrate_refs"], source_id
        assert source["evidence_refs"], source_id
        assert source["provenance_requirements"], source_id

        eligibility = source["eligibility"]
        for field in (
            "private_allowed",
            "dry_run_allowed",
            "public_live_allowed",
            "public_archive_allowed",
            "public_monetizable_allowed",
            "autonomous_public_allowed",
            "link_along_allowed",
            "metadata_first_allowed",
            "archive_only_allowed",
            "refusal_artifact_allowed",
        ):
            assert isinstance(eligibility[field], bool), source_id

        priors = source["bayesian_priors"]
        assert {
            "content-opportunity-model.posterior_state.source_prior",
            "content-opportunity-model.posterior_state.rights_pass_probability",
        } <= set(priors["posterior_refs"])

        for prior_name in (
            "source_prior",
            "rights_pass_prior",
            "provenance_strength_prior",
            "risk_prior",
        ):
            prior = priors[prior_name]
            assert prior["alpha"] > 0, (source_id, prior_name)
            assert prior["beta"] > 0, (source_id, prior_name)
            assert 0 <= prior["mean"] <= 1, (source_id, prior_name)
            assert prior["evidence_refs"], (source_id, prior_name)


def test_third_party_av_is_not_autonomous_public_without_explicit_clearance() -> None:
    for source_id, source in _sources_by_id().items():
        media = source["media_profile"]
        eligibility = source["eligibility"]

        if not media["third_party_av"]:
            continue

        if media["explicitly_cleared_for_autonomous_public"]:
            assert media["clearance_evidence_refs"], source_id
            assert source["rights_class"] in {"owned", "public_domain", "cc_compatible", "licensed"}
            continue

        assert eligibility["autonomous_public_allowed"] is False, source_id
        assert eligibility["public_live_allowed"] is False, source_id
        assert eligibility["public_archive_allowed"] is False, source_id
        assert eligibility["public_monetizable_allowed"] is False, source_id
        assert set(eligibility["allowed_public_modes"]) <= {"private", "dry_run"}, source_id
        assert (
            "third_party_av_uncleared" in eligibility["block_reasons"]
            or "forbidden_source_shape" in eligibility["block_reasons"]
        ), source_id

    body = _body()
    assert "Third-party AV is non-autonomous-public by default" in body
    assert "may not be autonomously carried, rebroadcast, cached" in body


def test_source_and_rights_pass_priors_feed_the_bayesian_model() -> None:
    sources = _sources_by_id()

    assert (
        sources["operator_owned_archive_segments"]["bayesian_priors"]["rights_pass_prior"]["mean"]
        >= 0.8
    )
    assert (
        sources["third_party_av_link_along_pool"]["bayesian_priors"]["rights_pass_prior"]["mean"]
        <= 0.25
    )
    assert (
        sources["forbidden_uncleared_media_cache"]["bayesian_priors"]["risk_prior"]["mean"] >= 0.8
    )

    body = _body()
    for phrase in (
        "`bayesian_priors.source_prior`",
        "`bayesian_priors.rights_pass_prior`",
        "`content-opportunity-model.posterior_state.source_prior`",
        "`content-opportunity-model.posterior_state.rights_pass_probability`",
    ):
        assert phrase in body


def test_format_policies_cover_all_formats_and_preserve_source_postures() -> None:
    formats = _formats_by_id()

    assert set(formats) == EXPECTED_FORMATS

    for format_id, policy in formats.items():
        assert set(policy["allowed_source_postures"]) <= EXPECTED_POSTURES, format_id
        assert policy["third_party_av_default"] == "non_autonomous_public", format_id
        assert policy["autonomous_public_third_party_av_allowed"] is False, format_id
        assert policy["clearance_required_for_third_party_av_public"] is True, format_id
        assert (
            policy["bayesian_inputs"]["source_prior_ref"]
            == "source_pool[].bayesian_priors.source_prior"
        )
        assert (
            policy["bayesian_inputs"]["rights_pass_prior_ref"]
            == "source_pool[].bayesian_priors.rights_pass_prior"
        )
        assert set(policy["blocked_rights_classes"]) >= {
            "fair_use_candidate",
            "forbidden",
            "unknown",
        }
        assert policy["required_downstream_fields"], format_id

    assert "link_along" in formats["watch_along"]["allowed_source_postures"]
    assert formats["watch_along"]["public_mode_ceiling"] == "dry_run"
    assert "refusal_artifact" in formats["refusal_breakdown"]["allowed_source_postures"]


def test_downstream_contract_prevents_reinferring_rights() -> None:
    ledger = _ledger()
    contract = ledger["downstream_contract"]

    assert set(contract["machine_consumers"]) == EXPECTED_CONSUMERS

    for field in (
        "source_url",
        "creator",
        "rightsholder",
        "rights_class",
        "license",
        "permission",
        "acquisition_method",
        "capture_method",
        "date_checked",
        "media_profile",
        "eligibility",
        "postures",
        "wcs_substrate_refs",
        "evidence_refs",
        "bayesian_priors",
    ):
        assert field in contract["preserved_fields"]

    body = _body()
    for phrase in (
        "scheduler, run store, public adapter, conversion broker, and",
        "from re-inferring rights",
        "`archive.vod_sidecar`",
        "`public.youtube_metadata`",
        "`asset.provenance_manifest`",
    ):
        assert phrase in body

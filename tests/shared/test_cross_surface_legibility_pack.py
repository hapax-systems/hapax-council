"""Tests for cross-surface public legibility pack content policy."""

from __future__ import annotations

from pathlib import Path

import yaml

PACK_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "publication-drafts"
    / "cross-surface-public-legibility-pack.yaml"
)

PROHIBITED_TERMS = [
    "community",
    "family",
    "tribe",
    "followers",
    "tier",
    "reward",
    "exclusive access",
    "member benefit",
    "please support",
    "help me",
    "donate",
    "fund us",
    "AI assistant",
    "smart home",
    "productivity tool",
    "will change",
    "revolutionary",
    "disrupting",
]


def _load_pack() -> dict:
    return yaml.safe_load(PACK_PATH.read_text())


def test_pack_loads_valid_yaml() -> None:
    pack = _load_pack()
    assert pack["schema_version"] == 2
    assert "spine" in pack
    assert "variants" in pack
    assert pack["publication_allowed"] is False
    assert pack["review_required"] == "claim_verification_council"


def test_all_required_variants_present() -> None:
    pack = _load_pack()
    required = {
        "github_org_profile",
        "weblog",
        "statuslog",
        "support_page",
    }
    assert required <= set(pack["variants"].keys())


def _contains_prohibited(text: str, term: str) -> bool:
    import re

    return bool(re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE))


def test_no_prohibited_language_in_variants() -> None:
    pack = _load_pack()
    for variant_name, variant in pack["variants"].items():
        text = variant.get("text", "")
        for term in PROHIBITED_TERMS:
            assert not _contains_prohibited(text, term), (
                f"variant '{variant_name}' contains prohibited term '{term}'"
            )


def test_no_prohibited_language_in_spine() -> None:
    pack = _load_pack()
    spine = pack["spine"]
    for term in PROHIBITED_TERMS:
        assert not _contains_prohibited(spine, term), f"spine contains prohibited term '{term}'"


def test_source_ref_policy_requires_sources_for_factual_claims() -> None:
    pack = _load_pack()
    policy = pack["source_ref_policy"].lower()
    assert "every factual public claim" in policy
    assert "source ref" in policy
    assert "unsourced claims" in policy


def test_support_page_no_perk_language() -> None:
    pack = _load_pack()
    text = pack["variants"]["support_page"]["text"].lower()
    assert "do not create access" in text
    assert "support entitlement" in text
    assert "separate cleared path" in text


def test_each_variant_has_surface() -> None:
    pack = _load_pack()
    for name, variant in pack["variants"].items():
        assert "surface" in variant, f"variant '{name}' missing surface field"


def test_weblog_variant_pins_publication_bus_surface_gates() -> None:
    pack = _load_pack()
    weblog = pack["variants"]["weblog"]
    assert weblog["publication_allowed"] is False
    assert set(weblog["target_surfaces"]) == {
        "omg-weblog",
        "omg-lol-weblog-bearer-fanout",
        "omg-lol-statuslog",
        "omg-lol-now",
        "omg-lol-pastebin",
        "omg-lol-purl",
        "omg-lol-web",
        "bridgy-webmention-publish",
        "mastodon-post",
        "bluesky-post",
        "arena-post",
        "zenodo-doi",
        "internet-archive-ias3",
    }
    assert set(weblog["required_gates"]) == {
        "source_artifact_public_safe",
        "source_refs_present",
        "rights_privacy_redaction_pass",
        "target_surface_allowlist_pass",
        "fanout_loop_prevention_present",
        "claim_review_current",
        "no_direct_public_egress",
    }


def test_github_org_profile_variant_points_to_canonical_renderer() -> None:
    pack = _load_pack()
    profile = pack["variants"]["github_org_profile"]
    assert profile["publication_allowed"] is False
    assert profile["source_of_truth"] == "hapax-constitution:sdlc.render.org_profile_readme"
    assert set(profile["required_gates"]) == {
        "claim_review_current",
        "source_refs_present",
        "public_repo_owner_check",
        "no_direct_public_egress",
    }
    ceiling = profile["claim_ceiling"].lower()
    assert "shipped read paths" in ceiling
    assert "autonomous write authority" in ceiling


def test_variants_respect_max_length() -> None:
    pack = _load_pack()
    for name, variant in pack["variants"].items():
        max_len = variant.get("max_length_chars")
        if max_len:
            text = variant.get("text", "")
            assert len(text) <= max_len, (
                f"variant '{name}' text ({len(text)} chars) exceeds max_length_chars ({max_len})"
            )

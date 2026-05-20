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
    assert pack["schema_version"] == 1
    assert "spine" in pack
    assert "variants" in pack


def test_all_required_variants_present() -> None:
    pack = _load_pack()
    required = {
        "youtube",
        "weblog",
        "statuslog",
        "grant_packet",
        "support_page",
        "artifact_catalog",
        "stakeholder_brief",
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


def test_grant_packet_has_source_refs() -> None:
    pack = _load_pack()
    grant = pack["variants"]["grant_packet"]
    assert len(grant.get("source_refs", [])) >= 3


def test_support_page_no_perk_language() -> None:
    pack = _load_pack()
    text = pack["variants"]["support_page"]["text"].lower()
    assert "no perks" in text
    assert "no community" in text or "no obligation" in text


def test_each_variant_has_surface() -> None:
    pack = _load_pack()
    for name, variant in pack["variants"].items():
        assert "surface" in variant, f"variant '{name}' missing surface field"


def test_variants_respect_max_length() -> None:
    pack = _load_pack()
    for name, variant in pack["variants"].items():
        max_len = variant.get("max_length_chars")
        if max_len:
            text = variant.get("text", "")
            assert len(text) <= max_len, (
                f"variant '{name}' text ({len(text)} chars) exceeds max_length_chars ({max_len})"
            )

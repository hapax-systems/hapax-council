"""Repo-side GitHub Sponsors activation contract."""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_funding_yml_targets_hapax_systems_org() -> None:
    funding = yaml.safe_load((REPO_ROOT / ".github" / "FUNDING.yml").read_text())

    assert funding["github"] == ["hapax-systems", "ryanklee"]


def test_readme_and_omg_landing_link_to_org_sponsors_profile() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    landing = (REPO_ROOT / "agents" / "omg_web_builder" / "static" / "index.html").read_text(
        encoding="utf-8"
    )

    assert "https://github.com/sponsors/hapax-systems" in readme
    assert "Sponsor Hapax research" in readme
    assert "https://github.com/sponsors/hapax-systems" in landing


def test_sponsors_tier_example_is_no_perk_org_support() -> None:
    config = tomllib.loads(
        (REPO_ROOT / "config" / "gh-sponsors-tiers.toml.example").read_text(encoding="utf-8")
    )

    assert config["profile"]["account"] == "hapax-systems"
    assert [tier["amount_usd_cents"] for tier in config["tiers"]] == [
        100,
        500,
        1000,
        2500,
    ]
    for tier in config["tiers"]:
        assert tier["kind"] == "monthly"
        assert tier["sponsorware_threshold"] == ""
        text = tier["description"].lower()
        assert "no perks" in text
        assert "access" in text
        assert "deliverables" in text
        assert "control" in text

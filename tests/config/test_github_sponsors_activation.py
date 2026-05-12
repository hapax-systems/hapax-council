"""Repo-side GitHub Sponsors activation contract."""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_funding_yml_targets_verified_public_sponsors_listing() -> None:
    funding = yaml.safe_load((REPO_ROOT / ".github" / "FUNDING.yml").read_text())

    assert funding["github"] == ["ryanklee"]


def test_readme_and_omg_landing_route_through_no_perk_support_page() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    landing = (REPO_ROOT / "agents" / "omg_web_builder" / "static" / "index.html").read_text(
        encoding="utf-8"
    )

    assert "https://hapax.omg.lol/support" in readme
    assert "Support Hapax research" in readme
    assert "github.com/sponsors/hapax-systems" not in readme
    assert "hapax.omg.lol/support" in landing
    assert "github.com/sponsors/hapax-systems" not in landing


def test_launch_proof_downgrades_all_payment_rails_claim() -> None:
    proof = (
        REPO_ROOT / "docs" / "monetization" / "hn-launch-support-money-rails-proof.md"
    ).read_text(encoding="utf-8")
    matrix = (REPO_ROOT / "docs" / "monetization" / "rails-capability-matrix.md").read_text(
        encoding="utf-8"
    )

    assert "all external rails as green" in proof
    assert "implementation capability" in matrix
    assert "every external account" in matrix


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

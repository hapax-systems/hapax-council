"""Pin the GitHub profile README's public-surface contract."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_README = REPO_ROOT / "docs" / "repo-pres" / "dot-github-scaffold" / "profile" / "README.md"


def _profile() -> str:
    return PROFILE_README.read_text(encoding="utf-8")


def test_profile_source_exists() -> None:
    assert PROFILE_README.exists()


def test_profile_centers_current_project_spine() -> None:
    body = _profile().lower()
    for token in (
        "single-operator",
        "externalized executive function",
        "semantic recruitment",
        "constitutional governance",
        "refusal-as-data",
        "public egress",
    ):
        assert token in body


def test_profile_declares_no_product_or_contributor_posture() -> None:
    body = _profile().lower()
    assert "not a product" in body
    assert "not seeking contributors" in body
    assert "support tickets" in body


def test_profile_maps_current_public_repos() -> None:
    body = _profile()
    for repo in (
        "https://github.com/hapax-systems/hapax-council",
        "https://github.com/hapax-systems/agentgov",
        "https://github.com/ryanklee/hapax-constitution",
        "https://github.com/ryanklee/hapax-officium",
        "https://github.com/ryanklee/hapax-assets",
    ):
        assert repo in body


def test_profile_does_not_link_private_repos_as_public() -> None:
    body = _profile()
    for private_repo in ("hapax-mcp", "hapax-watch", "hapax-phone"):
        assert f"https://github.com/ryanklee/{private_repo}" not in body
        assert f"`{private_repo}`" in body
    assert "private surfaces" in body


def test_profile_uses_current_council_location() -> None:
    body = _profile()
    assert "https://github.com/hapax-systems/hapax-council" in body
    assert "https://github.com/ryanklee/hapax-council" not in body

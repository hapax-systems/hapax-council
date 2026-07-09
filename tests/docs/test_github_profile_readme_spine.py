"""Pin the superseded dot-github scaffold contract."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_README = REPO_ROOT / "docs" / "repo-pres" / "dot-github-scaffold" / "profile" / "README.md"


def _profile() -> str:
    return PROFILE_README.read_text(encoding="utf-8")


def test_profile_scaffold_source_exists() -> None:
    assert PROFILE_README.exists()


def test_profile_scaffold_is_not_publish_source() -> None:
    body = _profile().lower()
    assert "superseded profile copy" in body
    assert "no longer a publish source" in body
    assert "hapax-systems/.github/profile/readme.md" in body


def test_profile_scaffold_points_to_canonical_renderer() -> None:
    body = _profile()
    assert "python -m sdlc.render --org-profile" in body
    assert "hapax-constitution" in body
    assert "test_cli_dry_run_prints_org_profile" in body
    assert "test_cli_org_profile_write_creates_nested_profile_readme" in body


def test_profile_scaffold_blocks_personal_account_drift() -> None:
    body = _profile()
    assert "github.com/ryanklee" not in body
    assert "non-organization owner" in body

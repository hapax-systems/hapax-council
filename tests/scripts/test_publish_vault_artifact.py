"""Tests for the vault Markdown publication bridge."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import publish_vault_artifact

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOW_HN_DRAFT = (
    REPO_ROOT / "docs" / "publication-drafts" / "2026-05-10-show-hn-governance-that-ships.md"
)


class TestBuildArtifact:
    def test_carries_source_path_and_author_model(self, tmp_path) -> None:
        source = tmp_path / "draft.md"
        source.write_text(
            "---\ntitle: Draft\nslug: draft\nauthor_model: codex\n---\n\nBody\n",
            encoding="utf-8",
        )

        artifact = publish_vault_artifact._build_artifact(
            body_md="Body",
            frontmatter={"title": "Draft", "slug": "draft", "author_model": "codex"},
            surfaces=["omg-weblog"],
            approver="Oudepode",
            source_path=source,
        )

        assert artifact.slug == "draft"
        assert artifact.source_path == str(source)
        assert artifact.author_model == "codex"
        assert artifact.is_approved()

    def test_resolves_existing_title_slug_frontmatter_casing(self) -> None:
        artifact = publish_vault_artifact._build_artifact(
            body_md="# Body Heading\n\nBody",
            frontmatter={"Title": "Canonical Draft", "Slug": "canonical-draft"},
            surfaces=["omg-weblog"],
            approver="Oudepode",
        )

        assert artifact.title == "Canonical Draft"
        assert artifact.slug == "canonical-draft"
        assert artifact.surfaces_targeted == ["omg-weblog"]


def test_show_hn_draft_dry_run_uses_existing_frontmatter_casing(tmp_path, capsys) -> None:
    rc = publish_vault_artifact.main(
        [
            str(SHOW_HN_DRAFT),
            "--surfaces",
            "omg-weblog",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "Show HN: Mechanical Governance for AI Coding Agents at 3,000+ PRs"
    assert payload["slug"] == "show-hn-governance-that-ships"
    assert payload["surfaces_targeted"] == ["omg-weblog"]
    assert payload["approval"] == "approved"
    assert not (tmp_path / "publish" / "inbox").exists()

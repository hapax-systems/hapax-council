"""Tests for the vault Markdown publication bridge."""

from __future__ import annotations

from scripts import publish_vault_artifact


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

"""Tests for the vault Markdown publication bridge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
            frontmatter={
                "title": "Draft",
                "slug": "draft",
                "author_model": "codex",
                "Publication-Allowed": True,
            },
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
            frontmatter={
                "Title": "Canonical Draft",
                "Slug": "canonical-draft",
                "Publication-Allowed": "approved",
            },
            surfaces=["omg-weblog"],
            approver="Oudepode",
        )

        assert artifact.title == "Canonical Draft"
        assert artifact.slug == "canonical-draft"
        assert artifact.surfaces_targeted == ["omg-weblog"]

    def test_carries_publication_gate_context_and_override(self) -> None:
        artifact = publish_vault_artifact._build_artifact(
            body_md="Body",
            frontmatter={
                "title": "Draft",
                "slug": "draft",
                "Publication-Allowed": True,
                "publication_gate_context": {
                    "numeric_expectations": {"42 hooks": 42},
                    "currentness_evidence_refs": ["receipt:hn-readiness"],
                },
                "publication_gate_override": {
                    "by_referent": "Oudepode",
                    "reason": "Reviewed receipts",
                },
            },
            surfaces=["omg-weblog"],
            approver="Oudepode",
        )

        assert artifact.publication_gate_context == {
            "numeric_expectations": {"42 hooks": 42},
            "currentness_evidence_refs": ["receipt:hn-readiness"],
        }
        assert artifact.publication_gate_override == {
            "by_referent": "Oudepode",
            "reason": "Reviewed receipts",
        }

    def test_requires_explicit_publication_allowed(self) -> None:
        with pytest.raises(publish_vault_artifact.PublicationGateError):
            publish_vault_artifact._build_artifact(
                body_md="Body",
                frontmatter={"title": "Draft", "slug": "draft"},
                surfaces=["omg-weblog"],
                approver="Oudepode",
            )

    def test_rejects_surface_outside_configured_allowlist(self) -> None:
        with pytest.raises(publish_vault_artifact.SurfaceAllowlistError):
            publish_vault_artifact._build_artifact(
                body_md="Body",
                frontmatter={
                    "title": "Draft",
                    "slug": "draft",
                    "Publication-Allowed": True,
                },
                surfaces=["perplexity-model-council"],
                approver="Oudepode",
            )


def test_allowed_draft_dry_run_uses_existing_frontmatter_casing(tmp_path, capsys) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        (
            "---\n"
            "Title: Allowed Draft\n"
            "Slug: allowed-draft\n"
            "Publication-Allowed: true\n"
            "---\n\n"
            "# Allowed Draft\n\nBody\n"
        ),
        encoding="utf-8",
    )

    rc = publish_vault_artifact.main(
        [
            str(draft),
            "--surfaces",
            "omg-weblog",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "Allowed Draft"
    assert payload["slug"] == "allowed-draft"
    assert payload["surfaces_targeted"] == ["omg-weblog"]
    assert payload["approval"] == "approved"
    assert not (tmp_path / "publish" / "inbox").exists()


def test_missing_publication_allowed_refuses_publication(tmp_path, capsys) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        ("---\nTitle: Missing Gate\nSlug: missing-gate\n---\n\n# Missing Gate\n\nBody\n"),
        encoding="utf-8",
    )

    rc = publish_vault_artifact.main(
        [
            str(draft),
            "--surfaces",
            "omg-weblog",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert rc == 1
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "publish" / "inbox").exists()


def test_malformed_publication_allowed_refuses_publication(tmp_path, capsys) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        (
            "---\n"
            "Title: Malformed Gate\n"
            "Slug: malformed-gate\n"
            "Publication-Allowed: not-yet\n"
            "---\n\n"
            "# Malformed Gate\n\nBody\n"
        ),
        encoding="utf-8",
    )

    rc = publish_vault_artifact.main(
        [
            str(draft),
            "--surfaces",
            "omg-weblog",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert rc == 1
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "publish" / "inbox").exists()


def test_invalid_yaml_frontmatter_refuses_publication_even_when_allowed(tmp_path, capsys) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        (
            "---\n"
            "Title: Invalid YAML\n"
            "Slug: invalid-yaml\n"
            "Publication-Allowed: true\n"
            "broken: [unterminated\n"
            "---\n\n"
            "# Invalid YAML\n\nBody\n"
        ),
        encoding="utf-8",
    )

    rc = publish_vault_artifact.main(
        [
            str(draft),
            "--surfaces",
            "omg-weblog",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert rc == 1
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "publish" / "inbox").exists()


def test_surface_outside_allowlist_refuses_publication(tmp_path, capsys) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        (
            "---\n"
            "Title: Bad Surface\n"
            "Slug: bad-surface\n"
            "Publication-Allowed: true\n"
            "---\n\n"
            "# Bad Surface\n\nBody\n"
        ),
        encoding="utf-8",
    )

    rc = publish_vault_artifact.main(
        [
            str(draft),
            "--surfaces",
            "perplexity-model-council",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    )

    assert rc == 1
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "publish" / "inbox").exists()


def test_superseded_show_hn_draft_dry_run_refuses_publication(tmp_path, capsys) -> None:
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

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert not (tmp_path / "publish" / "inbox").exists()

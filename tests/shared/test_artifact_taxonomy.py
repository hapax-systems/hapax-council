"""Tests for research artifact taxonomy and frontmatter validation."""

from __future__ import annotations

from pathlib import Path

from shared.artifact_taxonomy import (
    ArtifactClass,
    infer_artifact_class,
    validate_artifact,
)


def test_infer_spec():
    assert (
        infer_artifact_class(Path("docs/superpowers/specs/2026-05-15-foo.md")) == ArtifactClass.SPEC
    )


def test_infer_research():
    assert infer_artifact_class(Path("docs/research/2026-05-15-foo.md")) == ArtifactClass.RESEARCH


def test_infer_audit():
    assert infer_artifact_class(Path("docs/audits/foo-audit.md")) == ArtifactClass.AUDIT


def test_infer_plan():
    assert infer_artifact_class(Path("docs/superpowers/plans/foo-plan.md")) == ArtifactClass.PLAN


def test_infer_brief():
    assert infer_artifact_class(Path("docs/refusal-briefs/foo.md")) == ArtifactClass.BRIEF


def test_infer_unknown():
    assert infer_artifact_class(Path("README.md")) == ArtifactClass.UNKNOWN


def test_validate_fully_attributed_spec(tmp_path: Path):
    spec = tmp_path / "test-spec.md"
    spec.write_text(
        "---\nStatus: ready\nDate: 2026-05-15\nScope: foo\nNon-scope: none\nTask: bar\n---\n# Title"
    )
    result = validate_artifact(spec, ArtifactClass.SPEC)
    assert result.valid
    assert result.missing_required == ()
    assert result.missing_recommended == ()


def test_validate_missing_required(tmp_path: Path):
    spec = tmp_path / "test-spec.md"
    spec.write_text("---\nStatus: ready\n---\n# Title")
    result = validate_artifact(spec, ArtifactClass.SPEC)
    assert not result.valid
    assert "Date" in result.missing_required
    assert "Scope" in result.missing_required


def test_validate_no_frontmatter(tmp_path: Path):
    doc = tmp_path / "bare.md"
    doc.write_text("# Just a title\n\nNo frontmatter.")
    result = validate_artifact(doc, ArtifactClass.RESEARCH)
    assert not result.valid
    assert not result.has_frontmatter


def test_validate_research_with_date_only(tmp_path: Path):
    doc = tmp_path / "research.md"
    doc.write_text("---\nDate: 2026-05-15\n---\n# Research")
    result = validate_artifact(doc, ArtifactClass.RESEARCH)
    assert result.valid
    assert "Scope" in result.missing_recommended

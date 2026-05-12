"""Tests for ``shared.preprint_artifact``."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.co_author_model import CLAUDE_CODE, HAPAX, OUDEPODE
from shared.preprint_artifact import (
    ApprovalState,
    PreprintArtifact,
    from_omg_weblog_draft,
)

# ── Schema + defaults ───────────────────────────────────────────────


class TestSchema:
    def test_minimal_fields(self):
        artifact = PreprintArtifact(slug="test", title="Hello")
        assert artifact.slug == "test"
        assert artifact.title == "Hello"
        assert artifact.approval == ApprovalState.DRAFT
        assert artifact.schema_version == "1"

    def test_default_co_authors_is_canonical_cluster(self):
        artifact = PreprintArtifact(slug="x", title="X")
        names = [c.name for c in artifact.co_authors]
        assert names == ["Hapax", "Claude Code", "Oudepode"]

    def test_co_authors_override(self):
        artifact = PreprintArtifact(slug="x", title="X", co_authors=[HAPAX, OUDEPODE])
        assert [c.name for c in artifact.co_authors] == ["Hapax", "Oudepode"]

    def test_blank_slug_rejected(self):
        with pytest.raises(ValidationError):
            PreprintArtifact(slug="", title="X")

    def test_long_title_rejected(self):
        with pytest.raises(ValidationError):
            PreprintArtifact(slug="x", title="X" * 250)


# ── Approval lifecycle ──────────────────────────────────────────────


class TestApprovalLifecycle:
    def test_initial_state_is_draft(self):
        artifact = PreprintArtifact(slug="x", title="X")
        assert artifact.approval == ApprovalState.DRAFT
        assert not artifact.is_approved()

    def test_mark_approved_sets_audit_trail(self):
        artifact = PreprintArtifact(slug="x", title="X")
        artifact.mark_approved(by_referent="Oudepode")
        assert artifact.is_approved()
        assert artifact.approval == ApprovalState.APPROVED
        assert artifact.approved_by_referent == "Oudepode"
        assert artifact.approved_at is not None
        delta = datetime.now(UTC) - artifact.approved_at
        assert delta.total_seconds() < 5.0

    def test_mark_published_preserves_audit_trail(self):
        artifact = PreprintArtifact(slug="x", title="X")
        artifact.mark_approved(by_referent="OTO")
        approved_at = artifact.approved_at
        artifact.mark_published()
        assert artifact.approval == ApprovalState.PUBLISHED
        assert artifact.approved_at == approved_at
        assert artifact.approved_by_referent == "OTO"

    def test_mark_failed_preserves_audit_trail(self):
        artifact = PreprintArtifact(slug="x", title="X")
        artifact.mark_approved(by_referent="OTO")
        approved_at = artifact.approved_at
        artifact.mark_failed()
        assert artifact.approval == ApprovalState.FAILED
        assert artifact.approved_at == approved_at
        assert artifact.approved_by_referent == "OTO"


# ── Inbox layout ────────────────────────────────────────────────────


class TestInboxLayout:
    def test_inbox_path(self, tmp_path):
        artifact = PreprintArtifact(slug="my-paper", title="X")
        assert artifact.inbox_path(state_root=tmp_path) == tmp_path / "publish/inbox/my-paper.json"

    def test_draft_path(self, tmp_path):
        artifact = PreprintArtifact(slug="my-paper", title="X")
        assert artifact.draft_path(state_root=tmp_path) == tmp_path / "publish/draft/my-paper.json"

    def test_published_path(self, tmp_path):
        artifact = PreprintArtifact(slug="my-paper", title="X")
        assert (
            artifact.published_path(state_root=tmp_path)
            == tmp_path / "publish/published/my-paper.json"
        )

    def test_failed_path(self, tmp_path):
        artifact = PreprintArtifact(slug="my-paper", title="X")
        assert (
            artifact.failed_path(state_root=tmp_path) == tmp_path / "publish/failed/my-paper.json"
        )

    def test_log_path_per_surface(self, tmp_path):
        artifact = PreprintArtifact(slug="my-paper", title="X")
        assert (
            artifact.log_path("bluesky-post", state_root=tmp_path)
            == tmp_path / "publish/log/my-paper.bluesky-post.json"
        )


# ── JSON round-trip ─────────────────────────────────────────────────


class TestJsonRoundTrip:
    def test_round_trip_preserves_fields(self):
        original = PreprintArtifact(
            slug="round-trip",
            title="Round-trip test",
            abstract="A short abstract.",
            body_md="# Header\n\nBody.",
            surfaces_targeted=["bluesky-post", "osf-preprint"],
            attribution_block="Hapax + Claude Code + Oudepode (authorship intentionally unsettled).",
        )
        original.mark_approved(by_referent="Oudepode")

        encoded = original.model_dump_json()
        decoded = PreprintArtifact.model_validate_json(encoded)

        assert decoded.slug == original.slug
        assert decoded.title == original.title
        assert decoded.abstract == original.abstract
        assert decoded.body_md == original.body_md
        assert decoded.surfaces_targeted == original.surfaces_targeted
        assert decoded.attribution_block == original.attribution_block
        assert decoded.approval == ApprovalState.APPROVED
        assert decoded.approved_by_referent == "Oudepode"
        assert [c.name for c in decoded.co_authors] == ["Hapax", "Claude Code", "Oudepode"]

    def test_round_trip_via_filesystem(self, tmp_path):
        artifact = PreprintArtifact(slug="fs-round", title="Filesystem round-trip")
        path = artifact.draft_path(state_root=tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.model_dump_json(indent=2))

        loaded = PreprintArtifact.model_validate_json(path.read_text())
        assert loaded.slug == "fs-round"
        assert loaded.title == "Filesystem round-trip"


# ── omg_weblog_draft constructor ────────────────────────────────────


class TestFromOmgWeblogDraft:
    def test_default_surfaces(self):
        artifact = from_omg_weblog_draft(
            slug="post-1",
            title="A post",
            abstract="Brief.",
            body_md="Body.",
        )
        assert artifact.slug == "post-1"
        assert "omg-weblog" in artifact.surfaces_targeted
        assert "bluesky-post" in artifact.surfaces_targeted
        assert "bridgy-webmention-publish" in artifact.surfaces_targeted

    def test_default_surfaces_resolve_through_publication_registry(self):
        from agents.publication_bus.surface_registry import SURFACE_REGISTRY, is_engageable

        artifact = from_omg_weblog_draft(
            slug="post-1",
            title="A post",
            abstract="Brief.",
            body_md="Body.",
        )

        for surface in artifact.surfaces_targeted:
            assert surface in SURFACE_REGISTRY
            assert is_engageable(surface)

    def test_override_surfaces(self):
        artifact = from_omg_weblog_draft(
            slug="post-1",
            title="A post",
            abstract="Brief.",
            body_md="Body.",
            surfaces_targeted=["bluesky-post"],
        )
        assert artifact.surfaces_targeted == ["bluesky-post"]

    def test_co_author_override(self):
        artifact = from_omg_weblog_draft(
            slug="post-1",
            title="A post",
            abstract="Brief.",
            body_md="Body.",
            co_authors=[HAPAX, CLAUDE_CODE],
        )
        assert [c.name for c in artifact.co_authors] == ["Hapax", "Claude Code"]


# ── Pydantic semantics ──────────────────────────────────────────────


class TestPydanticSemantics:
    def test_unknown_field_ignored_pydantic_v2(self):
        encoded = json.dumps({"slug": "x", "title": "X", "future_field": 42})
        artifact = PreprintArtifact.model_validate_json(encoded)
        assert artifact.slug == "x"
        assert not hasattr(artifact, "future_field")


def test_grounding_gate_result_survives_round_trip() -> None:
    """grounding_gate_result must survive JSON serialization/deserialization."""
    gate = {
        "claim": {
            "evidence_refs": ["vault:research/source-1"],
            "provenance": {"source_refs": ["vault:research/source-1"]},
            "freshness": {"checked_at": "2026-05-11T00:00:00Z"},
            "refusal_correction_path": {"correction": "none"},
            "public_private_mode": "public",
        },
        "gate_result": {"passed": True},
        "public_private_mode": "public",
    }
    artifact = PreprintArtifact(
        slug="grounding-test",
        title="Grounding gate round-trip test",
        grounding_gate_result=gate,
    )
    data = artifact.model_dump()
    assert data["grounding_gate_result"] == gate

    restored = PreprintArtifact.model_validate(data)
    assert restored.grounding_gate_result == gate


def test_grounding_gate_result_defaults_to_none() -> None:
    artifact = PreprintArtifact(slug="no-gate", title="No grounding gate")
    assert artifact.grounding_gate_result is None

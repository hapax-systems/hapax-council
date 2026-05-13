"""Tests for PreprintArtifact → ResearchVehiclePublicEvent projection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema

from agents.publish_orchestrator.orchestrator import _artifact_fingerprint
from shared.preprint_artifact import (
    DEFAULT_OMG_WEBLOG_SURFACES,
    OMG_WEBLOG_DIRECT_FANOUT_SURFACES,
    PreprintArtifact,
    from_omg_weblog_draft,
)
from shared.publication_artifact_public_event import (
    DIRECT_DISPATCH_SECONDARY_FANOUT_HOLD_REASON,
    build_publication_artifact_public_event,
    github_public_material_surfaces,
    publication_artifact_public_event_id,
)

GENERATED_AT = datetime(2026, 4, 30, 12, 50, tzinfo=UTC)


def _artifact(
    *,
    slug: str = "refusal-annex-declined-bandcamp",
    surfaces: list[str] | None = None,
) -> PreprintArtifact:
    artifact = PreprintArtifact(
        slug=slug,
        title="Title that must not be copied into the public-event row",
        abstract="Abstract that must not be copied into the public-event row.",
        body_md="# Body\n\nPrivate draft body must stay out of public-event rows.",
        surfaces_targeted=surfaces or ["zenodo-refusal-deposit", "omg-weblog"],
    )
    artifact.mark_approved(by_referent="Oudepode")
    return artifact


def _write_log(
    state_root: Path,
    artifact: PreprintArtifact,
    surface: str,
    result: str,
    fingerprint: str,
) -> Path:
    path = artifact.log_path(surface, state_root=state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "slug": artifact.slug,
                "surface": surface,
                "result": result,
                "timestamp": "2026-04-30T12:49:00Z",
                "artifact_fingerprint": fingerprint,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_surface_log_event_preserves_orchestrator_audit_ownership(tmp_path: Path) -> None:
    artifact = _artifact()
    fingerprint = _artifact_fingerprint(artifact)
    log_path = _write_log(tmp_path, artifact, "zenodo-refusal-deposit", "ok", fingerprint)

    decision = build_publication_artifact_public_event(
        artifact,
        artifact_fingerprint=fingerprint,
        state_root=tmp_path,
        stage="surface_log",
        surface="zenodo-refusal-deposit",
        result="ok",
        result_timestamp="2026-04-30T12:49:00Z",
        source_path=log_path,
        generated_at=GENERATED_AT,
    )

    assert decision.status == "emitted"
    assert decision.audit_owner == "publish_orchestrator:publish/log/{slug}.{surface}.json"
    assert decision.idempotency_owner == "publish_orchestrator:artifact_fingerprint+surface_result"
    assert decision.public_event is not None
    event = decision.public_event
    assert event.event_type == "publication.artifact"
    assert event.occurred_at == "2026-04-30T12:49:00Z"
    assert event.source.evidence_ref == str(log_path)
    assert event.surface_policy.allowed_surfaces == ["archive", "health", "zenodo"]
    assert event.surface_policy.claim_archive is True
    assert event.surface_policy.claim_live is False
    assert event.surface_policy.claim_monetizable is False
    assert event.surface_policy.dry_run_reason is None
    assert f"artifact_fingerprint:{fingerprint}" in event.provenance.evidence_refs
    assert any(str(log_path) in ref for ref in event.provenance.evidence_refs)


def test_no_artifact_body_or_title_leaks_into_public_event(tmp_path: Path) -> None:
    artifact = _artifact()
    fingerprint = _artifact_fingerprint(artifact)

    decision = build_publication_artifact_public_event(
        artifact,
        artifact_fingerprint=fingerprint,
        state_root=tmp_path,
        stage="inbox",
        generated_at=GENERATED_AT,
    )

    assert decision.public_event is not None
    dumped = decision.public_event.model_dump_json()
    assert artifact.title not in dumped
    assert artifact.abstract not in dumped
    assert artifact.body_md not in dumped
    assert artifact.slug in dumped
    assert decision.public_event.surface_policy.dry_run_reason is not None
    assert "pending_surface_dispatch" in decision.public_event.surface_policy.dry_run_reason


def test_refusal_annex_bridgy_target_is_held_as_dry_run_scaffold(tmp_path: Path) -> None:
    artifact = _artifact(surfaces=["bridgy-webmention-publish"])
    fingerprint = _artifact_fingerprint(artifact)
    log_path = _write_log(tmp_path, artifact, "bridgy-webmention-publish", "ok", fingerprint)

    decision = build_publication_artifact_public_event(
        artifact,
        artifact_fingerprint=fingerprint,
        state_root=tmp_path,
        stage="surface_log",
        surface="bridgy-webmention-publish",
        result="ok",
        source_path=log_path,
        generated_at=GENERATED_AT,
    )

    assert decision.status == "held"
    assert decision.public_event is not None
    policy = decision.public_event.surface_policy
    assert policy.allowed_surfaces == ["health"]
    assert policy.claim_archive is False
    assert policy.fallback_action == "dry_run"
    assert policy.dry_run_reason is not None
    assert "refusal_annex_bridgy_fanout_not_claimed" in policy.dry_run_reason
    assert "mastodon" in policy.denied_surfaces
    assert "bluesky" in policy.denied_surfaces


def test_default_weblog_surface_projection_matrix_is_held_after_direct_dispatch(
    tmp_path: Path,
) -> None:
    artifact = from_omg_weblog_draft(
        slug="default-surface-matrix",
        title="Default surface matrix",
        abstract="Audit default publication-bus surfaces.",
        body_md="Body.",
        surfaces_targeted=list(OMG_WEBLOG_DIRECT_FANOUT_SURFACES),
    )
    artifact.mark_approved(by_referent="Oudepode")
    fingerprint = _artifact_fingerprint(artifact)

    expected_reasons = {
        "omg-weblog": [
            DIRECT_DISPATCH_SECONDARY_FANOUT_HOLD_REASON,
            "surface_policy_denied:omg-lol-weblog",
        ],
        "bluesky-post": [
            DIRECT_DISPATCH_SECONDARY_FANOUT_HOLD_REASON,
            "surface_policy_denied:bluesky-post",
        ],
        "mastodon-post": [
            DIRECT_DISPATCH_SECONDARY_FANOUT_HOLD_REASON,
            "surface_policy_denied:mastodon-post",
        ],
        "arena-post": [DIRECT_DISPATCH_SECONDARY_FANOUT_HOLD_REASON],
        "bridgy-webmention-publish": [
            DIRECT_DISPATCH_SECONDARY_FANOUT_HOLD_REASON,
            "surface_policy_denied:bridgy-webmention-publish",
        ],
    }

    assert DEFAULT_OMG_WEBLOG_SURFACES == ("omg-weblog",)
    assert artifact.surfaces_targeted == list(OMG_WEBLOG_DIRECT_FANOUT_SURFACES)
    for surface in OMG_WEBLOG_DIRECT_FANOUT_SURFACES:
        log_path = _write_log(tmp_path, artifact, surface, "ok", fingerprint)
        decision = build_publication_artifact_public_event(
            artifact,
            artifact_fingerprint=fingerprint,
            state_root=tmp_path,
            stage="surface_log",
            surface=surface,
            result="ok",
            result_timestamp="2026-04-30T12:49:00Z",
            source_path=log_path,
            generated_at=GENERATED_AT,
        )

        assert decision.status == "held", surface
        assert decision.public_event is not None
        policy = decision.public_event.surface_policy
        assert policy.allowed_surfaces == ["health"]
        assert policy.claim_archive is False
        assert policy.fallback_action == "hold"
        assert policy.dry_run_reason is not None
        assert policy.dry_run_reason.split(";") == expected_reasons[surface]


def test_publication_artifact_event_id_is_stable_and_schema_safe() -> None:
    event_id = publication_artifact_public_event_id(
        artifact_slug="Refusal Annex/Declined Bandcamp",
        artifact_fingerprint="abcdef0123456789abcdef0123456789",
        stage="surface_log",
        surface="zenodo-refusal-deposit",
        result="ok",
    )

    assert event_id == (
        "rvpe:publication_artifact:refusal_annex_declined_bandcamp:"
        "abcdef0123456789:surface_log:zenodo_refusal_deposit:ok"
    )


def test_github_public_material_surfaces_are_schema_and_model_supported() -> None:
    surfaces = set(github_public_material_surfaces())
    assert surfaces == {
        "github_readme",
        "github_profile",
        "github_release",
        "github_package",
        "github_pages",
        "zenodo",
    }

    schema = json.loads(
        Path("schemas/research-vehicle-public-event.schema.json").read_text(encoding="utf-8")
    )
    schema_surfaces = set(schema["$defs"]["surface"]["enum"])
    assert surfaces <= schema_surfaces

    artifact = _artifact(slug="github-public-material-witness", surfaces=["zenodo-doi"])
    fingerprint = _artifact_fingerprint(artifact)
    decision = build_publication_artifact_public_event(
        artifact,
        artifact_fingerprint=fingerprint,
        state_root=Path("/tmp/hapax-test-state"),
        stage="published",
        generated_at=GENERATED_AT,
    )
    assert decision.public_event is not None
    event = decision.public_event.model_copy(
        update={
            "surface_policy": decision.public_event.surface_policy.model_copy(
                update={"allowed_surfaces": sorted(surfaces)}
            )
        }
    )
    jsonschema.validate(event.model_dump(mode="json"), schema)

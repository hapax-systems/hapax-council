from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.github_public_surface import GitHubPublicSurfaceReport
from shared.github_publication_log import events_from_github_public_surface_report
from shared.publication_freshness import (
    ANTI_OVERCLAIM_REASON,
    PublicSurfaceFreshnessEnvelope,
    assess_public_surface_freshness,
    build_publication_freshness_event,
    build_publication_freshness_snapshot,
    github_events_to_freshness_envelopes,
    write_publication_freshness_events,
    write_publication_freshness_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "docs/repo-pres/github-public-surface-live-state-reconcile.json"
GENERATED_AT = "2026-05-01T00:50:00Z"


def _github_report() -> GitHubPublicSurfaceReport:
    return GitHubPublicSurfaceReport.model_validate(
        json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    )


def _github_envelopes() -> tuple[PublicSurfaceFreshnessEnvelope, ...]:
    github_events = events_from_github_public_surface_report(
        _github_report(),
        generated_at=GENERATED_AT,
    )
    return github_events_to_freshness_envelopes(
        github_events,
        checked_at=GENERATED_AT,
        ttl_s=1_800,
    )


def test_github_publication_witness_rows_project_to_freshness_envelopes() -> None:
    envelopes = _github_envelopes()

    assert envelopes
    assert {envelope.surface_type for envelope in envelopes} >= {
        "github.repo_metadata",
        "github.readme",
        "github.profile",
    }
    public_envelope = next(
        envelope for envelope in envelopes if envelope.freshness_result == "match"
    )
    assert public_envelope.value_braid_authority == "freshness_witness_only"
    assert public_envelope.truth_authority is False
    assert public_envelope.readback_hash
    assert public_envelope.blocks == ()


def test_missing_github_surface_becomes_public_current_blocker() -> None:
    missing = PublicSurfaceFreshnessEnvelope(
        surface_id="github.repo_metadata.hapax-systems/private-example",
        surface_type="github.repo_metadata",
        source_ref="fixture-report",
        target_ref="https://github.com/hapax-systems/private-example",
        source_of_truth="fixture",
        evidence_refs=("gh:repos/hapax-systems/private-example",),
        checked_at=GENERATED_AT,
        ttl_s=1_800,
        expires_at="2026-05-01T01:20:00Z",
        freshness_result="missing",
        blocks=("public_current", "release_authorized"),
    )

    assert missing.freshness_result == "missing"
    assert "public_current" in missing.blocks
    assert "release_authorized" in missing.blocks


def test_assessment_detects_mismatched_readback_hash() -> None:
    envelope = PublicSurfaceFreshnessEnvelope(
        surface_id="github.readme.hapax-systems/example.README.md",
        surface_type="github.readme",
        source_ref="fixture-source",
        target_ref="https://example.invalid/README.md",
        source_of_truth="fixture",
        evidence_refs=("fixture-readback",),
        rendered_hash="abc123",
        readback_hash="def456",
        checked_at=GENERATED_AT,
        ttl_s=1_800,
        expires_at="2026-05-01T01:20:00Z",
        freshness_result="unknown",
    )

    assessed = assess_public_surface_freshness(envelope, now=GENERATED_AT)

    assert assessed.freshness_result == "mismatch"
    assert assessed.blocks == ("public_current", "release_authorized")


def test_assessment_preserves_explicit_blocking_result_with_matching_hashes() -> None:
    envelope = PublicSurfaceFreshnessEnvelope(
        surface_id="github.readme.hapax-systems/example.README.md",
        surface_type="github.readme",
        source_ref="fixture-source",
        target_ref="https://example.invalid/README.md",
        source_of_truth="fixture",
        evidence_refs=("fixture-readback",),
        rendered_hash="abc123",
        readback_hash="abc123",
        checked_at=GENERATED_AT,
        ttl_s=1_800,
        expires_at="2026-05-01T01:20:00Z",
        freshness_result="auth_error",
    )

    assessed = assess_public_surface_freshness(envelope, now=GENERATED_AT)

    assert assessed.freshness_result == "auth_error"
    assert assessed.blocks == ("public_current", "release_authorized")


def test_assessment_marks_expired_envelope_stale() -> None:
    envelope = PublicSurfaceFreshnessEnvelope(
        surface_id="github.readme.hapax-systems/example.README.md",
        surface_type="github.readme",
        source_ref="fixture-source",
        target_ref="https://example.invalid/README.md",
        source_of_truth="fixture",
        evidence_refs=("fixture-readback",),
        rendered_hash="abc123",
        readback_hash="abc123",
        checked_at=GENERATED_AT,
        ttl_s=1,
        expires_at="2026-05-01T00:50:01Z",
        freshness_result="match",
    )

    assessed = assess_public_surface_freshness(envelope, now="2026-05-01T00:51:00Z")

    assert assessed.freshness_result == "stale"
    assert assessed.blocks == ("public_current", "release_authorized")


def test_match_requires_readback_hash() -> None:
    with pytest.raises(ValidationError, match="match freshness requires a readback_hash"):
        PublicSurfaceFreshnessEnvelope(
            surface_id="github.readme.hapax-systems/example.README.md",
            surface_type="github.readme",
            source_ref="fixture-source",
            source_of_truth="fixture",
            evidence_refs=("fixture-readback",),
            checked_at=GENERATED_AT,
            ttl_s=1_800,
            expires_at="2026-05-01T01:20:00Z",
            freshness_result="match",
        )


def test_expires_at_must_match_checked_at_plus_ttl() -> None:
    with pytest.raises(ValidationError, match="expires_at must equal checked_at plus ttl_s"):
        PublicSurfaceFreshnessEnvelope(
            surface_id="github.readme.hapax-systems/example.README.md",
            surface_type="github.readme",
            source_ref="fixture-source",
            source_of_truth="fixture",
            evidence_refs=("fixture-readback",),
            checked_at=GENERATED_AT,
            ttl_s=1_800,
            expires_at="2030-01-01T00:00:00Z",
            freshness_result="observed",
        )


def test_freshness_event_and_snapshot_are_witness_only(tmp_path: Path) -> None:
    snapshot = build_publication_freshness_snapshot(_github_envelopes(), generated_at=GENERATED_AT)
    event = build_publication_freshness_event(
        snapshot.envelopes[0],
        event_type="publication.surface_readback",
        generated_at=GENERATED_AT,
        occurred_at=GENERATED_AT,
    )

    assert event.event_id.startswith("pubfresh:publication.surface_readback")
    assert event.value_braid_authority == "freshness_witness_only"
    assert ANTI_OVERCLAIM_REASON in event.notes
    assert snapshot.claim_ceiling == "freshness_witness_only"

    log_path = tmp_path / "freshness-events.jsonl"
    state_path = tmp_path / "freshness-state.json"
    dry_lines = write_publication_freshness_events((event,), log_path=log_path, dry_run=True)
    dry_state = write_publication_freshness_snapshot(snapshot, path=state_path, dry_run=True)

    assert len(dry_lines) == 1
    assert json.loads(dry_lines[0])["event_type"] == "publication.surface_readback"
    assert json.loads(dry_state)["claim_ceiling"] == "freshness_witness_only"
    assert not log_path.exists()
    assert not state_path.exists()


def test_freshness_event_writes_are_idempotent_by_event_id(tmp_path: Path) -> None:
    snapshot = build_publication_freshness_snapshot(_github_envelopes(), generated_at=GENERATED_AT)
    event = build_publication_freshness_event(
        snapshot.envelopes[0],
        event_type="publication.surface_readback",
        generated_at=GENERATED_AT,
        occurred_at=GENERATED_AT,
    )
    log_path = tmp_path / "freshness-events.jsonl"

    first = write_publication_freshness_events((event,), log_path=log_path)
    second = write_publication_freshness_events((event,), log_path=log_path)

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(first) == 1
    assert second == ()
    assert [row["event_id"] for row in rows] == [event.event_id]


def test_freshness_event_write_fails_on_malformed_existing_ledger(tmp_path: Path) -> None:
    snapshot = build_publication_freshness_snapshot(_github_envelopes(), generated_at=GENERATED_AT)
    event = build_publication_freshness_event(
        snapshot.envelopes[0],
        event_type="publication.surface_readback",
        generated_at=GENERATED_AT,
        occurred_at=GENERATED_AT,
    )
    log_path = tmp_path / "freshness-events.jsonl"
    log_path.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="repair or quarantine the ledger"):
        write_publication_freshness_events((event,), log_path=log_path)

"""Tests for source-qualified TemporalSpan registry and media sidecar contracts."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.temporal_span_registry import (
    FAIL_CLOSED_POLICY,
    REQUIRED_ALIGNMENT_SOURCE_KINDS,
    REQUIRED_SIDECAR_KINDS,
    ClaimBearingMediaOutput,
    TemporalSpanRegistry,
    TemporalSpanRegistryError,
    load_temporal_span_registry_fixtures,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "temporal-span-registry.schema.json"
FIXTURES = REPO_ROOT / "config" / "temporal-span-registry-fixtures.json"


def _payload() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(FIXTURES.read_text(encoding="utf-8")))


def _fixtures():
    return load_temporal_span_registry_fixtures()


def test_schema_validates_temporal_span_registry_fixture_file() -> None:
    schema = cast("dict[str, Any]", json.loads(SCHEMA.read_text(encoding="utf-8")))
    payload = _payload()

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)
    assert set(schema["x-required_sidecar_kinds"]) == REQUIRED_SIDECAR_KINDS
    assert set(schema["x-required_alignment_source_kinds"]) == REQUIRED_ALIGNMENT_SOURCE_KINDS
    assert schema["x-fail_closed_policy"] == FAIL_CLOSED_POLICY


def test_loader_covers_required_sidecars_and_temporal_span_fields() -> None:
    fixtures = _fixtures()

    assert set(fixtures.required_sidecar_kinds) >= REQUIRED_SIDECAR_KINDS
    assert set(fixtures.sidecars_by_kind()) >= REQUIRED_SIDECAR_KINDS
    assert {span.source_kind for span in fixtures.spans} >= (
        REQUIRED_ALIGNMENT_SOURCE_KINDS | {"hls_segment", "vad_transition", "reverie_content"}
    )
    for span in fixtures.spans:
        assert span.source_id
        assert span.producer
        assert span.clock_domain
        assert span.observed_start_ns <= span.observed_end_ns
        assert span.validity_start_ns <= span.observed_start_ns
        assert span.validity_until_ns >= span.observed_end_ns
        assert span.sequence_ids
        assert span.source_refs
        assert span.content_hash.startswith("sha256:")
        assert span.artifact_path.startswith("/archive/")


def test_hls_segment_alignment_resolves_audio_camera_scene_ir_and_context_without_mtime() -> None:
    fixtures = _fixtures()
    alignment = fixtures.registry().resolve_alignment(
        fixtures.alignment_fixture.anchor_span_ref,
        required_source_kinds=fixtures.alignment_fixture.required_source_kinds,
    )

    assert alignment.used_mtime is False
    assert alignment.aligned_span_refs == fixtures.alignment_fixture.expected_aligned_span_refs
    assert alignment.missing_required_source_kinds == ()
    assert alignment.aligned_by_source_kind["audio_window"] == ("span:audio.broadcast.window.0042",)
    assert alignment.aligned_by_source_kind["camera_jpeg"] == ("span:camera.main.frame.1024",)
    assert alignment.aligned_by_source_kind["scene_detection"] == (
        "span:scene.detector.window.0042",
    )
    assert alignment.aligned_by_source_kind["ir_report"] == ("span:ir.presence.window.0042",)
    assert alignment.aligned_by_source_kind["stimmung_context"] == ("span:stimmung.context.0042",)
    assert alignment.aligned_by_source_kind["director_context"] == ("span:director.context.0042",)
    assert alignment.aligned_by_source_kind["research_condition"] == (
        "span:research.condition.fixture.0042",
    )


def test_alignment_excludes_same_time_span_from_other_capture_session() -> None:
    fixtures = _fixtures()
    span_map = fixtures.spans_by_id()
    foreign_audio = span_map["span:audio.broadcast.window.0042"].model_copy(
        update={
            "span_id": "span:audio.foreign.window.0042",
            "source_id": "audio:foreign:window0042",
            "sequence_ids": ("audio-window-foreign-0042",),
            "capture_session_id": "capture-session:foreign:2026-04-30",
            "source_span_refs": (),
        }
    )
    registry = TemporalSpanRegistry(
        spans=fixtures.spans + (foreign_audio,), sidecars=fixtures.sidecars
    )
    alignment = registry.resolve_alignment(
        fixtures.alignment_fixture.anchor_span_ref,
        required_source_kinds=("audio_window",),
    )

    assert alignment.aligned_span_refs == ("span:audio.broadcast.window.0042",)
    assert "span:audio.foreign.window.0042" not in alignment.aligned_span_refs


def test_alignment_excludes_incompatible_clock_domain_without_mapping_or_lineage() -> None:
    fixtures = _fixtures()
    span_map = fixtures.spans_by_id()
    incompatible_audio = span_map["span:audio.broadcast.window.0042"].model_copy(
        update={
            "span_id": "span:audio.unmapped-wall-clock.window.0042",
            "source_id": "audio:unmapped-wall-clock:window0042",
            "clock_domain": "wall_clock_ns",
            "sequence_ids": ("audio-window-unmapped-wall-clock-0042",),
            "source_span_refs": (),
            "metadata": {
                "sample_rate_hz": 48000,
                "channels": 2,
                "join_key": "temporal_span_overlap",
                "clock_domain_mapping_ref": "clock-map:other-session",
            },
        }
    )
    registry = TemporalSpanRegistry(
        spans=fixtures.spans + (incompatible_audio,),
        sidecars=fixtures.sidecars,
    )
    alignment = registry.resolve_alignment(
        fixtures.alignment_fixture.anchor_span_ref,
        required_source_kinds=("audio_window",),
    )

    assert alignment.aligned_span_refs == ("span:audio.broadcast.window.0042",)
    assert "span:audio.unmapped-wall-clock.window.0042" not in alignment.aligned_span_refs


def test_sidecars_reference_existing_spans_and_mirror_artifacts() -> None:
    fixtures = _fixtures()
    span_map = fixtures.spans_by_id()

    for sidecar in fixtures.sidecars:
        span = span_map[sidecar.span_ref]
        assert sidecar.join_policy == "temporal_span_overlap"
        assert sidecar.artifact_path == span.artifact_path
        assert sidecar.content_hash == span.content_hash


def test_missing_span_refs_fail_closed_for_claim_bearing_output_but_preserve_diagnostics() -> None:
    registry = _fixtures().registry()

    missing_claim = ClaimBearingMediaOutput(
        output_id="media_output:replay.card.missing-caption",
        output_kind="replay_card",
        claim_bearing=True,
        diagnostic_only=False,
        public_scope="public_safe",
        span_refs=("span:archive.hls.segment00042", "span:missing.caption.0042"),
        evidence_refs=("evidence:replay-card:fixture",),
    )
    missing_diagnostic = ClaimBearingMediaOutput(
        output_id="media_output:diagnostic.orphan-ir",
        output_kind="diagnostic_report",
        claim_bearing=False,
        diagnostic_only=True,
        public_scope="private",
        span_refs=("span:missing.ir-diagnostic.0042",),
    )

    claim_decision = registry.evaluate_claim_bearing_output(missing_claim)
    diagnostic_decision = registry.evaluate_claim_bearing_output(missing_diagnostic)

    assert claim_decision.allowed is False
    assert claim_decision.status == "blocked_missing_span_refs"
    assert claim_decision.missing_span_refs == ("span:missing.caption.0042",)
    assert claim_decision.diagnostic_preserved is False
    assert diagnostic_decision.allowed is False
    assert diagnostic_decision.status == "degraded_diagnostic"
    assert diagnostic_decision.missing_span_refs == ("span:missing.ir-diagnostic.0042",)
    assert diagnostic_decision.diagnostic_preserved is True


def test_claim_bearing_output_with_empty_span_refs_fails_closed() -> None:
    decision = (
        _fixtures()
        .registry()
        .evaluate_claim_bearing_output(
            ClaimBearingMediaOutput(
                output_id="media_output:replay.card.empty-span-refs",
                output_kind="replay_card",
                claim_bearing=True,
                diagnostic_only=False,
                public_scope="public_safe",
                span_refs=(),
                evidence_refs=("evidence:replay-card:fixture",),
            )
        )
    )

    assert decision.allowed is False
    assert decision.status == "blocked_no_span_refs"
    assert decision.reason_codes == ("empty_span_refs",)


def test_public_forbidden_and_private_scopes_fail_public_consumption_gate() -> None:
    registry = _fixtures().registry()
    forbidden = registry.evaluate_claim_bearing_output(
        ClaimBearingMediaOutput(
            output_id="media_output:replay.card.public-forbidden",
            output_kind="replay_card",
            claim_bearing=True,
            diagnostic_only=False,
            public_scope="public_forbidden",
            span_refs=("span:archive.hls.segment00042",),
            evidence_refs=("evidence:replay-card:fixture",),
        )
    )
    private = registry.evaluate_claim_bearing_output(
        ClaimBearingMediaOutput(
            output_id="media_output:replay.card.private-scope",
            output_kind="replay_card",
            claim_bearing=True,
            diagnostic_only=False,
            public_scope="private",
            span_refs=("span:archive.hls.segment00042",),
            evidence_refs=("evidence:replay-card:fixture",),
        )
    )

    assert forbidden.allowed is False
    assert forbidden.status == "blocked_public_scope"
    assert forbidden.reason_codes == ("public_scope_public_forbidden",)
    assert private.allowed is False
    assert private.status == "blocked_public_scope"
    assert private.reason_codes == ("public_scope_private",)


def test_private_or_rights_blocked_span_cannot_ground_public_claim() -> None:
    decision = (
        _fixtures()
        .registry()
        .evaluate_claim_bearing_output(
            ClaimBearingMediaOutput(
                output_id="media_output:replay.card.private-ir",
                output_kind="replay_card",
                claim_bearing=True,
                diagnostic_only=False,
                public_scope="public_safe",
                span_refs=("span:archive.hls.segment00042", "span:ir.presence.window.0042"),
                evidence_refs=("evidence:replay-card:fixture",),
            )
        )
    )

    assert decision.allowed is False
    assert decision.status == "blocked_private_or_rights"
    assert decision.blocked_span_refs == ("span:ir.presence.window.0042",)
    assert decision.reason_codes == ("private_or_rights_blocked_span_refs",)


def test_fixture_claim_gate_examples_match_model_decisions() -> None:
    fixtures = _fixtures()
    registry = fixtures.registry()

    for row in fixtures.claim_gate_fixtures:
        assert registry.evaluate_claim_bearing_output(row.output) == row.expected


def test_mtime_metadata_is_rejected_as_a_join_signal(tmp_path: Path) -> None:
    payload = copy.deepcopy(_payload())
    payload["spans"][0]["metadata"]["mtime_ns"] = 123
    path = tmp_path / "bad-temporal-span-registry-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TemporalSpanRegistryError, match="mtime"):
        load_temporal_span_registry_fixtures(path)


def test_nested_mtime_metadata_is_rejected_as_a_join_signal(tmp_path: Path) -> None:
    payload = copy.deepcopy(_payload())
    payload["spans"][0]["metadata"]["nested"] = {"capture_mtime_ns": 123}
    path = tmp_path / "bad-nested-temporal-span-registry-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TemporalSpanRegistryError, match="mtime"):
        load_temporal_span_registry_fixtures(path)

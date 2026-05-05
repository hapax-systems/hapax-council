"""Tests for the music request / provenance substrate adapter."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from shared.music.provenance import MusicManifestAsset
from shared.music_request_provenance_substrate_adapter import (
    DEFAULT_FRESHNESS_TTL_S,
    MUSIC_PROVENANCE_SUBSTRATE_ID,
    MUSIC_REQUEST_SUBSTRATE_ID,
    MUSIC_REQUEST_TOKEN,
    PRODUCER,
    TASK_ANCHOR,
    project_music_request_provenance_substrate,
)

NOW = 1_770_000_000.0
REPO_ROOT = Path(__file__).resolve().parents[2]
RVPE_SCHEMA = REPO_ROOT / "schemas" / "research-vehicle-public-event.schema.json"


def _request(
    *,
    request_id: str = "req-001",
    timestamp: float = NOW - 1.0,
    source: str = "operator.sidechat",
    interrupt_token: str = MUSIC_REQUEST_TOKEN,
    selection_source: str = "sidechat",
    token: str | None = "music:hapax-pool:a",
    provenance: str | None = "hapax-pool",
) -> dict[str, object]:
    track = {
        "path": "/pool/heliotrope.flac",
        "title": "Heliotrope",
        "artist": "Oudepode",
        "source": "local",
        "music_provenance": provenance,
        "music_license": "licensed-for-broadcast",
        "provenance_token": token,
    }
    return {
        "id": request_id,
        "timestamp": timestamp,
        "source": source,
        "type": "pattern_match",
        "interrupt_token": interrupt_token,
        "content": {
            "selection_source": selection_source,
            "track": track,
            "music_provenance": provenance,
            "provenance_token": token,
        },
    }


def _manifest(
    *,
    token: str | None = "music:hapax-pool:a",
    tier: str = "tier_1_platform_cleared",
    provenance: str = "hapax-pool",
    broadcast_safe: bool = True,
) -> MusicManifestAsset:
    return MusicManifestAsset(
        token=token,
        tier=tier,  # type: ignore[arg-type]
        source="local",
        music_provenance=provenance,  # type: ignore[arg-type]
        track_id="/pool/heliotrope.flac",
        license="licensed-for-broadcast",
        broadcast_safe=broadcast_safe,
    )


class TestConstants:
    def test_substrate_ids_and_anchor_are_pinned(self) -> None:
        assert MUSIC_REQUEST_SUBSTRATE_ID == "music_request_sidechat"
        assert MUSIC_PROVENANCE_SUBSTRATE_ID == "music_provenance"
        assert PRODUCER == "shared.music_request_provenance_substrate_adapter"
        assert TASK_ANCHOR == "music-request-provenance-substrate-adapter"
        assert DEFAULT_FRESHNESS_TTL_S == 30.0


class TestProjection:
    def test_private_request_becomes_structured_candidate_with_substrate_refs(self) -> None:
        candidates, rejections = project_music_request_provenance_substrate(
            [_request()],
            now=NOW,
            provenance_manifest=_manifest(),
            provenance_observed_at=NOW - 1.0,
        )

        assert rejections == []
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand.request_id == "req-001"
        assert cand.substrate_refs == ("music_request_sidechat", "music_provenance")
        assert cand.structured_impingement["interrupt_token"] == MUSIC_REQUEST_TOKEN
        assert cand.structured_impingement["substrate_refs"] == [
            "music_request_sidechat",
            "music_provenance",
        ]
        assert cand.event.source.substrate_id == MUSIC_REQUEST_SUBSTRATE_ID
        assert cand.event.source.producer == PRODUCER
        assert cand.event.source.task_anchor == TASK_ANCHOR
        assert cand.event.event_id.startswith("monetization_review:music_request:")
        assert cand.event.provenance.token == "music:hapax-pool:a"
        assert "substrate:music_provenance" in cand.event.provenance.evidence_refs

    def test_candidate_event_validates_against_rvpe_schema(self) -> None:
        candidates, _ = project_music_request_provenance_substrate(
            [_request()],
            now=NOW,
            provenance_manifest=_manifest(),
            provenance_observed_at=NOW - 1.0,
        )
        schema = json.loads(RVPE_SCHEMA.read_text(encoding="utf-8"))

        jsonschema.Draft202012Validator(schema).validate(
            candidates[0].event.model_dump(mode="json")
        )

    def test_missing_provenance_token_dry_runs_and_blocks_claims(self) -> None:
        candidates, rejections = project_music_request_provenance_substrate(
            [_request(token=None)],
            now=NOW,
            provenance_manifest=None,
            provenance_observed_at=None,
        )

        assert rejections == []
        cand = candidates[0]
        assert cand.public_risk == "missing_provenance_token"
        assert cand.public_claim_gate_ready is False
        assert cand.monetization_gate_ready is False
        assert cand.dry_run_reason == "missing_provenance_token"
        policy = cand.event.surface_policy
        assert policy.fallback_action == "dry_run"
        assert policy.claim_live is False
        assert policy.claim_monetizable is False
        assert policy.dry_run_reason == "missing_provenance_token"

    def test_positive_provenance_classifies_public_readiness_without_dispatch_claim(self) -> None:
        candidates, rejections = project_music_request_provenance_substrate(
            [_request()],
            now=NOW,
            provenance_manifest=_manifest(),
            provenance_observed_at=NOW,
            audio_safe=True,
            egress_public_claim=True,
        )

        assert rejections == []
        cand = candidates[0]
        assert cand.public_risk == "public_ready_private_control_only"
        assert cand.public_claim_gate_ready is True
        assert cand.monetization_gate_ready is True
        assert cand.dry_run_reason is None
        policy = cand.event.surface_policy
        assert policy.fallback_action == "private_only"
        assert policy.claim_live is False
        assert policy.claim_monetizable is False
        assert policy.requires_audio_safe is True
        assert policy.requires_egress_public_claim is True

    def test_audio_or_egress_absence_keeps_positive_provenance_in_dry_run(self) -> None:
        candidates, _ = project_music_request_provenance_substrate(
            [_request()],
            now=NOW,
            provenance_manifest=_manifest(),
            provenance_observed_at=NOW,
            audio_safe=False,
            egress_public_claim=True,
        )

        assert candidates[0].public_risk == "missing_audio_safety"
        assert candidates[0].event.surface_policy.fallback_action == "dry_run"

        candidates, _ = project_music_request_provenance_substrate(
            [_request()],
            now=NOW,
            provenance_manifest=_manifest(),
            provenance_observed_at=NOW,
            audio_safe=True,
            egress_public_claim=False,
        )
        assert candidates[0].public_risk == "missing_egress_public_claim"

    def test_unbroadcast_safe_or_risky_provenance_blocks_public_readiness(self) -> None:
        candidates, _ = project_music_request_provenance_substrate(
            [_request()],
            now=NOW,
            provenance_manifest=_manifest(tier="tier_4_risky", broadcast_safe=True),
            provenance_observed_at=NOW,
            audio_safe=True,
            egress_public_claim=True,
        )
        assert candidates[0].public_risk == "music_content_risk_blocks_public_claim"
        assert candidates[0].event.rights_class == "third_party_uncleared"

        candidates, _ = project_music_request_provenance_substrate(
            [_request(provenance="unknown")],
            now=NOW,
            provenance_manifest=_manifest(provenance="unknown", broadcast_safe=False),
            provenance_observed_at=NOW,
            audio_safe=True,
            egress_public_claim=True,
        )
        assert candidates[0].public_risk == "music_provenance_not_broadcast_safe"


class TestRejections:
    def test_stale_request_rejected_with_explicit_no_op_reason(self) -> None:
        candidates, rejections = project_music_request_provenance_substrate(
            [_request(timestamp=NOW - DEFAULT_FRESHNESS_TTL_S - 1.0)],
            now=NOW,
            provenance_manifest=_manifest(),
            provenance_observed_at=NOW,
        )

        assert candidates == []
        assert len(rejections) == 1
        assert rejections[0].reason == "stale_request"
        assert "ttl=" in rejections[0].detail

    def test_non_sidechat_route_rejected_before_output(self) -> None:
        candidates, rejections = project_music_request_provenance_substrate(
            [_request(source="public.chat")],
            now=NOW,
            provenance_manifest=_manifest(),
            provenance_observed_at=NOW,
        )

        assert candidates == []
        assert len(rejections) == 1
        assert rejections[0].reason == "missing_request_route"

    def test_duplicate_request_rejected(self) -> None:
        request = _request(request_id="dup")
        candidates, rejections = project_music_request_provenance_substrate(
            [request, request],
            now=NOW,
            provenance_manifest=_manifest(),
            provenance_observed_at=NOW,
        )

        assert len(candidates) == 1
        assert len(rejections) == 1
        assert rejections[0].reason == "duplicate"

    def test_manifest_mismatch_dry_runs_without_rejecting_private_evidence(self) -> None:
        candidates, rejections = project_music_request_provenance_substrate(
            [_request()],
            now=NOW,
            provenance_manifest=_manifest(token="music:hapax-pool:other"),
            provenance_observed_at=NOW,
        )

        assert rejections == []
        assert candidates[0].public_risk == "provenance_manifest_mismatch"
        assert candidates[0].event.surface_policy.dry_run_reason == "provenance_manifest_mismatch"

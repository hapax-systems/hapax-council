"""Tests for Phase 6 audio routing policy helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from shared.audio_routing_policy import (
    AudioRoutingPolicy,
    AudioRoutingPolicyError,
    RoutePolicy,
    audio_routing_manifest_json,
    load_audio_routing_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY = REPO_ROOT / "config" / "audio-routing.yaml"
MANIFEST = REPO_ROOT / "config" / "pipewire" / "generated" / "audio-routing-policy.manifest.json"
SCRIPT = REPO_ROOT / "scripts" / "generate-pipewire-audio-confs.py"


def _route(policy: AudioRoutingPolicy, source_id: str) -> RoutePolicy | None:
    return next((route for route in policy.routes if route.source_id == source_id), None)


def test_policy_loader_covers_private_blocked_and_broadcast_sources() -> None:
    policy = load_audio_routing_policy(POLICY)

    broadcast_tts = _route(policy, "broadcast-tts")
    music_bed = _route(policy, "music-bed")
    assistant = _route(policy, "assistant-private")
    notification = _route(policy, "notification-private")
    youtube = _route(policy, "youtube-bed")

    assert broadcast_tts is not None and broadcast_tts.broadcast_eligible is True
    assert music_bed is not None and music_bed.broadcast_eligible is True
    assert assistant is not None and assistant.broadcast_eligible is False
    assert notification is not None and notification.broadcast_eligible is False
    assert youtube is not None and youtube.broadcast_eligible is False
    assert _route(policy, "unmodeled-default-fallback") is None


def test_broadcast_eligible_routes_require_rights_provenance_and_no_default_fallback() -> None:
    policy = load_audio_routing_policy(POLICY)

    for source_id in policy.broadcast_eligible_source_ids():
        route = _route(policy, source_id)
        assert route is not None
        assert route.broadcast_eligibility_basis == "explicit_policy"
        assert route.rights_required is True
        assert route.provenance_required is True
        assert route.provenance_refs
        assert route.evidence_refs
        assert route.default_fallback_allowed is False


@pytest.mark.parametrize("source_id", ["assistant-private", "notification-private"])
def test_private_routes_are_never_broadcast_eligible(source_id: str) -> None:
    policy = load_audio_routing_policy(POLICY)
    route = _route(policy, source_id)

    assert route is not None
    assert route.broadcast_eligible is False
    assert route.public_claim_allowed is False
    assert "hapax-livestream-tap" not in route.target_chain
    assert "hapax-voice-fx-capture" not in route.target_chain
    assert "hapax-pc-loudnorm" not in route.target_chain


def test_magic_loudness_and_ducking_values_match_shared_constants() -> None:
    policy = load_audio_routing_policy(POLICY)

    assert policy.loudness_constants.pre_norm_target_lufs_i.constant_ref == (
        "PRE_NORM_TARGET_LUFS_I"
    )
    assert policy.loudness_constants.pre_norm_target_lufs_i.value == -18.0
    assert policy.loudness_constants.egress_target_lufs_i.constant_ref == ("EGRESS_TARGET_LUFS_I")
    assert policy.loudness_constants.egress_target_lufs_i.value == -14.0
    assert policy.ducking_constants.operator_voice.constant_ref == ("DUCK_DEPTH_OPERATOR_VOICE_DB")
    assert policy.ducking_constants.tts.constant_ref == "DUCK_DEPTH_TTS_DB"


def test_policy_validation_rejects_broadcast_route_without_artifact_owner() -> None:
    policy = load_audio_routing_policy(POLICY)
    payload = policy.model_dump(mode="json")
    route = next(route for route in payload["routes"] if route["source_id"] == "broadcast-tts")
    route["artifact_refs"].append("config/pipewire/unowned-broadcast.conf")

    with pytest.raises(AudioRoutingPolicyError, match="artifact refs lack ownership rows"):
        from shared.audio_routing_policy import AudioRoutingPolicy, assert_audio_routing_policy

        assert_audio_routing_policy(AudioRoutingPolicy.model_validate(payload))


def test_generated_manifest_matches_golden_output() -> None:
    policy = load_audio_routing_policy(POLICY)

    assert audio_routing_manifest_json(policy) == MANIFEST.read_text(encoding="utf-8")


def test_generator_check_mode_does_not_mutate_live_routing() -> None:
    result = subprocess.run(
        ["uv", "run", "python", str(SCRIPT), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_generated_manifest_keeps_unknown_and_default_fallback_blocked() -> None:
    text = MANIFEST.read_text(encoding="utf-8")

    assert '"unknown_source_broadcast_eligible": false' in text
    assert '"default_sink_fallback_broadcast_eligible": false' in text
    assert '"assistant-private"' in text
    assert '"notification-private"' in text

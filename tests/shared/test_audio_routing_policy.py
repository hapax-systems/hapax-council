"""Tests for Phase 6 audio routing policy helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from shared.audio_routing_policy import (
    DEFAULT_FORBIDDEN_LINKS_PATH,
    DEFAULT_LINK_MAP_PATH,
    DEFAULT_WIREPLUMBER_DENY_CONF_PATH,
    DEFAULT_WIREPLUMBER_DENY_SCRIPT_PATH,
    AudioRoutingPolicy,
    AudioRoutingPolicyError,
    RoutePolicy,
    audio_routing_manifest_json,
    generated_route_map_texts,
    generated_wireplumber_deny_policy_texts,
    load_audio_routing_policy,
    load_audio_topology_descriptor,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY = REPO_ROOT / "config" / "audio-routing.yaml"
MANIFEST = REPO_ROOT / "config" / "pipewire" / "generated" / "audio-routing-policy.manifest.json"
SCRIPT = REPO_ROOT / "scripts" / "generate-pipewire-audio-confs.py"
MK5_OUT = "alsa_output.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-output-0"
MK5_IN = "alsa_input.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-input-0"


def _route(policy: AudioRoutingPolicy, source_id: str) -> RoutePolicy | None:
    return next((route for route in policy.routes if route.source_id == source_id), None)


def test_policy_loader_covers_private_blocked_and_broadcast_sources() -> None:
    policy = load_audio_routing_policy(POLICY)

    broadcast_tts = _route(policy, "broadcast-tts")
    music_bed = _route(policy, "music-bed")
    assistant = _route(policy, "assistant-private")
    notification = _route(policy, "notification-private")
    youtube = _route(policy, "youtube-bed")
    s4 = _route(policy, "s4-content")
    m8 = _route(policy, "m8-instrument")

    assert broadcast_tts is not None and broadcast_tts.broadcast_eligible is True
    assert music_bed is not None and music_bed.broadcast_eligible is True
    assert assistant is not None and assistant.broadcast_eligible is False
    assert notification is not None and notification.broadcast_eligible is False
    assert youtube is not None and youtube.broadcast_eligible is False
    assert s4 is not None and s4.broadcast_eligible is False
    assert m8 is not None and m8.broadcast_eligible is False
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


def test_generated_route_maps_match_golden_output() -> None:
    policy = load_audio_routing_policy(POLICY)
    topology = load_audio_topology_descriptor()
    desired, forbidden = generated_route_map_texts(topology, policy)

    assert desired == DEFAULT_LINK_MAP_PATH.read_text(encoding="utf-8")
    assert forbidden == DEFAULT_FORBIDDEN_LINKS_PATH.read_text(encoding="utf-8")


def test_generated_route_maps_keep_private_default_dry_send_forbidden_not_desired() -> None:
    policy = load_audio_routing_policy(POLICY)
    topology = load_audio_topology_descriptor()
    desired, forbidden = generated_route_map_texts(topology, policy)

    assert f"hapax-private-playback:output_FL|{MK5_OUT}:playback_AUX10" in desired
    assert f"hapax-private-playback:output_FL|{MK5_OUT}:playback_AUX2" not in desired
    for source in (
        "hapax-pc-loudnorm-playback",
        "hapax-private-playback",
        "hapax-notification-private-playback",
    ):
        assert f"{source}:output_FL|{MK5_OUT}:playback_AUX2" in forbidden
        assert f"{source}:output_FR|{MK5_OUT}:playback_AUX3" in forbidden
    assert "input.loopback.sink.role.assistant-output" in forbidden
    assert "input.loopback.sink.role.notification-output" in forbidden


def test_generated_route_maps_only_allow_specified_mk5_and_sum_bus_links() -> None:
    policy = load_audio_routing_policy(POLICY)
    topology = load_audio_topology_descriptor()
    desired, forbidden = generated_route_map_texts(topology, policy)

    assert f"hapax-loudnorm-playback:output_FL|{MK5_OUT}:playback_AUX2" in desired
    assert f"hapax-loudnorm-playback:output_FR|{MK5_OUT}:playback_AUX3" in desired
    assert f"{MK5_IN}:capture_AUX2|hapax-voice-wet-capture:input_AUX2" in desired
    assert f"{MK5_IN}:capture_AUX3|hapax-voice-wet-capture:input_AUX3" in desired
    assert "hapax-voice-wet-playback:output_FL|hapax-livestream-tap:playback_FL" in desired
    assert f"{MK5_IN}:capture_AUX0|hapax-mic-rode-capture:input_AUX0" in desired
    assert "hapax-mic-rode-playback:output_FL|hapax-livestream-tap:playback_FL" in desired
    assert "hapax-music-loudnorm-playback:output_FL|hapax-livestream-tap:playback_FL" in desired
    assert "hapax-yt-loudnorm-playback:output_FL|hapax-livestream-tap:playback_FL" in desired
    assert f"hapax-private-playback:output_FL|{MK5_OUT}:playback_AUX10" in desired
    assert f"hapax-private-playback:output_FR|{MK5_OUT}:playback_AUX11" in desired
    assert "Akai_Professional_MPC" not in desired

    for disallowed in (
        "hapax-notification-private-playback",
        "hapax-m8-loudnorm-playback",
        "hapax-pc-loudnorm-playback",
    ):
        assert disallowed not in desired

    assert "hapax-yt-loudnorm-playback:output_FL|" not in forbidden
    assert "hapax-notification-private-playback:output_FL|" in forbidden
    assert f"hapax-notification-private-playback:output_FL|{MK5_OUT}:playback_AUX2" in forbidden
    assert f"hapax-pc-loudnorm-playback:output_FL|{MK5_OUT}:playback_AUX2" in forbidden


def test_generator_route_map_check_mode() -> None:
    result = subprocess.run(
        ["uv", "run", "python", str(SCRIPT), "--check-route-maps"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_generated_wireplumber_deny_policy_matches_golden_output() -> None:
    deny_conf, deny_script = generated_wireplumber_deny_policy_texts()

    assert deny_conf == DEFAULT_WIREPLUMBER_DENY_CONF_PATH.read_text(encoding="utf-8")
    assert deny_script == DEFAULT_WIREPLUMBER_DENY_SCRIPT_PATH.read_text(encoding="utf-8")
    assert "linking/hapax-deny-forbidden-target" in deny_script
    assert "linking/hapax-remove-forbidden-port-link" in deny_script
    assert "HAPAX_AUDIO_FORBIDDEN_LINKS" not in deny_script
    assert "io.open" not in deny_script
    assert "FAIL_CLOSED_FORBIDDEN_LINKS" in deny_script
    assert "optional_device_fallback_denied" in deny_script
    assert "hapax-polyend-instrument-capture" in deny_script
    assert "anonymous_loopback_to_multimedia_denied" in deny_script
    assert "input.loopback.sink.role.multimedia" in deny_script
    assert "output%.loopback%-%d+%-%d+" in deny_script
    assert "link:remove ()" in deny_script

    assert "FAIL_CLOSED_BOUNDARY_PAIRS" in deny_script
    assert "hapax-private-playback|hapax-livestream-tap" in deny_script
    assert f"hapax-private-playback|{MK5_OUT}" not in deny_script
    assert f"hapax-private-playback:output_FL|{MK5_OUT}:playback_AUX2" in deny_script
    assert "hapax-pc-loudnorm-playback|" in deny_script
    assert "hapax-private-playback|" in deny_script
    assert "hapax-yt-loudnorm-playback|" not in deny_script
    assert "hapax-notification-private-playback|" in deny_script
    assert f"hapax-notification-private-playback:output_FL|{MK5_OUT}:playback_AUX2" in deny_script
    assert f"hapax-pc-loudnorm-playback:output_FL|{MK5_OUT}:playback_AUX2" in deny_script
    assert (
        "input.loopback.sink.role.assistant-output|input.loopback.sink.role.multimedia"
        in deny_script
    )
    assert "degraded = false" in deny_script
    assert "WirePlumber's sandbox cannot lose the policy through missing file I/O" in deny_script
    assert "local pair_key = nil" in deny_script
    assert "policy.node_pairs [pair_key]" in deny_script
    assert "(node boundary " in deny_script


def test_wireplumber_boundary_node_pairs_do_not_overlap_desired_node_pairs() -> None:
    policy = load_audio_routing_policy(POLICY)
    topology = load_audio_topology_descriptor()
    desired, _ = generated_route_map_texts(topology, policy)
    _, deny_script = generated_wireplumber_deny_policy_texts(topology)

    def node_pairs(text: str) -> set[tuple[str, str]]:
        return {
            (source.split(":", maxsplit=1)[0], target.split(":", maxsplit=1)[0])
            for line in text.splitlines()
            if line and not line.startswith("#")
            for source, target in [line.split("|", maxsplit=1)]
        }

    desired_pairs = {f"{source}|{target}" for source, target in node_pairs(desired)}
    boundary_block = deny_script.split("local FAIL_CLOSED_BOUNDARY_PAIRS = {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]

    assert all(pair not in boundary_block for pair in desired_pairs)
    assert f"hapax-private-playback|{MK5_OUT}" not in boundary_block
    assert f"hapax-private-playback:output_FL|{MK5_OUT}:playback_AUX2" in deny_script


def test_generator_wireplumber_deny_policy_check_mode() -> None:
    result = subprocess.run(
        ["uv", "run", "python", str(SCRIPT), "--check-wireplumber-deny-policy"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_generator_installed_route_map_check_mode(tmp_path: Path) -> None:
    policy = load_audio_routing_policy(POLICY)
    topology = load_audio_topology_descriptor()
    desired, forbidden = generated_route_map_texts(topology, policy)
    installed_dir = tmp_path / "hapax"
    installed_dir.mkdir()
    (installed_dir / "audio-link-map.conf").write_text(desired, encoding="utf-8")
    (installed_dir / "audio-forbidden-links.conf").write_text(forbidden, encoding="utf-8")

    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(SCRIPT),
            "--check-installed-route-maps",
            "--installed-hapax-dir",
            str(installed_dir),
        ],
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

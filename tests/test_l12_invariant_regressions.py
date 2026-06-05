"""Regression: L-12 invariant pins for each of the 4 voice-silence root causes.

R-20 part 2 of the absence-class-bug-prevention-and-remediation epic.
Companion to the postmortem at
docs/research/2026-04-26-voice-silence-multi-incident-postmortem.md.

The L-12 invariant (`feedback_l12_equals_livestream_invariant`) has two
halves:
  forward: every audio source feeding the L-12 must reach broadcast
  inverse: any non-broadcast audio must leave the L-12 entirely

A full static-graph parser for the forward direction is non-trivial
(L-12 console routing + Evil Pet hardware loop + filter-chain
intermediates make general reachability hard to assert without false
positives on intentional patterns — e.g., music-duck → L-12 USB →
physical Evil Pet → CH 6 capture → broadcast IS correct but doesn't
appear as a static loopback). This module instead pins **the specific
configs whose absence/misconfiguration produced the four 2026-04-26
silence incidents**, so the same incidents cannot recur silently:

  - v1 (orphan voice_state probe): pinned via the COMPONENT_OWNERS
    test in tests/test_health_monitor_exploration.py (existing).
  - v3 (TTS chain not reaching broadcast): pinned here against the
    current mk5/S-4 baseline — TTS loudnorm MUST route to MOTU mk5 OUT
    AUX2/AUX3, the S-4 wet return MUST be captured from mk5 IN AUX2/AUX3,
    and the retired software direct-to-tap bridge MUST remain forbidden.
  - v4 (broadcast TTS via separate Broadcast media-role): pinned here —
    50-hapax-voice-duck.conf MUST register loopback.sink.role.broadcast
    in the requires list.
  - v5 (playback node passive): pinned here — hapax-l12-evilpet-capture.conf
    playback.props MUST declare node.passive = false.

  Plus the current M8 invariant: M8 remains disabled/fail-closed until a
  bounded route-activation task explicitly promotes it. It must not terminate
  at hapax-livestream-tap, L-12, MPC, or the mk5 dry-voice send while
  under-specified.
"""

from __future__ import annotations

from pathlib import Path

from shared.audio_topology import TopologyDescriptor

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPEWIRE_DIR = REPO_ROOT / "config" / "pipewire"
GENERATED_PIPEWIRE_DIR = PIPEWIRE_DIR / "generated" / "pipewire"
WIREPLUMBER_DIR = REPO_ROOT / "config" / "wireplumber"
CANONICAL_TOPOLOGY = REPO_ROOT / "config" / "audio-topology.yaml"
HAPAX_LINK_MAP = REPO_ROOT / "config" / "hapax" / "audio-link-map.conf"
HAPAX_FORBIDDEN_LINKS = REPO_ROOT / "config" / "hapax" / "audio-forbidden-links.conf"

L12_OUTPUT_NODE = (
    "alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40"
)
MPC_OUTPUT_NODE = "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-output-0"
# Interim MPC-only return (2026-05-29, L-12 removed): the MPC's own 24-ch USB
# return source. capture_AUX0/1 = public mix (broadcast); capture_AUX2/3 =
# private monitor (fenced from broadcast).
MPC_RETURN_NODE = "alsa_input.usb-Akai_Professional_MPC_LIVE_III_B-00.pro-input-0"
MK5_OUTPUT_NODE = "alsa_output.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-output-0"
MK5_INPUT_NODE = "alsa_input.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-input-0"
L12_CAPTURE_NODE = (
    "alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input"
)
PRIVATE_MONITOR_PLAYBACK_NODES = ("hapax-private-playback",)


def _read_conf(path: Path) -> str:
    return path.read_text()


def _strip_comments(text: str) -> str:
    """Strip # comments + blank lines (for code-line target.object scans)."""
    return "\n".join(
        line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
    )


def test_v3_tts_chain_routes_through_mk5_s4_wet_return() -> None:
    """v3: TTS must reach broadcast through the current mk5/S-4 analog insert,
    not through the retired software direct-to-tap bridge nor the orphaned
    MPC/L-12 wet returns."""
    descriptor = TopologyDescriptor.from_yaml(CANONICAL_TOPOLOGY)
    tts_loudnorm = descriptor.node_by_id("tts-loudnorm")
    wet_return = descriptor.node_by_id("voice-wet")
    assert tts_loudnorm.target_object == MK5_OUTPUT_NODE
    assert tts_loudnorm.params["playback_positions"] == "AUX2 AUX3"
    assert (
        tts_loudnorm.params["broadcast_forward_path"]
        == "mk5-output s4-analog-insert voice-wet hapax-livestream-tap"
    )
    assert wet_return.target_object == MK5_INPUT_NODE
    assert wet_return.params["capture_positions"] == "AUX2 AUX3"

    link_map = _strip_comments(_read_conf(HAPAX_LINK_MAP))
    assert (f"hapax-loudnorm-playback:output_FL|{MK5_OUTPUT_NODE}:playback_AUX2") in link_map
    assert (f"hapax-loudnorm-playback:output_FR|{MK5_OUTPUT_NODE}:playback_AUX3") in link_map
    assert f"{MK5_INPUT_NODE}:capture_AUX2|hapax-voice-wet-capture:input_AUX2" in link_map
    assert f"{MK5_INPUT_NODE}:capture_AUX3|hapax-voice-wet-capture:input_AUX3" in link_map
    assert "hapax-voice-wet-playback:output_FL|hapax-livestream-tap:playback_FL" in link_map
    assert "hapax-voice-wet-playback:output_FR|hapax-livestream-tap:playback_FR" in link_map

    # The orphaned MPC/L-12 wet return legs must NOT be in the desired map
    # (the reconciler must never enforce links to retired hardware).
    assert "hapax-mpc-usb-return-playback|" not in link_map
    assert f"{MPC_RETURN_NODE}:capture_AUX0|" not in link_map
    assert "hapax-l12-usb-return-playback|" not in link_map
    assert "hapax-l12-evilpet-playback:output_FL|hapax-livestream-tap" not in link_map
    assert f"{L12_CAPTURE_NODE}:capture_AUX8|" not in link_map

    assert "hapax-tts-broadcast-playback:output_FL|" not in link_map
    assert "hapax-tts-broadcast-playback:output_FR|" not in link_map

    tts_duck_conf = _strip_comments(_read_conf(PIPEWIRE_DIR / "hapax-tts-duck.conf"))
    assert "hapax-tts-broadcast-playback" not in tts_duck_conf
    assert 'target.object = "hapax-livestream-tap"' not in tts_duck_conf


def test_private_monitor_and_default_lanes_fenced_from_broadcast_and_voice_send() -> None:
    """Current mk5/S-4 fence: private/default lanes must not reach broadcast
    or the mk5 AUX2/3 dry-voice send into the S-4."""
    forbidden = _strip_comments(_read_conf(HAPAX_FORBIDDEN_LINKS))
    forbidden_pairs = (
        ("hapax-private-playback:output_FL", "hapax-livestream-tap:playback_FL"),
        ("hapax-private-playback:output_FR", "hapax-livestream-tap:playback_FR"),
        ("hapax-private-playback:output_FL", "hapax-broadcast-master-capture:input_FL"),
        ("hapax-private-playback:output_FR", "hapax-broadcast-master-capture:input_FR"),
        ("hapax-private-playback:output_FL", f"{MK5_OUTPUT_NODE}:playback_AUX2"),
        ("hapax-private-playback:output_FR", f"{MK5_OUTPUT_NODE}:playback_AUX3"),
        ("hapax-notification-private-playback:output_FL", "hapax-livestream-tap:playback_FL"),
        ("hapax-notification-private-playback:output_FR", "hapax-livestream-tap:playback_FR"),
        ("hapax-pc-loudnorm-playback:output_FL", f"{MK5_OUTPUT_NODE}:playback_AUX2"),
        ("hapax-pc-loudnorm-playback:output_FR", f"{MK5_OUTPUT_NODE}:playback_AUX3"),
    )
    for source, target in forbidden_pairs:
        assert f"{source}|{target}" in forbidden

    link_map = _strip_comments(_read_conf(HAPAX_LINK_MAP))
    assert "hapax-private-playback:output_FL|hapax-livestream-tap" not in link_map
    assert f"hapax-private-playback:output_FL|{MK5_OUTPUT_NODE}:playback_AUX2" not in link_map
    assert f"hapax-pc-loudnorm-playback:output_FL|{MK5_OUTPUT_NODE}:playback_AUX2" not in link_map


def test_youtube_send_sums_to_livestream_tap_and_remains_eligibility_gated() -> None:
    """Current mk5/S-4 topology: YouTube is a software-sum input to
    livestream-tap, while route policy still keeps the source eligibility
    explicitly gated pending real-content smoke evidence."""
    descriptor = TopologyDescriptor.from_yaml(CANONICAL_TOPOLOGY)
    yt = descriptor.node_by_id("yt-loudnorm")
    assert yt.params["playback_target"] == "hapax-livestream-tap"
    assert yt.params["broadcast_eligibility_gated"] == "blocked_until_smoke"

    link_map = _strip_comments(_read_conf(HAPAX_LINK_MAP))
    assert "hapax-yt-loudnorm-playback:output_FL|hapax-livestream-tap:playback_FL" in link_map
    assert "hapax-yt-loudnorm-playback:output_FR|hapax-livestream-tap:playback_FR" in link_map

    forbidden = _strip_comments(_read_conf(HAPAX_FORBIDDEN_LINKS))
    broadcast_targets = (
        "hapax-livestream-tap:playback_FL",
        "hapax-livestream-tap:playback_FR",
        "hapax-broadcast-master-capture:input_FL",
        "hapax-broadcast-master-capture:input_FR",
        "hapax-broadcast-normalized-capture:input_FL",
        "hapax-broadcast-normalized-capture:input_FR",
        "hapax-obs-broadcast-remap-capture:input_FL",
        "hapax-obs-broadcast-remap-capture:input_FR",
    )
    for target in broadcast_targets:
        assert f"hapax-yt-loudnorm-playback:output_FL|{target}" not in forbidden
        assert f"hapax-yt-loudnorm-playback:output_FR|{target}" not in forbidden


def test_generated_tts_artifacts_do_not_reintroduce_direct_broadcast_bridge() -> None:
    generated_tts_duck = _strip_comments(_read_conf(GENERATED_PIPEWIRE_DIR / "tts-duck.conf"))
    generated_tts_bridge = _strip_comments(
        _read_conf(GENERATED_PIPEWIRE_DIR / "tts-broadcast-playback.conf")
    )

    assert 'target.object = "hapax-livestream-tap"' not in generated_tts_duck
    assert 'target.object = "hapax-livestream-tap"' not in generated_tts_bridge
    assert "node.autoconnect = false" in generated_tts_duck
    assert "node.autoconnect = false" in generated_tts_bridge


def test_reconciler_map_owns_only_specified_mk5_private_tts_output() -> None:
    """Only private TTS playback is explicitly pinned to mk5 Phones AUX10/AUX11."""
    link_map = _strip_comments(_read_conf(HAPAX_LINK_MAP))
    assert f"hapax-private-playback:output_FL|{MK5_OUTPUT_NODE}:playback_AUX10" in link_map
    assert f"hapax-private-playback:output_FR|{MK5_OUTPUT_NODE}:playback_AUX11" in link_map

    forbidden = _strip_comments(_read_conf(HAPAX_FORBIDDEN_LINKS))
    assert f"hapax-private-playback:output_FL|{MK5_OUTPUT_NODE}:playback_AUX10" not in forbidden
    assert f"hapax-private-playback:output_FR|{MK5_OUTPUT_NODE}:playback_AUX11" not in forbidden
    assert f"hapax-private-playback:output_FL|{MK5_OUTPUT_NODE}:playback_AUX2" in forbidden
    assert f"hapax-private-playback:output_FR|{MK5_OUTPUT_NODE}:playback_AUX3" in forbidden
    assert (
        f"hapax-notification-private-playback:output_FL|{MK5_OUTPUT_NODE}:playback_AUX10"
        not in link_map
    )
    assert (
        f"hapax-notification-private-playback:output_FR|{MK5_OUTPUT_NODE}:playback_AUX11"
        not in link_map
    )

    assert "hapax-private:monitor_FL|hapax-private-monitor-capture:input_FL" in link_map
    assert "hapax-private:monitor_FR|hapax-private-monitor-capture:input_FR" in link_map
    assert "hapax-notification-private:monitor_FL|" not in link_map
    assert "hapax-notification-private:monitor_FR|" not in link_map
    assert (
        "input.loopback.sink.role.assistant-output:output_FL|hapax-private:playback_FL" in link_map
    )
    assert (
        "input.loopback.sink.role.assistant-output:output_FR|hapax-private:playback_FR" in link_map
    )
    assert (
        "input.loopback.sink.role.notification-output:output_FL|hapax-notification-private:playback_FL"
    ) in link_map
    assert (
        "input.loopback.sink.role.notification-output:output_FR|hapax-notification-private:playback_FR"
    ) in link_map


def test_v4_broadcast_role_loopback_required_in_voice_duck() -> None:
    """v4: 50-hapax-voice-duck.conf must register loopback.sink.role.broadcast
    so daimonion can route Broadcast-tagged TTS via a media-role separate
    from Assistant. Without this, the 2026-04-26 leak fix (Assistant →
    hapax-private) blocked broadcast TTS for ~6h."""
    conf = _read_conf(WIREPLUMBER_DIR / "50-hapax-voice-duck.conf")
    code = _strip_comments(conf)
    assert "loopback.sink.role.broadcast" in code, (
        "50-hapax-voice-duck.conf must declare loopback.sink.role.broadcast "
        "for daimonion's Broadcast-vs-Assistant per-destination split"
    )


def test_v5_evilpet_playback_node_is_active_not_passive() -> None:
    """v5: hapax-l12-evilpet-capture.conf playback.props must declare
    node.passive = false so the filter-chain actively pulls from L-12 USB
    rather than waiting for a downstream consumer claim. The 2026-04-26
    11:09 wireplumber double-restart triggered exactly this orphan state."""
    conf = _read_conf(PIPEWIRE_DIR / "hapax-l12-evilpet-capture.conf")
    # Find the playback.props block + assert node.passive = false within it.
    # Slice is generous (3 KB) to absorb long explanatory comments inside
    # the block — the conf is operator-readable + heavily commented.
    start = conf.index('node.name = "hapax-l12-evilpet-playback"')
    block = conf[start : start + 3000]
    assert "node.passive = false" in block, (
        "hapax-l12-evilpet-playback must declare node.passive = false; "
        "absence orphans the chain across wireplumber restarts (2026-04-26 v5)"
    )


def test_m8_loudnorm_has_no_live_target_while_under_specified() -> None:
    """M8 is under-specified and must not have live MPC/L-12/stream egress."""
    conf_path = PIPEWIRE_DIR / "hapax-m8-loudnorm.conf"
    if not conf_path.exists():
        return  # M8 conf may not be deployed yet on all branches
    code = _strip_comments(_read_conf(conf_path))
    assert "audio.position = [ AUX10 AUX11 ]" in code
    assert "node.autoconnect = false" in code
    assert f'target.object = "{MPC_OUTPUT_NODE}"' not in code
    assert f'target.object = "{L12_OUTPUT_NODE}"' not in code
    assert 'target.object = "hapax-livestream-tap"' not in code, (
        "M8 loudnorm must NOT terminate at hapax-livestream-tap while under-specified"
    )


def test_generated_m8_loudnorm_is_fail_closed_not_live() -> None:
    code = _strip_comments(_read_conf(GENERATED_PIPEWIRE_DIR / "m8-loudnorm.conf"))
    assert "audio.position = [ AUX10 AUX11 ]" in code
    assert "node.autoconnect = false" in code
    assert f'target.object = "{MPC_OUTPUT_NODE}"' not in code
    assert f'target.object = "{L12_OUTPUT_NODE}"' not in code
    assert 'target.object = "hapax-livestream-tap"' not in code


def test_m8_link_map_has_no_live_egress() -> None:
    """Under-specified M8 must not appear in desired live link map."""
    link_map = _strip_comments(_read_conf(HAPAX_LINK_MAP))
    assert "hapax-m8-loudnorm-playback:output_AUX10|" not in link_map
    assert "hapax-m8-loudnorm-playback:output_AUX11|" not in link_map
    assert "hapax-m8-loudnorm-playback:output_FL|" not in link_map
    assert "hapax-m8-loudnorm-playback:output_FR|" not in link_map


def test_m8_optional_capture_is_fail_closed_when_hardware_absent() -> None:
    """The optional M8 source must not fall back to L-12/default capture."""
    conf = _strip_comments(_read_conf(PIPEWIRE_DIR / "hapax-m8-loudnorm.conf"))
    start = conf.index('node.name = "hapax-m8-instrument-capture"')
    end = conf.index('node.name = "hapax-m8-instrument-playback"')
    capture_block = conf[start:end]
    assert "node.autoconnect = false" in capture_block
    assert "node.dont-fallback = true" in capture_block
    assert "node.dont-reconnect = true" in capture_block
    assert "node.dont-move = true" in capture_block
    assert "state.restore = false" in capture_block


def test_evilpet_capture_has_stream_dont_remix() -> None:
    """RCA #2441: hapax-l12-evilpet-capture.conf capture.props must declare
    stream.dont-remix = true to disable PipeWire's audioconvert channelmix
    matrix. Without this, the 14→4 surround downmix maps AUX2 content into
    the AUX5 slot (cross-corr 0.998 vs intended AUX5 at 0.386), causing
    the broadcast chain to carry reserve-channel content instead of Evil
    Pet return audio. Reference: docs/research/2026-05-03-l12-evilpet-
    stride-leakage-rca.md, cc-task audio-l12-evilpet-channelmix-stride-fix."""
    conf = _read_conf(PIPEWIRE_DIR / "hapax-l12-evilpet-capture.conf")
    # Find the capture.props block (must be before playback.props).
    start = conf.index('node.name = "hapax-l12-evilpet-capture"')
    end = conf.index('node.name = "hapax-l12-evilpet-playback"')
    capture_block = conf[start:end]
    assert "stream.dont-remix = true" in capture_block, (
        "hapax-l12-evilpet-capture capture.props must declare "
        "stream.dont-remix = true to prevent audioconvert channelmix "
        "AUX2→AUX5 stride leakage (RCA #2441)"
    )


def test_evilpet_capture_narrow_4ch_preserved() -> None:
    """Constitutional invariant: the L-12 evilpet capture must stay at
    4 channels [AUX1 AUX3 AUX4 AUX5]. Widening to 14 was tried in PR
    #2422 and broke the anti-feedback invariant. This test pins the narrow
    design as canonical."""
    conf = _read_conf(PIPEWIRE_DIR / "hapax-l12-evilpet-capture.conf")
    start = conf.index('node.name = "hapax-l12-evilpet-capture"')
    end = conf.index('node.name = "hapax-l12-evilpet-playback"')
    capture_block = conf[start:end]
    assert "audio.channels = 4" in capture_block, (
        "L-12 evilpet capture must stay at audio.channels = 4 (narrow design)"
    )
    assert "AUX1" in capture_block and "AUX5" in capture_block, (
        "L-12 evilpet capture must include AUX1 and AUX5 in audio.position"
    )

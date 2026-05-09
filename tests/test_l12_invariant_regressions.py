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
    current MPC-first baseline — TTS loudnorm MUST route to MPC USB
    AUX2/AUX3, the L-12 wet return MUST capture AUX8-AUX11, and the
    retired software direct-to-tap bridge MUST remain forbidden.
  - v4 (broadcast TTS via separate Broadcast media-role): pinned here —
    50-hapax-voice-duck.conf MUST register loopback.sink.role.broadcast
    in the requires list.
  - v5 (playback node passive): pinned here — hapax-l12-evilpet-capture.conf
    playback.props MUST declare node.passive = false.

  Plus the M8 forward-invariant (operator directive 2026-05-02 inverted
  the prior bypass design): hapax-m8-loudnorm.conf MUST write to the
  L-12 USB analog-surround output and MUST NOT terminate at
  hapax-livestream-tap. Nothing goes straight to stream — every wet
  audio source feeding broadcast passes through L-12 first.
"""

from __future__ import annotations

from pathlib import Path

from shared.audio_topology import TopologyDescriptor

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPEWIRE_DIR = REPO_ROOT / "config" / "pipewire"
WIREPLUMBER_DIR = REPO_ROOT / "config" / "wireplumber"
CANONICAL_TOPOLOGY = REPO_ROOT / "config" / "audio-topology.yaml"
HAPAX_LINK_MAP = REPO_ROOT / "config" / "hapax" / "audio-link-map.conf"
HAPAX_FORBIDDEN_LINKS = REPO_ROOT / "config" / "hapax" / "audio-forbidden-links.conf"

L12_OUTPUT_NODE = (
    "alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40"
)
MPC_OUTPUT_NODE = "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"
L12_CAPTURE_NODE = (
    "alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input"
)


def _read_conf(path: Path) -> str:
    return path.read_text()


def _strip_comments(text: str) -> str:
    """Strip # comments + blank lines (for code-line target.object scans)."""
    return "\n".join(
        line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
    )


def test_v3_tts_chain_routes_through_mpc_l12_wet_return() -> None:
    """v3: TTS must reach broadcast through the current MPC/L-12 wet
    return, not through the retired software direct-to-tap bridge."""
    descriptor = TopologyDescriptor.from_yaml(CANONICAL_TOPOLOGY)
    tts_loudnorm = descriptor.node_by_id("tts-loudnorm")
    wet_return = descriptor.node_by_id("l12-usb-return-capture")
    assert tts_loudnorm.target_object == MPC_OUTPUT_NODE
    assert tts_loudnorm.params["playback_positions"] == "AUX2 AUX3"
    assert (
        tts_loudnorm.params["broadcast_forward_path"]
        == "mpc-usb-output l12-usb-return-capture hapax-livestream-tap"
    )
    assert wet_return.target_object == L12_CAPTURE_NODE
    assert wet_return.params["capture_positions"] == "AUX8 AUX9 AUX10 AUX11"

    link_map = _strip_comments(_read_conf(HAPAX_LINK_MAP))
    for aux in ("AUX8", "AUX9", "AUX10", "AUX11"):
        assert (
            f"{L12_CAPTURE_NODE}:capture_{aux}|hapax-l12-usb-return-capture:input_{aux}" in link_map
        )
    assert "hapax-l12-usb-return-playback:output_FL|hapax-livestream-tap:playback_FL" in link_map
    assert "hapax-l12-usb-return-playback:output_FR|hapax-livestream-tap:playback_FR" in link_map

    forbidden = _strip_comments(_read_conf(HAPAX_FORBIDDEN_LINKS))
    assert "hapax-tts-broadcast-playback:output_FL|hapax-livestream-tap:playback_FL" in forbidden
    assert "hapax-tts-broadcast-playback:output_FR|hapax-livestream-tap:playback_FR" in forbidden


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


def test_m8_loudnorm_routes_through_l12_not_direct_to_stream() -> None:
    """M8 forward-invariant (operator directive 2026-05-02): hapax-m8-loudnorm.conf
    MUST write to the L-12 USB output and MUST NOT terminate at
    hapax-livestream-tap directly. The prior bypass design was inverted —
    nothing goes straight to stream, everything passes through L-12 first."""
    conf_path = PIPEWIRE_DIR / "hapax-m8-loudnorm.conf"
    if not conf_path.exists():
        return  # M8 conf may not be deployed yet on all branches
    code = _strip_comments(_read_conf(conf_path))
    assert L12_OUTPUT_NODE in code, (
        "M8 audio must route through L-12; hapax-m8-loudnorm.conf "
        "must target the L-12 USB analog-surround output (operator directive 2026-05-02)"
    )
    assert 'target.object = "hapax-livestream-tap"' not in code, (
        "M8 loudnorm must NOT terminate at hapax-livestream-tap directly; "
        "nothing goes straight to stream (operator directive 2026-05-02)"
    )


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

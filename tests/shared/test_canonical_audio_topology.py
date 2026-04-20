"""Regression pin: the canonical config/audio-topology.yaml must always parse.

If this test fails, someone edited config/audio-topology.yaml into an
invalid state — CI should catch it before the descriptor lands and
breaks the Phase 6 CI verify job. Run the actual YAML through the same
TopologyDescriptor validators the live CLI uses.
"""

from __future__ import annotations

from pathlib import Path

from shared.audio_topology import TopologyDescriptor

CANONICAL_YAML = Path(__file__).resolve().parents[2] / "config" / "audio-topology.yaml"


def test_canonical_descriptor_parses() -> None:
    """config/audio-topology.yaml must always satisfy the schema."""
    assert CANONICAL_YAML.exists(), (
        "config/audio-topology.yaml missing — canonical descriptor deleted?"
    )
    d = TopologyDescriptor.from_yaml(CANONICAL_YAML)
    assert d.schema_version == 1


def test_canonical_has_expected_node_ids() -> None:
    """The livestream-critical node IDs must all be present.

    If any of these disappear, the generator won't emit the confs
    daimonion + TTS + OBS depend on — a silent livestream regression.
    Pin them here so a rename has to be explicit in the test too.
    """
    d = TopologyDescriptor.from_yaml(CANONICAL_YAML)
    ids = {n.id for n in d.nodes}
    expected = {
        "l6-capture",
        "livestream-tap",
        "main-mix-tap",
        "voice-fx",
        "livestream-loopback",
        "private-loopback",
        "ryzen-analog-out",
    }
    assert expected.issubset(ids), f"missing expected node ids: {expected - ids}"


def test_canonical_main_mix_tap_has_plus12db() -> None:
    """The L6 Main Mix tap must carry +12 dB makeup gain to hit broadcast LUFS.

    History: the descriptor was tuned empirically against -18 dBFS
    broadcast target (see config/pipewire/hapax-l6-evilpet-capture.conf).
    If a future edit drops the gain back to unity, livestream audio
    reads quiet in OBS.
    """
    d = TopologyDescriptor.from_yaml(CANONICAL_YAML)
    mix_edges = [e for e in d.edges if e.source == "l6-capture" and e.target == "main-mix-tap"]
    assert len(mix_edges) == 2  # AUX10 + AUX11
    for e in mix_edges:
        assert e.makeup_gain_db == 12.0, (
            f"main-mix-tap gain regressed: {e.source_port} at {e.makeup_gain_db} dB"
        )


def test_canonical_voice_fx_targets_ryzen() -> None:
    """TTS must route to Ryzen analog-stereo (→ L6 ch 5 hardware)."""
    d = TopologyDescriptor.from_yaml(CANONICAL_YAML)
    voice_fx = d.node_by_id("voice-fx")
    assert voice_fx.target_object == "alsa_output.pci-0000_73_00.6.analog-stereo"


# ── Audio-normalization PR-2: livestream-duck node + edge rewrite ────


def test_canonical_has_livestream_duck_node() -> None:
    """The TTS-driven ducker node must be present with the spec'd shape.

    Plan §lines 46-51: kind=filter_chain, target_object matches the
    L6 USB playback target (Ryzen analog), params carry duck_signal_path
    + duck_key for PR-3's TtsDuckController.
    """
    d = TopologyDescriptor.from_yaml(CANONICAL_YAML)
    duck = d.node_by_id("livestream-duck")
    assert duck is not None, "livestream-duck node missing — PR-2 unshipped"
    assert duck.kind == "filter_chain"
    assert duck.pipewire_name == "hapax-livestream-duck"
    assert duck.target_object == "alsa_output.pci-0000_73_00.6.analog-stereo"


def test_livestream_duck_carries_duck_params() -> None:
    """params.duck_signal_path + params.duck_key — PR-3 reads these."""
    d = TopologyDescriptor.from_yaml(CANONICAL_YAML)
    duck = d.node_by_id("livestream-duck")
    assert duck.params["duck_signal_path"] == "/dev/shm/hapax-compositor/voice-state.json"
    assert duck.params["duck_key"] == "tts_active"
    # Strategy doc §4.2 row 1: -10 dB ≈ gain 0.316
    assert duck.params["duck_gain_db"] == -10.0
    assert duck.params["default_gain"] == 1.0


def test_livestream_loopback_targets_duck_not_ryzen() -> None:
    """The interpose: hapax-livestream now wires through the duck node."""
    d = TopologyDescriptor.from_yaml(CANONICAL_YAML)
    loopback = d.node_by_id("livestream-loopback")
    assert loopback.target_object == "hapax-livestream-duck", (
        "livestream-loopback must target the duck node, not Ryzen directly — "
        "PR-2 interpose unshipped"
    )


def test_canonical_livestream_duck_edge_chain() -> None:
    """Edges describe livestream-loopback → livestream-duck → ryzen-analog-out."""
    d = TopologyDescriptor.from_yaml(CANONICAL_YAML)
    edges = d.edges
    # Old direct edge MUST be gone
    direct = [
        e for e in edges if e.source == "livestream-loopback" and e.target == "ryzen-analog-out"
    ]
    assert direct == [], (
        "livestream-loopback → ryzen-analog-out edge must be removed (PR-2 interpose)"
    )
    # New chain MUST be present
    loop_to_duck = [
        e for e in edges if e.source == "livestream-loopback" and e.target == "livestream-duck"
    ]
    duck_to_ryzen = [
        e for e in edges if e.source == "livestream-duck" and e.target == "ryzen-analog-out"
    ]
    assert len(loop_to_duck) == 1, "missing livestream-loopback → livestream-duck edge"
    assert len(duck_to_ryzen) == 1, "missing livestream-duck → ryzen-analog-out edge"


def test_livestream_duck_conf_file_exists() -> None:
    """config/pipewire/hapax-livestream-duck.conf is the actual PipeWire
    config the operator deploys. Pin its existence + key shape."""
    conf_path = (
        Path(__file__).resolve().parents[2] / "config" / "pipewire" / "hapax-livestream-duck.conf"
    )
    assert conf_path.exists(), "PipeWire conf file for the duck node missing"
    text = conf_path.read_text()
    assert "hapax-livestream-duck" in text
    assert "filter-chain" in text
    assert "alsa_output.pci-0000_73_00.6.analog-stereo" in text

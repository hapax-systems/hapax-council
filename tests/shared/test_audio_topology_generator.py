"""Tests for shared.audio_topology_generator — descriptor → PipeWire conf."""

from __future__ import annotations

import pytest

from shared.audio_topology import (
    ChannelMap,
    Edge,
    Node,
    NodeKind,
    TopologyDescriptor,
)
from shared.audio_topology_generator import (
    _gain_db_to_linear,
    generate_confs,
    node_to_conf_fragment,
)


class TestGainConversion:
    @pytest.mark.parametrize(
        ("db", "expected"),
        [
            (0.0, 1.0),
            (6.0, 1.995),
            (12.0, 3.981),
            (-6.0, 0.5012),
            (20.0, 10.0),
        ],
    )
    def test_db_to_linear(self, db: float, expected: float) -> None:
        assert _gain_db_to_linear(db) == pytest.approx(expected, rel=1e-3)


class TestAlsaSourceFragment:
    def test_emits_factory_adapter(self) -> None:
        d = TopologyDescriptor(
            nodes=[
                Node(
                    id="l6-capture",
                    kind=NodeKind.ALSA_SOURCE,
                    pipewire_name="alsa_input.usb-ZOOM_L6-00.multitrack",
                    hw="hw:L6,0",
                    channels=ChannelMap(count=12, positions=[f"AUX{i}" for i in range(12)]),
                    description="L6 multitrack capture",
                ),
            ],
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        assert "factory.name = api.alsa.pcm.source" in text
        assert 'node.name    = "alsa_input.usb-ZOOM_L6-00.multitrack"' in text
        assert "audio.channels = 12" in text
        assert "AUX0 AUX1 AUX2 AUX3 AUX4 AUX5 AUX6 AUX7 AUX8 AUX9 AUX10 AUX11" in text
        assert 'api.alsa.path = "hw:L6,0"' in text


class TestAlsaSinkFragment:
    def test_emits_factory_sink(self) -> None:
        d = TopologyDescriptor(
            nodes=[
                Node(
                    id="ryzen-out",
                    kind=NodeKind.ALSA_SINK,
                    pipewire_name="alsa_output.pci-0000_73_00.6.analog-stereo",
                    hw="hw:0,0",
                ),
            ],
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        assert "factory.name = api.alsa.pcm.sink" in text
        assert "media.class  = Audio/Sink" in text
        assert 'api.alsa.path = "hw:0,0"' in text


class TestFilterChainFragment:
    def test_plain_filter_chain_no_gain_stage(self) -> None:
        d = TopologyDescriptor(
            nodes=[
                Node(
                    id="voice-fx",
                    kind=NodeKind.FILTER_CHAIN,
                    pipewire_name="hapax-voice-fx-capture",
                    target_object="alsa_output.pci-0000_73_00.6.analog-stereo",
                ),
            ],
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        assert "libpipewire-module-filter-chain" in text
        # No incoming edges → no gain stage.
        assert "filter.graph" not in text
        assert 'target.object = "alsa_output.pci-0000_73_00.6.analog-stereo"' in text

    def test_filter_chain_with_12db_makeup_emits_builtin_mixer(self) -> None:
        """Real-world: L6 Main Mix AUX10+11 → +12 dB makeup → livestream tap."""
        d = TopologyDescriptor(
            nodes=[
                Node(
                    id="l6-capture",
                    kind=NodeKind.ALSA_SOURCE,
                    pipewire_name="alsa_input.usb-ZOOM_L6-00.multitrack",
                    hw="hw:L6,0",
                    channels=ChannelMap(count=12, positions=[f"AUX{i}" for i in range(12)]),
                ),
                Node(
                    id="main-mix-tap",
                    kind=NodeKind.FILTER_CHAIN,
                    pipewire_name="hapax-l6-evilpet-capture",
                    target_object="hapax-livestream-tap",
                    channels=ChannelMap(count=2, positions=["FL", "FR"]),
                ),
            ],
            edges=[
                Edge(
                    source="l6-capture",
                    source_port="AUX10",
                    target="main-mix-tap",
                    target_port="FL",
                    makeup_gain_db=12.0,
                ),
                Edge(
                    source="l6-capture",
                    source_port="AUX11",
                    target="main-mix-tap",
                    target_port="FR",
                    makeup_gain_db=12.0,
                ),
            ],
        )
        text = node_to_conf_fragment(d.node_by_id("main-mix-tap"), d)
        assert "filter.graph" in text
        assert "builtin label = mixer" in text
        # +12 dB = ~3.981 linear
        assert "3.9811" in text
        # Two incoming edges → two mixer nodes.
        assert "gain_0" in text
        assert "gain_1" in text

    def test_filter_chain_negative_gain(self) -> None:
        d = TopologyDescriptor(
            nodes=[
                Node(
                    id="src",
                    kind=NodeKind.ALSA_SOURCE,
                    pipewire_name="in",
                    hw="hw:0,0",
                ),
                Node(
                    id="attenuator",
                    kind=NodeKind.FILTER_CHAIN,
                    pipewire_name="hapax-attenuator",
                ),
            ],
            edges=[Edge(source="src", target="attenuator", makeup_gain_db=-6.0)],
        )
        text = node_to_conf_fragment(d.node_by_id("attenuator"), d)
        # -6 dB ≈ 0.5012 linear.
        assert "0.5012" in text


class TestTapFragment:
    def test_null_sink_factory(self) -> None:
        d = TopologyDescriptor(
            nodes=[
                Node(
                    id="livestream-tap",
                    kind=NodeKind.TAP,
                    pipewire_name="hapax-livestream-tap",
                ),
            ],
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        assert "factory.name = support.null-audio-sink" in text
        assert 'node.name    = "hapax-livestream-tap"' in text


class TestLoopbackFragment:
    def test_loopback_targets_ryzen(self) -> None:
        d = TopologyDescriptor(
            nodes=[
                Node(
                    id="livestream-loopback",
                    kind=NodeKind.LOOPBACK,
                    pipewire_name="hapax-livestream",
                    target_object="alsa_output.pci-0000_73_00.6.analog-stereo",
                ),
            ],
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        assert "libpipewire-module-loopback" in text
        assert 'target.object = "alsa_output.pci-0000_73_00.6.analog-stereo"' in text

    def test_loopback_emits_fail_closed_private_monitor_params(self) -> None:
        d = TopologyDescriptor(
            nodes=[
                Node(
                    id="private-monitor-output",
                    kind=NodeKind.LOOPBACK,
                    pipewire_name="hapax-private-playback",
                    target_object="alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output",
                    params={
                        "capture_source": "hapax-private",
                        "stream.capture.sink": True,
                        "node.autoconnect": False,
                        "node.dont-fallback": True,
                        "node.dont-reconnect": True,
                        "node.dont-move": True,
                        "node.linger": True,
                        "state.restore": False,
                        "stream.dont-remix": True,
                    },
                ),
            ],
        )

        text = node_to_conf_fragment(d.nodes[0], d)

        assert 'target.object = "hapax-private"' in text
        assert "stream.capture.sink = true" in text
        assert (
            'target.object = "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"'
            in text
        )
        assert "node.autoconnect = false" in text
        assert "node.dont-fallback = true" in text
        assert "node.dont-reconnect = true" in text
        assert "node.dont-move = true" in text
        assert "node.linger = true" in text
        assert "state.restore = false" in text
        assert "stream.dont-remix = true" in text


class TestGenerateConfs:
    def test_one_file_per_node(self) -> None:
        d = TopologyDescriptor(
            nodes=[
                Node(
                    id="a",
                    kind=NodeKind.ALSA_SOURCE,
                    pipewire_name="in-a",
                    hw="hw:0,0",
                ),
                Node(id="b", kind=NodeKind.TAP, pipewire_name="tap-b"),
            ],
        )
        out = generate_confs(d)
        assert set(out.keys()) == {"pipewire/a.conf", "pipewire/b.conf"}
        for content in out.values():
            assert content.strip()  # non-empty


class TestParamsPassthrough:
    def test_unknown_params_preserved(self) -> None:
        d = TopologyDescriptor(
            nodes=[
                Node(
                    id="l6",
                    kind=NodeKind.ALSA_SOURCE,
                    pipewire_name="l6",
                    hw="hw:L6,0",
                    params={"api.alsa.use-acp": False, "api.alsa.disable-batch": True},
                ),
            ],
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        assert "api.alsa.use-acp = false" in text
        assert "api.alsa.disable-batch = true" in text

    def test_reserved_params_not_duplicated(self) -> None:
        """Keys handled by the template (audio.channels, etc.) are suppressed in params output."""
        d = TopologyDescriptor(
            nodes=[
                Node(
                    id="l6",
                    kind=NodeKind.ALSA_SOURCE,
                    pipewire_name="l6",
                    hw="hw:L6,0",
                    channels=ChannelMap(count=2, positions=["FL", "FR"]),
                    # Rogue operator-authored duplicate — should be ignored.
                    params={"audio.channels": 4, "api.alsa.custom-flag": True},
                ),
            ],
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        # Channel map source wins.
        assert text.count("audio.channels = 2") == 1
        # audio.channels = 4 must NOT appear.
        assert "audio.channels = 4" not in text
        # Custom flag still emits.
        assert "api.alsa.custom-flag = true" in text

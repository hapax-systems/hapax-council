"""LADSPA chain templates for the audio topology generator (audit F#8).

Three templates extend the legacy generic ``filter_chain`` emit so the
descriptor can fully specify the load-bearing chain shapes:

- ``loudnorm`` — single ``fast_lookahead_limiter_1913`` LADSPA stage.
- ``duck``     — paired-mono ``builtin mixer`` ducker.
- ``usb-bias`` — ``fast_lookahead_limiter_1913`` configured as a
  USB-IN line-driver, clamped to the LADSPA ``[-20, +20]`` range.

Each template is asserted byte-stable (deterministic codegen output)
and structurally correct (LADSPA plugin name, mixer node count,
target.object plumbing, optional FL/FR → RL/RR remap).
"""

from __future__ import annotations

import pytest

from shared.audio_topology import (
    ChannelMap,
    Node,
    NodeKind,
    TopologyDescriptor,
)
from shared.audio_topology_generator import (
    ConfigError,
    node_to_conf_fragment,
)


def _wrap(node: Node) -> TopologyDescriptor:
    """Wrap a single chain node in a descriptor (no edges needed)."""
    return TopologyDescriptor(nodes=[node])


class TestLoudnormChain:
    def test_emits_fast_lookahead_limiter(self) -> None:
        d = _wrap(
            Node(
                id="music-loudnorm",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="hapax-music-loudnorm",
                target_object="hapax-music-duck",
                description="Music loudnorm (test)",
                chain_kind="loudnorm",
                limit_db=-18.0,
                release_s=0.20,
            )
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        assert "libpipewire-module-filter-chain" in text
        assert 'plugin = "fast_lookahead_limiter_1913"' in text
        assert 'label = "fastLookaheadLimiter"' in text
        assert '"Input gain (dB)" = 0.0' in text
        assert '"Limit (dB)"      = -18.0' in text
        assert '"Release time (s)" = 0.2' in text
        # Sink shape — the descriptor's filter-chain capture side is a sink.
        assert 'media.class = "Audio/Sink"' in text
        assert 'target.object = "hapax-music-duck"' in text

    def test_default_release_when_omitted(self) -> None:
        d = _wrap(
            Node(
                id="x",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="x",
                chain_kind="loudnorm",
                limit_db=-14.0,
            )
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        # Default release matches the live music-loudnorm/voice-fx-loudnorm value.
        assert '"Release time (s)" = 0.2' in text

    def test_byte_stable_emit(self) -> None:
        node = Node(
            id="byte-stable",
            kind=NodeKind.FILTER_CHAIN,
            pipewire_name="hapax-byte-stable",
            target_object="hapax-downstream",
            chain_kind="loudnorm",
            limit_db=-18.0,
            release_s=0.20,
        )
        d = _wrap(node)
        first = node_to_conf_fragment(d.nodes[0], d)
        second = node_to_conf_fragment(d.nodes[0], d)
        assert first == second  # codegen is deterministic

    def test_loudnorm_requires_limit_db(self) -> None:
        d = _wrap(
            Node(
                id="incomplete",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="x",
                chain_kind="loudnorm",
                # limit_db omitted on purpose
            )
        )
        with pytest.raises(ConfigError, match="limit_db"):
            node_to_conf_fragment(d.nodes[0], d)


class TestDuckChain:
    def test_emits_paired_mono_mixers(self) -> None:
        d = _wrap(
            Node(
                id="music-duck",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="hapax-music-duck",
                target_object="alsa_output.usb-ZOOM_Corporation_L-12-00.analog-surround-40",
                description="Music duck (test)",
                chain_kind="duck",
            )
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        # Two mono builtin mixers with default Gain 1 = 1.0.
        assert text.count("builtin name = duck_l label = mixer") == 1
        assert text.count("builtin name = duck_r label = mixer") == 1
        assert text.count('"Gain 1" = 1.0') == 2
        # Stereo wiring through In 1 → Out per channel.
        assert 'inputs  = [ "duck_l:In 1" "duck_r:In 1" ]' in text
        assert 'outputs = [ "duck_l:Out"  "duck_r:Out"  ]' in text
        # Sink shape, target plumbing.
        assert 'media.class = "Audio/Sink"' in text
        assert (
            'target.object = "alsa_output.usb-ZOOM_Corporation_L-12-00.analog-surround-40"' in text
        )

    def test_byte_stable_emit(self) -> None:
        node = Node(
            id="duck",
            kind=NodeKind.FILTER_CHAIN,
            pipewire_name="hapax-duck",
            chain_kind="duck",
        )
        d = _wrap(node)
        first = node_to_conf_fragment(d.nodes[0], d)
        second = node_to_conf_fragment(d.nodes[0], d)
        assert first == second


class TestUsbBiasChain:
    def test_emits_fast_lookahead_limiter_with_input_gain(self) -> None:
        d = _wrap(
            Node(
                id="music-line-driver",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="hapax-music-usb-line-driver",
                target_object="alsa_output.usb-ZOOM_Corporation_L-12-00.analog-surround-40",
                description="Music USB IN line-driver (test)",
                chain_kind="usb-bias",
                bias_db=12.0,
                limit_db=-1.0,
                release_s=0.05,
                remap_to_rear=True,
            )
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        assert 'plugin = "fast_lookahead_limiter_1913"' in text
        assert 'label = "fastLookaheadLimiter"' in text
        assert '"Input gain (dB)" = 12.0' in text
        assert '"Limit (dB)"      = -1.0' in text
        assert '"Release time (s)" = 0.05' in text
        # Sink shape — the descriptor's filter-chain capture side is a sink.
        assert 'media.class = "Audio/Sink"' in text
        assert (
            'target.object = "alsa_output.usb-ZOOM_Corporation_L-12-00.analog-surround-40"' in text
        )
        # remap_to_rear=True → playback-side audio.position rewritten.
        assert "audio.position = [ RL RR ]" in text

    def test_no_remap_keeps_descriptor_positions(self) -> None:
        d = _wrap(
            Node(
                id="bias-fl-fr",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="hapax-bias-fl-fr",
                chain_kind="usb-bias",
                bias_db=6.0,
            )
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        # Default ChannelMap is FL/FR — playback side keeps it.
        assert "audio.position = [ FL FR ]" in text
        assert "audio.position = [ RL RR ]" not in text

    def test_byte_stable_emit(self) -> None:
        node = Node(
            id="bias-stable",
            kind=NodeKind.FILTER_CHAIN,
            pipewire_name="hapax-bias-stable",
            chain_kind="usb-bias",
            bias_db=9.0,
            limit_db=-1.0,
            release_s=0.05,
        )
        d = _wrap(node)
        first = node_to_conf_fragment(d.nodes[0], d)
        second = node_to_conf_fragment(d.nodes[0], d)
        assert first == second

    def test_usb_bias_requires_bias_db(self) -> None:
        d = _wrap(
            Node(
                id="incomplete",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="x",
                chain_kind="usb-bias",
            )
        )
        with pytest.raises(ConfigError, match="bias_db"):
            node_to_conf_fragment(d.nodes[0], d)

    @pytest.mark.parametrize("bias_db", [-20.0, -10.0, 0.0, 9.0, 12.0, 19.99, 20.0])
    def test_usb_bias_in_range_accepted(self, bias_db: float) -> None:
        d = _wrap(
            Node(
                id="x",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="x",
                chain_kind="usb-bias",
                bias_db=bias_db,
            )
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        assert f'"Input gain (dB)" = {bias_db}' in text

    @pytest.mark.parametrize(
        "bias_db",
        [
            27.0,  # the historical hapax-music-usb-line-driver value — out of LADSPA spec.
            20.01,  # just over the upper bound
            -20.01,  # just under the lower bound
            -100.0,  # absurd
            100.0,  # absurd
        ],
    )
    def test_usb_bias_out_of_range_raises_config_error(self, bias_db: float) -> None:
        d = _wrap(
            Node(
                id="overshoot",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="x",
                chain_kind="usb-bias",
                bias_db=bias_db,
            )
        )
        with pytest.raises(ConfigError, match=r"\[-20\.0, 20\.0\] dB"):
            node_to_conf_fragment(d.nodes[0], d)


class TestChainKindDispatch:
    """The chain_kind dispatcher must coexist with legacy filter-chain emit."""

    def test_legacy_filter_chain_with_no_chain_kind(self) -> None:
        # When chain_kind is omitted, the legacy generic filter-chain
        # template emits — same shape as before F#8.
        d = _wrap(
            Node(
                id="legacy",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="hapax-legacy",
                target_object="alsa_output.something",
                # chain_kind is None
            )
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        assert "libpipewire-module-filter-chain" in text
        # No LADSPA plugin, no duck mixer pair, no chain template noise.
        assert 'plugin = "fast_lookahead_limiter_1913"' not in text
        assert "builtin name = duck_l" not in text
        # Legacy shape preserves target.object passthrough.
        assert 'target.object = "alsa_output.something"' in text

    def test_loudnorm_and_duck_distinct_outputs(self) -> None:
        loud = _wrap(
            Node(
                id="loud",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="loud",
                chain_kind="loudnorm",
                limit_db=-14.0,
            )
        )
        duck = _wrap(
            Node(
                id="duck",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="duck",
                chain_kind="duck",
            )
        )
        loud_text = node_to_conf_fragment(loud.nodes[0], loud)
        duck_text = node_to_conf_fragment(duck.nodes[0], duck)
        assert loud_text != duck_text
        assert "fast_lookahead_limiter_1913" in loud_text
        assert "fast_lookahead_limiter_1913" not in duck_text
        assert "duck_l" in duck_text
        assert "duck_l" not in loud_text


class TestChannelMap:
    """ChannelMap should pass through the LADSPA chain templates correctly."""

    def test_loudnorm_5_1_channels(self) -> None:
        d = _wrap(
            Node(
                id="surround",
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name="surround",
                chain_kind="loudnorm",
                limit_db=-14.0,
                channels=ChannelMap(count=6, positions=["FL", "FR", "FC", "LFE", "RL", "RR"]),
            )
        )
        text = node_to_conf_fragment(d.nodes[0], d)
        assert "audio.channels = 6" in text
        assert "audio.position = [ FL FR FC LFE RL RR ]" in text

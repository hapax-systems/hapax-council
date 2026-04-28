"""Tests for shared.audio_topology_inspector — pw-dump → TopologyDescriptor."""

from __future__ import annotations

import json
from typing import Any

from shared.audio_topology import NodeKind
from shared.audio_topology_inspector import (
    _classify_node_kind,
    _id_from_name,
    check_tts_broadcast_path,
    pw_dump_to_descriptor,
)


def _pw_node(
    *,
    id: int,
    node_name: str,
    media_class: str,
    factory: str = "",
    hw: str | None = None,
    target: str | None = None,
    channels: int = 2,
    positions: list[str] | None = None,
    description: str = "",
) -> dict[str, Any]:
    """Build a minimal pw-dump Node object for tests."""
    props: dict[str, Any] = {
        "node.name": node_name,
        "media.class": media_class,
        "factory.name": factory,
        "audio.channels": channels,
    }
    if hw:
        props["api.alsa.path"] = hw
    if target:
        props["target.object"] = target
    if positions:
        props["audio.position"] = positions
    if description:
        props["node.description"] = description
    return {"id": id, "type": "PipeWire:Interface:Node", "info": {"props": props}}


def _pw_link(*, id: int, out_node: int, in_node: int) -> dict[str, Any]:
    return {
        "id": id,
        "type": "PipeWire:Interface:Link",
        "info": {
            "output-node-id": out_node,
            "output-port-id": 0,
            "input-node-id": in_node,
            "input-port-id": 0,
        },
    }


class TestClassifyNodeKind:
    def test_alsa_source(self) -> None:
        assert (
            _classify_node_kind(
                {
                    "media.class": "Audio/Source",
                    "factory.name": "api.alsa.pcm.source",
                    "api.alsa.path": "hw:L6,0",
                }
            )
            == NodeKind.ALSA_SOURCE
        )

    def test_alsa_sink(self) -> None:
        assert (
            _classify_node_kind(
                {
                    "media.class": "Audio/Sink",
                    "factory.name": "api.alsa.pcm.sink",
                    "api.alsa.path": "hw:0,0",
                }
            )
            == NodeKind.ALSA_SINK
        )

    def test_null_sink_tap(self) -> None:
        assert (
            _classify_node_kind(
                {
                    "media.class": "Audio/Sink",
                    "factory.name": "support.null-audio-sink",
                }
            )
            == NodeKind.TAP
        )

    def test_filter_chain(self) -> None:
        assert (
            _classify_node_kind(
                {
                    "media.class": "Audio/Sink",
                    "factory.name": "filter-chain",
                }
            )
            == NodeKind.FILTER_CHAIN
        )

    def test_loopback(self) -> None:
        assert (
            _classify_node_kind(
                {
                    "media.class": "Audio/Sink",
                    "factory.name": "loopback",
                }
            )
            == NodeKind.LOOPBACK
        )

    def test_unknown_stream_returns_none(self) -> None:
        """Application streams don't match any graph node kind we model."""
        assert (
            _classify_node_kind(
                {"media.class": "Stream/Output/Audio", "factory.name": "client-node"}
            )
            is None
        )

    def test_broadcast_playback_stream_is_modeled(self) -> None:
        """Broadcast loopback playback proves the bridge reaches its target."""
        assert (
            _classify_node_kind(
                {
                    "node.name": "hapax-tts-broadcast-playback",
                    "media.class": "Stream/Output/Audio",
                    "target.object": "hapax-livestream-tap",
                }
            )
            == NodeKind.LOOPBACK
        )

    def test_non_broadcast_playback_stream_is_skipped(self) -> None:
        assert (
            _classify_node_kind(
                {
                    "node.name": "hapax-tts-duck-playback",
                    "media.class": "Stream/Output/Audio",
                    "target.object": "hapax-livestream-tap",
                }
            )
            is None
        )


class TestIdFromName:
    def test_hapax_names_roundtrip_as_is(self) -> None:
        assert _id_from_name("hapax-livestream-tap") == "hapax-livestream-tap"

    def test_alsa_long_name_compresses(self) -> None:
        """ALSA multi-segment names trim to the last two dash-separated segments."""
        # Result is still a valid kebab-ish id — tolerates the dot
        # from ``00.multitrack`` since Node.id validator only rejects
        # whitespace + uppercase.
        assert (
            _id_from_name("alsa_input.usb-ZOOM_Corporation_L6-00.multitrack") == "l6-00.multitrack"
        )

    def test_lowercase_and_dash_normalised(self) -> None:
        assert _id_from_name("HapaxVoice_FX") == "hapaxvoice-fx"


class TestPwDumpToDescriptor:
    def test_empty_dump(self) -> None:
        d = pw_dump_to_descriptor([])
        assert d.nodes == []
        assert d.edges == []

    def test_single_alsa_source(self) -> None:
        dump = [
            _pw_node(
                id=100,
                node_name="alsa_input.usb-ZOOM-L6-00",
                media_class="Audio/Source",
                factory="api.alsa.pcm.source",
                hw="hw:L6,0",
                channels=12,
            )
        ]
        d = pw_dump_to_descriptor(dump)
        assert len(d.nodes) == 1
        assert d.nodes[0].kind == NodeKind.ALSA_SOURCE
        assert d.nodes[0].hw == "hw:L6,0"
        assert d.nodes[0].channels.count == 12

    def test_pipewire_position_strings_strip_commas(self) -> None:
        dump = [
            _pw_node(
                id=100,
                node_name="alsa_input.usb-ZOOM-L12-00",
                media_class="Audio/Source",
                factory="api.alsa.pcm.source",
                hw="hw:L12,0",
                channels=4,
            )
        ]
        dump[0]["info"]["props"]["audio.position"] = "[ FL, FR, RL, RR ]"

        d = pw_dump_to_descriptor(dump)

        assert d.nodes[0].channels.positions == ["FL", "FR", "RL", "RR"]

    def test_ignores_application_streams(self) -> None:
        """Stream/Output/Audio nodes (apps) don't land in the descriptor."""
        dump = [
            {
                "id": 200,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "node.name": "OBS",
                        "media.class": "Stream/Output/Audio",
                        "factory.name": "client-node",
                    }
                },
            }
        ]
        d = pw_dump_to_descriptor(dump)
        assert d.nodes == []

    def test_links_become_edges(self) -> None:
        dump = [
            _pw_node(
                id=100,
                node_name="alsa_input.usb-ZOOM-L6-00",
                media_class="Audio/Source",
                factory="api.alsa.pcm.source",
                hw="hw:L6,0",
            ),
            _pw_node(
                id=200,
                node_name="hapax-livestream-tap",
                media_class="Audio/Sink",
                factory="support.null-audio-sink",
            ),
            _pw_link(id=300, out_node=100, in_node=200),
        ]
        d = pw_dump_to_descriptor(dump)
        assert len(d.nodes) == 2
        assert len(d.edges) == 1
        src_id = d.nodes[0].id
        tgt_id = d.nodes[1].id
        assert d.edges[0].source == src_id
        assert d.edges[0].target == tgt_id

    def test_link_to_unknown_node_is_skipped(self) -> None:
        """Links whose endpoints aren't in the descriptor drop silently."""
        dump = [
            _pw_node(
                id=100,
                node_name="hapax-livestream-tap",
                media_class="Audio/Sink",
                factory="support.null-audio-sink",
            ),
            _pw_link(id=300, out_node=999, in_node=100),
        ]
        d = pw_dump_to_descriptor(dump)
        assert len(d.edges) == 0

    def test_json_string_input(self) -> None:
        """pw_dump_to_descriptor accepts raw JSON string from run_pw_dump."""
        dump = [
            _pw_node(
                id=100,
                node_name="hapax-tap",
                media_class="Audio/Sink",
                factory="support.null-audio-sink",
            )
        ]
        d = pw_dump_to_descriptor(json.dumps(dump))
        assert len(d.nodes) == 1

    def test_dedup_by_descriptor_id(self) -> None:
        """Two pw-level nodes normalising to the same id: first wins."""
        dump = [
            _pw_node(
                id=100,
                node_name="hapax-livestream-tap",
                media_class="Audio/Sink",
                factory="support.null-audio-sink",
            ),
            _pw_node(
                id=101,
                node_name="hapax-livestream-tap",
                media_class="Audio/Sink",
                factory="support.null-audio-sink",
            ),
        ]
        d = pw_dump_to_descriptor(dump)
        assert len(d.nodes) == 1

    def test_realworld_graph(self) -> None:
        """Full-ish graph matching today's workstation topology (abridged)."""
        dump = [
            _pw_node(
                id=100,
                node_name="alsa_input.usb-L6-00.multitrack",
                media_class="Audio/Source",
                factory="api.alsa.pcm.source",
                hw="hw:L6,0",
                channels=12,
                positions=[f"AUX{i}" for i in range(12)],
            ),
            _pw_node(
                id=101,
                node_name="hapax-livestream-tap",
                media_class="Audio/Sink",
                factory="support.null-audio-sink",
                channels=2,
                positions=["FL", "FR"],
            ),
            _pw_node(
                id=102,
                node_name="hapax-l6-evilpet-capture",
                media_class="Audio/Sink",
                factory="filter-chain",
                target="hapax-livestream-tap",
            ),
            _pw_node(
                id=103,
                node_name="alsa_output.pci-0000_73_00.6.analog-stereo",
                media_class="Audio/Sink",
                factory="api.alsa.pcm.sink",
                hw="hw:0,0",
            ),
            _pw_link(id=200, out_node=100, in_node=102),
            _pw_link(id=201, out_node=102, in_node=101),
        ]
        d = pw_dump_to_descriptor(dump)
        assert len(d.nodes) == 4
        kinds = {n.kind for n in d.nodes}
        assert NodeKind.ALSA_SOURCE in kinds
        assert NodeKind.ALSA_SINK in kinds
        assert NodeKind.TAP in kinds
        assert NodeKind.FILTER_CHAIN in kinds
        assert len(d.edges) == 2


class TestTtsBroadcastPathCheck:
    def test_ok_when_tts_duck_bridges_to_livestream_tap(self) -> None:
        dump = [
            _pw_node(
                id=100,
                node_name="hapax-tts-duck",
                media_class="Audio/Sink",
                factory="filter-chain",
            ),
            _pw_node(
                id=101,
                node_name="hapax-tts-broadcast-playback",
                media_class="Audio/Sink",
                factory="loopback",
            ),
            _pw_node(
                id=102,
                node_name="hapax-livestream-tap",
                media_class="Audio/Sink",
                factory="support.null-audio-sink",
            ),
            _pw_link(id=200, out_node=100, in_node=101),
            _pw_link(id=201, out_node=101, in_node=102),
        ]
        result = check_tts_broadcast_path(pw_dump_to_descriptor(dump))
        assert result.ok is True
        assert result.missing_nodes == ()
        assert result.missing_edges == ()

    def test_reports_missing_bridge_node(self) -> None:
        dump = [
            _pw_node(
                id=100,
                node_name="hapax-tts-duck",
                media_class="Audio/Sink",
                factory="filter-chain",
            ),
            _pw_node(
                id=102,
                node_name="hapax-livestream-tap",
                media_class="Audio/Sink",
                factory="support.null-audio-sink",
            ),
        ]
        result = check_tts_broadcast_path(pw_dump_to_descriptor(dump))
        assert result.ok is False
        assert "hapax-tts-broadcast-*" in result.missing_nodes

    def test_reports_missing_forward_edge(self) -> None:
        dump = [
            _pw_node(
                id=100,
                node_name="hapax-tts-duck",
                media_class="Audio/Sink",
                factory="filter-chain",
            ),
            _pw_node(
                id=101,
                node_name="hapax-tts-broadcast-playback",
                media_class="Audio/Sink",
                factory="loopback",
            ),
            _pw_node(
                id=102,
                node_name="hapax-livestream-tap",
                media_class="Audio/Sink",
                factory="support.null-audio-sink",
            ),
            _pw_link(id=200, out_node=100, in_node=101),
        ]
        result = check_tts_broadcast_path(pw_dump_to_descriptor(dump))
        assert result.ok is False
        assert "hapax-tts-broadcast-* -> hapax-livestream-tap" in result.missing_edges

    def test_accepts_live_loopback_split_capture_and_playback_nodes(self) -> None:
        dump = [
            _pw_node(
                id=100,
                node_name="hapax-tts-duck",
                media_class="Audio/Sink",
                factory="filter-chain",
            ),
            _pw_node(
                id=101,
                node_name="hapax-tts-broadcast-capture",
                media_class="Stream/Input/Audio",
                target="hapax-tts-duck",
            ),
            _pw_node(
                id=102,
                node_name="hapax-tts-broadcast-playback",
                media_class="Stream/Output/Audio",
                target="hapax-livestream-tap",
            ),
            _pw_node(
                id=103,
                node_name="hapax-livestream-tap",
                media_class="Audio/Sink",
                factory="support.null-audio-sink",
            ),
            _pw_link(id=200, out_node=100, in_node=101),
            _pw_link(id=201, out_node=102, in_node=103),
        ]
        result = check_tts_broadcast_path(pw_dump_to_descriptor(dump))
        assert result.ok is True

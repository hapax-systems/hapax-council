"""Tests for shared.audio_topology_inspector — pw-dump → TopologyDescriptor."""

from __future__ import annotations

import json
from textwrap import dedent
from typing import Any

import numpy as np

from shared.audio_topology import Node, NodeKind, TopologyDescriptor
from shared.audio_topology_inspector import (
    _classify_node_kind,
    _id_from_name,
    channel_peak_dbfs,
    check_l12_broadcast_scene_active,
    check_l12_forward_invariant,
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


def _descriptor(body: str) -> TopologyDescriptor:
    return TopologyDescriptor.from_yaml(dedent(body))


def _replace_node(
    descriptor: TopologyDescriptor,
    node_id: str,
    **updates: object,
) -> TopologyDescriptor:
    nodes: list[Node] = []
    for node in descriptor.nodes:
        nodes.append(node.model_copy(update=updates) if node.id == node_id else node)
    return descriptor.model_copy(update={"nodes": nodes})


def _l12_scene_assignments() -> dict[str, str]:
    return {
        "CH2": "cortado-contact-mic",
        "CH3": "reserve",
        "CH4": "sampler-chain",
        "CH5": "rode-wireless-pro-rx",
        "CH6": "legacy-evil-pet-return-aux5",
        "CH7": "reserve",
        "CH8": "reserve",
        "CH9": "mpc-content-return-l",
        "CH10": "mpc-content-return-r",
        "CH11": "mpc-voice-return-l",
        "CH12": "mpc-voice-return-r",
        "CH13": "master-l-dropped-from-broadcast",
        "CH14": "master-r-dropped-from-broadcast",
    }


def _l12_scene_fixture() -> TopologyDescriptor:
    return _replace_node(
        _l12_contract_fixture(),
        "l12-capture",
        expected_scene="BROADCAST-V2",
        expected_channel_assignments=_l12_scene_assignments(),
    )


def _scene_pcm(
    *,
    content_l_amp: int = 20000,
    content_r_amp: int = 20000,
    voice_l_amp: int = 20000,
    voice_r_amp: int = 20000,
    legacy_aux5_amp: int = 0,
    samples: int = 4800,
) -> bytes:
    buffer = np.zeros((samples, 14), dtype=np.int16)
    buffer[:, 5] = legacy_aux5_amp
    buffer[:, 8] = content_l_amp
    buffer[:, 9] = content_r_amp
    buffer[:, 10] = voice_l_amp
    buffer[:, 11] = voice_r_amp
    return buffer.tobytes()


def _l12_contract_fixture() -> TopologyDescriptor:
    return _descriptor(
        """
        schema_version: 2
        description: l12 invariant fixture
        nodes:
          - id: l12-capture
            kind: alsa_source
            pipewire_name: alsa_input.usb-ZOOM_Corporation_L-12-00.multichannel-input
            hw: hw:L12,0
            channels:
              count: 14
              positions: [AUX0, AUX1, AUX2, AUX3, AUX4, AUX5, AUX6, AUX7, AUX8, AUX9, AUX10, AUX11, AUX12, AUX13]
          - id: l12-usb-return
            kind: alsa_sink
            pipewire_name: alsa_output.usb-ZOOM_Corporation_L-12-00.analog-surround-40
            hw: surround40:L12
            channels:
              count: 4
              positions: [FL, FR, RL, RR]
          - id: livestream-tap
            kind: tap
            pipewire_name: hapax-livestream-tap
          - id: l12-evilpet-capture
            kind: filter_chain
            pipewire_name: hapax-l12-evilpet-capture
            target_object: alsa_input.usb-ZOOM_Corporation_L-12-00.multichannel-input
            params:
              capture_positions: AUX1 AUX3 AUX4 AUX5
              forbidden_capture_positions: AUX8 AUX9 AUX10 AUX11 AUX12 AUX13
              playback_target: hapax-livestream-tap
          - id: l12-usb-return-capture
            kind: filter_chain
            pipewire_name: hapax-l12-usb-return-capture
            target_object: alsa_input.usb-ZOOM_Corporation_L-12-00.multichannel-input
            params:
              capture_positions: AUX8 AUX9 AUX10 AUX11
              playback_target: hapax-livestream-tap
              mpc_wet_return: true
          - id: mpc-usb-output
            kind: alsa_sink
            pipewire_name: alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output
            hw: hw:MPCB,0
            channels:
              count: 24
          - id: private-sink
            kind: tap
            pipewire_name: hapax-private
            params:
              fail_closed: true
          - id: notification-private-sink
            kind: tap
            pipewire_name: hapax-notification-private
            params:
              fail_closed: true
          - id: yeti-headphone-output
            kind: alsa_sink
            pipewire_name: alsa_output.usb-Blue_Microphones_Yeti-00.analog-stereo
            hw: front:Yeti
            params:
              private_monitor_endpoint: true
          - id: private-monitor-capture
            kind: filter_chain
            pipewire_name: hapax-private-monitor-capture
            target_object: hapax-private
            params:
              stream.capture.sink: true
          - id: private-monitor-output
            kind: loopback
            pipewire_name: hapax-private-playback
            target_object: alsa_output.usb-Blue_Microphones_Yeti-00.analog-stereo
            params:
              node.dont-fallback: true
              node.dont-reconnect: true
              node.dont-move: true
              node.linger: true
              state.restore: false
              fail_closed_on_target_absent: true
              private_monitor_bridge: true
          - id: notification-private-monitor-capture
            kind: filter_chain
            pipewire_name: hapax-notification-private-monitor-capture
            target_object: hapax-notification-private
            params:
              stream.capture.sink: true
          - id: notification-private-monitor-output
            kind: loopback
            pipewire_name: hapax-notification-private-playback
            target_object: alsa_output.usb-Blue_Microphones_Yeti-00.analog-stereo
            params:
              node.dont-fallback: true
              node.dont-reconnect: true
              node.dont-move: true
              node.linger: true
              state.restore: false
              fail_closed_on_target_absent: true
              private_monitor_bridge: true
          - id: role-multimedia
            kind: loopback
            pipewire_name: input.loopback.sink.role.multimedia
            target_object: hapax-pc-loudnorm
          - id: role-notification
            kind: loopback
            pipewire_name: input.loopback.sink.role.notification
            target_object: hapax-notification-private
          - id: role-assistant
            kind: loopback
            pipewire_name: input.loopback.sink.role.assistant
            target_object: hapax-private
          - id: role-broadcast
            kind: loopback
            pipewire_name: input.loopback.sink.role.broadcast
            target_object: hapax-voice-fx-capture
          - id: pc-loudnorm
            kind: filter_chain
            pipewire_name: hapax-pc-loudnorm
            target_object: alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output
            params:
              notification_excluded: true
          - id: voice-fx
            kind: filter_chain
            pipewire_name: hapax-voice-fx-capture
            target_object: hapax-loudnorm-capture
          - id: tts-loudnorm
            kind: filter_chain
            pipewire_name: hapax-loudnorm-capture
            target_object: alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output
            params:
              playback_positions: AUX2 AUX3
              broadcast_forward_path: mpc-usb-output l12-usb-return-capture hapax-livestream-tap
        edges:
          - source: l12-capture
            target: l12-evilpet-capture
          - source: l12-capture
            target: l12-usb-return-capture
          - source: l12-usb-return-capture
            target: livestream-tap
          - source: private-sink
            target: private-monitor-capture
          - source: private-monitor-capture
            target: private-monitor-output
          - source: notification-private-sink
            target: notification-private-monitor-capture
          - source: notification-private-monitor-capture
            target: notification-private-monitor-output
        """
    )


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

    def test_private_monitor_playback_stream_is_modeled(self) -> None:
        assert (
            _classify_node_kind(
                {
                    "node.name": "hapax-private-playback",
                    "media.class": "Stream/Output/Audio",
                    "target.object": ("alsa_output.usb-Blue_Microphones_Yeti-00.analog-stereo"),
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
        """ALSA multi-segment names trim to the last three dash-separated segments.

        Three (rather than two) prevents ID collisions between devices
        whose ALSA suffix shares the trailing two segments (e.g. L-12
        and MPC both ending in ``00.multichannel-input``). Result is
        still kebab-ish — Node.id validator only rejects whitespace
        + uppercase, so the dot in ``00.multitrack`` is tolerated.
        """
        assert (
            _id_from_name("alsa_input.usb-ZOOM_Corporation_L6-00.multitrack")
            == "corporation-l6-00.multitrack"
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
    def _current_mpc_dump(self, *, include_final_edge: bool = True) -> list[dict[str, Any]]:
        dump = [
            _pw_node(
                id=100,
                node_name="input.loopback.sink.role.broadcast",
                media_class="Audio/Sink",
                factory="loopback",
            ),
            _pw_node(
                id=101,
                node_name="hapax-voice-fx-capture",
                media_class="Audio/Sink",
                factory="filter-chain",
            ),
            _pw_node(
                id=102,
                node_name="hapax-loudnorm-capture",
                media_class="Audio/Sink",
                factory="filter-chain",
            ),
            _pw_node(
                id=103,
                node_name="alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output",
                media_class="Audio/Sink",
                factory="api.alsa.pcm.sink",
                hw="hw:7",
                channels=24,
            ),
            _pw_node(
                id=104,
                node_name="hapax-l12-usb-return-capture",
                media_class="Audio/Sink",
                factory="filter-chain",
            ),
            _pw_node(
                id=105,
                node_name="hapax-livestream-tap",
                media_class="Audio/Sink",
                factory="support.null-audio-sink",
            ),
            _pw_node(
                id=106,
                node_name="hapax-broadcast-master-capture",
                media_class="Audio/Sink",
                factory="filter-chain",
            ),
        ]
        if include_final_edge:
            dump.append(_pw_link(id=200, out_node=105, in_node=106))
        return dump

    def test_ok_when_current_mpc_wet_return_path_is_present(self) -> None:
        result = check_tts_broadcast_path(pw_dump_to_descriptor(self._current_mpc_dump()))
        assert result.ok is True
        assert result.missing_nodes == ()
        assert result.missing_edges == ()

    def test_reports_missing_mpc_wet_return_node(self) -> None:
        dump = [
            node
            for node in self._current_mpc_dump()
            if node.get("info", {}).get("props", {}).get("node.name")
            != "hapax-l12-usb-return-capture"
        ]
        result = check_tts_broadcast_path(pw_dump_to_descriptor(dump))
        assert result.ok is False
        assert "hapax-l12-usb-return-capture" in result.missing_nodes

    def test_reports_missing_final_tap_to_master_edge(self) -> None:
        dump = self._current_mpc_dump(include_final_edge=False)
        result = check_tts_broadcast_path(pw_dump_to_descriptor(dump))
        assert result.ok is False
        assert "hapax-livestream-tap -> hapax-broadcast-master-capture" in result.missing_edges

    def test_retired_direct_tts_bridge_is_not_sufficient(self) -> None:
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
            _pw_link(id=201, out_node=101, in_node=103),
        ]
        result = check_tts_broadcast_path(pw_dump_to_descriptor(dump))
        assert result.ok is False
        assert "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output" in (
            result.missing_nodes
        )


class TestL12BroadcastSceneAssertion:
    def test_channel_peak_dbfs_isolated_to_selected_channel(self) -> None:
        pcm = _scene_pcm(content_l_amp=8000, voice_l_amp=0, voice_r_amp=0)

        assert channel_peak_dbfs(pcm, channels=14, channel_index=8) > -20.0
        assert channel_peak_dbfs(pcm, channels=14, channel_index=10) == float("-inf")

    def test_passes_when_scene_metadata_and_levels_match(self) -> None:
        result = check_l12_broadcast_scene_active(
            _l12_scene_fixture(),
            pcm_int16=_scene_pcm(),
            duration_s=30.0,
        )

        assert result.ok is True
        assert result.evidence["descriptor_expected_scene"] == "BROADCAST-V2"
        assert result.evidence["content_return_state"] == "active"
        assert result.evidence["voice_return_state"] == "active"
        assert result.evidence["content_return_peak_dbfs"] > -10.0
        assert result.evidence["voice_return_peak_dbfs"] > -10.0

    def test_fails_when_content_return_pair_is_cold(self) -> None:
        result = check_l12_broadcast_scene_active(
            _l12_scene_fixture(),
            pcm_int16=_scene_pcm(content_l_amp=0, content_r_amp=0),
            duration_s=30.0,
        )

        assert result.ok is False
        assert result.evidence["content_return_state"] == "silent"
        assert any("AUX8 content return L peak" in violation for violation in result.violations)
        assert any("AUX9 content return R peak" in violation for violation in result.violations)

    def test_fails_when_voice_return_pair_is_cold(self) -> None:
        result = check_l12_broadcast_scene_active(
            _l12_scene_fixture(),
            pcm_int16=_scene_pcm(voice_l_amp=0, voice_r_amp=0),
            duration_s=30.0,
        )

        assert result.ok is False
        assert result.evidence["voice_return_state"] == "silent"
        assert any("AUX10 voice return L peak" in violation for violation in result.violations)
        assert any("AUX11 voice return R peak" in violation for violation in result.violations)

    def test_fails_legacy_aux10_11_only_false_green(self) -> None:
        result = check_l12_broadcast_scene_active(
            _l12_scene_fixture(),
            pcm_int16=_scene_pcm(content_l_amp=0, content_r_amp=0),
            duration_s=30.0,
        )

        assert result.ok is False
        assert result.evidence["voice_return_state"] == "active"
        assert result.evidence["content_return_state"] == "silent"

    def test_fails_real_silence(self) -> None:
        result = check_l12_broadcast_scene_active(
            _l12_scene_fixture(),
            pcm_int16=_scene_pcm(
                content_l_amp=0,
                content_r_amp=0,
                voice_l_amp=0,
                voice_r_amp=0,
            ),
            duration_s=30.0,
        )

        assert result.ok is False
        assert result.evidence["content_return_state"] == "silent"
        assert result.evidence["voice_return_state"] == "silent"

    def test_fails_when_expected_scene_metadata_does_not_match(self) -> None:
        descriptor = _replace_node(
            _l12_scene_fixture(),
            "l12-capture",
            expected_scene="BROADCAST",
        )

        result = check_l12_broadcast_scene_active(
            descriptor,
            pcm_int16=_scene_pcm(),
            duration_s=30.0,
        )

        assert result.ok is False
        assert any("expected_scene='BROADCAST'" in v for v in result.violations)

    def test_requires_minimum_thirty_second_probe_window(self) -> None:
        result = check_l12_broadcast_scene_active(
            _l12_scene_fixture(),
            pcm_int16=_scene_pcm(),
            duration_s=5.0,
        )

        assert result.ok is False
        assert any("requires at least 30s" in v for v in result.violations)


class TestL12ForwardInvariantCheck:
    def test_accepts_current_directionality_contract(self) -> None:
        result = check_l12_forward_invariant(_l12_contract_fixture())

        assert result.ok is True
        assert result.violations == ()

    def test_fails_when_tts_mpc_return_lacks_broadcast_forward_path(self) -> None:
        descriptor = _l12_contract_fixture()
        tts = descriptor.node_by_id("tts-loudnorm")
        descriptor = _replace_node(
            descriptor,
            "tts-loudnorm",
            params={k: v for k, v in tts.params.items() if k != "broadcast_forward_path"},
        )

        result = check_l12_forward_invariant(descriptor)

        assert result.ok is False
        codes = {violation.code for violation in result.violations}
        assert "tts_broadcast_forward_path_not_declared" in codes
        assert "tts_l12_missing_livestream_forward_path" in codes

    def test_fails_when_assistant_reaches_broadcast_voice_fx_path(self) -> None:
        descriptor = _replace_node(
            _l12_contract_fixture(),
            "role-assistant",
            target_object="hapax-voice-fx-capture",
        )

        result = check_l12_forward_invariant(descriptor)

        assert result.ok is False
        assert any(
            violation.code == "private_route_reaches_broadcast_path"
            and "role-assistant" in violation.message
            and "voice-fx" in violation.message
            for violation in result.violations
        )

    def test_fails_when_notification_falls_back_to_pc_loudnorm(self) -> None:
        descriptor = _replace_node(
            _l12_contract_fixture(),
            "role-notification",
            target_object="hapax-pc-loudnorm",
        )

        result = check_l12_forward_invariant(descriptor)

        assert result.ok is False
        assert any(
            violation.code == "private_route_reaches_broadcast_path"
            and "role-notification" in violation.message
            and "pc-loudnorm" in violation.message
            for violation in result.violations
        )

    def test_fails_when_private_sink_gets_l12_downstream_bridge(self) -> None:
        descriptor = _replace_node(
            _l12_contract_fixture(),
            "private-sink",
            target_object="alsa_output.usb-ZOOM_Corporation_L-12-00.analog-surround-40",
            params={"fail_closed": False},
        )

        result = check_l12_forward_invariant(descriptor)

        codes = {violation.code for violation in result.violations}
        assert "private_sink_not_fail_closed" in codes
        assert "private_route_reaches_broadcast_path" in codes

    def test_fails_when_private_monitor_bridge_targets_l12(self) -> None:
        descriptor = _replace_node(
            _l12_contract_fixture(),
            "private-monitor-output",
            target_object="alsa_output.usb-ZOOM_Corporation_L-12-00.analog-surround-40",
        )

        result = check_l12_forward_invariant(descriptor)

        codes = {violation.code for violation in result.violations}
        assert "private_monitor_bridge_target_not_allowed_endpoint" in codes
        assert "private_route_reaches_broadcast_path" in codes

    def test_fails_when_private_monitor_bridge_can_fallback(self) -> None:
        descriptor = _l12_contract_fixture()
        bridge = descriptor.node_by_id("notification-private-monitor-output")
        params = {**bridge.params, "node.dont-fallback": False}
        descriptor = _replace_node(
            descriptor,
            "notification-private-monitor-output",
            params=params,
        )

        result = check_l12_forward_invariant(descriptor)

        assert any(
            violation.code == "private_monitor_bridge_not_fail_closed"
            and "node.dont-fallback=True" in violation.message
            for violation in result.violations
        )

    def test_fails_when_unknown_source_targets_l12_return(self) -> None:
        descriptor = _l12_contract_fixture()
        extra = descriptor.node_by_id("pc-loudnorm").model_copy(
            update={
                "id": "unclassified-monitor-bridge",
                "pipewire_name": "hapax-unclassified-monitor-bridge",
                "target_object": "alsa_output.usb-ZOOM_Corporation_L-12-00.analog-surround-40",
                "params": {},
            }
        )
        descriptor = descriptor.model_copy(update={"nodes": [*descriptor.nodes, extra]})

        result = check_l12_forward_invariant(descriptor)

        assert any(
            violation.code == "unexpected_l12_return_producer"
            and "unclassified-monitor-bridge" in violation.message
            for violation in result.violations
        )

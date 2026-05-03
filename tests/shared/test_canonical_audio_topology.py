"""Regression pins for the canonical config/audio-topology.yaml descriptor."""

from __future__ import annotations

import re
from pathlib import Path

from shared.audio_topology import TopologyDescriptor
from shared.audio_topology_inspector import check_l12_forward_invariant

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_YAML = REPO_ROOT / "config" / "audio-topology.yaml"
L12_CAPTURE_CONF = REPO_ROOT / "config" / "pipewire" / "hapax-l12-evilpet-capture.conf"
L12_SOURCE_NAME = (
    "alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.multichannel-input"
)
L12_RETURN_NAME = (
    "alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40"
)


def _descriptor() -> TopologyDescriptor:
    return TopologyDescriptor.from_yaml(CANONICAL_YAML)


def test_canonical_descriptor_parses() -> None:
    assert CANONICAL_YAML.exists(), (
        "config/audio-topology.yaml missing - canonical descriptor deleted?"
    )
    d = _descriptor()
    # Schema v3 (audit F#8): typed filter-chain template params for the
    # generator's LADSPA loudnorm / duck / usb-bias chains.
    assert d.schema_version == 3


def test_canonical_has_current_livestream_node_ids() -> None:
    """Livestream-critical node IDs must pin the L-12-era graph."""
    ids = {n.id for n in _descriptor().nodes}
    expected = {
        "l12-capture",
        "l12-usb-return",
        "yeti-headphone-output",
        "livestream-tap",
        "l12-evilpet-capture",
        "broadcast-master-capture",
        "broadcast-normalized-capture",
        "obs-broadcast-remap-capture",
        "role-assistant",
        "role-broadcast",
        "private-sink",
        "private-monitor-capture",
        "private-monitor-output",
        "notification-private-sink",
        "notification-private-monitor-capture",
        "notification-private-monitor-output",
        "voice-fx",
        "tts-loudnorm",
        "tts-duck",
        "tts-broadcast-capture",
        "tts-broadcast-playback",
        "pc-loudnorm",
        "s4-loopback",
        "m8-instrument-capture",
        "m8-loudnorm",
    }
    assert expected.issubset(ids), f"missing expected node ids: {expected - ids}"


def test_retired_l6_ryzen_nodes_are_not_canonical() -> None:
    """The descriptor must not drift back to the retired L6/Ryzen graph."""
    ids = {n.id for n in _descriptor().nodes}
    retired = {
        "l6-capture",
        "main-mix-tap",
        "ryzen-analog-out",
        "private-loopback",
        "livestream-duck",
    }
    assert ids.isdisjoint(retired), f"retired nodes still present: {ids & retired}"


def test_l12_hardware_nodes_pin_live_names() -> None:
    d = _descriptor()
    l12_capture = d.node_by_id("l12-capture")
    l12_return = d.node_by_id("l12-usb-return")

    assert l12_capture.kind == "alsa_source"
    assert l12_capture.pipewire_name == L12_SOURCE_NAME
    assert l12_capture.channels.count == 14
    assert l12_capture.channels.positions == [f"AUX{i}" for i in range(14)]

    assert l12_return.kind == "alsa_sink"
    assert l12_return.pipewire_name == L12_RETURN_NAME
    assert l12_return.channels.count == 4
    assert l12_return.channels.positions == ["FL", "FR", "RL", "RR"]


def test_l12_evilpet_capture_preserves_inverse_safety_invariant() -> None:
    """Descriptor pins the narrowed L-12 capture binding.

    AUX8/9 (vinyl), AUX10/11 (PC return), and AUX12/13 (master bus) must
    stay outside the broadcast capture node.
    """
    d = _descriptor()
    l12_capture = d.node_by_id("l12-capture")
    capture = d.node_by_id("l12-evilpet-capture")

    assert capture.target_object == L12_SOURCE_NAME
    assert capture.params["capture_channels"] == 4
    assert capture.params["capture_positions"] == "AUX1 AUX3 AUX4 AUX5"
    assert capture.params["forbidden_capture_positions"] == "AUX8 AUX9 AUX10 AUX11 AUX12 AUX13"
    assert capture.params["playback_target"] == "hapax-livestream-tap"
    assert capture.params["playback_node_passive"] is False

    assert any(edge.source == l12_capture.id and edge.target == capture.id for edge in d.edges), (
        "missing L-12 capture source -> l12-evilpet-capture edge"
    )


def test_l12_evilpet_conf_matches_descriptor_narrowed_binding() -> None:
    d = _descriptor()
    capture = d.node_by_id("l12-evilpet-capture")
    conf = L12_CAPTURE_CONF.read_text(encoding="utf-8")

    assert "audio.channels = 4" in conf
    assert "audio.position = [ AUX1 AUX3 AUX4 AUX5 ]" in conf
    capture_match = re.search(r"capture\.props\s*=\s*\{(.*?)\}", conf, re.DOTALL)
    assert capture_match, "could not locate L-12 capture.props block"
    capture_props = capture_match.group(1)
    for forbidden in str(capture.params["forbidden_capture_positions"]).split():
        assert f" {forbidden} " not in capture_props, (
            f"{forbidden} must not be bound in L-12 capture"
        )


def test_broadcast_master_chain_is_canonical() -> None:
    d = _descriptor()
    master = d.node_by_id("broadcast-master-capture")
    normalized = d.node_by_id("broadcast-normalized-capture")
    obs = d.node_by_id("obs-broadcast-remap-capture")

    assert master.target_object == "hapax-livestream-tap"
    assert master.params["playback_source"] == "hapax-broadcast-master"
    assert normalized.target_object == "hapax-broadcast-master"
    assert normalized.params["playback_source"] == "hapax-broadcast-normalized"
    assert obs.target_object == "hapax-broadcast-normalized"
    assert any(
        edge.source == "livestream-tap" and edge.target == "broadcast-master-capture"
        for edge in d.edges
    )


def test_private_and_notification_sinks_are_fail_closed() -> None:
    d = _descriptor()
    private = d.node_by_id("private-sink")
    notify = d.node_by_id("notification-private-sink")
    private_capture = d.node_by_id("private-monitor-capture")
    private_output = d.node_by_id("private-monitor-output")
    notify_capture = d.node_by_id("notification-private-monitor-capture")
    notify_output = d.node_by_id("notification-private-monitor-output")
    yeti = d.node_by_id("yeti-headphone-output")
    s4 = d.node_by_id("s4-output")
    role_assistant = d.node_by_id("role-assistant")
    role_notification = d.node_by_id("role-notification")

    assert private.kind == "tap"
    assert private.target_object is None
    assert private.params["fail_closed"] is True
    assert role_assistant.target_object == "hapax-private"

    assert notify.kind == "tap"
    assert notify.target_object is None
    assert notify.params["fail_closed"] is True
    assert role_notification.target_object == "hapax-notification-private"

    assert yeti.params["private_monitor_endpoint"] is True
    assert s4.params["private_monitor_endpoint"] is True
    assert private_capture.target_object == "hapax-private"
    assert private_capture.params["stream.capture.sink"] is True
    assert private_output.target_object == s4.pipewire_name
    assert notify_capture.target_object == "hapax-notification-private"
    assert notify_capture.params["stream.capture.sink"] is True
    assert notify_output.target_object == s4.pipewire_name

    for bridge in (private_output, notify_output):
        assert bridge.params["node.dont-fallback"] is True
        assert bridge.params["node.dont-reconnect"] is True
        assert bridge.params["node.dont-move"] is True
        assert bridge.params["state.restore"] is False
        assert bridge.params["fail_closed_on_target_absent"] is True

    edge_pairs = {(edge.source, edge.target) for edge in d.edges}
    assert ("private-sink", "private-monitor-capture") in edge_pairs
    assert ("private-monitor-capture", "private-monitor-output") in edge_pairs
    assert ("notification-private-sink", "notification-private-monitor-capture") in edge_pairs
    assert (
        "notification-private-monitor-capture",
        "notification-private-monitor-output",
    ) in edge_pairs


def test_tts_broadcast_path_has_l12_return_and_livestream_forward_path() -> None:
    d = _descriptor()
    role_broadcast = d.node_by_id("role-broadcast")
    voice_fx = d.node_by_id("voice-fx")
    loudnorm = d.node_by_id("tts-loudnorm")
    duck = d.node_by_id("tts-duck")
    broadcast_capture = d.node_by_id("tts-broadcast-capture")
    broadcast_playback = d.node_by_id("tts-broadcast-playback")

    assert role_broadcast.target_object == "hapax-voice-fx-capture"
    assert voice_fx.target_object == "hapax-loudnorm-capture"
    assert loudnorm.target_object == "hapax-tts-duck"
    assert duck.target_object == L12_RETURN_NAME
    assert duck.params["playback_positions"] == "RL RR"
    assert broadcast_capture.target_object == "hapax-tts-duck"
    assert broadcast_playback.target_object == "hapax-livestream-tap"

    edge_pairs = {(edge.source, edge.target) for edge in d.edges}
    assert ("tts-duck", "tts-broadcast-capture") in edge_pairs
    assert ("tts-broadcast-playback", "livestream-tap") in edge_pairs


def test_pc_loudnorm_lands_on_l12_return_but_notifications_do_not() -> None:
    d = _descriptor()
    pc = d.node_by_id("pc-loudnorm")
    role_multimedia = d.node_by_id("role-multimedia")
    role_notification = d.node_by_id("role-notification")

    assert role_multimedia.target_object == "hapax-pc-loudnorm"
    assert pc.target_object == L12_RETURN_NAME
    assert pc.params["playback_positions"] == "RL RR"
    assert pc.params["notification_excluded"] is True
    assert role_notification.target_object == "hapax-notification-private"


def test_s4_loopback_targets_livestream_tap() -> None:
    d = _descriptor()
    s4 = d.node_by_id("s4-loopback")

    assert s4.kind == "loopback"
    assert s4.pipewire_name == "hapax-s4-content"
    assert s4.target_object == "hapax-livestream-tap"
    assert s4.params["audio.format"] == "S32"
    assert s4.params["audio.rate"] == 48000


def test_m8_loudnorm_bypasses_l12_and_missing_hardware_is_classified() -> None:
    d = _descriptor()
    m8_source = d.node_by_id("m8-usb-source")
    m8_capture = d.node_by_id("m8-instrument-capture")
    m8_loudnorm = d.node_by_id("m8-loudnorm")

    assert m8_source.params["audit_classification"] == "external-hardware-optional"
    assert m8_capture.target_object == m8_source.pipewire_name
    assert m8_loudnorm.target_object == "hapax-livestream-tap"
    assert m8_loudnorm.params["bypasses_l12"] is True

    forbidden_edges = [
        edge
        for edge in d.edges
        if {edge.source, edge.target} & {"l12-capture", "l12-usb-return"}
        and {edge.source, edge.target} & {"m8-instrument-capture", "m8-loudnorm"}
    ]
    assert forbidden_edges == [], "M8 descriptor path must not touch L-12 hardware"


def test_l12_forward_invariant_static_guard_passes() -> None:
    """Canonical descriptor must satisfy the L-12 forward/private route guard."""
    result = check_l12_forward_invariant(_descriptor())

    assert result.ok, result.format()

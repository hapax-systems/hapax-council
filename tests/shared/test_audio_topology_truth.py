"""Tests for the Audio Topology Truth Surface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from shared.audio_topology import Edge, Node, NodeKind, TopologyDescriptor
from shared.audio_topology_inspector import (
    TopologyTruth,
    build_ingress_ledger,
    build_live_capsule,
    build_route_class_matrix,
    build_topology_truth,
)


def _minimal_routing_config() -> dict[str, Any]:
    return {
        "fail_closed_policy": {
            "unknown_source_broadcast_eligible": False,
        },
        "routes": [
            {
                "source_id": "voice-broadcast",
                "producer": "daimonion",
                "role": "broadcast",
                "pipewire_node": "hapax-voice-fx-capture",
                "target_chain": ["hapax-voice-fx-capture", "hapax-loudnorm-capture"],
                "route_class": "broadcast_voice",
                "broadcast_eligible": True,
                "broadcast_eligibility_basis": "explicit_policy",
            },
            {
                "source_id": "assistant-private",
                "producer": "daimonion",
                "role": "assistant",
                "pipewire_node": "input.loopback.sink.role.assistant",
                "target_chain": ["hapax-private"],
                "route_class": "private",
                "broadcast_eligible": False,
                "broadcast_eligibility_basis": "private_refused",
            },
            {
                "source_id": "multimedia-default",
                "producer": "desktop-session",
                "role": "multimedia",
                "pipewire_node": "hapax-pc-loudnorm",
                "target_chain": ["hapax-pc-loudnorm"],
                "route_class": "default_multimedia_fail_closed",
                "broadcast_eligible": False,
                "broadcast_eligibility_basis": "disabled_pc_usb56",
            },
        ],
    }


def _minimal_live_descriptor(*extra_names: str) -> TopologyDescriptor:
    nodes = [
        Node(
            id="voice-fx",
            kind=NodeKind.FILTER_CHAIN,
            pipewire_name="hapax-voice-fx-capture",
        ),
        Node(
            id="livestream-tap",
            kind=NodeKind.TAP,
            pipewire_name="hapax-livestream-tap",
        ),
        Node(
            id="broadcast-master",
            kind=NodeKind.FILTER_CHAIN,
            pipewire_name="hapax-broadcast-master-capture",
        ),
    ]
    for name in extra_names:
        node_id = name.replace(".", "-").lower()
        nodes.append(Node(id=node_id, kind=NodeKind.LOOPBACK, pipewire_name=name))
    return TopologyDescriptor(
        schema_version=2,
        nodes=nodes,
        edges=[Edge(source="livestream-tap", target="broadcast-master")],
    )


# --- Ingress Ledger ---


def test_ingress_ledger_broadcast_vs_private() -> None:
    config = _minimal_routing_config()
    ledger = build_ingress_ledger(config)

    by_id = {e.source_id: e for e in ledger}
    assert by_id["voice-broadcast"].livestream_eligible is True
    assert by_id["voice-broadcast"].exposure_domain == "broadcast"
    assert by_id["assistant-private"].livestream_eligible is False
    assert by_id["assistant-private"].exposure_domain == "private"
    assert by_id["multimedia-default"].exposure_domain == "fail_closed"


def test_ingress_ledger_live_presence() -> None:
    config = _minimal_routing_config()
    live = _minimal_live_descriptor()
    ledger = build_ingress_ledger(config, live)

    by_id = {e.source_id: e for e in ledger}
    assert by_id["voice-broadcast"].live_present is True
    assert by_id["assistant-private"].live_present is False
    assert by_id["multimedia-default"].live_present is False


def test_ingress_ledger_no_live_all_false() -> None:
    config = _minimal_routing_config()
    ledger = build_ingress_ledger(config, None)
    assert all(not e.live_present for e in ledger)


def test_ingress_ledger_target_chain() -> None:
    config = _minimal_routing_config()
    ledger = build_ingress_ledger(config)
    by_id = {e.source_id: e for e in ledger}
    assert by_id["voice-broadcast"].target_chain == (
        "hapax-voice-fx-capture",
        "hapax-loudnorm-capture",
    )


# --- Route-Class Matrix ---


def test_route_class_matrix_broadcast_allowed() -> None:
    config = _minimal_routing_config()
    matrix = build_route_class_matrix(config)

    broadcast_edges = [e for e in matrix if e.target_domain == "broadcast"]
    by_class = {e.route_class: e for e in broadcast_edges}

    assert by_class["broadcast_voice"].status == "allowed"
    assert by_class["private"].status == "forbidden"
    assert by_class["default_multimedia_fail_closed"].status == "fail_closed"


def test_route_class_matrix_private_domain() -> None:
    config = _minimal_routing_config()
    matrix = build_route_class_matrix(config)

    private_edges = [e for e in matrix if e.target_domain == "private"]
    by_class = {e.route_class: e for e in private_edges}

    assert by_class["private"].status == "allowed"
    assert by_class["broadcast_voice"].status == "forbidden"


def test_route_class_matrix_reasons_populated() -> None:
    config = _minimal_routing_config()
    matrix = build_route_class_matrix(config)
    for edge in matrix:
        assert edge.reason, f"Empty reason for {edge.route_class} → {edge.target_domain}"


# --- Live Capsule ---


def _setup_capsule_repo(tmp_path: Path, *, stale: bool = False) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipewire" / "generated").mkdir(parents=True)
    (tmp_path / "config" / "hapax").mkdir(parents=True)
    (tmp_path / "config" / "wireplumber").mkdir(parents=True)

    topo = tmp_path / "config" / "audio-topology.yaml"
    topo.write_text("nodes: []")
    routing = tmp_path / "config" / "audio-routing.yaml"
    routing.write_text("routes: []")
    manifest = tmp_path / "config" / "pipewire" / "generated" / "audio-routing-policy.manifest.json"
    manifest.write_text("{}")
    forbidden = tmp_path / "config" / "hapax" / "audio-forbidden-links.conf"
    forbidden.write_text("# deny rules")
    linkmap = tmp_path / "config" / "hapax" / "audio-link-map.conf"
    linkmap.write_text("# link map")

    deny_hook = tmp_path / "config" / "wireplumber" / "98-hapax-link-deny.conf"
    deny_hook.write_text("# deny hook active")

    from shared.audio_topology_inspector import _hash_file_short

    hashes = {}
    for rel in [
        "config/audio-topology.yaml",
        "config/audio-routing.yaml",
        "config/pipewire/generated/audio-routing-policy.manifest.json",
        "config/hapax/audio-forbidden-links.conf",
        "config/hapax/audio-link-map.conf",
    ]:
        hashes[rel] = _hash_file_short(tmp_path / rel)

    if stale:
        hashes["config/audio-topology.yaml"] = "0000000000000000"

    capsule = tmp_path / "config" / "audio-current-capsule.yaml"
    capsule.write_text(yaml.dump({"source_hashes": hashes}))

    return tmp_path


def test_live_capsule_fresh(tmp_path: Path) -> None:
    repo = _setup_capsule_repo(tmp_path)
    capsule = build_live_capsule(repo)
    assert not capsule.stale_sources
    assert capsule.wireplumber_deny_present is True


def test_live_capsule_stale_detection(tmp_path: Path) -> None:
    repo = _setup_capsule_repo(tmp_path, stale=True)
    capsule = build_live_capsule(repo)
    assert len(capsule.stale_sources) == 1
    assert "audio-topology.yaml" in capsule.stale_sources[0]
    assert "hash drift" in capsule.stale_sources[0]


def test_live_capsule_missing_deny_hook(tmp_path: Path) -> None:
    repo = _setup_capsule_repo(tmp_path)
    (repo / "config" / "wireplumber" / "98-hapax-link-deny.conf").unlink()
    capsule = build_live_capsule(repo)
    assert capsule.wireplumber_deny_present is False


def test_live_capsule_obs_egress_witness() -> None:
    live = _minimal_live_descriptor()
    capsule = build_live_capsule(Path("/nonexistent"), live)
    assert capsule.obs_egress_witness is True


def test_live_capsule_obs_egress_absent() -> None:
    live = TopologyDescriptor(
        schema_version=2,
        nodes=[
            Node(id="tap", kind=NodeKind.TAP, pipewire_name="hapax-livestream-tap"),
        ],
        edges=[],
    )
    capsule = build_live_capsule(Path("/nonexistent"), live)
    assert capsule.obs_egress_witness is False


def test_live_capsule_physical_device_witness(tmp_path: Path) -> None:
    repo = _setup_capsule_repo(tmp_path)
    topo = TopologyDescriptor(
        schema_version=2,
        nodes=[
            Node(
                id="l12-capture",
                kind=NodeKind.ALSA_SOURCE,
                pipewire_name="alsa_input.usb-ZOOM_Corporation_L-12_SERIAL-00.multichannel-input",
                hw="hw:CARD=L12",
            ),
        ],
    )
    live = _minimal_live_descriptor(
        "alsa_input.usb-ZOOM_Corporation_L-12_SERIAL-00.multichannel-input"
    )
    capsule = build_live_capsule(repo, live, topo)
    assert len(capsule.physical_devices) == 1
    assert capsule.physical_devices[0].live_present is True
    assert capsule.physical_devices[0].descriptor_id == "l12-capture"


# --- Topology Truth (integration) ---


def test_topology_truth_no_warnings_offline(tmp_path: Path) -> None:
    repo = _setup_capsule_repo(tmp_path)
    truth = build_topology_truth(repo, live=None)
    assert isinstance(truth, TopologyTruth)
    assert not truth.warnings


def test_topology_truth_stale_warns(tmp_path: Path) -> None:
    repo = _setup_capsule_repo(tmp_path, stale=True)
    truth = build_topology_truth(repo, live=None)
    stale_warnings = [w for w in truth.warnings if w.startswith("STALE")]
    assert len(stale_warnings) == 1


def test_topology_truth_missing_deny_warns(tmp_path: Path) -> None:
    repo = _setup_capsule_repo(tmp_path)
    (repo / "config" / "wireplumber" / "98-hapax-link-deny.conf").unlink()
    truth = build_topology_truth(repo, live=None)
    deny_warnings = [w for w in truth.warnings if "deny hook" in w]
    assert len(deny_warnings) == 1


def test_topology_truth_missing_broadcast_source_warns(tmp_path: Path) -> None:
    repo = _setup_capsule_repo(tmp_path)
    routing = _minimal_routing_config()
    (repo / "config" / "audio-routing.yaml").write_text(yaml.dump(routing))
    live = _minimal_live_descriptor()
    truth = build_topology_truth(repo, live=live)
    assert not any("assistant-private" in w for w in truth.warnings), (
        "private source should not warn"
    )


def test_topology_truth_missing_obs_egress_warns(tmp_path: Path) -> None:
    repo = _setup_capsule_repo(tmp_path)
    live = TopologyDescriptor(schema_version=2, nodes=[], edges=[])
    truth = build_topology_truth(repo, live=live)
    egress_warnings = [w for w in truth.warnings if "egress" in w]
    assert len(egress_warnings) == 1

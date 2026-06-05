from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "config" / "screwm-aggregate-port-owners.json"

REQUIRED_PORT_IDS = {
    "audio_governance",
    "layout_programme_control",
    "temporal_glfeedback_effects",
    "recording_hls_egress",
    "camera_resilience_live_texture",
    "drift_modulation_currency",
}

MINIMUM_RETAINED_CAPABILITIES = {
    "ducking",
    "vad",
    "lufs_panic",
    "consent_egress",
    "egress_loopback",
    "layout_switching",
    "programme_rotation",
    "glfeedback_chain",
    "receiver_local_drift",
    "hls_branch",
    "segment_archive_rotation",
    "stable_by_id_devices",
    "v4l2_stall_recovery",
    "density_grounding",
    "geo_drift_cvar_drive",
    "live_texture_deploy_rebuild",
    "unified_reactivity_export",
}


def _load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _iter_refs(port: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for key in ("source_owners", "route_bridges", "deterministic_tests"):
        refs.extend(port[key])
    return refs


def test_screwm_aggregate_contract_declares_required_ports() -> None:
    contract = _load_contract()
    ports = {port["id"]: port for port in contract["required_ports"]}

    assert contract["version"] == "screwm-aggregate-port-owners-v1"
    assert contract["status"] == "operative_required"
    assert contract["retired_surfaces"] == ["logos_tauri_frontend"]
    assert set(ports) == REQUIRED_PORT_IDS

    declared_capabilities = {
        capability for port in ports.values() for capability in port["required_capabilities"]
    }
    assert declared_capabilities >= MINIMUM_RETAINED_CAPABILITIES


def test_every_port_has_owners_bridges_tests_and_failure_predicates() -> None:
    for port in _load_contract()["required_ports"]:
        assert port["required_capabilities"], port["id"]
        assert port["source_owners"], port["id"]
        assert port["route_bridges"], port["id"]
        assert port["deterministic_tests"], port["id"]
        assert port["failure_predicates"], port["id"]
        assert all(predicate.endswith(".") for predicate in port["failure_predicates"])


def test_declared_source_and_test_anchors_exist() -> None:
    for port in _load_contract()["required_ports"]:
        for ref in _iter_refs(port):
            path = REPO_ROOT / ref["path"]
            assert path.exists(), f"{port['id']} missing {ref['path']}"
            text = path.read_text(encoding="utf-8")
            for anchor in ref["anchors"]:
                assert anchor in text, f"{port['id']} missing {anchor!r} in {ref['path']}"


def test_contract_does_not_recruit_retired_frontend_paths() -> None:
    retired_tokens = ("hapax-logos", "tauri", "logos")

    for port in _load_contract()["required_ports"]:
        for ref in _iter_refs(port):
            lowered = ref["path"].lower()
            assert not any(token in lowered for token in retired_tokens), ref["path"]


def test_runtime_witness_boundary_is_explicit_for_source_only_gate() -> None:
    contract = _load_contract()

    assert (
        "source contract proves owner and test anchors only" in contract["runtime_witness_policy"]
    )
    assert "audiovisual quality remain separate" in contract["runtime_witness_policy"]
    hls_port = next(
        port for port in contract["required_ports"] if port["id"] == "recording_hls_egress"
    )
    assert "runtime_witness_required" in hls_port["required_capabilities"]

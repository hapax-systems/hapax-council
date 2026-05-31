from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOUNDARY_PATH = REPO_ROOT / "config" / "screwm-compositor-sunset-boundary.json"
SPEC_PATH = REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-05-23-screwm-quake-hybrid-isap.md"
CLAUDE_PATH = REPO_ROOT / "CLAUDE.md"

REQUIRED_PORTS = {
    "audio_reactivity": "audio reactivity",
    "drift_modulation_currency": "drift/modulation currency",
    "wgsl_node_graph_parity": "WGSL node graph parity",
    "cairo_ward_atlas": "Cairo/ward atlas rendering",
    "image_video_classification": "image/video classification",
    "audio_governance_ducking_lufs_vad_consent": (
        "audio governance: ducking, LUFS panic, VAD, and consent egress"
    ),
    "layout_switching_transition_fsm": "layout switching and transition FSM",
    "director_programme_control": "director/programme control",
    "temporal_glfeedback_effects": "temporal/glfeedback effects",
    "recording_hls_egress": "recording/HLS egress",
    "camera_resilience": "camera resilience",
}


def _boundary() -> dict:
    return json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))


def _compact(text: str) -> str:
    return " ".join(text.split())


def test_tauri_sunset_boundary_is_machine_readable() -> None:
    boundary = _boundary()

    assert boundary["version"] == "screwm-compositor-sunset-boundary-v1"
    assert boundary["authority_case"] == "CASE-SCREWM-QUAKE-MIGRATION-20260523"
    assert boundary["parent_spec"] == str(SPEC_PATH.relative_to(REPO_ROOT))
    assert boundary["aggregate_target"]["id"] == "screwm_native_aggregate"
    assert boundary["aggregate_target"]["lost_capabilities_allowed"] is False
    assert boundary["aggregate_target"]["runtime_mutation_in_this_slice"] is False

    assert boundary["sunsetted_surfaces"] == [
        {
            "id": "logos_tauri_frontend",
            "scope": "Logos/Tauri desktop UI shell only",
            "status": "sunsetted_intentional",
            "runtime_required": False,
            "must_not_revive_as_primary_runtime": True,
            "does_not_sunset_compositor_capabilities": True,
        }
    ]


def test_all_compositor_capabilities_remain_required_ports() -> None:
    ports = {port["id"]: port for port in _boundary()["required_compositor_ports"]}

    assert set(ports) == set(REQUIRED_PORTS)
    for port_id, label in REQUIRED_PORTS.items():
        port = ports[port_id]
        assert port["label"] == label
        assert port["status"] == "required_port"
        assert port["target_owner"] == "screwm_native_aggregate"
        assert "minimum_contract" in port
        assert port["minimum_contract"].strip()


def test_guidance_replaces_stale_tauri_only_runtime_with_aggregate_boundary() -> None:
    guidance = CLAUDE_PATH.read_text(encoding="utf-8")
    compact_guidance = _compact(guidance)

    assert "## Tauri-Only Runtime" not in guidance
    assert "Logos = Tauri 2" not in guidance
    assert "## Screwm Aggregate Runtime" in guidance
    assert "Only the Logos/Tauri desktop frontend is intentionally sunsetted" in compact_guidance
    assert "Do not revive it as the primary runtime" in compact_guidance
    assert "The `hapax-logos` workspace may still contain shared visual crates" in compact_guidance
    for label in REQUIRED_PORTS.values():
        assert label in compact_guidance


def test_isap_records_sunset_boundary_and_required_ports() -> None:
    spec = SPEC_PATH.read_text(encoding="utf-8")
    compact_spec = _compact(spec)

    assert "### 2.1 Sunset Boundary (Load-Bearing)" in spec
    assert "Only the Logos/Tauri desktop frontend is sunsetted" in compact_spec
    assert "The studio compositor capability set is not sunsetted" in compact_spec
    assert "release-blocking error" in compact_spec
    assert "the retired desktop shell is not the aggregate runtime" in compact_spec
    for label in REQUIRED_PORTS.values():
        assert label in compact_spec


def test_forbidden_interpretations_block_darkplaces_only_regression() -> None:
    forbidden = set(_boundary()["forbidden_interpretations"])

    assert "Treating hapax-logos inactivity as a regression by itself." in forbidden
    assert "Using Tauri sunset as permission to remove studio-compositor behavior." in forbidden
    assert (
        "Shipping Screwm as DarkPlaces-only when required compositor ports are absent." in forbidden
    )
    assert "Counting advisory layout/config state as witnessed runtime layout success." in forbidden

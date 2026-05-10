"""Contract tests for the livestream render architecture shadow plan."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "config" / "livestream-render-architecture-shadow-plan.yaml"
SCHEMA_PATH = REPO_ROOT / "schemas" / "livestream-render-architecture-shadow-plan.schema.json"
SPEC_PATH = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-05-10-livestream-render-architecture-shadow-plan.md"
)


def _contract() -> dict[str, object]:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_shadow_plan_schema_validates_contract() -> None:
    schema = _schema()
    contract = _contract()

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(contract)

    assert schema["title"] == "LivestreamRenderArchitectureShadowPlan"
    assert contract["task_id"] == "livestream-compositor-render-architecture-shadow-plan"


def test_decision_rejects_local_optima_but_keeps_gstreamer_io_roles() -> None:
    contract = _contract()
    decision = contract["decision"]
    alternatives = {item["id"]: item for item in contract["alternatives"]}

    assert (
        decision["selected_architecture"] == "clock_owned_render_core_with_gstreamer_ingest_egress"
    )
    assert decision["render_clock_owner"] == "render_core"
    assert decision["rejects_monolithic_gstreamer_composition_as_global_maximum"] is True
    assert decision["current_system_unchanged"] is True
    assert decision["current_containment_not_restored"] is True
    assert set(decision["gstreamer_roles"]) >= {
        "camera_ingest",
        "decode",
        "caps_negotiation",
        "egress_encoding",
        "transport_adapter",
    }

    required_alternatives = {
        "monolithic_gstreamer_compositor",
        "gstreamer_multi_pipeline_bridge",
        "rust_wgpu_renderd",
        "pipewire_graph_compositor",
        "obs_scene_or_plugin_owner",
        "ffmpeg_libavfilter_compositor",
    }
    assert required_alternatives <= set(alternatives)
    assert alternatives["monolithic_gstreamer_compositor"]["local_optimum"] is True
    assert alternatives["monolithic_gstreamer_compositor"]["verdict"] == (
        "rejected_as_global_maximum"
    )
    assert (
        alternatives["rust_wgpu_renderd"]["verdict"] == "selected_as_shadow_target_after_abi_proof"
    )


def test_clock_and_adapter_contracts_are_nonblocking() -> None:
    contract = _contract()
    clock = contract["clock_contract"]

    assert clock["owner"] == "render_core"
    assert clock["frame_deadline_ms"] <= 34
    assert clock["missing_source_degrades_within_ms"] <= 2000
    assert clock["source_sampling"] == "nonblocking_latest_value"
    assert clock["egress_policy"] == "adapters_receive_latest_complete_frame_only"
    assert {
        "camera",
        "ward",
        "shader",
        "hls",
        "v4l2",
        "obs",
        "public_output_consumer",
    } <= set(clock["prohibited_waits"])

    for adapter in contract["egress_adapters"]:
        assert adapter["blocking_allowed"] is False
        assert adapter["failure_effect"] == "adapter_degraded_only"
        assert adapter["queue"] in {"single_latest", "leaky_downstream", "bounded_drop_oldest"}


def test_frame_source_abi_and_failure_policies_pin_two_second_degradation() -> None:
    contract = _contract()
    abi = contract["frame_source_abi"]

    assert set(abi["metadata_fields"]) == {
        "timestamp_ns",
        "sequence",
        "width",
        "height",
        "colorspace",
        "source_class",
        "health",
        "fallback_policy",
        "render_cost_us",
    }
    assert "shared_memory_frame_ring" in abi["transport"]
    assert "metadata_sidecar_json" in abi["transport"]

    policies = {item["source_class"]: item for item in contract["source_failure_policies"]}
    assert {"camera_rgb", "camera_ir", "cairo_ward", "reverie_shader"} <= set(policies)
    for policy in policies.values():
        assert policy["max_degrade_ms"] <= 2000
        assert policy["fallback"] in {
            "last_good_then_offline_slate",
            "hold_last_good_then_suppress",
        }


def test_shadow_mode_has_measurable_success_chaos_soak_and_rollback() -> None:
    shadow = _contract()["shadow_mode"]
    subset = shadow["subset"]

    assert shadow["enabled_by_default"] is False
    assert shadow["private_output_only"] is True
    assert {"brio-operator", "c920-desk", "c920-overhead"} <= set(subset["cameras"])
    assert {"egress_footer", "programme_banner", "grounding_provenance_ticker"} <= set(
        subset["wards"]
    )
    assert "reverie" in subset["shader_inputs"]
    assert subset["private_output"].startswith("/dev/shm/hapax-compositor/render-shadow/")

    for criterion in shadow["success_criteria"]:
        assert {"id", "metric", "pass", "fail"} <= set(criterion)

    chaos_ids = {item["id"] for item in shadow["chaos_tests"]}
    assert {
        "camera_freeze",
        "ward_timeout",
        "shader_hang",
        "hls_writer_stall",
        "v4l2_writer_stall",
        "obs_cached_frame",
        "public_output_slow_consumer",
    } <= chaos_ids
    assert shadow["soak_tests"][0]["duration"] == "PT2H"
    assert shadow["rollback"]["disable_flag"] == "HAPAX_RENDER_CORE_SHADOW=0"
    assert len(shadow["rollback"]["steps"]) >= 2


def test_migration_forbids_public_cutover_until_final_candidate_stage() -> None:
    migration = _contract()["migration"]

    assert migration[-1]["stage"] == "public_cutover_candidate"
    assert migration[-1]["public_cutover_allowed"] is True
    for stage in migration[:-1]:
        assert stage["public_cutover_allowed"] is False
    assert any(stage["stage"] == "s5_cutover_packet" for stage in migration)


def test_av_sdlc_inspection_checkpoints_and_commands_are_pinned() -> None:
    inspection = _contract()["av_sdlc_inspection"]

    assert {
        "CP-SOURCE-TRUTH",
        "CP-RENDER-TRUTH",
        "CP-EGRESS-TRUTH",
        "CP-CONSUMER-PUBLIC-TRUTH",
        "CP-LAYOUT-VALIDITY",
        "CP-INSPECTION-EVIDENCE",
        "CP-REGRESSION-GATES",
        "CP-INCIDENT-EXIT-HOLD",
    } <= set(inspection["required_checkpoints"])
    assert (
        "scripts/compositor-inspect before incident-render-architecture"
        in inspection["evidence_commands"]
    )
    assert "scripts/hapax-live-surface-preflight --json" in inspection["evidence_commands"]


def test_local_seam_references_point_at_real_symbols() -> None:
    for seam in _contract()["local_seams"]:
        path = REPO_ROOT / seam["path"]
        assert path.exists(), f"missing seam path {path}"
        text = path.read_text(encoding="utf-8")
        symbol_tail = seam["symbol"].split(".")[-1]
        assert symbol_tail in text, f"{seam['symbol']} not found in {path}"


def test_spec_links_to_contract_and_names_no_cutover() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert "config/livestream-render-architecture-shadow-plan.yaml" in text
    assert "clock-owned render core" in text
    assert "no production cutover" in text.lower()
    assert "HAPAX_RENDER_CORE_SHADOW=0" in text

"""Phase 1+2 mk5 port-level compiler/proof tests."""

from __future__ import annotations

import importlib.util
import subprocess
from copy import deepcopy
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import shared.audio_loudness as loudness
from shared.audio_graph import (
    CandidateBundle,
    PortAudioGraph,
    ProofCode,
    ProofReport,
    compile_port_audio_graph,
    run_all_proofs,
)
from shared.audio_graph.proof import generated_forbidden_edges

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config/audio-graph.yaml"


def _load_graph() -> PortAudioGraph:
    return PortAudioGraph.from_yaml(CONFIG_PATH)


def _graph_data() -> dict[str, Any]:
    return _load_graph().model_dump(mode="python", by_alias=True)


def _mutated_graph(mutator) -> PortAudioGraph:
    data = deepcopy(_graph_data())
    mutator(data)
    return PortAudioGraph.model_validate(data)


def _codes(graph: PortAudioGraph) -> set[ProofCode]:
    return {violation.code for violation in run_all_proofs(graph).violations}


def _find_desired_link(data: dict[str, Any], *, source: str, target: str) -> dict[str, Any]:
    return next(
        edge
        for edge in data["desired_links"]
        if edge["source"] == source and edge["target"] == target
    )


def _load_generate_audio_graph_module() -> Any:
    script = REPO_ROOT / "scripts/generate-audio-graph"
    loader = SourceFileLoader("generate_audio_graph", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_valid_mk5_model_passes_and_uses_loudness_ssot() -> None:
    graph = _load_graph()
    bundle = compile_port_audio_graph(graph)

    assert bundle.proof_report.ok
    assert bundle.manifest["clock_rate"] == 44100
    unique_forbidden_keys = {
        edge.key
        for edge in (
            *graph.forbidden_links,
            *generated_forbidden_edges(graph),
            *graph.fence.known_blocked_links,
        )
    }
    raw_forbidden_count = (
        len(graph.forbidden_links)
        + len(generated_forbidden_edges(graph))
        + len(graph.fence.known_blocked_links)
    )
    assert bundle.manifest["forbidden_link_count"] == len(unique_forbidden_keys)
    assert bundle.manifest["forbidden_link_count"] < raw_forbidden_count
    constants = bundle.manifest["loudness_constants"]
    assert constants["egress_target_lufs_i"] == loudness.EGRESS_TARGET_LUFS_I
    assert constants["egress_true_peak_dbtp"] == loudness.EGRESS_TRUE_PEAK_DBTP
    assert constants["pre_norm_target_lufs_i"] == loudness.PRE_NORM_TARGET_LUFS_I
    assert constants["master_input_makeup_db"] == loudness.MASTER_INPUT_MAKEUP_DB
    assert constants["duck_depth_operator_voice_db"] == loudness.DUCK_DEPTH_OPERATOR_VOICE_DB
    assert constants["duck_depth_tts_db"] == loudness.DUCK_DEPTH_TTS_DB
    assert "pipewire/hapax-wet-broadcast_tts.conf" not in bundle.manifest["pipewire_files"]
    assert "pipewire/hapax-wet-broadcast-tts-wet-profile.conf" in bundle.manifest["pipewire_files"]
    assert graph.monitors["livestream_phones"].source == "hapax-broadcast-normalized:capture_FL"
    assert graph.monitors["livestream_phones_r"].source == "hapax-broadcast-normalized:capture_FR"
    assert graph.monitors["private_out5"].target.endswith(":playback_AUX4")
    assert graph.fence.default_sink == "hapax-pc-loudnorm-playback"


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("role-assistant:output_FL", "hapax-livestream-tap:playback_FL"),
        ("role-notification:output_FL", "hapax-broadcast-master-capture:input_FL"),
        ("hapax-pc-loudnorm-playback:output_FL", "hapax-broadcast-normalized-capture:input_FL"),
        ("m8-capture:output_FL", "hapax-obs-broadcast-remap-capture:input_FL"),
        (
            "role-assistant:output_FL",
            "alsa_output.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-output-0:playback_AUX10",
        ),
    ],
)
def test_private_notification_quarantine_unknown_paths_fail_closed(
    source: str,
    target: str,
) -> None:
    def mutate(data: dict[str, Any]) -> None:
        if source.startswith("m8-capture"):
            data["nodes"]["m8-capture"]["ports"]["output_FL"]["exposure"] = "unknown"
        data["desired_links"].append({"source": source, "target": target})

    codes = _codes(_mutated_graph(mutate))

    assert ProofCode.PF1_ALLOWLIST_ROUTE_CLASS in codes
    assert ProofCode.PF10_PRIVACY_REACHABILITY in codes


def test_limiter_absent_fails_obs_path_proof() -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["nodes"]["hapax-broadcast-normalized"]["required_effects"] = []

    assert ProofCode.LIMITER_OBS_PATH in _codes(_mutated_graph(mutate))


def test_operator_mic_missing_dry_safe_fails_never_drop_speech() -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["sources"]["operator_mic"]["dry_safe"] = False

    assert ProofCode.NEVER_DROP_SPEECH in _codes(_mutated_graph(mutate))


def test_desired_forbidden_overlap_fails() -> None:
    def mutate(data: dict[str, Any]) -> None:
        edge = _find_desired_link(
            data,
            source="role-assistant:output_FL",
            target="hapax-wet-assistant-private:input_FL",
        )
        data["forbidden_links"].append(edge)

    assert ProofCode.DESIRED_FORBIDDEN_OVERLAP in _codes(_mutated_graph(mutate))


def test_plugin_control_default_out_of_bounds_fails() -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["wet_profiles"]["program_subtle"]["controls"][0]["default"] = 99

    assert ProofCode.PLUGIN_CONTROL_RANGE in _codes(_mutated_graph(mutate))


def test_default_sink_physical_eligibility_fails() -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["devices"]["motu_mk5"]["ports"]["phones_l"]["default_sink_eligible"] = True

    assert ProofCode.PF7_DEFAULT_SINK_FAIL_CLOSED in _codes(_mutated_graph(mutate))


def test_gain_budget_over_24_db_fails() -> None:
    def mutate(data: dict[str, Any]) -> None:
        edge = _find_desired_link(
            data,
            source="hapax-mic-rode-playback:output_MONO",
            target="hapax-livestream-tap:playback_FL",
        )
        edge["gain_db"] = 25.0

    assert ProofCode.PF11_GAIN_BUDGET in _codes(_mutated_graph(mutate))


def test_gain_budget_checks_alternate_channel_paths() -> None:
    def mutate(data: dict[str, Any]) -> None:
        edge = _find_desired_link(
            data,
            source="hapax-mic-rode-playback:output_MONO",
            target="hapax-livestream-tap:playback_FR",
        )
        edge["gain_db"] = 25.0

    assert ProofCode.PF11_GAIN_BUDGET in _codes(_mutated_graph(mutate))


def test_m8_double_feed_to_voice_wet_fails() -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["desired_links"].append(
            {
                "source": "m8-capture:output_FL",
                "target": "hapax-voice-wet-capture:input_FL",
            }
        )

    codes = _codes(_mutated_graph(mutate))

    assert ProofCode.PF12_KNOWN_LEAK_VECTORS in codes
    assert ProofCode.DESIRED_FORBIDDEN_OVERLAP in codes


def test_monitor_port_must_be_pinned() -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["nodes"]["hapax-livestream-tap"]["ports"]["monitor_FL"]["dont_reconnect"] = False

    assert ProofCode.PF9_MONITOR_PIN in _codes(_mutated_graph(mutate))


def test_capture_port_must_be_pinned() -> None:
    def mutate(data: dict[str, Any]) -> None:
        data["nodes"]["hapax-mic-rode-capture"]["ports"]["input_MONO"]["autoconnect"] = True

    assert ProofCode.PF8_CAPTURE_PIN in _codes(_mutated_graph(mutate))


def test_source_cannot_use_software_wet_and_hardware_insert() -> None:
    data = _graph_data()
    data["sources"]["music_bed"]["hardware_insert"] = "s4_livestream_lane"
    with pytest.raises(ValidationError):
        PortAudioGraph.model_validate(data)


def test_role_default_bus_cross_reference_is_validated() -> None:
    data = _graph_data()
    data["roles"]["broadcast_voice"]["default_bus"] = "bus.missing"
    with pytest.raises(ValidationError, match="default_bus"):
        PortAudioGraph.model_validate(data)


def test_monitor_cross_reference_is_validated() -> None:
    data = _graph_data()
    data["monitors"]["livestream_phones_r"]["target"] = "missing-node:playback_AUX11"
    with pytest.raises(ValidationError, match="monitor"):
        PortAudioGraph.model_validate(data)


def test_candidate_emit_writes_only_to_shadow_dir(tmp_path: Path) -> None:
    candidate_dir = tmp_path / "candidate"
    result = subprocess.run(
        ["scripts/generate-audio-graph", "--emit-candidate", str(candidate_dir)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (candidate_dir / "hapax/audio-link-map.conf").exists()
    assert (candidate_dir / "hapax/audio-forbidden-links.conf").exists()
    assert (candidate_dir / "hapax/audio-privacy-proof.json").exists()
    assert (candidate_dir / "wireplumber/98-hapax-link-deny.lua").exists()


def test_candidate_emit_rejects_artifact_key_escape(tmp_path: Path) -> None:
    module = _load_generate_audio_graph_module()
    bundle = CandidateBundle(
        proof_report=ProofReport(),
        hapax_confs={"../escape.conf": "bad"},
    )
    with pytest.raises(ValueError, match="escapes output dir"):
        module._write_candidate_dir(bundle, tmp_path / "candidate")


def test_candidate_emit_rejects_duplicate_artifact_keys(tmp_path: Path) -> None:
    module = _load_generate_audio_graph_module()
    bundle = CandidateBundle(
        proof_report=ProofReport(),
        pipewire_confs={"same.conf": "a"},
        wireplumber_confs={"same.conf": "b"},
    )
    with pytest.raises(ValueError, match="path collision"):
        module._write_candidate_dir(bundle, tmp_path / "candidate")


def test_candidate_emit_refuses_live_config_path() -> None:
    result = subprocess.run(
        ["scripts/generate-audio-graph", "--emit-candidate", str(Path.home() / ".config/hapax")],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "refusing to emit candidate artifacts" in result.stderr


def test_check_cli_exits_zero_on_valid_model() -> None:
    result = subprocess.run(
        ["scripts/generate-audio-graph", "--check"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert '"ok": true' in result.stdout

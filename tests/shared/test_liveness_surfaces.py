"""Conformance for support-only liveness surface declarations."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from shared.liveness import (
    ALIVE,
    HELD_NOT_ADMITTED,
    STALLED,
    LivenessWatchdog,
    classify,
    read_heartbeat,
)
from shared.liveness_surfaces import (
    DEPLOY_LAG_BUDGET_S,
    LANE_PROGRESS_STALL_T_S,
    deploy_heartbeat,
    deploy_op_id,
    deploy_spec,
    lane_progress_heartbeat,
    lane_progress_op_id,
    lane_progress_spec,
    legacy_deploy_stalled,
    legacy_lane_progress_stalled,
    legacy_reaper_stalled,
    proof_surface_specs,
    reaper_heartbeat,
    reaper_op_id,
    reaper_spec,
    register_proof_surfaces,
)

NOW = 10_000.0


def test_heartbeat_adapters_build_exact_support_observations(tmp_path: Path) -> None:
    lane_progress_heartbeat("eps", output_mtime=1234.0, output_lines=77, beat_dir=tmp_path)
    lane = read_heartbeat(lane_progress_op_id("eps"), beat_dir=tmp_path)
    assert lane is not None and lane.ts == 1234.0 and lane.token == "77"

    reaper_heartbeat("beta", last_progress_ts=500.0, progress_token=9, beat_dir=tmp_path)
    reaper = read_heartbeat(reaper_op_id("beta"), beat_dir=tmp_path)
    assert reaper is not None and reaper.ts == 500.0 and reaper.token == "9"

    deploy_heartbeat(last_deployed_ts=42.0, last_deployed_sha="abc123", beat_dir=tmp_path)
    deploy = read_heartbeat(deploy_op_id(), beat_dir=tmp_path)
    assert deploy is not None and deploy.ts == 42.0 and deploy.token == "abc123"


def test_surface_specs_use_symbolic_adapters_not_argv() -> None:
    lane = lane_progress_spec("eps")
    reaper = reaper_spec("eps")
    deploy = deploy_spec()
    assert lane.adapter is not None
    assert lane.adapter.action_kind == "lane.resume"
    assert lane.adapter.target_id == "eps"
    assert reaper.adapter is not None and reaper.adapter.action_kind == "lane.reap"
    assert deploy.adapter is not None and deploy.adapter.action_kind == "deploy.rearm"
    for spec in (lane, reaper, deploy):
        assert not hasattr(spec, "recovery_cmd")
        assert not hasattr(spec.adapter, "argv")


@pytest.mark.parametrize(
    ("age", "tau"),
    [(0, 1800), (100, 1800), (1800, 1800), (1801, 1800), (5000, 2000)],
)
def test_reaper_classification_matches_legacy_support_predicate(age: float, tau: float) -> None:
    from shared.liveness import Heartbeat

    heartbeat = Heartbeat(reaper_op_id("beta"), ts=NOW - age, token="T")
    verdict = classify(
        reaper_spec("beta"),
        heartbeat,
        prev_token="T",
        now=NOW,
        threshold_s=tau,
    )
    assert (verdict.status == STALLED) == legacy_reaper_stalled(age, tau)


@pytest.mark.parametrize("age", [0, 500, 900, 901, 5000])
def test_lane_classification_matches_legacy_support_predicate(age: float) -> None:
    from shared.liveness import Heartbeat

    heartbeat = Heartbeat(lane_progress_op_id("eps"), ts=NOW - age, token="100")
    verdict = classify(
        lane_progress_spec("eps"),
        heartbeat,
        prev_token="100",
        now=NOW,
        threshold_s=LANE_PROGRESS_STALL_T_S,
    )
    assert (verdict.status == STALLED) == legacy_lane_progress_stalled(NOW - age, NOW)


@pytest.mark.parametrize("age", [0, 900, 1800, 1801, 9999])
def test_deploy_classification_matches_legacy_support_predicate(age: float) -> None:
    from shared.liveness import Heartbeat

    heartbeat = Heartbeat(deploy_op_id(), ts=NOW - age, token="sha")
    verdict = classify(
        deploy_spec(),
        heartbeat,
        prev_token="sha",
        now=NOW,
        threshold_s=DEPLOY_LAG_BUDGET_S,
    )
    assert (verdict.status == STALLED) == legacy_deploy_stalled(NOW - age, NOW)


def test_progressing_token_is_alive_even_past_threshold() -> None:
    from shared.liveness import Heartbeat

    heartbeat = Heartbeat(reaper_op_id("beta"), ts=NOW - 5000, token="200")
    verdict = classify(
        reaper_spec("beta"),
        heartbeat,
        prev_token="100",
        now=NOW,
        threshold_s=1800.0,
    )
    assert verdict.status == ALIVE
    assert legacy_reaper_stalled(5000, 1800.0) is True


def test_proof_surface_specs_are_pure_and_complete() -> None:
    specs = proof_surface_specs(["beta", "eps"])
    assert {spec.op_id for spec in specs} == {
        "lane:beta:progress",
        "lane:eps:progress",
        "reaper:beta",
        "reaper:eps",
        "deploy:post-merge",
    }
    assert all(spec.adapter is not None for spec in specs)


def test_register_proof_surfaces_persists_no_commands(tmp_path: Path) -> None:
    specs = register_proof_surfaces(["beta"], registry_dir=tmp_path)
    assert len(specs) == 3
    for path in tmp_path.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "recovery_cmd" not in text
        assert "scripts/" not in text
        assert "adapter_id" in text


def test_stale_deploy_projects_hold_and_executes_nothing(tmp_path: Path) -> None:
    registry, beats = tmp_path / "registry", tmp_path / "beats"
    from shared.liveness import register

    register(deploy_spec(), registry_dir=registry)
    deploy_heartbeat(last_deployed_ts=0.0, last_deployed_sha="abc", beat_dir=beats)
    result = LivenessWatchdog(
        registry_dir=registry,
        beat_dir=beats,
        now_fn=lambda: 5000.0,
    ).scan()[0]
    assert result.status == STALLED
    assert result.effect_state == HELD_NOT_ADMITTED
    assert result.recovered is False
    assert result.hold is not None
    assert result.hold.operation == "deploy.rearm"


def test_main_list_is_read_only() -> None:
    from shared import liveness_surfaces as surfaces

    with mock.patch.object(surfaces, "register_proof_surfaces") as register_mock:
        assert surfaces.main(["list", "beta"]) == 0
    register_mock.assert_not_called()


def test_main_install_registers_support_only_descriptors() -> None:
    from shared import liveness_surfaces as surfaces

    with mock.patch.object(surfaces, "register_proof_surfaces", return_value=[]) as register_mock:
        assert surfaces.main(["install", "beta", "eps"]) == 0
    register_mock.assert_called_once_with(["beta", "eps"])


def test_unknown_command_returns_2() -> None:
    from shared import liveness_surfaces as surfaces

    assert surfaces.main(["bogus"]) == 2


def test_module_contains_no_executable_surface_registry() -> None:
    source = Path(__file__).resolve().parents[2] / "shared" / "liveness_surfaces.py"
    text = source.read_text(encoding="utf-8")
    assert "SURFACE_RECOVERY" not in text
    assert "resume_cmd" not in text
    assert "kill_cmd" not in text
    assert "rearm_cmd" not in text
    assert "scripts/hapax-" not in text

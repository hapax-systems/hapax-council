"""Regression tests for the migrated surfaces — the substrate's stalled/quiet
verdict must equal each legacy bespoke watchdog's decision (behavior-preserving
cutover). Self-contained (no shared conftest).
"""

from __future__ import annotations

import types
from pathlib import Path
from unittest import mock

import pytest

from shared.liveness import (
    ALIVE,
    STALLED,
    Heartbeat,
    LivenessWatchdog,
    classify,
    read_heartbeat,
    register,
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
    reaper_heartbeat,
    reaper_op_id,
    reaper_spec,
    register_proof_surfaces,
)
from shared.recovery_governor import RecoveryGovernor, RecoveryParams

NOW = 10_000.0


# ── heartbeat adapters build the right (ts, token) ───────────────────────────


def test_lane_progress_heartbeat_adapter(tmp_path: Path) -> None:
    lane_progress_heartbeat("eps", output_mtime=1234.0, output_lines=77, beat_dir=tmp_path)
    hb = read_heartbeat(lane_progress_op_id("eps"), beat_dir=tmp_path)
    assert hb is not None and hb.ts == 1234.0 and hb.token == "77"


def test_reaper_heartbeat_adapter(tmp_path: Path) -> None:
    reaper_heartbeat("beta", last_progress_ts=500.0, progress_token=9, beat_dir=tmp_path)
    hb = read_heartbeat(reaper_op_id("beta"), beat_dir=tmp_path)
    assert hb is not None and hb.ts == 500.0 and hb.token == "9"


def test_deploy_heartbeat_adapter(tmp_path: Path) -> None:
    deploy_heartbeat(last_deployed_ts=42.0, last_deployed_sha="abc123", beat_dir=tmp_path)
    hb = read_heartbeat(deploy_op_id(), beat_dir=tmp_path)
    assert hb is not None and hb.ts == 42.0 and hb.token == "abc123"


# ── classification equivalence: substrate verdict == legacy decision ─────────


@pytest.mark.parametrize(
    "age,tau", [(0, 1800), (100, 1800), (1800, 1800), (1801, 1800), (5000, 2000)]
)
def test_reaper_classification_matches_legacy(age: float, tau: float) -> None:
    hb = Heartbeat(reaper_op_id("beta"), ts=NOW - age, token="T", meta={})
    v = classify(reaper_spec("beta", kill_cmd=["x"]), hb, prev_token="T", now=NOW, threshold_s=tau)
    assert (v.status == STALLED) == legacy_reaper_stalled(age, tau)


@pytest.mark.parametrize("mtime_age", [0, 500, 900, 901, 5000])
def test_lane_progress_classification_matches_legacy(mtime_age: float) -> None:
    hb = Heartbeat(lane_progress_op_id("eps"), ts=NOW - mtime_age, token="100", meta={})
    v = classify(
        lane_progress_spec("eps", resume_cmd=["x"]),
        hb,
        prev_token="100",
        now=NOW,
        threshold_s=LANE_PROGRESS_STALL_T_S,
    )
    assert (v.status == STALLED) == legacy_lane_progress_stalled(NOW - mtime_age, NOW)


@pytest.mark.parametrize("deploy_age", [0, 900, 1800, 1801, 9999])
def test_deploy_classification_matches_legacy(deploy_age: float) -> None:
    hb = Heartbeat(deploy_op_id(), ts=NOW - deploy_age, token="sha", meta={})
    v = classify(
        deploy_spec(rearm_cmd=["x"]),
        hb,
        prev_token="sha",
        now=NOW,
        threshold_s=DEPLOY_LAG_BUDGET_S,
    )
    assert (v.status == STALLED) == legacy_deploy_stalled(NOW - deploy_age, NOW)


# ── the substrate's strict improvement: progressing token is never recovered ──


def test_reaper_progressing_token_not_reaped_even_past_tau() -> None:
    # legacy should_reap is age-only and WOULD reap here; the substrate sees the
    # progress token advance (100→200) and classifies alive — strictly safer.
    hb = Heartbeat(reaper_op_id("beta"), ts=NOW - 5000, token="200", meta={})
    v = classify(
        reaper_spec("beta", kill_cmd=["x"]), hb, prev_token="100", now=NOW, threshold_s=1800.0
    )
    assert v.status == ALIVE
    assert legacy_reaper_stalled(5000, 1800.0) is True


# ── registration + end-to-end recovery under the legacy stall condition ──────


def test_register_proof_surfaces_registers_all(tmp_path: Path) -> None:
    specs = register_proof_surfaces(["beta", "eps"], registry_dir=tmp_path)
    op_ids = {s.op_id for s in specs}
    assert op_ids == {
        "lane:beta:progress",
        "lane:eps:progress",
        "reaper:beta",
        "reaper:eps",
        "deploy:post-merge",
    }
    # role is appended to the recovery argv so the entrypoint knows its target
    lane_beta = next(s for s in specs if s.op_id == "lane:beta:progress")
    assert lane_beta.recovery_cmd[-1] == "beta"


class _RecordingExec:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> bool:
        self.calls.append(list(cmd))
        return True


def _governor(tmp_path: Path, *, now: float) -> RecoveryGovernor:
    return RecoveryGovernor(
        params=RecoveryParams(bucket_burst=10, bucket_rate=10.0),
        state_dir=tmp_path / "gov",
        now_fn=lambda: now,
        admission_fn=lambda: types.SimpleNamespace(state="open"),
        psi_readable_fn=lambda: True,
        jitter_fn=lambda d: d,
        notify_fn=lambda *a, **k: None,
        mint_fn=lambda *a, **k: None,
    )


def test_deploy_surface_end_to_end_recovers_when_stale(tmp_path: Path) -> None:
    reg, beats = tmp_path / "registry", tmp_path / "beats"
    register(deploy_spec(rearm_cmd=["rearm"]), registry_dir=reg)
    deploy_heartbeat(last_deployed_ts=0.0, last_deployed_sha="abc", beat_dir=beats)  # silent 5000s
    execer = _RecordingExec()
    wd = LivenessWatchdog(
        registry_dir=reg,
        beat_dir=beats,
        scan_state_path=tmp_path / "s.json",
        governor=_governor(tmp_path, now=5000.0),
        now_fn=lambda: 5000.0,
        exec_fn=execer,
        ledger_fn=lambda e: None,
        tau_fn=lambda lineage: 1800.0,
    )
    res = wd.scan()
    assert res[0].status == STALLED  # age 5000 > budget 1800
    assert execer.calls == [["rearm"]]
    # and the legacy alarm agrees on the same input
    assert legacy_deploy_stalled(0.0, 5000.0) is True


# ── CLI routing ──────────────────────────────────────────────────────────────


def test_main_install_routes_to_register() -> None:
    from shared import liveness_surfaces as ls

    with mock.patch.object(ls, "register_proof_surfaces", return_value=[]) as m:
        assert ls.main(["install", "beta", "eps"]) == 0
        m.assert_called_once_with(["beta", "eps"])


def test_main_beat_deploy_routes_to_adapter() -> None:
    from shared import liveness_surfaces as ls

    with mock.patch.object(ls, "deploy_heartbeat") as m:
        assert ls.main(["beat-deploy", "1700.0", "abc123"]) == 0
        m.assert_called_once_with(last_deployed_ts=1700.0, last_deployed_sha="abc123")


def test_main_unknown_command_returns_2() -> None:
    from shared import liveness_surfaces as ls

    assert ls.main(["bogus"]) == 2

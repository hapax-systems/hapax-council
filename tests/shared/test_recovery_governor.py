"""Recovery pressure stays support-only until the execution gate admits it."""

from __future__ import annotations

import json
import types
from pathlib import Path

from shared import recovery_governor as rg


def _gov(tmp: Path, *, state: str = "open", readable: bool = True, **kwargs):
    defaults = {
        "state_dir": tmp,
        "admission_fn": lambda: types.SimpleNamespace(state=state),
        "psi_readable_fn": lambda: readable,
        "critical_validator_fn": lambda target: True,
        "mode": "enforce",
    }
    defaults.update(kwargs)
    return rg.RecoveryGovernor(**defaults)


def test_aimd_delay_and_pressure_parameters_remain_pure() -> None:
    base = rg.RecoveryParams()
    assert [rg.aimd_backoff_delay(i, base) for i in range(5)] == [
        30.0,
        60.0,
        120.0,
        240.0,
        480.0,
    ]
    assert rg.aimd_backoff_delay(7, base) == base.cap_s
    assert rg.params_for_state("paced", base).bucket_rate == base.bucket_rate * 0.5
    assert rg.params_for_state("closed", base).suspend_noncritical
    assert rg.params_for_state("degraded", base).bucket_burst == base.degraded_burst


def test_token_bucket_is_a_pure_support_calculation() -> None:
    params = rg.RecoveryParams()
    state = rg.BucketState(tokens=float(params.bucket_burst), updated=1000.0)
    outcomes: list[bool] = []
    for _ in range(5):
        allowed, state = rg.bucket_take(
            state,
            1000.0,
            rate=params.bucket_rate,
            burst=params.bucket_burst,
        )
        outcomes.append(allowed)
    assert outcomes == [True, True, True, False, False]


def test_converge_caps_are_modulation_not_admission() -> None:
    assert rg.converge_action_cap("open") == 6
    assert rg.converge_action_cap("paced") == 2
    assert rg.converge_action_cap("closed") == 0
    assert rg.converge_action_cap("closed", critical_pending=True) == 1


def test_open_pressure_still_holds_without_execution_chain(tmp_path: Path) -> None:
    assessment = _gov(tmp_path, state="open").permit("lane:beta", now=0.0)
    assert assessment.modulation_allows
    assert not assessment.permitted
    assert assessment.reason == rg.HOLD_REASON
    assert assessment.authority_ceiling == rg.AUTHORITY_CEILING


def test_all_pressure_states_hold_without_execution_chain(tmp_path: Path) -> None:
    for state in ("open", "paced", "closed", "degraded"):
        assessment = _gov(tmp_path / state, state=state).permit("lane:beta", now=0.0)
        assert not assessment.permitted
        assert assessment.reason == rg.HOLD_REASON


def test_critical_signal_cannot_mint_permission(tmp_path: Path) -> None:
    assessment = _gov(tmp_path, state="closed").permit(
        "coordinator", critical=True, now=0.0
    )
    assert assessment.critical
    assert assessment.modulation_allows
    assert not assessment.permitted


def test_disable_environment_cannot_bypass_hold(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(rg.OFF_ENV, "1")
    assessment = _gov(tmp_path, state="open").permit("lane:beta")
    assert not assessment.permitted
    assert assessment.reason == rg.HOLD_REASON


def test_unknown_or_failed_signals_degrade_and_hold(tmp_path: Path) -> None:
    def broken_signal() -> bool:
        raise RuntimeError("hostile signal failure")

    broken = _gov(tmp_path / "broken", psi_readable_fn=broken_signal)
    unknown = _gov(tmp_path / "unknown", state="impossible")
    for governor in (broken, unknown):
        assessment = governor.permit("lane:x")
        assert assessment.state == "degraded"
        assert not assessment.permitted


def test_default_pressure_read_never_persists_hysteresis(monkeypatch) -> None:
    from shared import sdlc_pressure_gate

    def forbidden_store(*args, **kwargs) -> None:
        raise AssertionError("pressure assessment attempted persistence")

    monkeypatch.setattr(sdlc_pressure_gate, "_store_state", forbidden_store)
    assessment = rg.RecoveryGovernor(psi_readable_fn=lambda: True).permit("lane:x")
    assert not assessment.permitted


def test_effect_collaborators_are_never_called(tmp_path: Path) -> None:
    calls: list[str] = []

    governor = _gov(
        tmp_path,
        notify_fn=lambda *args, **kwargs: calls.append("notify"),
        mint_fn=lambda *args, **kwargs: calls.append("mint"),
        shielded_fn=lambda: calls.append("shield") or True,
        jitter_fn=lambda delay: calls.append("jitter") or delay,
    )
    governor.permit("lane:x", critical=True)
    governor.record_outcome("lane:x", success=False)
    governor.permit_batch(["lane:x", "lane:y"])
    assert calls == []


def test_permit_record_and_batch_never_create_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "must-not-exist"
    governor = _gov(state_dir)
    assert not governor.permit("lane:x").permitted
    assert all(not item.permitted for item in governor.permit_batch(["lane:y", "lane:z"]))
    governor.record_outcome("lane:x", success=False)
    assert governor.backoff_entry("lane:x") == rg.BackoffEntry(0.0, 0, "")
    assert governor.failopen_count() == 0
    assert not state_dir.exists()


def test_main_effect_verbs_visibly_hold_and_do_no_io(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(rg.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    governor = _gov(tmp_path / "state")

    for argv in (
        ["--permit", "lane:x"],
        ["--permit-batch", "lane:x", "lane:y"],
        ["--record", "lane:x", "fail"],
        ["--kill", "12345"],
    ):
        assert rg.main(argv, governor=governor) == rg.BACKOFF
        assert "HOLD" in capsys.readouterr().err

    assert killed == []
    assert not (tmp_path / "state").exists()


def test_main_state_and_stats_are_read_only(tmp_path: Path, capsys) -> None:
    state_dir = tmp_path / "state"
    governor = _gov(state_dir, state="paced")
    assert rg.main(["--state"], governor=governor) == 1
    assert capsys.readouterr().out.strip() == "paced"

    assert rg.main(["--stats"], governor=governor) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats == {
        "authority_ceiling": rg.AUTHORITY_CEILING,
        "effective_mode": "support",
        "effects_authorized": False,
        "state": "paced",
    }
    assert not state_dir.exists()

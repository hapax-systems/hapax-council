"""Conformance: modulation cannot become recovery authority under load."""

from __future__ import annotations

import types
from pathlib import Path

from shared import recovery_governor as rg

N_TARGETS = 50


def _governor(tmp: Path, box: dict[str, str], *, readable: bool = True):
    return rg.RecoveryGovernor(
        state_dir=tmp / "state",
        admission_fn=lambda: types.SimpleNamespace(state=box["state"]),
        psi_readable_fn=lambda: readable,
        critical_validator_fn=lambda target: True,
        mode="enforce",
    )


def test_open_modulation_does_not_authorize_a_recovery_wave(tmp_path: Path) -> None:
    governor = _governor(tmp_path, {"state": "open"})
    assessments = governor.permit_batch([f"lane:{index}" for index in range(N_TARGETS)])

    assert all(item.modulation_allows for item in assessments)
    assert sum(item.permitted for item in assessments) == 0
    assert all(item.reason == rg.HOLD_REASON for item in assessments)
    assert not (tmp_path / "state").exists()


def test_pressure_oscillation_never_changes_the_authority_ceiling(tmp_path: Path) -> None:
    box = {"state": "open"}
    governor = _governor(tmp_path, box)
    observed = []

    for state in ("open", "paced", "closed", "degraded", "open"):
        box["state"] = state
        assessment = governor.permit("lane:beta", critical=True)
        observed.append((assessment.state, assessment.permitted, assessment.authority_ceiling))

    assert [state for state, _, _ in observed] == [
        "open",
        "paced",
        "closed",
        "degraded",
        "open",
    ]
    assert all(not permitted for _, permitted, _ in observed)
    assert all(ceiling == rg.AUTHORITY_CEILING for _, _, ceiling in observed)
    assert not (tmp_path / "state").exists()


def test_unreadable_pressure_is_not_a_fail_open_path(tmp_path: Path) -> None:
    governor = _governor(tmp_path, {"state": "open"}, readable=False)
    assessments = [governor.permit(f"lane:{index}") for index in range(N_TARGETS)]

    assert all(item.state == "degraded" for item in assessments)
    assert all(not item.permitted for item in assessments)
    assert not (tmp_path / "state").exists()


def test_recorded_failures_cannot_mint_or_notify(tmp_path: Path) -> None:
    effects: list[str] = []
    governor = rg.RecoveryGovernor(
        state_dir=tmp_path / "state",
        admission_fn=lambda: types.SimpleNamespace(state="open"),
        psi_readable_fn=lambda: True,
        notify_fn=lambda *args, **kwargs: effects.append("notify"),
        mint_fn=lambda *args, **kwargs: effects.append("mint"),
        mode="enforce",
    )

    for attempt in range(rg.RecoveryParams().max_attempts * 4):
        governor.record_outcome("lane:broken", success=False, now=float(attempt))

    assert effects == []
    assert governor.backoff_entry("lane:broken").attempt == 0
    assert not (tmp_path / "state").exists()

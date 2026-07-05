"""Env-gate policy for ``HAPAX_INTAKE_FIT_BLEND`` — the task-spec ``[0.0, 0.5)`` clamp.

These tests pin the *deployment policy* (which blends are reachable from the environment),
not the pure ``composite_rank_key`` arithmetic (covered by ``test_intake_fit_scorer.py``).
The clamp is the safety rail: a misconfigured ``HAPAX_INTAKE_FIT_BLEND=50`` cannot distort
the rank-key, and a negative or non-finite value cannot reach the scheduler. ``0.0`` keeps
the plan byte-identical to pure WSJF — the default-off golden guarantee.

Scope: ``agents.coordinator.core._intake_fit_blend``. The cc-task acceptance criteria
(``cc-task-sdlc-router-intake-shadow-20260704``) bound the blend to ``[0.0, 0.5)``; this
file is what makes that criterion machine-checked (closes the codex-1/glm-1 finding that the
knob was finite-checked but not clamped).
"""

from __future__ import annotations

import math

import pytest

from agents.coordinator.core import _intake_fit_blend


@pytest.fixture
def blend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear HAPAX_INTAKE_FIT_BLEND so each test states its own input explicitly."""
    monkeypatch.delenv("HAPAX_INTAKE_FIT_BLEND", raising=False)


def test_unset_falls_back_to_zero(blend_env: None) -> None:
    # Unset => default-off => byte-identical plan (the golden guarantee).
    assert _intake_fit_blend() == 0.0


def test_explicit_zero_passes_through(blend_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_INTAKE_FIT_BLEND", "0.0")
    assert _intake_fit_blend() == 0.0


def test_typical_active_value_passes_through(
    blend_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 0.25 is the task-spec's typical active shadow value — inside [0.0, 0.5), unchanged.
    monkeypatch.setenv("HAPAX_INTAKE_FIT_BLEND", "0.25")
    assert _intake_fit_blend() == 0.25


def test_negative_clamps_to_zero(blend_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # A negative blend is unreachable from the env (the pure-fn contract is tested separately).
    monkeypatch.setenv("HAPAX_INTAKE_FIT_BLEND", "-1.0")
    assert _intake_fit_blend() == 0.0


def test_ceil_exclusive_saturates_to_just_below(
    blend_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # [0.0, 0.5) is half-open: 0.5 itself is out of range -> saturate to the largest float < 0.5.
    monkeypatch.setenv("HAPAX_INTAKE_FIT_BLEND", "0.5")
    clamped = _intake_fit_blend()
    assert clamped < 0.5
    assert clamped == math.nextafter(0.5, 0.0)


def test_oversize_clamps_down(blend_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # A gross misconfiguration (50.0) cannot distort the rank-key — the safety rail holds.
    monkeypatch.setenv("HAPAX_INTAKE_FIT_BLEND", "50.0")
    clamped = _intake_fit_blend()
    assert clamped < 0.5
    assert clamped == math.nextafter(0.5, 0.0)


def test_nan_falls_back_to_zero(blend_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # A NaN would poison the scheduler's max() sort; it must never reach the rank-key.
    monkeypatch.setenv("HAPAX_INTAKE_FIT_BLEND", "nan")
    assert _intake_fit_blend() == 0.0


def test_inf_falls_back_to_zero(blend_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_INTAKE_FIT_BLEND", "inf")
    assert _intake_fit_blend() == 0.0


def test_non_numeric_falls_back_to_zero(blend_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # A garbage value is honest-DARK, never raises.
    monkeypatch.setenv("HAPAX_INTAKE_FIT_BLEND", "not-a-number")
    assert _intake_fit_blend() == 0.0

"""Reverie governance — VetoChain + FallbackChain for visual actuation.

Structural mirror of Daimonion's governance chains. Determines whether
visual expression should proceed, be suppressed, or be reduced based
on consent state, resource availability, and system health.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("reverie.governance")

CONSENT_STATE = Path("/dev/shm/hapax-daimonion/consent-state.json")
GPU_STATE = Path("/proc/driver/nvidia/gpus")  # existence check only


class VisualVeto:
    """A single veto condition for visual actuation."""

    def __init__(self, name: str, check: Any) -> None:
        self.name = name
        self._check = check

    def evaluate(self, ctx: dict[str, Any]) -> str | None:
        """Return reason string if vetoed, None if allowed."""
        return self._check(ctx)


class VisualVetoChain:
    """Deny-wins constraint evaluation for visual expression.

    Monotonic: adding vetoes only restricts, never expands permissions.
    Mirrors Daimonion's VetoChain semantics.
    """

    def __init__(self, vetoes: list[VisualVeto] | None = None) -> None:
        self._vetoes = vetoes or []

    def add(self, veto: VisualVeto) -> None:
        self._vetoes.append(veto)

    def evaluate(self, ctx: dict[str, Any]) -> tuple[bool, str | None]:
        """Evaluate all vetoes. Returns (allowed, reason)."""
        for veto in self._vetoes:
            reason = veto.evaluate(ctx)
            if reason is not None:
                return False, f"{veto.name}: {reason}"
        return True, None


def _check_consent(ctx: dict[str, Any]) -> str | None:
    """Veto if consent is refused (guest present, no contract)."""
    consent_phase = ctx.get("consent_phase", "no_guest")
    if consent_phase == "consent_refused":
        return "consent refused — visual expression suppressed"
    return None


def _check_gpu(ctx: dict[str, Any]) -> str | None:
    """Veto if GPU is unavailable."""
    pipeline_dir = Path("/dev/shm/hapax-imagination/pipeline")
    if not pipeline_dir.exists():
        return "imagination pipeline directory missing"
    return None


def _check_stimmung_critical(ctx: dict[str, Any]) -> str | None:
    """Veto heavy visual effects under critical system health."""
    stance = ctx.get("stance", "nominal")
    if stance == "critical":
        return "system health critical — visual expression suspended"
    return None


def build_default_veto_chain() -> VisualVetoChain:
    """Build the standard visual governance veto chain."""
    chain = VisualVetoChain()
    chain.add(VisualVeto("consent", _check_consent))
    chain.add(VisualVeto("gpu", _check_gpu))
    chain.add(VisualVeto("health", _check_stimmung_critical))
    return chain


def read_consent_phase() -> str:
    """Read current consent phase from SHM."""
    try:
        if CONSENT_STATE.exists():
            data = json.loads(CONSENT_STATE.read_text())
            return data.get("phase", "no_guest")
    except (OSError, json.JSONDecodeError):
        pass
    return "no_guest"


def guest_reduction_factor(consent_phase: str) -> float:
    """Compute visual intensity reduction when guest is present.

    Applies to all visual chain deltas — Reverie stays visible but
    less intense when a guest is in the room.
    """
    if consent_phase in ("consent_pending", "guest_detected"):
        return 0.6
    if consent_phase == "consent_refused":
        return 0.0  # veto should catch this, but defense in depth
    return 1.0

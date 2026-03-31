"""Reverie governance — VetoChain for visual actuation using shared primitives.

Structural peer of Daimonion's governance chains. Uses shared VetoChain[SystemContext]
for full audit trail, axiom linkage, and | composition.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agents._capability import SystemContext
from agents._governance.primitives import Veto, VetoChain

log = logging.getLogger("reverie.governance")

CONSENT_STATE = Path("/dev/shm/hapax-daimonion/consent-state.json")


def build_reverie_veto_chain() -> VetoChain[SystemContext]:
    """Build the standard visual governance veto chain on shared primitives."""
    return VetoChain(
        [
            Veto(
                "consent_refused",
                lambda ctx: ctx.consent_state.get("phase") != "consent_refused",
                axiom="interpersonal_transparency",
                description="Suppress visual expression when consent refused",
            ),
            Veto(
                "consent_pending",
                lambda ctx: ctx.consent_state.get("phase") != "consent_pending",
                axiom="interpersonal_transparency",
                description="Suppress during consent negotiation window",
            ),
            Veto(
                "gpu_unavailable",
                lambda _ctx: Path("/dev/shm/hapax-imagination/pipeline").exists(),
                description="Imagination pipeline directory must exist",
            ),
            Veto(
                "health_critical",
                lambda ctx: ctx.stimmung_stance != "critical",
                description="Suspend visual expression under critical health",
            ),
        ]
    )


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
    """Compute visual intensity reduction when guest is present."""
    if consent_phase in ("consent_pending", "guest_detected"):
        return 0.6
    if consent_phase == "consent_refused":
        return 0.0
    return 1.0

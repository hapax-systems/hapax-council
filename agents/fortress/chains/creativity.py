"""Creativity governance chain (Layer 3.5 in subsumption).

Produces creative/aesthetic actions when safety conditions are met.
Gated by Maslow hierarchy, neuroception, and creativity suppression.
"""

from __future__ import annotations

from agents.fortress.creativity import (
    creativity_available,
    maslow_gate,
    neuroception_safe,
)
from agents.fortress.schema import FullFortressState
from agents.hapax_voice.governance import (
    Candidate,
    FallbackChain,
    Selected,
    Veto,
    VetoChain,
    VetoResult,
)


def _maslow_satisfied(state: FullFortressState) -> bool:
    return maslow_gate(state)


def _neuroception_ok(state: FullFortressState) -> bool:
    # Normalize DF stress (0-200000) to 0-1 range
    stress = state.most_stressed_value / 200_000
    return neuroception_safe(stress)


def _wants_semantic_naming(state: FullFortressState) -> bool:
    """Naming is cheap — low creativity threshold."""
    stress = state.most_stressed_value / 200_000
    return creativity_available(stress, 0.0) > 0.3  # suppression not available here, use 0


def _wants_architectural_experiment(state: FullFortressState) -> bool:
    """Architecture requires resources and population."""
    stress = state.most_stressed_value / 200_000
    return creativity_available(stress, 0.0) > 0.6 and state.population >= 30


def _wants_aesthetic_enrichment(state: FullFortressState) -> bool:
    """Enrichment requires established fortress."""
    stress = state.most_stressed_value / 200_000
    return creativity_available(stress, 0.0) > 0.4 and state.wealth.created > 10000


class CreativityChain:
    """Governance chain for creative/aesthetic fortress decisions."""

    CHAIN_NAME = "creativity"

    def __init__(self) -> None:
        self._veto_chain: VetoChain[FullFortressState] = VetoChain(
            [
                Veto("maslow_gate", _maslow_satisfied, description="Lower needs must be met"),
                Veto("neuroception", _neuroception_ok, description="System must feel safe"),
            ]
        )
        self._fallback: FallbackChain[FullFortressState, str] = FallbackChain(
            candidates=[
                Candidate("semantic_naming", _wants_semantic_naming, "semantic_naming"),
                Candidate(
                    "architectural_experiment",
                    _wants_architectural_experiment,
                    "architectural_experiment",
                ),
                Candidate(
                    "aesthetic_enrichment",
                    _wants_aesthetic_enrichment,
                    "aesthetic_enrichment",
                ),
            ],
            default="no_action",
        )

    def evaluate(self, state: FullFortressState) -> tuple[VetoResult, Selected[str]]:
        """Evaluate creativity vetoes and select creative action."""
        veto_result = self._veto_chain.evaluate(state)
        if not veto_result.allowed:
            return veto_result, Selected(action="no_action", selected_by="vetoed")
        selection = self._fallback.select(state)
        return veto_result, selection

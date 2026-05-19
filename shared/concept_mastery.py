"""shared/concept_mastery.py — Bayesian Knowledge Tracing for audience concept awareness.

Tracks per-concept mastery estimates: P(audience_knows[X] | evidence).
Uses standard BKT update rules. Writes state to SHM for consumption by
narrative arc and content programming layers.

Zero external dependencies — stdlib only.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

SHM_DIR = Path("/dev/shm/hapax-perception")
SHM_FILE = SHM_DIR / "concept-mastery.json"

# BKT parameters
DEFAULT_PRIOR = 0.1  # P(L_0) — audience starts knowing nothing
DEFAULT_P_TRANSIT = 0.3  # P(T) — probability of learning transition per exposure
DEFAULT_P_SLIP = 0.1  # P(S) — probability of slip (knows but fails to demonstrate)
DEFAULT_P_GUESS = 0.2  # P(G) — probability of guessing correctly without knowing


class ConceptMastery:
    """BKT per-concept mastery: P(audience_knows[X] | evidence)."""

    def __init__(
        self,
        concepts: list[str],
        prior: float = DEFAULT_PRIOR,
        p_transit: float = DEFAULT_P_TRANSIT,
        p_slip: float = DEFAULT_P_SLIP,
        p_guess: float = DEFAULT_P_GUESS,
    ) -> None:
        self._mastery: dict[str, float] = {c: prior for c in concepts}
        self._p_transit = p_transit
        self._p_slip = p_slip
        self._p_guess = p_guess

    def update_segment_covered(self, concept: str, retention: float = 1.0) -> None:
        """Segment explained concept — raise posterior, weighted by retention.

        Models a "correct" observation: the concept was covered, and we assume
        the audience received it (modulated by retention factor 0..1).

        BKT update for correct response:
            P(L_n | correct) = P(L_{n-1}) * (1 - P(S))
                              / (P(L_{n-1}) * (1 - P(S)) + (1 - P(L_{n-1})) * P(G))

        Then apply learning transition:
            P(L_n) = P(L_n | correct) + (1 - P(L_n | correct)) * P(T)

        Retention scales the effective P(T): lower retention = weaker learning.
        """
        if concept not in self._mastery:
            return
        p_l = self._mastery[concept]

        # Posterior given "correct" observation (segment covered = evidence of reception)
        numerator = p_l * (1.0 - self._p_slip)
        denominator = numerator + (1.0 - p_l) * self._p_guess
        p_l_given_correct = numerator / denominator if denominator > 0 else p_l

        # Learning transition, scaled by retention
        effective_p_t = self._p_transit * max(0.0, min(1.0, retention))
        self._mastery[concept] = p_l_given_correct + (1.0 - p_l_given_correct) * effective_p_t

    def update_chat_mention(self, concept: str) -> None:
        """Audience mentioned concept in chat — confirms reception.

        Stronger evidence than segment coverage: direct demonstration of knowledge.
        Models as a "correct" observation with high confidence (no retention loss),
        plus a boosted learning transition.
        """
        if concept not in self._mastery:
            return
        p_l = self._mastery[concept]

        # Posterior given correct (chat mention is strong evidence)
        numerator = p_l * (1.0 - self._p_slip)
        denominator = numerator + (1.0 - p_l) * self._p_guess
        p_l_given_correct = numerator / denominator if denominator > 0 else p_l

        # Boosted transition — chat mention implies active engagement
        boosted_p_t = min(1.0, self._p_transit * 1.5)
        self._mastery[concept] = p_l_given_correct + (1.0 - p_l_given_correct) * boosted_p_t

    def mastery(self, concept: str) -> float:
        """Return P(audience_knows[concept])."""
        return self._mastery.get(concept, 0.0)

    def zpd_concepts(self) -> list[str]:
        """Return concepts where P in [0.3, 0.7] — zone of proximal development."""
        return [c for c, p in self._mastery.items() if 0.3 <= p <= 0.7]

    def unknown_concepts(self) -> list[str]:
        """Return concepts where P < 0.3 — audience likely doesn't know."""
        return [c for c, p in self._mastery.items() if p < 0.3]

    def known_concepts(self) -> list[str]:
        """Return concepts where P > 0.7 — audience likely knows."""
        return [c for c, p in self._mastery.items() if p > 0.7]

    def add_concept(self, concept: str, prior: float = DEFAULT_PRIOR) -> None:
        """Add a new concept to track (no-op if already present)."""
        if concept not in self._mastery:
            self._mastery[concept] = prior

    def all_mastery(self) -> dict[str, float]:
        """Return full mastery state."""
        return dict(self._mastery)

    # ── SHM persistence ──────────────────────────────────────────────

    def write_shm(self) -> None:
        """Write current mastery state to SHM."""
        SHM_DIR.mkdir(parents=True, exist_ok=True)
        state: dict[str, Any] = {
            "mastery": {c: round(p, 6) for c, p in self._mastery.items()},
            "zpd": self.zpd_concepts(),
            "unknown": self.unknown_concepts(),
            "known": self.known_concepts(),
            "params": {
                "p_transit": self._p_transit,
                "p_slip": self._p_slip,
                "p_guess": self._p_guess,
            },
            "updated_at": time.time(),
        }
        tmp = SHM_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(SHM_FILE)

    @classmethod
    def read_shm(cls) -> ConceptMastery | None:
        """Read mastery state from SHM. Returns None if missing or corrupt."""
        try:
            raw = json.loads(SHM_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        mastery = raw.get("mastery", {})
        if not mastery:
            return None
        params = raw.get("params", {})
        obj = cls(
            concepts=list(mastery.keys()),
            p_transit=params.get("p_transit", DEFAULT_P_TRANSIT),
            p_slip=params.get("p_slip", DEFAULT_P_SLIP),
            p_guess=params.get("p_guess", DEFAULT_P_GUESS),
        )
        obj._mastery = {k: float(v) for k, v in mastery.items()}
        return obj


# ── ZPD affordance pressure signal ──────────────────────────────────

ZPD_SIGNAL_FILE = SHM_DIR / "zpd-signal.json"


def compute_zpd_affordance_pressure() -> dict[str, Any]:
    """Compute affordance pressure from concept mastery state.

    Reads concept mastery from SHM, computes the proportion of concepts
    in ZPD range (ripe for explanation) and unknown range (high information
    gap). Writes the signal to SHM for consumption by programme scoring
    and content recruitment layers.

    Returns a dict with zpd_concepts, unknown_concepts, zpd_pressure,
    and unknown_pressure. Returns zero-pressure defaults if mastery
    state is unavailable.
    """
    cm = ConceptMastery.read_shm()
    if cm is None:
        result: dict[str, Any] = {
            "zpd_concepts": [],
            "unknown_concepts": [],
            "zpd_pressure": 0.0,
            "unknown_pressure": 0.0,
            "updated_at": time.time(),
        }
        _write_zpd_signal(result)
        return result

    all_concepts = cm.all_mastery()
    total = len(all_concepts)
    zpd = cm.zpd_concepts()
    unknown = cm.unknown_concepts()

    result = {
        "zpd_concepts": zpd,
        "unknown_concepts": unknown,
        "zpd_pressure": len(zpd) / total if total > 0 else 0.0,
        "unknown_pressure": len(unknown) / total if total > 0 else 0.0,
        "updated_at": time.time(),
    }
    _write_zpd_signal(result)
    return result


def _write_zpd_signal(data: dict[str, Any]) -> None:
    """Atomic write of ZPD signal to SHM."""
    SHM_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ZPD_SIGNAL_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(ZPD_SIGNAL_FILE)

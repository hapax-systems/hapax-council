"""Affordance-as-retrieval — relational capability selection models."""

from __future__ import annotations

import math
import random
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

MonetizationRisk = Literal["unknown", "none", "low", "medium", "high"]

# Provenance/ContentID risk taxonomy. Distinct axis from `monetization_risk`
# (which classifies SEMANTIC content risk: profanity, reaction-content, etc.).
# `content_risk` classifies BROADCAST PROVENANCE risk: where the audio/visual
# came from and whether playing it on YouTube can trigger ContentID claims.
#
# Per `docs/superpowers/research/2026-04-23-content-source-registry-research.md`
# §6.1 — five tiers, gated independently of monetization_risk:
#
#   tier_0_owned             — operator-owned, generated, hardware-captured
#                              (oudepode catalog, wgpu shaders, studio cameras)
#   tier_1_platform_cleared  — Storyblocks, Streambeats, YT Audio Library —
#                              channel-whitelisted at the platform
#   tier_2_provenance_known  — verified CC0 (Freesound hand-checked),
#                              Internet Archive raw PD uploads
#   tier_3_uncertain         — direct Bandcamp permission per release,
#                              CC-BY (attribution required), public-domain
#                              compositions of post-1923 recordings
#   tier_4_risky             — vinyl, commercial music, raw type-beats,
#                              stream-ripped YouTube, uncleared TV/film
#
# Default is `unknown` so missing metadata cannot silently become safe.
# Public-capable capabilities must opt into a concrete tier with a reason,
# rights/provenance refs, and evidence refs.
#
# Gate semantics in `shared/governance/content_risk.py`:
#   tier_4 → unconditional block
#   tier_3 → permitted only with operator session unlock
#            (HAPAX_CONTENT_RISK_UNLOCK_TIER env var)
#   tier_2 → permitted only when programme opts in via
#            Programme.content_opt_ins
#   tier_0 / tier_1 → always permitted
ContentRisk = Literal[
    "unknown",
    "tier_0_owned",
    "tier_1_platform_cleared",
    "tier_2_provenance_known",
    "tier_3_uncertain",
    "tier_4_risky",
]


class OperationalProperties(BaseModel, frozen=True):
    requires_gpu: bool = False
    requires_network: bool = False
    latency_class: str = "fast"
    persistence: str = "none"
    medium: str | None = None
    consent_required: bool = False
    # Explicit interpersonal consent requirement. Operator/network permission
    # is not modeled here; candidates with consent_required=True and missing
    # scoped metadata fail closed in AffordancePipeline.
    consent_person_id: str | None = None
    consent_data_category: str | None = None
    priority_floor: bool = False

    # Monetization-safety classification (task #165, demonet plan Phase 1).
    # "high": unconditionally blocked at the affordance pipeline level (the
    # capability cannot be recruited on any surface).
    # "medium": blocked unless the active Programme opts the capability in
    # via Programme.constraints.monetization_opt_ins (Phase 5 wiring).
    # "low"/"none": passes through the gate unchanged.
    # "unknown": blocks public/monetizable surfaces until the catalog
    # supplies an explicit classification.
    # See shared/governance/monetization_safety.py for the filter semantics
    # and docs/research/2026-04-19-demonetization-safety-design.md §1.1
    # for the classification rubric.
    public_capable: bool = False
    monetization_risk: MonetizationRisk = "unknown"
    risk_reason: str | None = None

    # Provenance/ContentID risk — see ContentRisk Literal above.
    # Default unknown: public-capable capabilities must make their rights
    # and provenance posture explicit instead of inheriting tier_0_owned.
    content_risk: ContentRisk = "unknown"
    content_risk_reason: str | None = None
    rights_ref: str | None = None
    provenance_ref: str | None = None
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class CapabilityRecord(BaseModel, frozen=True):
    name: str
    description: str
    daemon: str
    operational: OperationalProperties = Field(default_factory=OperationalProperties)


class ActivationState(BaseModel):
    use_count: int = 0
    last_use_ts: float = 0.0
    first_use_ts: float = 0.0
    ts_alpha: float = 2.0
    ts_beta: float = 1.0

    # Cap alpha/beta to prevent Thompson saturation. Without a cap, the
    # geometric decay formula (alpha * 0.99 + 1.0) converges to 100.0,
    # producing Beta(100, ~0) which samples ~1.0 deterministically. With
    # a cap of 10, Beta(10, 1) samples ~0.9 with variance ~0.008 — still
    # exploitative but occasionally dips low enough for newcomers at
    # Beta(2, 1) = 0.67 to win a competition.
    _TS_CAP: float = 10.0

    def base_level(self, now: float, decay: float = 0.5) -> float:
        if self.use_count == 0:
            return -10.0
        t1 = max(0.001, now - self.last_use_ts)
        if self.use_count == 1:
            return math.log(t1 ** (-decay))
        tn = max(0.001, now - self.first_use_ts)
        recent = t1 ** (-decay)
        old_approx = 2 * (self.use_count - 1) / (tn**0.5 + t1**0.5)
        return math.log(recent + old_approx)

    def thompson_sample(self) -> float:
        return random.betavariate(max(0.01, self.ts_alpha), max(0.01, self.ts_beta))

    # Floor for the opposing parameter. Without a floor, beta decays to 0.01
    # under sustained success, making Beta(10, 0.01) ≈ 1.0 deterministic.
    # Floor of 1.0 means Beta(10, 1) samples ~0.91 with variance ~0.007 —
    # still exploitative but with enough variance for newcomers to occasionally win.
    _TS_FLOOR: float = 1.0

    def record_success(self, gamma: float = 0.99) -> None:
        now = time.time()
        self.ts_alpha = min(self._TS_CAP, self.ts_alpha * gamma + 1.0)
        self.ts_beta = max(self._TS_FLOOR, self.ts_beta * gamma)
        self.use_count += 1
        if self.first_use_ts == 0.0:
            self.first_use_ts = now
        self.last_use_ts = now

    def record_failure(self, gamma: float = 0.99) -> None:
        self.ts_alpha = max(self._TS_FLOOR, self.ts_alpha * gamma)
        self.ts_beta = min(self._TS_CAP, self.ts_beta * gamma + 1.0)
        self.use_count += 1

    # Preset-variety Phase 4 (task #166): time-decay the Thompson posterior
    # toward the Beta(2, 1) prior on every non-recruitment tick so a long
    # monopoly by capability A doesn't permanently freeze capability B's
    # ``thompson_sample()``. ``decay_unused`` is a STATE update on the
    # candidate, not a branch — there is no `if was_recruited: continue`.
    # Decay-rate guidance:
    #   gamma=1.000  → no decay (operator override to disable phase)
    #   gamma=0.999  → ~700-tick half-life (gentle, hours)
    #   gamma=0.99   → ~70-tick half-life (~1 min at 1 Hz)
    #   gamma=0.95   → ~14-tick half-life (restless)
    _PRIOR_ALPHA: float = 2.0
    _PRIOR_BETA: float = 1.0

    def decay_unused(self, gamma_unused: float = 0.999) -> None:
        """Pull ``ts_alpha`` / ``ts_beta`` toward the Beta(2, 1) prior.

        Idempotent for ``gamma_unused == 1.0`` (no decay). Floors are
        enforced at ``_TS_FLOOR`` so a candidate cannot decay to zero.
        Does NOT touch ``use_count`` / ``last_use_ts`` — those reflect
        actual recruitment, not non-recruitment ticks.
        """
        if gamma_unused >= 1.0:
            return
        self.ts_alpha = max(
            self._TS_FLOOR,
            self.ts_alpha * gamma_unused + self._PRIOR_ALPHA * (1.0 - gamma_unused),
        )
        self.ts_beta = max(
            self._TS_FLOOR,
            self.ts_beta * gamma_unused + self._PRIOR_BETA * (1.0 - gamma_unused),
        )

    def to_summary(self) -> dict[str, float]:
        """Summary for cross-daemon visibility via Qdrant payload."""
        total = self.ts_alpha + self.ts_beta
        return {
            "use_count": self.use_count,
            "last_use_ts": self.last_use_ts,
            "ts_alpha": self.ts_alpha,
            "ts_beta": self.ts_beta,
            "success_rate": self.ts_alpha / total if total > 0 else 0.5,
        }


class SelectionCandidate(BaseModel):
    capability_name: str
    similarity: float = 0.0
    base_level: float = 0.0
    context_boost: float = 0.0
    thompson_score: float = 0.0
    # Preset-variety Phase 3 (task #166): perceptual-distance to the rolling
    # window of recently-applied capabilities. Higher = more novel; 0.0
    # means an embedding identical to one already in the window.
    # AffordancePipeline folds this into ``combined`` via W_RECENCY when
    # ``HAPAX_AFFORDANCE_RECENCY_WEIGHT`` is non-zero.
    recency_distance: float = 0.0
    exact_recency_penalty: float = 0.0
    cost_weight: float = 1.0
    combined: float = 0.0
    suppressed: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)


class _RecencyTracker(BaseModel):
    """Rolling window of recently-applied capability embeddings.

    Per preset-variety plan §3 (task #166): tracks the last ``window_size``
    recruitment outcomes by ``(capability_name, embedding)`` so the
    pipeline can score each new candidate by its perceptual distance to
    the window. The novelty signal is purely additive — recency is a
    SCORING INPUT folded into ``combined``, never a filter.

    Distance metric: ``1 - max_cosine_sim`` over the window. An empty
    window returns ``1.0`` (max novelty), which means recency contributes
    its full weight to a candidate when no history exists yet.
    """

    window_size: int = 10
    entries: list[tuple[str, list[float]]] = Field(default_factory=list)

    def record_apply(self, name: str, embedding: list[float] | None) -> None:
        """Append an applied capability + embedding; truncate to window_size."""
        if not embedding:
            return
        self.entries.append((name, list(embedding)))
        if len(self.entries) > self.window_size:
            self.entries = self.entries[-self.window_size :]

    def distance(self, embedding: list[float] | None) -> float:
        """Return ``1 - max cosine similarity`` over the window.

        Returns ``1.0`` (max novelty) when the window is empty or the
        candidate embedding is missing/zero-norm.
        """
        if not self.entries or not embedding:
            return 1.0
        max_sim = 0.0
        norm_a = sum(v * v for v in embedding) ** 0.5
        if norm_a == 0.0:
            return 1.0
        for _name, vec in self.entries:
            if len(vec) != len(embedding):
                continue
            norm_b = sum(v * v for v in vec) ** 0.5
            if norm_b == 0.0:
                continue
            dot = sum(a * b for a, b in zip(embedding, vec, strict=True))
            sim = dot / (norm_a * norm_b)
            if sim > max_sim:
                max_sim = sim
        return max(0.0, min(1.0, 1.0 - max_sim))

    def exact_match_penalty(self, capability_name: str, window_size: int = 3) -> float:
        """Returns 1.0 if the capability was used in the last `window_size` ticks, else 0.0.

        This replaces the hardcoded variety-gate in compositional_consumer, allowing
        the affordance pipeline to apply a soft prior against rapid re-selection of
        the exact same capability (e.g. camera hero roles) while still permitting
        it if the perceptual similarity is overwhelming.
        """
        recent = self.entries[-window_size:] if window_size > 0 else self.entries
        for name, _ in reversed(recent):
            if name == capability_name:
                return 1.0
        return 0.0

    def cluster_similarity(self) -> float:
        """Return the mean pairwise cosine similarity across the window.

        Phase 6 of preset-variety-plan: when this metric crosses 0.85,
        the pipeline emits a ``content.too-similar-recently`` impingement
        so the surface can SEE that it's been clustering and recruit a
        ``novelty.shift`` move if context allows. Returns ``0.0`` for
        windows of size <2 (no clustering possible). Pairs whose vectors
        differ in dimension or are zero-norm are skipped silently.
        """
        if len(self.entries) < 2:
            return 0.0
        sims: list[float] = []
        for i in range(len(self.entries)):
            _name_i, vec_i = self.entries[i]
            norm_i = sum(v * v for v in vec_i) ** 0.5
            if norm_i == 0.0:
                continue
            for j in range(i + 1, len(self.entries)):
                _name_j, vec_j = self.entries[j]
                if len(vec_j) != len(vec_i):
                    continue
                norm_j = sum(v * v for v in vec_j) ** 0.5
                if norm_j == 0.0:
                    continue
                dot = sum(a * b for a, b in zip(vec_i, vec_j, strict=True))
                sims.append(dot / (norm_i * norm_j))
        if not sims:
            return 0.0
        return max(0.0, min(1.0, sum(sims) / len(sims)))

"""Salience-based model routing — activation over heuristics.

Routes each utterance based on how much it activates the operator's concern
graph, not how complex the utterance appears. Grounded in Desimone & Duncan's
biased competition model and Sperber & Wilson's relevance theory.

Two routing signals (Corbetta/Shulman dual-attention):
  1. Concern overlap (dorsal/top-down): cosine sim to concern anchors
  2. Novelty (ventral/bottom-up): distance from all known patterns

Combined with utterance features (dialog act, hedges, pre-sequences) into
a continuous activation score mapped to model tiers.

Replaces model_router.py.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from agents.hapax_daimonion.model_router import TIER_ROUTES, ModelTier, RoutingDecision
from agents.hapax_daimonion.salience.concern_graph import ConcernGraph
from agents.hapax_daimonion.salience.embedder import Embedder
from agents.hapax_daimonion.salience.utterance_features import UtteranceFeatures, extract

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ActivationBreakdown:
    """Diagnostic breakdown of activation score components."""

    concern_overlap: float
    novelty: float
    dialog_feature_score: float
    raw_activation: float
    final_activation: float  # after overrides
    override: str  # "" if no override, else reason
    tier: str
    embed_ms: float
    total_ms: float


# ── Default thresholds ──────────────────────────────────────────────

_DEFAULT_THRESHOLDS: dict[str, float] = {
    "canned_max": 0.15,
    "local_max": 0.45,
    "fast_max": 0.60,
    "strong_max": 0.78,
    # above strong_max → CAPABLE
}

_DEFAULT_WEIGHTS: dict[str, float] = {
    "concern_overlap": 0.55,
    "novelty": 0.15,
    "dialog_features": 0.30,
}

# ── Governance override patterns ────────────────────────────────────

# Only "refused" forces CAPABLE — active refusal needs best model to handle gracefully.
# "pending" uses normal routing (guest may be transient, face dedup may be wrong).
# "active" (consent granted) is normal operation — no override needed.
_CONSENT_PHASES = frozenset({"refused"})


class SalienceRouter:
    """Activation-based model router.

    Computes per-utterance activation in <20ms total and routes to the
    right model tier based on how much the utterance matters to the
    operator right now.

    Includes hysteresis to prevent jarring tier oscillation between
    consecutive turns, and cold-start guard to default to FAST when
    the concern graph is empty (no environmental context yet).
    """

    def __init__(
        self,
        embedder: Embedder,
        concern_graph: ConcernGraph,
        thresholds: dict[str, float] | None = None,
        weights: dict[str, float] | None = None,
    ) -> None:
        self._embedder = embedder
        self._concern_graph = concern_graph
        self._thresholds = thresholds or _DEFAULT_THRESHOLDS
        self._weights = weights or _DEFAULT_WEIGHTS
        self._recent_turns: list[str] = []
        self._max_recent_turns: int = 10
        self._last_breakdown: ActivationBreakdown | None = None
        # Hysteresis: track previous tier to resist oscillation
        self._prev_tier: ModelTier | None = None
        self._seeking: bool = False
        # Exploration tracking (spec §8: kappa=0.012, T_patience=300s)
        from shared.exploration_tracker import ExplorationTrackerBundle

        self._exploration = ExplorationTrackerBundle(
            component="salience_router",
            edges=["concern_overlap", "activation_level"],
            traces=["novelty_signal", "tier_selection"],
            neighbors=["stimmung", "dmn_pulse"],
            kappa=0.012,
            t_patience=300.0,
            sigma_explore=0.10,
        )
        self._prev_activation: float = 0.0

    @property
    def last_breakdown(self) -> ActivationBreakdown | None:
        """Last routing decision breakdown for diagnostics."""
        return self._last_breakdown

    def set_seeking(self, seeking: bool) -> None:
        """When system is in SEEKING stance, boost novelty weight."""
        self._seeking = seeking

    def effective_novelty_weight(self) -> float:
        """Current novelty weight (boosted in SEEKING stance)."""
        base = self._weights.get("novelty", 0.15)
        return 0.30 if self._seeking else base

    def route(
        self,
        transcript: str,
        *,
        turn_count: int = 0,
        activity_mode: str = "idle",
        consent_phase: str = "none",
        guest_mode: bool = False,
        face_count: int = 0,
        has_tools: bool = True,
        desk_activity: str = "idle",
    ) -> RoutingDecision:
        """Route an utterance to a model tier based on activation score.

        This replaces model_router.route() with salience-based routing.
        """
        t_start = time.monotonic()

        # ── Extract utterance features (<1ms) ─────────────────────
        features = extract(transcript, self._recent_turns)

        # ── Governance overrides (non-negotiable) ─────────────────
        if consent_phase in _CONSENT_PHASES:
            self._record_breakdown(
                0.0, 0.0, 0.0, 1.0, f"consent_{consent_phase}", "CAPABLE", t_start
            )
            return RoutingDecision(
                tier=ModelTier.CAPABLE,
                model=TIER_ROUTES[ModelTier.CAPABLE],
                reason=f"consent_{consent_phase}",
                canned_response="",
            )

        if guest_mode:
            self._record_breakdown(0.0, 0.0, 0.0, 1.0, "guest_or_multiface", "CAPABLE", t_start)
            return RoutingDecision(
                tier=ModelTier.CAPABLE,
                model=TIER_ROUTES[ModelTier.CAPABLE],
                reason="guest_or_multiface",
                canned_response="",
            )

        # ── Phatic / canned override ─────────────────────────────
        # Check canned patterns for short utterances — catches greetings
        # at turn 0 and phatic exchanges at any turn.
        if features.word_count <= 6:
            canned = self._pick_canned(transcript, turn_count)
            if canned:
                self._record_breakdown(0.0, 0.0, 0.0, 0.0, "phatic", "CANNED", t_start)
                return RoutingDecision(
                    tier=ModelTier.CANNED,
                    model="",
                    reason="phatic",
                    canned_response=canned,
                )

        # ── Explicit escalation override ──────────────────────────
        if features.has_explicit_escalation:
            self._record_breakdown(0.0, 0.0, 0.0, 1.0, "explicit_escalation", "CAPABLE", t_start)
            self._add_recent_turn(transcript)
            return RoutingDecision(
                tier=ModelTier.CAPABLE,
                model=TIER_ROUTES[ModelTier.CAPABLE],
                reason="explicit_escalation",
                canned_response="",
            )

        # ── Cold-start guard ────────────────────────────────────
        # Empty concern graph = no environmental context yet.
        # Default to FAST so we don't underserve important early
        # utterances. Normal routing takes over once the graph populates.
        if self._concern_graph.anchor_count == 0:
            self._record_breakdown(0.0, 0.0, 0.0, 0.5, "cold_start", "FAST", t_start)
            self._prev_tier = ModelTier.FAST
            self._add_recent_turn(transcript)
            return RoutingDecision(
                tier=ModelTier.FAST,
                model=TIER_ROUTES[ModelTier.FAST],
                reason="cold_start",
                canned_response="",
            )

        # ── Embed utterance (<1ms with Model2Vec) ────────────────
        t_embed = time.monotonic()
        utt_vec = self._embedder.embed(transcript)
        embed_ms = (time.monotonic() - t_embed) * 1000

        # ── Compute activation signals ───────────────────────────
        concern_overlap = self._concern_graph.query(utt_vec)
        novelty = self._concern_graph.novelty(utt_vec)

        # Dialog feature score: composite of dialog act, pre-sequences, etc.
        dialog_score = self._dialog_feature_score(features, turn_count)

        # ── Weighted activation (turn-modulated) ─────────────────
        # Gradual ramp: early turns rely on dialog structure (concern
        # graph is noisy for greetings — consent anchors spike on
        # "you there", "hey"). Concern overlap scales in slowly as the
        # conversation establishes topic and the novelty signal stabilizes.
        w = dict(self._weights)  # copy so we don't mutate defaults
        if turn_count <= 2:
            # Opening: almost entirely dialog structure
            w["concern_overlap"] = 0.10
            w["novelty"] = 0.05
            w["dialog_features"] = 0.85
        elif turn_count <= 4:
            # Warming: dialog still dominant, concern blending in
            w["concern_overlap"] = 0.25
            w["novelty"] = 0.10
            w["dialog_features"] = 0.65
        elif turn_count <= 7:
            # Established: balanced blend
            w["concern_overlap"] = 0.40
            w["novelty"] = 0.15
            w["dialog_features"] = 0.45
        # else: use configured weights (full concern activation)

        # SEEKING stance: boost novelty weight at expense of concern overlap
        if self._seeking:
            novelty_boost = 0.30 - w["novelty"]
            if novelty_boost > 0:
                w["novelty"] = 0.30
                w["concern_overlap"] = max(0.0, w["concern_overlap"] - novelty_boost)

        activation = (
            concern_overlap * w["concern_overlap"]
            + novelty * w["novelty"]
            + dialog_score * w["dialog_features"]
        )
        activation = max(0.0, min(1.0, activation))

        # Production mode boost: active desk engagement increases salience
        # (utterances during production sessions are more likely intentional)
        if desk_activity in ("scratching", "drumming", "tapping"):
            activation = min(1.0, activation + 0.08)

        # ── Map to tier ──────────────────────────────────────────
        tier = self._activation_to_tier(activation)

        # ── Hysteresis: resist de-escalation oscillation ────────
        # Escalation is unrestricted (new information should be served).
        # De-escalation is damped: can only drop one tier per turn.
        # This prevents jarring quality shifts between consecutive
        # utterances and is ADHD-friendly (consistent > variable quality).
        if self._prev_tier is not None and tier.value < self._prev_tier.value:
            tier = ModelTier(max(tier.value, self._prev_tier.value - 1))
        self._prev_tier = tier

        # Track recent turns for feature extraction
        self._add_recent_turn(transcript)

        # Exploration signal
        self._exploration.feed_habituation(
            "concern_overlap", concern_overlap, self._prev_activation, 0.2
        )
        self._exploration.feed_habituation(
            "activation_level", activation, self._prev_activation, 0.1
        )
        self._exploration.feed_interest("novelty_signal", novelty, 0.2)
        self._exploration.feed_interest("tier_selection", float(tier.value) / 4.0, 0.3)
        self._exploration.feed_error(1.0 - activation)
        self._exploration.compute_and_publish()
        self._prev_activation = activation

        # Add utterance to concern graph's recent window for novelty
        self._concern_graph.add_recent_utterance(utt_vec)

        # Record breakdown for diagnostics
        self._record_breakdown(
            concern_overlap, novelty, dialog_score, activation, "", tier.name, t_start, embed_ms
        )

        log.info(
            "SALIENCE activation=%.3f concern=%.3f novelty=%.3f dialog=%.3f "
            "tier=%s embed=%.1fms total=%.1fms transcript=%r",
            activation,
            concern_overlap,
            novelty,
            dialog_score,
            tier.name,
            embed_ms,
            (time.monotonic() - t_start) * 1000,
            transcript[:60],
        )

        return RoutingDecision(
            tier=tier,
            model=TIER_ROUTES[tier],
            reason=f"salience:{activation:.2f}",
            canned_response="",
        )

    def _dialog_feature_score(self, features: UtteranceFeatures, turn_count: int) -> float:
        """Compute dialog feature contribution to activation.

        Maps conversational features to a 0.0-1.0 score indicating how much
        the utterance's conversational structure demands model intelligence.
        """
        score = 0.0

        # Meta-questions and commands need capable models
        if features.dialog_act == "meta_question":
            score += 0.8
        elif features.dialog_act == "command":
            score += 0.4
        elif features.dialog_act == "wh_question":
            score += 0.3
        elif features.dialog_act in ("open_question", "yes_no_question"):
            # Casual questions — don't escalate unless long
            if features.word_count >= 10:
                score += 0.3
            else:
                score += 0.1
        elif features.dialog_act == "statement":
            # Longer statements suggest more complex thought
            if features.word_count >= 15:
                score += 0.5
            elif features.word_count >= 10:
                score += 0.3
            elif features.word_count >= 6:
                score += 0.1

        # Pre-sequences signal upcoming complexity
        if features.is_pre_sequence:
            score += 0.3

        # Hedges suggest uncertainty — may need more thoughtful response
        if features.hedge_count >= 2:
            score += 0.1

        # Deep conversation naturally escalates
        if turn_count >= 6:
            score += 0.2
        elif turn_count >= 3:
            score += 0.1

        # Topic continuity: high continuity = stay at current level,
        # low continuity = might be a topic shift worth escalating for
        if features.topic_continuity < 0.1 and turn_count > 2:
            score += 0.15  # potential topic shift

        return min(score, 1.0)

    def _activation_to_tier(self, activation: float) -> ModelTier:
        """Map activation to tier. Intelligence-first: always CAPABLE.

        CANNED handled by phatic detection in route(), never here.
        Activation still computed for effort calibration — not tier selection.
        """
        return ModelTier.CAPABLE

    def _pick_canned(self, transcript: str, turn_count: int) -> str:
        """Pick a canned response for phatic utterances. Reuses model_router patterns."""

        text = transcript.strip()

        # Import canned patterns from model_router (reuse, don't duplicate)
        from agents.hapax_daimonion.model_router import _CANNED_PATTERNS, _GREETING_CANNED

        # First-turn greetings
        if turn_count <= 1 and len(text.split()) <= 6:
            for pattern, responses in _GREETING_CANNED:
                if pattern.match(text):
                    return responses[turn_count % len(responses)]

        # Later-turn phatic
        if len(text.split()) <= 4 and turn_count > 1:
            for pattern, responses in _CANNED_PATTERNS:
                if pattern.match(text):
                    return responses[turn_count % len(responses)]

        return ""

    def _add_recent_turn(self, transcript: str) -> None:
        """Track recent turns for topic continuity computation."""
        self._recent_turns.append(transcript)
        if len(self._recent_turns) > self._max_recent_turns:
            self._recent_turns.pop(0)

    def _record_breakdown(
        self,
        concern: float,
        novelty: float,
        dialog: float,
        activation: float,
        override: str,
        tier: str,
        t_start: float,
        embed_ms: float = 0.0,
    ) -> None:
        self._last_breakdown = ActivationBreakdown(
            concern_overlap=concern,
            novelty=novelty,
            dialog_feature_score=dialog,
            raw_activation=activation,
            final_activation=activation,
            override=override,
            tier=tier,
            embed_ms=embed_ms,
            total_ms=(time.monotonic() - t_start) * 1000,
        )

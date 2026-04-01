"""shared/apperception.py — Self-band architecture for Hapax apperception.

Content-free processing cascade that discovers "self" by running on events
from existing subsystems. The self emerges from the processing, not from
predefined content.

Pure-logic module: no I/O, no threading, no network. Cascade steps are
deterministic (modulo controlled stochastic resonance in step 2).

Research basis: 7 threads, 80+ sources. Guardrails: cohesive but not rigid
(Kohut), decentered but engaged (ACT), constituted through relation
(Merleau-Ponty chiasm), grounded in work not approval (Hegel), transparent
not defended (Weil), no suppression pathway, context-adaptive noise.
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from collections import deque
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from shared.control_signal import ControlSignal, publish_health
from shared.impingement import Impingement, ImpingementType

log = logging.getLogger(__name__)

# ── Source Types ─────────────────────────────────────────────────────────────

Source = Literal[
    "prediction_error",
    "correction",
    "pattern_shift",
    "stimmung_event",
    "cross_resonance",
    "absence",
    "performance",
]

ALL_SOURCES: list[Source] = [
    "prediction_error",
    "correction",
    "pattern_shift",
    "stimmung_event",
    "cross_resonance",
    "absence",
    "performance",
]

# ── Apperception (single self-observation) ───────────────────────────────────


class Apperception(BaseModel, frozen=True):
    """A single self-observation produced by the cascade."""

    source: Source
    trigger_text: str
    cascade_depth: int = Field(ge=1, le=7)
    observation: str  # "I notice..."
    valence: float = Field(ge=-1.0, le=1.0)
    valence_target: str  # which self-dimension
    action: str = ""  # internal, never operator-facing
    reflection: str = ""  # meta-observation, step 6 only
    noise_level: float = Field(ge=0.0, le=1.0, default=0.0)
    stimmung_stance: str = "nominal"
    timestamp: float = Field(default_factory=time.time)


# ── SelfDimension (accumulated evidence per aspect) ──────────────────────────


class SelfDimension(BaseModel):
    """Accumulated evidence about one aspect of self-knowledge.

    Dimensions emerge from processing, not predefined. Names are discovered
    through the cascade (e.g. "activity_recognition", "temporal_prediction").
    """

    name: str
    confidence: float = Field(ge=0.05, le=0.95, default=0.5)
    affirming_count: int = 0
    problematizing_count: int = 0
    last_shift_time: float = Field(default_factory=time.time)

    @property
    def stability(self) -> float:
        """Seconds since last confidence shift."""
        return time.time() - self.last_shift_time

    def update(self, valence: float) -> None:
        """Apply transmuting internalization update rule.

        Positive valence affirms, negative problematizes. Large errors (>0.7)
        dampen change rate instead of being rejected (narcissistic inflation guard).
        """
        if valence > 0:
            self.affirming_count += 1
        elif valence < 0:
            self.problematizing_count += 1

        magnitude = abs(valence)
        # Dampening: large corrections reduce step size (anti-inflation)
        # Below 0.7: step scales linearly with magnitude.
        # Above 0.7: step shrinks as magnitude grows, always less than at 0.7.
        if magnitude > 0.7:
            # At 0.7: step would be 0.014. Above 0.7: decreases toward 0.
            overshoot = magnitude - 0.7  # 0.0 to 0.3
            step = 0.02 * 0.7 * (1.0 - overshoot / 0.3)
            step = max(step, 0.001)  # never zero
        else:
            step = 0.02 * magnitude

        direction = 1.0 if valence > 0 else -1.0
        new_conf = self.confidence + direction * step
        # Clamp to [0.05, 0.95] — never fully certain or fully collapsed
        new_conf = max(0.05, min(0.95, new_conf))

        if new_conf != self.confidence:
            self.last_shift_time = time.time()
        self.confidence = new_conf


# ── SelfModel (complete self-knowledge) ──────────────────────────────────────

# Coherence floor prevents total collapse (shame spiral guard)
COHERENCE_FLOOR = 0.15
COHERENCE_CEILING = 1.0


class SelfModel(BaseModel):
    """Complete self-knowledge state. Inspectable, no hidden internal state."""

    dimensions: dict[str, SelfDimension] = Field(default_factory=dict)
    recent_observations: deque[str] = Field(default_factory=lambda: deque(maxlen=20))
    recent_reflections: deque[str] = Field(default_factory=lambda: deque(maxlen=10))
    coherence: float = Field(ge=COHERENCE_FLOOR, le=COHERENCE_CEILING, default=0.7)

    model_config = {"arbitrary_types_allowed": True}

    def get_or_create_dimension(self, name: str) -> SelfDimension:
        """Get an existing dimension or create a new one (emergent discovery)."""
        if name not in self.dimensions:
            self.dimensions[name] = SelfDimension(name=name)
        return self.dimensions[name]

    def update_coherence(self) -> None:
        """Recalculate coherence from dimension agreement.

        Coherence = mean confidence across dimensions. Floor at COHERENCE_FLOOR
        to prevent total collapse (shame spiral guard).
        """
        if not self.dimensions:
            return
        mean_conf = sum(d.confidence for d in self.dimensions.values()) / len(self.dimensions)
        self.coherence = max(COHERENCE_FLOOR, min(COHERENCE_CEILING, mean_conf))

    def to_dict(self) -> dict:
        """Serialize for JSON storage (shm, cache)."""
        return {
            "dimensions": {
                name: {
                    "name": d.name,
                    "confidence": d.confidence,
                    "affirming_count": d.affirming_count,
                    "problematizing_count": d.problematizing_count,
                    "last_shift_time": d.last_shift_time,
                }
                for name, d in self.dimensions.items()
            },
            "recent_observations": list(self.recent_observations),
            "recent_reflections": list(self.recent_reflections),
            "coherence": self.coherence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SelfModel:
        """Deserialize from JSON storage."""
        model = cls()
        known_fields = {
            "name",
            "confidence",
            "affirming_count",
            "problematizing_count",
            "last_shift_time",
        }
        for name, d in data.get("dimensions", {}).items():
            filtered = {k: v for k, v in d.items() if k in known_fields}
            model.dimensions[name] = SelfDimension(**filtered)
        for obs in data.get("recent_observations", []):
            model.recent_observations.append(obs)
        for ref in data.get("recent_reflections", []):
            model.recent_reflections.append(ref)
        model.coherence = max(COHERENCE_FLOOR, min(COHERENCE_CEILING, data.get("coherence", 0.7)))
        return model


# ── Cascade Event (input to the cascade) ────────────────────────────────────


class CascadeEvent(BaseModel, frozen=True):
    """An event from an existing subsystem that the cascade processes."""

    source: Source
    text: str
    magnitude: float = Field(ge=0.0, le=1.0, default=0.5)
    metadata: dict = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


# ── Stimmung Modulation Table ────────────────────────────────────────────────


class StimmungModulation(BaseModel, frozen=True):
    """How stimmung stance modulates cascade behavior."""

    sources_allowed: list[Source] | None = None  # None = all
    noise_level: float | None = None  # None = context-adaptive
    noise_reduction: float = 1.0  # multiplier on noise
    reflection_threshold_multiplier: float = 1.0
    reflection_enabled: bool = True
    dampened: bool = False


_STIMMUNG_TABLE: dict[str, StimmungModulation] = {
    "nominal": StimmungModulation(
        noise_reduction=1.0,
    ),
    "cautious": StimmungModulation(
        noise_reduction=0.5,
    ),
    "degraded": StimmungModulation(
        noise_level=0.1,
        reflection_threshold_multiplier=2.0,
        dampened=True,
    ),
    "critical": StimmungModulation(
        sources_allowed=["prediction_error", "correction"],
        noise_level=0.0,
        reflection_enabled=False,
    ),
}


def get_stimmung_modulation(stance: str) -> StimmungModulation:
    """Get modulation parameters for a stimmung stance."""
    return _STIMMUNG_TABLE.get(stance, _STIMMUNG_TABLE["nominal"])


# ── ApperceptionCascade (7 steps, pure logic) ───────────────────────────────

# Default relevance threshold
DEFAULT_RELEVANCE_THRESHOLD = 0.2

# Rumination breaker: consecutive negative valences on same dimension
RUMINATION_LIMIT = 5
RUMINATION_GATE_SECONDS = 600  # 10 minutes


class ApperceptionCascade:
    """Seven-step processing cascade that produces self-observations.

    Pure logic, no I/O. Deterministic modulo controlled stochastic resonance
    in step 2 (relevance). All state is in the SelfModel, which is fully
    inspectable.
    """

    def __init__(
        self,
        self_model: SelfModel | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.model = self_model or SelfModel()
        self.rng = rng or random.Random()

        # Dedup: last 50 trigger hashes
        self._recent_triggers: deque[str] = deque(maxlen=50)

        # Rumination tracking: dimension → list of recent valences
        self._valence_history: dict[str, deque[float]] = {}

        # Rumination gate: dimension → ungate time
        self._attention_gates: dict[str, float] = {}

        # Exploration tracking (spec §8: kappa=0.005, T_patience=120s)
        from shared.exploration_tracker import ExplorationTrackerBundle

        self._exploration = ExplorationTrackerBundle(
            component="apperception",
            edges=["trigger_novelty", "valence_diversity"],
            traces=["cascade_frequency", "gate_activity"],
            neighbors=["dmn_pulse", "stimmung"],
            kappa=0.005,
            t_patience=120.0,
        )
        self._prev_trigger_count: float = 0.0

        # Context-adaptive noise (0.1-0.4)
        self._base_noise: float = 0.2

    # ── Step 1: Attention ────────────────────────────────────────────────

    def _step_attention(self, event: CascadeEvent, modulation: StimmungModulation) -> bool:
        """Is this about me? All system events pass. Dedup last 50 triggers.
        Critical stimmung: only prediction_error + correction.
        """
        # Source filter by stimmung
        if modulation.sources_allowed is not None:
            if event.source not in modulation.sources_allowed:
                return False

        # Dedup by trigger hash
        trigger_hash = hashlib.md5(
            f"{event.source}:{event.text}".encode(), usedforsecurity=False
        ).hexdigest()[:12]
        if trigger_hash in self._recent_triggers:
            return False
        self._recent_triggers.append(trigger_hash)

        return True

    # ── Step 2: Relevance ────────────────────────────────────────────────

    def _step_relevance(
        self,
        event: CascadeEvent,
        modulation: StimmungModulation,
    ) -> tuple[bool, float]:
        """Difference that makes a difference? Threshold + stochastic resonance.

        Returns (passes, relevance_score).
        """
        # Base relevance from magnitude
        relevance = event.magnitude

        # Noise injection — stochastic resonance
        noise = self._compute_noise(modulation)
        if noise > 0:
            relevance += self.rng.gauss(0, noise * 0.1)

        # Corrections always relevant
        if event.source == "correction":
            return True, max(relevance, 0.5)

        threshold = DEFAULT_RELEVANCE_THRESHOLD
        # Low coherence reduces threshold (easier to rebuild)
        if self.model.coherence < 0.4:
            threshold *= 0.5

        return relevance >= threshold, relevance

    def _compute_noise(self, modulation: StimmungModulation) -> float:
        """Compute noise level with stimmung modulation."""
        if modulation.noise_level is not None:
            return modulation.noise_level
        return self._base_noise * modulation.noise_reduction

    # ── Step 3: Integration ──────────────────────────────────────────────

    def _step_integration(self, event: CascadeEvent) -> tuple[str, list[str]]:
        """Connects to prior self-observations? Search self-model dimensions
        + recent observations for overlap.

        Returns (target_dimension, integration_links).
        """
        # Map source to likely dimension
        dimension_map: dict[Source, str] = {
            "prediction_error": "temporal_prediction",
            "correction": "accuracy",
            "pattern_shift": "pattern_recognition",
            "stimmung_event": "system_awareness",
            "cross_resonance": "cross_modal_integration",
            "absence": "continuity",
            "performance": "processing_quality",
        }
        target = dimension_map.get(event.source, "general")

        # Check for metadata-specified dimension
        if "dimension" in event.metadata:
            target = event.metadata["dimension"]

        # Find integration links (recent observations mentioning this dimension)
        links: list[str] = []
        for obs in self.model.recent_observations:
            if target in obs.lower() or event.source in obs.lower():
                links.append(obs)

        return target, links

    # ── Step 4: Valence ──────────────────────────────────────────────────
    # BOUNDARY: downstream cannot modify upstream. Valence is frozen after this step.
    # No suppression pathway.

    _SOURCE_POLARITY: dict[Source, float] = {
        "prediction_error": -0.5,
        "correction": -0.7,
        "pattern_shift": 0.0,  # neutral, magnitude determines direction
        "stimmung_event": 0.0,
        "cross_resonance": 0.3,
        "absence": -0.3,
        "performance": 0.0,
    }

    def _step_valence(self, event: CascadeEvent) -> float:
        """Affirms or problematizes self-model?

        Map source → polarity. Correction = problematizing.
        Pattern confirmed = affirming. Scaled by magnitude.
        """
        base = self._SOURCE_POLARITY.get(event.source, 0.0)

        # Pattern shift direction from metadata
        if event.source == "pattern_shift":
            confirmed = event.metadata.get("confirmed", None)
            if confirmed is True:
                base = 0.5
            elif confirmed is False:
                base = -0.5

        # Stimmung events: degradation is problematizing
        if event.source == "stimmung_event":
            direction = event.metadata.get("direction", "stable")
            if direction == "improving":
                base = 0.3
            elif direction in ("degrading", "worsening"):
                base = -0.3

        # Performance: above baseline affirms, below problematizes
        if event.source == "performance":
            baseline = event.metadata.get("baseline", 0.5)
            base = (event.magnitude - baseline) * 1.0

        # Scale by magnitude
        valence = base * event.magnitude
        return max(-1.0, min(1.0, valence))

    # ── Step 5: Action ───────────────────────────────────────────────────

    def _step_action(self, valence: float, target: str, confidence: float) -> str:
        """What should I do? Mostly empty. Only for high-confidence
        problematizing that suggests specific behavioral change. Internal only.
        """
        # Only generate action for strong problematizing on well-established dimensions
        if valence < -0.5 and confidence > 0.6:
            return f"Consider adjusting approach to {target}"
        return ""

    # ── Step 6: Reflection ───────────────────────────────────────────────

    def _step_reflection(
        self,
        valence: float,
        target: str,
        links: list[str],
        dimension: SelfDimension,
        modulation: StimmungModulation,
    ) -> str:
        """What should I think? Meta-observation when valence conflicts with
        dimension trend OR 3+ integration links. NOT re-evaluating valence.
        """
        if not modulation.reflection_enabled:
            return ""

        # Threshold for reflection trigger
        threshold = 3 * modulation.reflection_threshold_multiplier

        # Conflict: valence direction opposes dimension trend
        # Requires minimum history to establish a trend (avoid false conflicts on new dimensions)
        total_evidence = dimension.affirming_count + dimension.problematizing_count
        trend_positive = dimension.affirming_count > dimension.problematizing_count
        valence_positive = valence > 0
        conflict = total_evidence >= 3 and (
            (trend_positive and not valence_positive) or (not trend_positive and valence_positive)
        )

        if conflict:
            return (
                f"I notice a tension: {target} trend is "
                f"{'positive' if trend_positive else 'negative'} "
                f"but this event {'affirms' if valence_positive else 'problematizes'}"
            )

        # Many integration links suggest a pattern worth noting
        if len(links) >= threshold:
            return f"I notice recurring pattern around {target} ({len(links)} connections)"

        return ""

    # ── Step 7: Retention ────────────────────────────────────────────────

    def _step_retention(
        self,
        cascade_depth: int,
        relevance: float,
        valence: float,
        reflection: str,
        source: Source,
    ) -> bool:
        """Worth keeping? Corrections always. Depth >= 5 with moderate signal.
        Depth 4 only with high signal (both relevance AND valence).
        """
        if source == "correction":
            return True

        if cascade_depth >= 5:
            return relevance > 0.3 or abs(valence) > 0.2 or bool(reflection)

        # Depth 4: retain only high-signal events (tighter gate)
        if cascade_depth == 4:
            return relevance > 0.5 and abs(valence) > 0.3

        return False

    # ── Rumination Breaker ───────────────────────────────────────────────

    def _check_rumination(self, target: str, valence: float) -> bool:
        """Returns True if this dimension is currently gated (rumination breaker active)."""
        now = time.time()

        # Check if gate is active
        if target in self._attention_gates:
            if now < self._attention_gates[target]:
                return True
            else:
                del self._attention_gates[target]

        # Track valence history
        if target not in self._valence_history:
            self._valence_history[target] = deque(maxlen=RUMINATION_LIMIT + 1)
        self._valence_history[target].append(valence)

        # Check for consecutive negative
        history = self._valence_history[target]
        if len(history) >= RUMINATION_LIMIT:
            recent = list(history)[-RUMINATION_LIMIT:]
            if all(v < 0 for v in recent):
                self._attention_gates[target] = now + RUMINATION_GATE_SECONDS
                return True

        return False

    # ── Full Cascade ─────────────────────────────────────────────────────

    def process(self, event: CascadeEvent, stimmung_stance: str = "nominal") -> Apperception | None:
        """Run the full 7-step cascade on an event.

        Returns an Apperception if retained, None if filtered at any step.
        """
        modulation = get_stimmung_modulation(stimmung_stance)

        # Step 1: Attention
        if not self._step_attention(event, modulation):
            return None

        # Step 2: Relevance
        passes, relevance = self._step_relevance(event, modulation)
        if not passes:
            return None

        # Step 3: Integration
        target, links = self._step_integration(event)

        # Step 4: Valence (compute BEFORE rumination check)
        valence = self._step_valence(event)

        # Rumination check with actual valence (all sources, gate + record)
        if self._check_rumination(target, valence):
            return None

        # Get/create the target dimension
        dimension = self.model.get_or_create_dimension(target)

        # Step 5: Action
        action = self._step_action(valence, target, dimension.confidence)

        # Step 6: Reflection
        reflection = self._step_reflection(valence, target, links, dimension, modulation)

        # Cascade depth — how far the event penetrated
        cascade_depth = 4  # reached valence
        if action:
            cascade_depth = 5
        if reflection:
            cascade_depth = 6

        # Step 7: Retention
        retained = self._step_retention(cascade_depth, relevance, valence, reflection, event.source)
        if retained:
            cascade_depth = max(cascade_depth, 7)

        if not retained:
            return None

        # Build observation text
        noise = self._compute_noise(modulation)
        observation = f"I notice {event.source.replace('_', ' ')}: {event.text}"

        apperception = Apperception(
            source=event.source,
            trigger_text=event.text,
            cascade_depth=cascade_depth,
            observation=observation,
            valence=valence,
            valence_target=target,
            action=action,
            reflection=reflection,
            noise_level=noise,
            stimmung_stance=stimmung_stance,
        )

        # Update self-model
        dimension.update(valence)
        self.model.recent_observations.append(observation)
        if reflection:
            self.model.recent_reflections.append(reflection)
        self.model.update_coherence()

        publish_health(
            ControlSignal(
                component="apperception",
                reference=1.0,
                perception=self.model.coherence,
            )
        )
        # Control law: coherence below 0.2 → gate sources
        _ap_error = self.model.coherence < 0.2
        self._cl_errors = getattr(self, "_cl_errors", 0)
        self._cl_ok = getattr(self, "_cl_ok", 0)
        self._cl_degraded = getattr(self, "_cl_degraded", False)
        if _ap_error:
            self._cl_errors += 1
            self._cl_ok = 0
        else:
            self._cl_errors = 0
            self._cl_ok += 1

        if self._cl_errors >= 3 and not self._cl_degraded:
            self._cl_degraded = True
            self._cl_saved_sources = None  # all sources were allowed
            log.warning("Control law [apperception]: degrading — gating to correction-only")

        if self._cl_ok >= 5 and self._cl_degraded:
            self._cl_degraded = False
            log.info("Control law [apperception]: recovered — all 7 sources re-enabled")

        # Exploration signal
        trigger_count = float(len(self._recent_triggers))
        valence_diversity = float(len(self._valence_history))
        self._exploration.feed_habituation(
            "trigger_novelty", trigger_count, self._prev_trigger_count, 5.0
        )
        self._exploration.feed_habituation("valence_diversity", valence_diversity, 0.0, 2.0)
        self._exploration.feed_interest("cascade_frequency", trigger_count, 5.0)
        gate_count = sum(1 for t in self._attention_gates.values() if t > time.time())
        self._exploration.feed_interest("gate_activity", float(gate_count), 1.0)
        self._exploration.feed_error(1.0 - self.model.coherence)
        self._exploration.compute_and_publish()
        self._prev_trigger_count = trigger_count

        return apperception


# ── ApperceptionStore (persistence, implemented in Batch 4) ──────────────────


class ApperceptionStore:
    """Handles persistence of apperceptions to Qdrant.

    Batches apperceptions and flushes to Qdrant on a slow cadence (60s).
    Uses 768-dim nomic embeddings (same as other collections).
    """

    COLLECTION_NAME = "hapax-apperceptions"

    def __init__(self) -> None:
        self._pending: list[Apperception] = []

    def add(self, apperception: Apperception) -> None:
        """Queue an apperception for batch persistence."""
        self._pending.append(apperception)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def ensure_collection(self) -> None:
        """Create the Qdrant collection if it doesn't exist. Idempotent."""
        from qdrant_client.models import Distance, VectorParams

        from agents._config import EXPECTED_EMBED_DIMENSIONS, get_qdrant

        client = get_qdrant()
        collections = [c.name for c in client.get_collections().collections]
        if self.COLLECTION_NAME not in collections:
            client.create_collection(
                collection_name=self.COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=EXPECTED_EMBED_DIMENSIONS,
                    distance=Distance.COSINE,
                ),
            )

    def flush(self) -> int:
        """Flush pending apperceptions to Qdrant. Returns count flushed.

        Best-effort: embedding or Qdrant failures are logged and skipped.
        """
        if not self._pending:
            return 0

        from agents._config import embed_batch_safe, get_qdrant

        batch = list(self._pending)
        self._pending.clear()

        # Build texts for embedding
        texts = [f"{a.observation} [{a.valence_target}]" for a in batch]
        vectors = embed_batch_safe(texts, prefix="search_document")
        if vectors is None:
            return 0

        self.ensure_collection()

        # Build Qdrant points
        import uuid

        from qdrant_client.models import PointStruct

        points = []
        for apperception, vector in zip(batch, vectors, strict=True):
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={
                        "source": apperception.source,
                        "trigger_text": apperception.trigger_text,
                        "observation": apperception.observation,
                        "valence": apperception.valence,
                        "valence_target": apperception.valence_target,
                        "action": apperception.action,
                        "reflection": apperception.reflection,
                        "cascade_depth": apperception.cascade_depth,
                        "stimmung_stance": apperception.stimmung_stance,
                        "timestamp": apperception.timestamp,
                    },
                )
            )

        try:
            client = get_qdrant()
            client.upsert(collection_name=self.COLLECTION_NAME, points=points)
            return len(points)
        except Exception:
            log.warning("Apperception flush failed", exc_info=True)
            return 0

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Search archived apperceptions by semantic similarity.

        Returns list of payload dicts, most relevant first.
        """
        from agents._config import embed_safe, get_qdrant

        vector = embed_safe(query, prefix="search_query")
        if vector is None:
            return []

        self.ensure_collection()

        try:
            client = get_qdrant()
            results = client.query_points(
                collection_name=self.COLLECTION_NAME,
                query=vector,
                limit=limit,
            ).points
            return [r.payload for r in results if r.payload]
        except Exception:
            log.warning("Apperception search failed", exc_info=True)
            return []


# ── Impingement → Cascade Event mapping ───────────────────────────────────


def impingement_to_cascade_event(imp: Impingement) -> CascadeEvent | None:
    """Map a perception impingement to an apperception cascade event.
    Only STATISTICAL_DEVIATION from perception.* sources maps to prediction_error.
    """
    if imp.type != ImpingementType.STATISTICAL_DEVIATION:
        return None
    if not imp.source.startswith("perception."):
        return None
    metric = imp.content.get("metric", imp.source)
    value = imp.content.get("value", "")
    delta = imp.content.get("delta", 0)
    return CascadeEvent(
        source="prediction_error",
        text=f"Perception signal {metric} deviated: value={value}, delta={delta}",
        magnitude=imp.strength,
        metadata={"impingement_id": imp.id, "metric": metric},
        timestamp=imp.timestamp,
    )


def consume_perception_impingements(
    *, path: Path | None = None, cursor: int = 0
) -> list[CascadeEvent]:
    """Read new perception impingements from JSONL and convert to cascade events."""
    from shared.impingement_consumer import ImpingementConsumer

    _path = path or Path("/dev/shm/hapax-dmn/impingements.jsonl")
    consumer = ImpingementConsumer(_path)
    consumer._cursor = cursor
    events = []
    for imp in consumer.read_new():
        event = impingement_to_cascade_event(imp)
        if event is not None:
            events.append(event)
    return events

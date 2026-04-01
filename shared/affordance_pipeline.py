"""Unified affordance selection pipeline."""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.affordance import ActivationState, CapabilityRecord, SelectionCandidate
from shared.affordance_metrics import AffordanceMetrics
from shared.impingement import Impingement, render_impingement_text

log = logging.getLogger("affordance_pipeline")

ACTIVATION_STATE_PATH = Path("/home/hapax/.cache/hapax/affordance-activation-state.json")
COLLECTION_NAME = "affordances"
DEFAULT_TOP_K = 10
SUPPRESSION_FACTOR = 0.3
THRESHOLD = 0.05
W_SIMILARITY = 0.50
W_BASE_LEVEL = 0.20
W_CONTEXT = 0.10
W_THOMPSON = 0.20


class EmbeddingCache:
    def __init__(self, max_size: int = 256) -> None:
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._max_size = max_size

    def _key(self, content: dict[str, Any]) -> str:
        raw = str(sorted(content.items()))
        return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()

    def get(self, content: dict[str, Any]) -> list[float] | None:
        key = self._key(content)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, content: dict[str, Any], embedding: list[float]) -> None:
        key = self._key(content)
        self._cache[key] = embedding
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)


@dataclass
class InterruptHandler:
    capability_name: str
    daemon: str


@dataclass
class InhibitionEntry:
    source: str
    content_hash: str
    inhibited_until: float


class AffordancePipeline:
    def __init__(self) -> None:
        self._activation: dict[str, ActivationState] = {}
        self._embed_cache = EmbeddingCache()
        self._interrupt_handlers: dict[str, list[InterruptHandler]] = {}
        self._seeking: bool = False
        self._inhibitions: list[InhibitionEntry] = []
        self._cascade_log: list[dict[str, Any]] = []
        self._context_associations: dict[tuple[str, str], float] = {}
        self._dismissal_log: list[dict[str, Any]] = []
        self._metrics = AffordanceMetrics()
        from shared.circuit_breaker import CircuitBreaker

        self._retrieve_breaker = CircuitBreaker(
            "qdrant_retrieve", failure_threshold=3, cooldown_s=60.0
        )
        self._index_breaker = CircuitBreaker("qdrant_index", failure_threshold=5, cooldown_s=60.0)
        # Exploration tracking (spec §8: kappa=0.012, T_patience=300s)
        from shared.exploration_tracker import ExplorationTrackerBundle

        self._exploration = ExplorationTrackerBundle(
            component="affordance_pipeline",
            edges=["impingement_source", "candidate_diversity"],
            traces=["selection_frequency", "activation_spread"],
            neighbors=["dmn_pulse", "imagination"],
            kappa=0.012,
            t_patience=300.0,
            sigma_explore=0.10,
        )
        self._prev_source_hash: float = 0.0

    def _ensure_collection(self, client: object, vector_size: int) -> None:
        """Create the affordances collection if it doesn't exist."""
        from qdrant_client.models import Distance, VectorParams

        if not client.collection_exists(COLLECTION_NAME):  # type: ignore[union-attr]
            client.create_collection(  # type: ignore[union-attr]
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
            log.info("Created Qdrant collection '%s' (dim=%d)", COLLECTION_NAME, vector_size)

    def index_capability(self, record: CapabilityRecord) -> bool:
        from shared.config import embed_safe, get_qdrant

        embedding = embed_safe(record.description, prefix="search_document")
        if embedding is None:
            log.warning("Cannot embed capability '%s'", record.name)
            return False
        if not self._index_breaker.allow_request():
            return False
        try:
            from qdrant_client.models import PointStruct

            client = get_qdrant()
            self._ensure_collection(client, len(embedding))
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, record.name))
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=embedding,
                        payload={
                            "capability_name": record.name,
                            "description": record.description,
                            "daemon": record.daemon,
                            "requires_gpu": record.operational.requires_gpu,
                            "latency_class": record.operational.latency_class,
                            "consent_required": record.operational.consent_required,
                            "priority_floor": record.operational.priority_floor,
                            "available": True,
                        },
                    )
                ],
            )
            self._index_breaker.record_success()
        except Exception:
            self._index_breaker.record_failure()
            log.warning("Failed to index '%s' in Qdrant", record.name, exc_info=True)
            return False
        if record.name not in self._activation:
            self._activation[record.name] = ActivationState()
        log.info("Indexed capability: %s", record.name)
        return True

    def set_seeking(self, seeking: bool) -> None:
        """SEEKING stance: widen retrieval (more candidates, lower threshold)."""
        self._seeking = seeking

    def register_interrupt(self, token: str, capability_name: str, daemon: str) -> None:
        self._interrupt_handlers.setdefault(token, []).append(
            InterruptHandler(capability_name=capability_name, daemon=daemon)
        )

    def select(
        self,
        impingement: Impingement,
        top_k: int = DEFAULT_TOP_K,
        context: dict[str, Any] | None = None,
    ) -> list[SelectionCandidate]:
        if impingement.interrupt_token:
            handlers = self._interrupt_handlers.get(impingement.interrupt_token, [])
            if handlers:
                result = [
                    SelectionCandidate(
                        capability_name=h.capability_name,
                        similarity=1.0,
                        combined=1.0,
                        payload={"daemon": h.daemon, "interrupt": True},
                    )
                    for h in handlers
                ]
                winner = result[0] if result else None
                self._metrics.record_selection(
                    impingement_source=impingement.source,
                    impingement_metric=impingement.content.get("metric", ""),
                    candidates_count=len(result),
                    winner=winner.capability_name if winner else None,
                    winner_similarity=1.0,
                    winner_combined=1.0,
                    was_interrupt=True,
                )
                return result
        if self._is_inhibited(impingement):
            return []
        embedding = self._get_embedding(impingement)
        if embedding is None:
            return self._fallback_keyword_match(impingement)
        candidates = self._retrieve(embedding, top_k)
        if not candidates:
            return []
        now = time.time()
        for c in candidates:
            state = self._activation.get(c.capability_name, ActivationState())
            c.base_level = self._normalize_base_level(state.base_level(now))
            c.context_boost = self._compute_context_boost(c.capability_name, context)
            c.thompson_score = state.thompson_sample()
            cost = 0.3 if c.payload.get("requires_gpu") else 0.0
            if c.payload.get("latency_class") == "slow":
                cost = max(cost, 0.5)
            c.cost_weight = 1.0 - cost * 0.5
            c.combined = (
                W_SIMILARITY * c.similarity
                + W_BASE_LEVEL * c.base_level
                + W_CONTEXT * c.context_boost
                + W_THOMPSON * c.thompson_score
            ) * c.cost_weight
        priority = [c for c in candidates if c.payload.get("priority_floor")]
        normal = [c for c in candidates if not c.payload.get("priority_floor")]
        if priority:
            priority.sort(key=lambda c: -c.combined)
            self._log_cascade(impingement, priority)
            return priority
        if len(normal) > 1:
            normal.sort(key=lambda c: -c.combined)
            winner_score = normal[0].combined
            for c in normal[1:]:
                suppression = (winner_score - c.combined) * SUPPRESSION_FACTOR
                c.combined = max(0.0, c.combined - suppression)
        # SEEKING stance: lower threshold to surface more distant associations
        effective_threshold = THRESHOLD * 0.5 if self._seeking else THRESHOLD
        survivors = [c for c in normal if c.combined > effective_threshold]
        survivors.sort(key=lambda c: -c.combined)
        self._log_cascade(impingement, survivors)
        winner = survivors[0] if survivors else None
        self._metrics.record_selection(
            impingement_source=impingement.source,
            impingement_metric=impingement.content.get("metric", ""),
            candidates_count=len(candidates),
            winner=winner.capability_name if winner else None,
            winner_similarity=winner.similarity if winner else 0.0,
            winner_combined=winner.combined if winner else 0.0,
            was_interrupt=False,
            was_fallback=embedding is None,
        )
        # Exploration signal
        source_hash = hash(impingement.source) % 100 / 100.0
        diversity = float(len(set(c.capability_name for c in candidates))) if candidates else 0.0
        self._exploration.feed_habituation(
            "impingement_source", source_hash, self._prev_source_hash, 0.3
        )
        self._exploration.feed_habituation("candidate_diversity", diversity, 0.0, 2.0)
        self._exploration.feed_interest("selection_frequency", float(len(survivors)), 1.0)
        spread = float(len(self._activation))
        self._exploration.feed_interest("activation_spread", spread, 5.0)
        self._exploration.feed_error(0.0 if survivors else 1.0)
        self._exploration.compute_and_publish()
        self._prev_source_hash = source_hash

        return survivors

    def record_success(self, capability_name: str) -> None:
        state = self._activation.setdefault(capability_name, ActivationState())
        state.record_success()

    def record_failure(self, capability_name: str) -> None:
        state = self._activation.setdefault(capability_name, ActivationState())
        state.record_failure()

    def record_outcome(
        self, capability_name: str, success: bool, context: dict[str, Any] | None = None
    ) -> None:
        """Record outcome and update learned associations."""
        if success:
            self.record_success(capability_name)
        else:
            self.record_failure(capability_name)

        self._metrics.record_outcome(
            capability_name,
            success,
            {k: str(v) for k, v in context.items()} if context else None,
        )

        # Hebbian: strengthen/weaken context associations
        if context:
            delta = 0.1 if success else -0.05
            for _key, value in context.items():
                self.update_context_association(str(value), capability_name, delta=delta)

    def decay_associations(self, factor: float = 0.995) -> None:
        """Decay all context associations toward zero (passive forgetting)."""
        to_remove = []
        for key, strength in self._context_associations.items():
            new_val = strength * factor
            if abs(new_val) < 0.001:
                to_remove.append(key)
            else:
                self._context_associations[key] = new_val
        for key in to_remove:
            del self._context_associations[key]

    def record_dismissal(
        self,
        capability_name: str,
        impingement_id: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Record that the operator dismissed a capability's output.

        Bridges to record_outcome(success=False) and logs for audit.
        """
        self.record_outcome(capability_name, success=False, context=context)
        self._dismissal_log.append(
            {
                "timestamp": time.time(),
                "capability": capability_name,
                "impingement_id": impingement_id,
            }
        )
        if len(self._dismissal_log) > 100:
            self._dismissal_log = self._dismissal_log[-50:]

    def save_activation_state(self) -> None:
        """Persist activation states and context associations to disk."""
        data = {
            "activations": {name: state.model_dump() for name, state in self._activation.items()},
            "associations": {f"{k[0]}|{k[1]}": v for k, v in self._context_associations.items()},
        }
        path = ACTIVATION_STATE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(path)

    def load_activation_state(self) -> None:
        """Load persisted activation states and context associations."""
        path = ACTIVATION_STATE_PATH
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            for name, state_dict in data.get("activations", {}).items():
                self._activation[name] = ActivationState(**state_dict)
            for key_str, strength in data.get("associations", {}).items():
                parts = key_str.split("|", 1)
                if len(parts) == 2:
                    self._context_associations[(parts[0], parts[1])] = strength
        except Exception:
            log.warning("Failed to load activation state", exc_info=True)

    @property
    def metrics(self) -> AffordanceMetrics:
        return self._metrics

    def get_audit_snapshot(self) -> dict[str, Any]:
        """Return structured audit data for observability."""
        return {
            "capabilities_tracked": len(self._activation),
            "associations_learned": len(self._context_associations),
            "recent_cascades": len(self._cascade_log),
            "inhibitions_active": len(
                [i for i in self._inhibitions if i.inhibited_until > time.monotonic()]
            ),
            "dismissals_total": len(self._dismissal_log),
            "activation_states": {
                name: {
                    "use_count": s.use_count,
                    "ts_alpha": round(s.ts_alpha, 2),
                    "ts_beta": round(s.ts_beta, 2),
                    "last_use": s.last_use_ts,
                }
                for name, s in self._activation.items()
            },
            "top_associations": sorted(
                [(f"{k[0]}→{k[1]}", round(v, 3)) for k, v in self._context_associations.items()],
                key=lambda x: -abs(x[1]),
            )[:20],
            "metrics_summary": self._metrics.compute_summary(),
        }

    def add_inhibition(self, impingement: Impingement, duration_s: float = 30.0) -> None:
        content_hash = self._content_hash(impingement)
        self._inhibitions.append(
            InhibitionEntry(
                source=impingement.source,
                content_hash=content_hash,
                inhibited_until=time.monotonic() + duration_s,
            )
        )

    def _is_inhibited(self, impingement: Impingement) -> bool:
        now = time.monotonic()
        self._inhibitions = [e for e in self._inhibitions if e.inhibited_until > now]
        content_hash = self._content_hash(impingement)
        return any(
            e.source == impingement.source and e.content_hash == content_hash
            for e in self._inhibitions
        )

    @staticmethod
    def _content_hash(impingement: Impingement) -> str:
        if not impingement.content:
            return ""
        return hashlib.md5(
            str(sorted(impingement.content.items())).encode(), usedforsecurity=False
        ).hexdigest()

    def _get_embedding(self, impingement: Impingement) -> list[float] | None:
        if impingement.embedding is not None:
            return impingement.embedding
        cached = self._embed_cache.get(impingement.content)
        if cached is not None:
            return cached
        from shared.config import embed_safe

        text = render_impingement_text(impingement)
        embedding = embed_safe(text, prefix="search_query")
        if embedding is not None:
            self._embed_cache.put(impingement.content, embedding)
        return embedding

    def _retrieve(self, embedding: list[float], top_k: int) -> list[SelectionCandidate]:
        if not self._retrieve_breaker.allow_request():
            return []
        try:
            from shared.config import get_qdrant

            client = get_qdrant()
            results = client.query_points(
                collection_name=COLLECTION_NAME,
                query=embedding,
                limit=top_k,
                query_filter={"must": [{"key": "available", "match": {"value": True}}]},
            ).points
            self._retrieve_breaker.record_success()
        except Exception:
            self._retrieve_breaker.record_failure()
            log.debug("Qdrant retrieval failed", exc_info=True)
            return []
        return [
            SelectionCandidate(
                capability_name=hit.payload.get("capability_name", ""),
                similarity=hit.score,
                payload=hit.payload or {},
            )
            for hit in results
        ]

    def _fallback_keyword_match(self, impingement: Impingement) -> list[SelectionCandidate]:
        metric = impingement.content.get("metric", "")
        source = impingement.source
        if not metric and not source:
            return []
        try:
            from shared.config import get_qdrant

            client = get_qdrant()
            results, _ = client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter={"must": [{"key": "available", "match": {"value": True}}]},
                limit=100,
            )
        except Exception:
            log.debug("Qdrant keyword fallback failed", exc_info=True)
            return []
        candidates = []
        search_terms = {metric.lower(), source.lower()}
        for point in results:
            desc = (point.payload or {}).get("description", "").lower()
            name = (point.payload or {}).get("capability_name", "").lower()
            score = sum(1 for term in search_terms if term and (term in desc or term in name))
            if score > 0:
                candidates.append(
                    SelectionCandidate(
                        capability_name=point.payload.get("capability_name", ""),
                        similarity=min(1.0, score * 0.3),
                        payload=point.payload or {},
                    )
                )
        return candidates

    @staticmethod
    def _normalize_base_level(raw: float) -> float:
        clamped = max(-10.0, min(10.0, raw))
        return 1.0 / (1.0 + 2.718281828 ** (-clamped))

    def _compute_context_boost(self, capability_name: str, context: dict[str, Any] | None) -> float:
        if not context:
            return 0.0
        total = 0.0
        n_cues = 0
        for _cue_key, cue_value in context.items():
            assoc_key = (str(cue_value), capability_name)
            strength = self._context_associations.get(assoc_key, 0.0)
            if strength != 0.0:
                total += strength
                n_cues += 1
        if n_cues == 0:
            return 0.0
        w = 1.0 / max(1, n_cues)
        return max(0.0, min(1.0, total * w))

    def update_context_association(
        self, cue_value: str, capability_name: str, delta: float = 0.1
    ) -> None:
        key = (cue_value, capability_name)
        current = self._context_associations.get(key, 0.0)
        self._context_associations[key] = max(-1.0, min(4.0, current + delta))

    def _log_cascade(self, impingement: Impingement, winners: list[SelectionCandidate]) -> None:
        if not winners:
            return
        entry = {
            "timestamp": time.time(),
            "impingement_id": impingement.id,
            "source": impingement.source,
            "metric": impingement.content.get("metric", ""),
            "winners": [
                {
                    "name": w.capability_name,
                    "similarity": round(w.similarity, 3),
                    "combined": round(w.combined, 3),
                }
                for w in winners
            ],
        }
        self._cascade_log.append(entry)
        if len(self._cascade_log) > 100:
            self._cascade_log = self._cascade_log[-50:]

    @property
    def recent_cascades(self) -> list[dict[str, Any]]:
        return list(self._cascade_log)

    def get_activation_state(self, capability_name: str) -> ActivationState:
        return self._activation.get(capability_name, ActivationState())

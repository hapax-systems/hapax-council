"""Unified affordance selection pipeline."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shared.affordance import ActivationState, CapabilityRecord, SelectionCandidate
from shared.affordance_metrics import AffordanceMetrics
from shared.affordance_recruitment_metrics import (
    record_recruitment as _record_recruitment,
)
from shared.conative_impingement import action_tendency_prior_for_candidate
from shared.embed_cache import DiskEmbeddingCache
from shared.exploration import ExplorationSignal
from shared.impingement import Impingement, render_impingement_text
from shared.visual_mode_bias import get_visual_mode_bias

log = logging.getLogger("affordance_pipeline")

if TYPE_CHECKING:
    from shared.affordance_outcome_adapter import AffordanceOutcomeDecision
    from shared.capability_outcome import CapabilityOutcomeEnvelope

ACTIVATION_STATE_PATH = Path("/home/hapax/.cache/hapax/affordance-activation-state.json")
_DISK_CACHE_PATH = Path.home() / ".cache" / "hapax" / "embed-cache.json"
COLLECTION_NAME = "affordances"
DEFAULT_TOP_K = 10
SUPPRESSION_FACTOR = 0.3
THRESHOLD = 0.05
# Score formula weights. Preset-variety Phase 3 (task #166) renormalizes
# from 0.50/0.20/0.10/0.20 → 0.45/0.18/0.09/0.18/0.10 to fold in
# ``recency_distance`` as a perceptual-novelty term. The 0.10 weight is
# small enough that strong narrative still wins, but large enough to
# break ties in favor of perceptually-distant options.
W_SIMILARITY = 0.45
W_BASE_LEVEL = 0.18
W_CONTEXT = 0.09
W_THOMPSON = 0.18
# Operator-runtime override of recency-distance weight. Default 0.10
# (Phase 3 lands active). Set to "0" to disable the term without
# redeploy. Read once per ``select()`` call so flips take effect on
# the next recruitment.
RECENCY_WEIGHT_ENV = "HAPAX_AFFORDANCE_RECENCY_WEIGHT"
W_RECENCY_DEFAULT = 0.10
# Recency tracker rolling window size (capabilities, not embeddings).
RECENCY_WINDOW_SIZE = 10
# Preset-variety Phase 6: perceptual-distance impingement emission.
# Mean pairwise cosine sim across the recency window crossing this
# threshold triggers a ``content.too-similar-recently`` impingement.
PERCEPTUAL_CLUSTER_THRESHOLD: float = 0.85
# Cooldown between perceptual-distance impingement emissions per pipeline
# instance — keeps a sustained-cluster window from spamming the bus.
PERCEPTUAL_IMPINGEMENT_COOLDOWN_S: float = 30.0
# Where impingements land — same SHM file the daimonion + reverie + dmn
# consumers tail (see ``shared/sensor_protocol.IMPINGEMENTS_FILE``).
_PERCEPTUAL_IMPINGEMENTS_FILE = Path("/dev/shm/hapax-dmn/impingements.jsonl")
# Persistent recruitment log — per-winner record consumed by
# ``scripts/measure-preset-variety-baseline.py`` to compute
# ``per_preset_activation_count`` + ``colorgrade_halftone_ratio``
# (preset-variety plan Phase 1 / Phase 9). Path mirrors the default
# the baseline script reads from. Append-only; operator rotates
# manually if needed (~80 bytes/line × ~5/sec ≈ 35 MB/day).
RECRUITMENT_LOG_FILE = Path.home() / "hapax-state" / "affordance" / "recruitment-log.jsonl"
# Operator-runtime override of recruitment-log writing.
# Set ``HAPAX_RECRUITMENT_LOG=0`` to disable (default-on).
RECRUITMENT_LOG_ENV = "HAPAX_RECRUITMENT_LOG"
# Dispatch-trace log — one line per ``select()`` call. Records the gate at
# which the impingement was dropped (or ``dispatched`` when a winner emerged)
# so the dispatch-dropout investigation can distinguish family-filter empty
# from threshold-miss from consent-veto. See
# ``docs/research/2026-04-22-dispatch-dropout-investigation.md`` for context.
# Set ``HAPAX_DISPATCH_TRACE=0`` to disable (default-on).
DISPATCH_TRACE_FILE = Path.home() / "hapax-state" / "affordance" / "dispatch-trace.jsonl"
DISPATCH_TRACE_ENV = "HAPAX_DISPATCH_TRACE"
# Preset-variety Phase 4: Thompson posterior decay on non-recruitment.
# 0.999 ≈ 700-tick half-life (gentle); 1.0 disables. Operator-tunable.
THOMPSON_DECAY_ENV = "HAPAX_AFFORDANCE_THOMPSON_DECAY"
THOMPSON_DECAY_DEFAULT = 0.999
# Consent contract registry refresh window. Cheap to refresh (4 yaml files)
# but pipeline.select() is hot-pathed (per-frame in reverie mixer, per-impingement
# in run_loops_aux), so we cache for 60s instead of reading every call.
_CONSENT_CACHE_TTL_S = 60.0

# D-26 (Phase 5): active-programme refresh window. Tighter than the consent
# cache because Programme transitions (e.g. quiet_frame activation) need to
# take effect on the gate within ~1s — slower would let medium-risk content
# leak through during a governance hold. Reading the JSONL store on every
# call is too expensive on the recruitment hot path; 1s is the right
# trade-off for human-action-cadence Programme changes.
_PROGRAMME_CACHE_TTL_S = 1.0


def _apply_exploration_noise(
    candidates: list[SelectionCandidate],
    signal: ExplorationSignal | None,
    sigma_explore: float,
) -> None:
    """Apply boredom-proportional noise to candidate scores (15th control law).

    When boredom_index > 0.7 (aligned with exploration control law threshold),
    inject Gaussian noise scaled by sigma_explore * boredom_index. This disrupts
    monotonic winners only during genuine stagnation, not normal operation.
    Modifies candidates in-place. Scores clamped to >= 0.
    """
    if signal is None or signal.boredom_index <= 0.7:
        return
    noise_scale = sigma_explore * signal.boredom_index
    for c in candidates:
        c.combined = max(0.0, c.combined + random.gauss(0, noise_scale))


def _conative_strength_posterior(impingement: Impingement) -> float:
    raw = impingement.content.get("strength_posterior", impingement.strength)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return impingement.strength


def _emit_consent_refusal(*, axiom: str, surface: str, reason: str) -> None:
    """Append a structured event to the canonical refusal log.

    Used by the affordance-pipeline consent gate when the contract
    registry holds no active consent (or the loader itself raised),
    so consent_required capabilities are about to be blocked.

    The cache TTL on the consent gate (60s) bounds emission rate to
    at most one append per minute per pipeline instance — the gate
    only loads contracts on cache miss, and emit is conditional on
    the load returning False.

    Best-effort: writer failures swallowed so an observability hiccup
    never breaks the consent decision path.
    """
    try:
        from datetime import UTC, datetime

        from agents.refusal_brief import RefusalEvent, append

        append(
            RefusalEvent(
                timestamp=datetime.now(UTC),
                axiom=axiom,
                surface=surface,
                reason=reason[:160],
            )
        )
    except Exception:
        pass


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

    def _text_key(self, text: str) -> str:
        return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()

    def get_by_text(self, text: str) -> list[float] | None:
        key = self._text_key(text)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put_by_text(self, text: str, embedding: list[float]) -> None:
        key = self._text_key(text)
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


def embed_batch_safe(texts: list[str], prefix: str = "search_document") -> list[list[float]] | None:
    """Batch embed with graceful degradation."""
    try:
        from shared.config import embed_batch

        return embed_batch(texts, prefix=prefix)
    except RuntimeError:
        log.warning("embed_batch_safe: Ollama unavailable")
        return None


class AffordancePipeline:
    def __init__(self) -> None:
        self._activation: dict[str, ActivationState] = {}
        # Preset-variety Phase 3: rolling window of recently-applied
        # (capability_name, embedding) pairs. Updated when a winner is
        # selected in ``select()``; queried at scoring time to compute
        # each candidate's ``recency_distance``.
        from shared.affordance import _RecencyTracker

        self._recency = _RecencyTracker(window_size=RECENCY_WINDOW_SIZE)
        # Preset-variety Phase 6: track when we last emitted a
        # perceptual-distance impingement to enforce the cooldown.
        self._last_perceptual_emission_at: float = 0.0
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
        # Consent gate cache (see _consent_allows): True iff at least one
        # active consent contract exists. Refreshed every _CONSENT_CACHE_TTL_S
        # seconds. Starts as None so the first consent_required candidate
        # forces an immediate load.
        self._consent_has_active: bool | None = None
        self._consent_loaded_at: float = 0.0
        # D-26: active-programme cache for the monetization gate. Loaded on
        # first gate-passing select() call and refreshed every
        # _PROGRAMME_CACHE_TTL_S seconds. Read failures (no store, malformed
        # JSONL) yield None — the gate then sees no opt-ins, which is
        # fail-CLOSED for medium-risk capabilities (correct safety posture).
        self._active_programme: Any = None
        self._programme_loaded_at: float = 0.0

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
                            "medium": record.operational.medium,
                            "public_capable": record.operational.public_capable,
                            "monetization_risk": record.operational.monetization_risk,
                            "risk_reason": record.operational.risk_reason,
                            "content_risk": record.operational.content_risk,
                            "content_risk_reason": record.operational.content_risk_reason,
                            "rights_ref": record.operational.rights_ref,
                            "provenance_ref": record.operational.provenance_ref,
                            "evidence_refs": list(record.operational.evidence_refs),
                            "activation_summary": self._activation.get(
                                record.name, ActivationState()
                            ).to_summary(),
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

    def index_capabilities_batch(self, records: list[CapabilityRecord]) -> int:
        """Index multiple capabilities in a single embed + upsert operation.

        Uses disk cache to avoid re-embedding static descriptions across restarts.
        Calls embed_batch() once for cache misses. Upserts all points in one Qdrant call.
        """
        if not records:
            return 0

        from shared.config import EMBEDDING_MODEL, EXPECTED_EMBED_DIMENSIONS, get_qdrant

        prefix = "search_document"
        prefixed_texts = [f"{prefix}: {r.description}" for r in records]

        disk_cache = DiskEmbeddingCache(
            cache_path=_DISK_CACHE_PATH,
            model=EMBEDDING_MODEL,
            dimension=EXPECTED_EMBED_DIMENSIONS,
        )
        hits, miss_indices, miss_texts = disk_cache.bulk_lookup(prefixed_texts)

        if miss_texts:
            # miss_texts are already prefixed ("search_document: ...") for cache keying.
            # Pass empty prefix so embed_batch() doesn't double-prefix.
            fresh = embed_batch_safe(miss_texts, prefix="")
            if fresh is None:
                log.warning("Batch embed failed, falling back to individual indexing")
                return sum(1 for r in records if self.index_capability(r))
            for idx, vec in zip(miss_indices, fresh, strict=True):
                hits[idx] = vec
                disk_cache.put(prefixed_texts[idx], vec)
            disk_cache.save()

        from qdrant_client.models import PointStruct

        points: list[PointStruct] = []
        for i, record in enumerate(records):
            embedding = hits.get(i)
            if embedding is None:
                continue
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, record.name))
            points.append(
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
                        "medium": record.operational.medium,
                        "public_capable": record.operational.public_capable,
                        "monetization_risk": record.operational.monetization_risk,
                        "risk_reason": record.operational.risk_reason,
                        "content_risk": record.operational.content_risk,
                        "content_risk_reason": record.operational.content_risk_reason,
                        "rights_ref": record.operational.rights_ref,
                        "provenance_ref": record.operational.provenance_ref,
                        "evidence_refs": list(record.operational.evidence_refs),
                        "activation_summary": self._activation.get(
                            record.name, ActivationState()
                        ).to_summary(),
                        "available": True,
                    },
                )
            )

        if not points:
            return 0

        try:
            client = get_qdrant()
            self._ensure_collection(client, len(points[0].vector))
            client.upsert(collection_name=COLLECTION_NAME, points=points)
            self._index_breaker.record_success()
        except Exception:
            self._index_breaker.record_failure()
            log.warning("Batch Qdrant upsert failed", exc_info=True)
            return 0

        for record in records:
            if record.name not in self._activation:
                self._activation[record.name] = ActivationState()

        log.info(
            "Batch-indexed %d capabilities (%d cached, %d freshly embedded)",
            len(points),
            len(records) - len(miss_texts),
            len(miss_texts),
        )
        return len(points)

    def set_seeking(self, seeking: bool) -> None:
        """SEEKING stance: widen retrieval (more candidates, lower threshold)."""
        self._seeking = seeking

    def _consent_allows(self, candidate: SelectionCandidate) -> bool:
        """Gate ``consent_required`` candidates on the active contract registry.

        Closes a systemic axiom-enforcement gap surfaced by the 2026-04-12
        beta audit: ``shared/affordance_registry.py`` declares
        ``consent_required=True`` on 7 capabilities (knowledge search, web
        search, send message, livestream toggle, etc.), and the recruitment
        pipeline propagates that flag into the Qdrant payload, but until
        this method existed nothing actually read it back. Result: every
        capability marked "needs consent" was being recruited as if no
        consent gate existed.

        Behaviour:

        - Candidates without ``consent_required`` in the payload always
          pass — no contract load incurred.
        - Candidates with ``consent_required=True`` pass iff
          :func:`shared.governance.consent.load_contracts` reports at least
          one active contract. The result is cached for
          ``_CONSENT_CACHE_TTL_S`` seconds because select() is hot-pathed
          (per-frame in the reverie mixer, per-impingement in the run
          loops).
        - Any exception during contract loading **fails closed** —
          consent_required candidates are blocked and a warning is logged.
          This matches the legacy gate's safety stance and the wider
          consent-engine fail-closed control law in
          :class:`shared.governance.consent.ConsentRegistry`.
        """
        if not candidate.payload.get("consent_required"):
            return True
        now = time.time()
        if self._consent_has_active is None or now - self._consent_loaded_at > _CONSENT_CACHE_TTL_S:
            try:
                from shared.governance.consent import load_contracts

                registry = load_contracts()
                # Iterate via __iter__ — the legacy gate in
                # shared/capability_registry.py:162 reaches for a
                # non-existent .contracts attribute and accidentally
                # AttributeError-blocks every consent_required capability.
                self._consent_has_active = any(c.active for c in registry)
                self._consent_loaded_at = now
                if not self._consent_has_active:
                    _emit_consent_refusal(
                        axiom="interpersonal_transparency",
                        surface="affordance_pipeline:consent_gate",
                        reason="no active consent contract — consent_required candidates blocked",
                    )
            except Exception:
                log.warning(
                    "Consent gate failed for %s — blocking (fail-closed)",
                    candidate.capability_name,
                )
                self._consent_has_active = False
                self._consent_loaded_at = now
                _emit_consent_refusal(
                    axiom="interpersonal_transparency",
                    surface="affordance_pipeline:consent_gate",
                    reason="contract loader exception — gate failed closed",
                )
        return bool(self._consent_has_active)

    def _apply_programme_bias(
        self, candidates: list[SelectionCandidate], programme: Any
    ) -> list[SelectionCandidate]:
        """Phase 4 of programme-layer plan (D-28).

        Multiplies each candidate's composed score by the active
        Programme's per-capability bias multiplier. NEVER shrinks the
        candidate set — set-size preservation is a hard architectural
        invariant per ``project_programmes_enable_grounding``. The
        validator on ``capability_bias_negative`` rejects zero
        multipliers, so a strongly-biased-negative capability can
        still recruit if its base similarity + impingement pressure
        overcome the bias.

        No-op when ``programme is None`` (steady state — no active
        programme, nothing to bias).

        Increments ``hapax_programme_candidate_set_reduction_total`` if
        the input + output lists differ in length — this is a bug
        sentinel and must always remain at 0 in production.
        """
        if programme is None:
            return candidates
        before_len = len(candidates)
        programme_id = getattr(programme, "programme_id", "unknown")
        for c in candidates:
            try:
                multiplier = float(programme.bias_multiplier(c.capability_name))
            except Exception:
                # Programme without bias_multiplier method (test stub) or
                # raised — treat as 1.0 (no bias). Cannot break recruitment
                # on a programme-method gap.
                multiplier = 1.0
            c.combined = max(0.0, c.combined * multiplier)
            # Phase 9 invariant: soft-prior-not-hardening detector. If a
            # candidate received negative bias (multiplier < 1) and the
            # post-bias combined still survives the recruitment threshold,
            # the candidate will (likely) be recruited DESPITE programme
            # bias — that's the soft-prior-overridden event. Fire the
            # counter so a stream where the counter stays at zero per
            # programme can be flagged as a hard-gate regression.
            if multiplier < 1.0 and c.combined > THRESHOLD:
                try:
                    from shared.programme_observability import emit_soft_prior_override

                    emit_soft_prior_override(programme_id, reason="negative_bias_overcome")
                except Exception:
                    log.debug("emit_soft_prior_override failed", exc_info=True)
        # Sentinel: helper MUST preserve list length. Any reduction is a
        # bug; emit a counter so a future regression surfaces immediately.
        if len(candidates) != before_len:
            try:
                from shared.governance.demonet_metrics import METRICS as _M

                programme_id = getattr(programme, "programme_id", "unknown")
                _M.inc_programme_candidate_set_reduction(programme_id)
            except Exception:
                log.warning(
                    "programme bias INVARIANT VIOLATION: candidate set "
                    "shrunk from %d to %d under programme %r",
                    before_len,
                    len(candidates),
                    getattr(programme, "programme_id", "?"),
                )
        return candidates

    def _active_programme_cached(self) -> Any:
        """Return the currently-active Programme (D-26 / plan Phase 5).

        Reads ``shared.programme_store.default_store().active_programme()``
        with a TTL cache (``_PROGRAMME_CACHE_TTL_S``) so the recruitment
        hot path doesn't open the JSONL store on every gate call. Returns
        ``None`` if the store is empty, unreadable, or no Programme has
        status=ACTIVE — the gate then sees no opt-ins, fail-CLOSED for
        medium-risk capabilities (correct safety posture).

        Read failures (FileNotFoundError, JSON parse errors) are logged
        once per refresh cycle but never propagated — programme lookup
        cannot break the recruitment pipeline.
        """
        now = time.time()
        # Refresh on time-only condition; None is a LEGITIMATE cached value
        # (means "no active Programme") so cannot serve as a not-loaded
        # sentinel. _programme_loaded_at=0.0 (init default) forces the first
        # call to load.
        if now - self._programme_loaded_at > _PROGRAMME_CACHE_TTL_S:
            try:
                from shared.programme_store import default_store

                self._active_programme = default_store().active_programme()
            except Exception:  # noqa: BLE001 — programme lookup must never break recruitment
                log.warning("active_programme lookup failed; falling back to None", exc_info=True)
                self._active_programme = None
            self._programme_loaded_at = now
        return self._active_programme

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
        # Dispatch-dropout investigation (2026-04-22): build a trace dict
        # populated at each gate so we can attribute the ~98% dropout
        # observed for ``studio_compositor.director.compositional`` source
        # impingements to a specific stage. ``dropout_at`` stays ``None``
        # only when survivors are returned. Trace flushed to JSONL on
        # every return path via ``_emit_dispatch_trace``.
        trace: dict[str, Any] = {
            "timestamp": time.time(),
            "impingement_id": impingement.id,
            "source": impingement.source,
            "metric": impingement.content.get("metric", ""),
            "intent_family": impingement.intent_family,
            "dropout_at": None,
            "stages": {},
        }
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
                trace["stages"]["interrupt_handlers"] = len(result)
                trace["winner"] = winner.capability_name if winner else None
                self._emit_dispatch_trace(trace)
                return result
            else:
                # Interrupt token with no registered handler — don't fall through
                # to general retrieval; the token was intended for a specific handler.
                trace["dropout_at"] = "interrupt_no_handler"
                trace["interrupt_token"] = impingement.interrupt_token
                self._emit_dispatch_trace(trace)
                return []
        if self._is_inhibited(impingement):
            trace["dropout_at"] = "inhibited"
            self._emit_dispatch_trace(trace)
            return []
        embedding = self._get_embedding(impingement)
        if embedding is None:
            fallback = self._fallback_keyword_match(impingement)
            trace["dropout_at"] = "no_embedding_fallback" if not fallback else None
            trace["stages"]["fallback_keyword_match"] = len(fallback)
            self._emit_dispatch_trace(trace)
            return fallback
        # Stage 1 routing fix (2026-04-18): if the impingement carries an
        # ``intent_family`` (set by the studio compositor's director on
        # CompositionalImpingements), restrict the recruitment search to
        # capabilities matching that family. Without this, a director
        # "cut to closeup of turntable" tagged camera.hero could be
        # hijacked by a Reverie satellite shader whose Gibson-verb
        # description happened to score higher in cosine similarity.
        # When intent_family is None (the default for non-compositional
        # impingements like sensory deviations), recruitment falls back
        # to the legacy global-catalog scoring behavior.
        if impingement.intent_family:
            candidates = self._retrieve_family(embedding, impingement.intent_family, top_k)
            trace["stages"]["retrieve_family"] = len(candidates)
        else:
            candidates = self._retrieve(embedding, top_k)
            trace["stages"]["retrieve_global"] = len(candidates)
        if not candidates:
            trace["dropout_at"] = (
                "retrieve_family_empty" if impingement.intent_family else "retrieve_global_empty"
            )
            self._emit_dispatch_trace(trace)
            return []
        # Consent gate — closes the audit-surfaced enforcement gap. See
        # _consent_allows() for the rationale and fail-closed semantics.
        candidates = [c for c in candidates if self._consent_allows(c)]
        trace["stages"]["after_consent"] = len(candidates)
        if not candidates:
            trace["dropout_at"] = "consent_filter_empty"
            self._emit_dispatch_trace(trace)
            return []
        # Monetization-risk gate (task #165, plan Phase 1). High-risk always
        # blocked; medium-risk requires a programme opt-in. D-26 (plan
        # Phase 5) wires the active-programme lookup so opt-ins set on the
        # current Programme actually reach the gate. Low/none pass unchanged.
        # D-17: quiet_frame subscriber install. install() is no-op unless
        # HAPAX_QUIET_FRAME_AUTO=1 in env — keeps test imports from
        # accidentally enabling the wire. Idempotent (register_assess_listener
        # dedupes), so calling on every select() is cheap and avoids module-
        # import-time side effects.
        from shared.governance import quiet_frame_subscriber
        from shared.governance.content_risk import GATE as _CONTENT_RISK_GATE
        from shared.governance.monetization_safety import GATE as _MONET_GATE

        quiet_frame_subscriber.install()
        active_programme = self._active_programme_cached()
        candidates = _MONET_GATE.candidate_filter(candidates, programme=active_programme)
        trace["stages"]["after_monetization"] = len(candidates)
        if not candidates:
            trace["dropout_at"] = "monetization_filter_empty"
            self._emit_dispatch_trace(trace)
            return []
        # Content-source registry Phase 1 (PR for plan §1): filter on
        # provenance/ContentID risk independently of monetization_risk.
        # tier_4 unconditionally blocked; tier_3 requires session unlock;
        # tier_2 requires programme opt-in; tier_0/tier_1 pass.
        candidates = _CONTENT_RISK_GATE.candidate_filter(candidates, programme=active_programme)
        trace["stages"]["after_content_risk"] = len(candidates)
        if not candidates:
            trace["dropout_at"] = "content_risk_filter_empty"
            self._emit_dispatch_trace(trace)
            return []
        now = time.time()
        # Preset-variety Phase 3: read recency weight per-call so operator
        # flips take effect on the next recruitment.
        try:
            w_recency = float(os.environ.get(RECENCY_WEIGHT_ENV, W_RECENCY_DEFAULT))
        except (TypeError, ValueError):
            w_recency = W_RECENCY_DEFAULT
        # u8-compositor-preset-bias-consumer: snapshot the per-mode
        # bias once for the whole select() call. get_visual_mode_bias()
        # reads the working-mode file at-call-cost; capturing once per
        # impingement (rather than per-candidate) honors the helper's
        # docstring contract while still flipping within 60s of a
        # `hapax-working-mode` CLI mode change. Defaults to 1.0 for
        # any capability NOT in the PRESET_FAMILY_WEIGHTS table.
        visual_bias = get_visual_mode_bias()
        for c in candidates:
            state = self._activation.get(c.capability_name, ActivationState())
            c.base_level = self._normalize_base_level(state.base_level(now))
            c.context_boost = self._compute_context_boost(c.capability_name, context)
            c.thompson_score = state.thompson_sample()
            # Recency distance: novelty against the rolling window of
            # recently-applied capabilities. The candidate's embedding
            # may live on its payload or on the impingement; fall back to
            # the impingement embedding if the candidate has none.
            candidate_embedding = c.payload.get("embedding") or embedding
            c.recency_distance = self._recency.distance(candidate_embedding)
            cost = 0.3 if c.payload.get("requires_gpu") else 0.0
            if c.payload.get("latency_class") == "slow":
                cost = max(cost, 0.5)
            c.cost_weight = 1.0 - cost * 0.5
            c.exact_recency_penalty = (
                self._recency.exact_match_penalty(c.capability_name, window_size=3) * 0.15
            )
            c.combined = (
                W_SIMILARITY * c.similarity
                + W_BASE_LEVEL * c.base_level
                + W_CONTEXT * c.context_boost
                + W_THOMPSON * c.thompson_score
                + w_recency * c.recency_distance
                - c.exact_recency_penalty
            ) * c.cost_weight
            # Conative action tendency is a small scoring prior, never a
            # candidate filter. This lets a "speak" impulse lean toward
            # narration while preserving competing non-speech affordances.
            c.combined += action_tendency_prior_for_candidate(
                action_tendency=impingement.content.get("action_tendency"),
                strength_posterior=_conative_strength_posterior(impingement),
                capability_name=c.capability_name,
                payload=c.payload,
            )
            # u8-compositor-preset-bias-consumer: mode-aware multiplier
            # on `fx.family.*` candidates per shared/visual_mode_bias.py
            # PRESET_FAMILY_WEIGHTS table. RND favors audio-reactive +
            # glitch-dense; research favors calm-textural + warm-minimal.
            # SOFT-PRIOR multiplier — never a candidate filter. Capability
            # names outside `fx.family.*` pass through with weight 1.0
            # (default in `family_weight()`), so this is a no-op for them.
            if c.capability_name.startswith("fx.family."):
                c.combined *= visual_bias.family_weight(c.capability_name)
        # Phase 4 of programme-layer plan (D-28): apply programme bias as
        # SOFT PRIOR multiplier on the composed score. Per
        # `project_programmes_enable_grounding` memory + spec §5.1: the
        # programme NEVER shrinks the candidate set; bias is a multiplier
        # only. Set-size preservation is a hard architectural invariant
        # (validator on capability_bias_negative rejects 0.0; the helper
        # below preserves len() exactly).
        candidates = self._apply_programme_bias(candidates, active_programme)
        priority = [c for c in candidates if c.payload.get("priority_floor")]
        normal = [c for c in candidates if not c.payload.get("priority_floor")]
        if priority:
            priority.sort(key=lambda c: -c.combined)
            self._log_cascade(impingement, priority)
            trace["stages"]["priority_floor_winners"] = len(priority)
            trace["winner"] = priority[0].capability_name
            trace["winner_combined"] = round(priority[0].combined, 3)
            self._emit_dispatch_trace(trace)
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
        # Audit-closeout 12.3: per-recruitment Prometheus counter, labelled
        # by 6-domain taxonomy. Cardinality is hard-bounded in the helper
        # so a registry extension can't blow up the label set.
        for survivor in survivors:
            _record_recruitment(survivor.capability_name)
        # Threshold-miss detail: when survivors is empty but normal had
        # candidates, capture the top score and the threshold so PR-A2 can
        # see how far below the bar the best score landed.
        trace["stages"]["normal_candidates"] = len(normal)
        trace["stages"]["effective_threshold"] = round(effective_threshold, 4)
        if normal and not survivors:
            top = max(normal, key=lambda c: c.combined)
            trace["dropout_at"] = "threshold_miss"
            trace["top_score"] = round(top.combined, 4)
            trace["top_similarity"] = round(top.similarity, 4)
            trace["top_capability"] = top.capability_name
        elif survivors:
            trace["winner"] = survivors[0].capability_name
            trace["winner_combined"] = round(survivors[0].combined, 4)
            trace["winner_similarity"] = round(survivors[0].similarity, 4)
            trace["survivors"] = len(survivors)
        winner = survivors[0] if survivors else None
        # Preset-variety Phase 3: feed the winner into the recency tracker
        # so the next ``select()`` call scores its peers as more novel.
        # No-op when no winner emerged.
        if winner is not None:
            winner_embedding = winner.payload.get("embedding") or embedding
            self._recency.record_apply(winner.capability_name, winner_embedding)
            # Camera salience broker query (Phase B of
            # bayesian-camera-salience-broker-production-wiring). Attach
            # the salience bundle to the winner payload so downstream
            # capability daemons can ground their decisions in Bayesian
            # camera/IR evidence. Fail-closed: errors swallowed.
            try:
                from shared.camera_salience_singleton import broker as _camera_broker

                _salience_bundle = _camera_broker().query(
                    consumer="affordance",
                    decision_context=f"affordance_select:{impingement.source}",
                    candidate_action=winner.capability_name,
                )
                if _salience_bundle is not None:
                    winner.payload["camera_salience_bundle"] = (
                        _salience_bundle.to_wcs_projection_payload()
                    )
            except Exception:
                log.debug("camera salience affordance query failed", exc_info=True)
            # Phase 6: emit perceptual-distance impingement when the
            # window has clustered above threshold. Cooldown bounded so
            # a sustained cluster doesn't spam the bus.
            self._maybe_emit_perceptual_distance_impingement()
        # Preset-variety Phase 4: decay Thompson posterior on every
        # non-recruited candidate so dormant capabilities recover toward
        # the Beta(2, 1) prior. Disabled by setting the env to "1.0".
        try:
            gamma_unused = float(os.environ.get(THOMPSON_DECAY_ENV, THOMPSON_DECAY_DEFAULT))
        except (TypeError, ValueError):
            gamma_unused = THOMPSON_DECAY_DEFAULT
        if gamma_unused < 1.0:
            winner_name = winner.capability_name if winner is not None else None
            for c in candidates:
                if c.capability_name == winner_name:
                    continue
                state = self._activation.setdefault(c.capability_name, ActivationState())
                state.decay_unused(gamma_unused)
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
        sig = self._exploration.compute_and_publish()
        self._prev_source_hash = source_hash

        # 15th control law: boredom-proportional scoring noise
        _apply_exploration_noise(survivors, sig, self._exploration.sigma_explore)
        survivors.sort(key=lambda c: -c.combined)

        self._emit_dispatch_trace(trace)
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
        """Record a low-level internal/exploration outcome.

        Runtime world outcomes should prefer record_capability_outcome(), which
        gates CapabilityOutcomeEnvelope through witness and learning policy
        before collapsing to this boolean primitive.
        """
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

    def record_capability_outcome(
        self,
        outcome: CapabilityOutcomeEnvelope,
        context: dict[str, Any] | None = None,
    ) -> AffordanceOutcomeDecision:
        """Gate a CapabilityOutcomeEnvelope before mutating learning state."""

        from shared.affordance_outcome_adapter import decide_affordance_outcome_update

        decision = decide_affordance_outcome_update(outcome)
        if decision.should_update:
            if decision.success is None:
                raise ValueError("affordance outcome decision requested update without success")
            self.record_outcome(decision.capability_name, decision.success, context=context)
        return decision

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
        text = render_impingement_text(impingement)
        cached = self._embed_cache.get_by_text(text)
        if cached is not None:
            return cached
        from shared.config import embed_safe

        embedding = embed_safe(text, prefix="search_query")
        if embedding is not None:
            self._embed_cache.put_by_text(text, embedding)
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

    def _retrieve_family(
        self,
        embedding: list[float],
        intent_family: str,
        top_k: int,
    ) -> list[SelectionCandidate]:
        """Family-restricted retrieval — Stage 1 routing fix.

        Pulls a wider candidate window (5× ``top_k``) from Qdrant, then
        keeps only candidates whose ``capability_name`` matches the
        ``intent_family`` prefix. Returns the top-k by similarity.

        Why post-filter rather than push the constraint into the Qdrant
        query: Qdrant payloads currently store ``capability_name`` and
        ``daemon`` but not a structured ``family`` field. Adding one
        would require a schema migration + reseed of the affordances
        collection. Post-filter is correct (we only ever return
        family-matching candidates) and the wider window keeps the
        recall ceiling generous so a low-similarity-but-only-match still
        surfaces.

        ``intent_family`` is matched as a *prefix* against
        ``capability_name``: ``"camera.hero"`` matches
        ``"cam.hero.overhead.vinyl-spinning"`` (after the canonical
        ``camera.hero -> cam.hero`` family-name normalization in
        ``_canonical_family_prefix``). ``"ward.size"`` matches every
        ``ward.size.<ward_id>.<modifier>`` capability. Returns an empty
        list if the family has no registered capabilities OR no
        capabilities scored above the retrieval floor.
        """
        prefix = self._canonical_family_prefix(intent_family)
        if not prefix:
            log.debug(
                "intent_family %s has no canonical capability prefix; "
                "falling through to global retrieval",
                intent_family,
            )
            return self._retrieve(embedding, top_k)
        # Pull a wider window so the post-filter has material to keep.
        wider = self._retrieve(embedding, top_k=max(top_k * 5, 50))
        kept = [c for c in wider if c.capability_name.startswith(prefix)]
        if not kept:
            log.info(
                "family-restricted retrieval (%s, prefix=%s) returned no "
                "candidates from %d-wide window — director impingement "
                "will not recruit anything this tick",
                intent_family,
                prefix,
                len(wider),
            )
            return []
        return sorted(kept, key=lambda c: -c.similarity)[:top_k]

    @staticmethod
    def _canonical_family_prefix(intent_family: str) -> str:
        """Map ``IntentFamily`` literal to the capability-name prefix.

        ``IntentFamily`` values are operator-legible names (``camera.hero``,
        ``preset.bias``); the actual capability catalog uses tighter
        prefixes (``cam.hero``, ``fx.family``). This map keeps the two
        vocabularies aligned without forcing the literal to match the
        prefix character-for-character. Unknown families return the
        family string itself as the prefix — useful for ``ward.*``
        families which already match their capability prefixes.
        """
        canonical = {
            "camera.hero": "cam.hero.",
            "preset.bias": "fx.family.",
            "overlay.emphasis": "overlay.",
            "youtube.direction": "youtube.",
            "attention.winner": "attention.winner.",
            "stream_mode.transition": "stream.mode.",
        }
        if intent_family in canonical:
            return canonical[intent_family]
        # ward.* families already match capability prefixes 1:1
        # (e.g., "ward.size" → "ward.size.")
        if intent_family.startswith("ward."):
            return intent_family + "."
        # Unknown — try literal-as-prefix; better than dropping the
        # family entirely.
        return intent_family + "."

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

    def _maybe_emit_perceptual_distance_impingement(self) -> None:
        """Phase 6: emit ``content.too-similar-recently`` when the recency
        window has clustered above ``PERCEPTUAL_CLUSTER_THRESHOLD``.

        Anti-repetition as IMPINGEMENT, not gate. The surface is told
        "the last N applies have clustered" — recruitment decides whether
        ``novelty.shift`` outweighs whatever the next narrative justifies.
        Cooldown bounded; emission is fail-open (any I/O error is
        swallowed so the hot path never raises).
        """
        cluster_size = len(self._recency.entries)
        if cluster_size < 2:
            return
        cluster_sim = self._recency.cluster_similarity()
        if cluster_sim < PERCEPTUAL_CLUSTER_THRESHOLD:
            return
        now = time.time()
        if (now - self._last_perceptual_emission_at) < PERCEPTUAL_IMPINGEMENT_COOLDOWN_S:
            return
        self._last_perceptual_emission_at = now
        narrative = (
            f"The visual chain has stayed in a similar register for "
            f"the last {cluster_size} applies (cluster similarity "
            f"{cluster_sim:.2f}). Reach for something perceptually "
            f"distant if the moment allows."
        )
        # Build the impingement payload manually to avoid a circular
        # import on Impingement (which depends on shared/affordance via
        # the consent gate metadata).
        payload = {
            "id": uuid.uuid4().hex[:12],
            "timestamp": now,
            "source": "affordance_pipeline.recency",
            "type": "boredom",
            "strength": min(1.0, max(0.0, (cluster_sim - 0.5) * 2.0)),
            "content": {
                "metric": "preset_recency_cluster",
                "cluster_similarity": round(cluster_sim, 3),
                "cluster_size": cluster_size,
                "narrative": narrative,
            },
            "context": {},
            "intent_family": "content.too-similar-recently",
            "embedding": None,
            "interrupt_token": None,
            "parent_id": None,
            "trace_id": None,
            "span_id": None,
        }
        try:
            _PERCEPTUAL_IMPINGEMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with _PERCEPTUAL_IMPINGEMENTS_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
        except OSError:
            from shared.affordance_jsonl_write_metrics import record_write_failure

            record_write_failure("perceptual_impingements")

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
        # Persist the WINNER (top-1) to the recruitment log for the
        # preset-variety baseline / Phase 9 measurement script. Only the
        # top winner is logged — survivors[1:] are tied for ranking but
        # only the top is "applied". Fail-open; logging errors must not
        # break the recruitment hot path.
        self._persist_recruitment_winner(entry)

    def _persist_recruitment_winner(self, entry: dict[str, Any]) -> None:
        """Append the cascade entry's top winner to ``recruitment-log.jsonl``.

        Lightweight payload (no embeddings) — enough to compute the
        per-preset activation count + colorgrade:halftone ratio that the
        Phase 1 baseline script tries to load. Disabled by setting
        ``HAPAX_RECRUITMENT_LOG=0``.
        """
        if os.environ.get(RECRUITMENT_LOG_ENV, "1") == "0":
            return
        winners = entry.get("winners") or []
        if not winners:
            return
        top = winners[0]
        line = {
            "timestamp": entry["timestamp"],
            "capability_name": top.get("name", ""),
            "similarity": top.get("similarity", 0.0),
            "combined": top.get("combined", 0.0),
            "impingement_source": entry.get("source", ""),
            "impingement_metric": entry.get("metric", ""),
        }
        try:
            RECRUITMENT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with RECRUITMENT_LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line) + "\n")
        except OSError:
            from shared.affordance_jsonl_write_metrics import record_write_failure

            record_write_failure("recruitment_log")

    def _emit_dispatch_trace(self, trace: dict[str, Any]) -> None:
        """Append a dispatch-trace JSONL record for the dropout investigation.

        Fail-open; recruitment must never break on logging failure.
        Disabled via ``HAPAX_DISPATCH_TRACE=0``. Each line attributes one
        ``select()`` call to its outcome: ``dropout_at`` names the gate
        that returned [], or stays ``None`` when survivors emerged.
        """
        # Per-outcome Prometheus counter — increment BEFORE the env gate so
        # operators get the in-memory signal even when JSONL is disabled.
        # Pairs with hapax_affordance_recruitment_total + outcome_total.
        from shared.affordance_dispatch_metrics import record_dispatch

        record_dispatch(trace.get("dropout_at"))

        if os.environ.get(DISPATCH_TRACE_ENV, "1") == "0":
            return
        try:
            DISPATCH_TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with DISPATCH_TRACE_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(trace, default=str) + "\n")
        except OSError:
            from shared.affordance_jsonl_write_metrics import record_write_failure

            record_write_failure("dispatch_trace")

    @property
    def recent_cascades(self) -> list[dict[str, Any]]:
        return list(self._cascade_log)

    def get_activation_state(self, capability_name: str) -> ActivationState:
        return self._activation.get(capability_name, ActivationState())

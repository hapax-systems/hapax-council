"""Process-global CameraSalienceBroker singleton.

Provides ``broker()`` for production call sites in the director loop and
affordance pipeline. The broker is instantiated lazily on first call,
loading apertures from the canonical fixture file.

Phase B of cc-task ``bayesian-camera-salience-broker-production-wiring``.

Thread-safe: the singleton is protected by a module-level lock and the
broker's ``evaluate()`` is a pure function of its inputs (no mutation).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from pydantic import ValidationError

from shared.bayesian_camera_salience_world_surface import (
    BAYESIAN_CAMERA_SALIENCE_FIXTURES,
    CameraObservationEnvelope,
    CameraSalienceBroker,
    CameraSalienceBundle,
    CameraSalienceQuery,
    ConsumerKind,
    EvidenceClass,
    ObservationAperture,
    PrivacyMode,
    PublicClaimMode,
)

log = logging.getLogger(__name__)

_lock = threading.Lock()
_singleton: _BrokerSingleton | None = None
_QUERY_COUNTER: Any = None
_METRICS_AVAILABLE = False

try:
    from prometheus_client import REGISTRY, Counter

    _registry = REGISTRY
    try:
        from agents.studio_compositor import metrics as _compositor_metrics

        if _compositor_metrics.REGISTRY is not None:
            _registry = _compositor_metrics.REGISTRY
    except Exception:
        pass

    _existing = getattr(_registry, "_names_to_collectors", {}).get(
        "camera_salience_broker_queries"
    ) or getattr(_registry, "_names_to_collectors", {}).get("camera_salience_broker_queries_total")
    _QUERY_COUNTER = _existing or Counter(
        "camera_salience_broker_queries_total",
        "Camera salience broker query attempts by consumer.",
        ("consumer",),
        registry=_registry,
    )
    _METRICS_AVAILABLE = True
except Exception:
    log.info("prometheus_client unavailable; camera salience query metric disabled")


def _record_query_metric(consumer: str) -> None:
    try:
        if _METRICS_AVAILABLE and _QUERY_COUNTER is not None:
            _QUERY_COUNTER.labels(consumer=consumer).inc()
    except Exception:
        log.debug("camera salience query metric emit failed", exc_info=True)


class _BrokerSingleton:
    """Wrapper holding apertures + rolling observation window."""

    def __init__(self, apertures: tuple[ObservationAperture, ...]) -> None:
        self._apertures = apertures
        self._observations: list[CameraObservationEnvelope] = []
        self._obs_lock = threading.Lock()
        self._max_window = 500  # rolling window size

    def ingest(self, envelope: CameraObservationEnvelope | None) -> None:
        """Ingest a producer envelope into the rolling window.

        ``None`` envelopes (adapter fail-closed) are silently dropped.
        """
        if envelope is None:
            return
        with self._obs_lock:
            self._observations.append(envelope)
            # Trim oldest observations beyond the rolling window
            if len(self._observations) > self._max_window:
                self._observations = self._observations[-self._max_window :]

    def query(
        self,
        *,
        consumer: str,
        decision_context: str,
        candidate_action: str,
        evidence_classes: tuple[EvidenceClass, ...] | None = None,
        time_budget_ms: int = 50,
        max_images: int = 0,
        max_tokens: int = 200,
        privacy_mode: PrivacyMode = PrivacyMode.PRIVATE,
    ) -> CameraSalienceBundle | None:
        """Query the broker. Returns ``None`` on any error (fail-closed)."""
        _record_query_metric(consumer)
        try:
            with self._obs_lock:
                observations = tuple(self._observations)
            if not observations:
                return None

            broker = CameraSalienceBroker(
                apertures=self._apertures,
                observations=observations,
            )
            query_obj = CameraSalienceQuery(
                query_id=f"camera-salience-query:{consumer}.{time.time_ns()}",
                consumer=ConsumerKind(consumer),
                decision_context=decision_context,
                candidate_action=candidate_action,
                time_budget_ms=time_budget_ms,
                privacy_mode=privacy_mode,
                public_claim_mode=PublicClaimMode.NONE,
                evidence_classes=evidence_classes
                or (
                    EvidenceClass.FRAME,
                    EvidenceClass.IR_PRESENCE,
                    EvidenceClass.COMPOSED_LIVESTREAM,
                ),
                max_images=max_images,
                max_tokens=max_tokens,
            )
            return broker.evaluate(query_obj)
        except (ValidationError, ValueError, KeyError, TypeError):
            log.debug("camera salience query failed", exc_info=True)
            return None
        except Exception:
            log.debug("camera salience query unexpected error", exc_info=True)
            return None

    @property
    def observation_count(self) -> int:
        with self._obs_lock:
            return len(self._observations)


def broker() -> _BrokerSingleton:
    """Return the process-global broker singleton (lazy init)."""
    global _singleton
    if _singleton is not None:
        return _singleton
    with _lock:
        if _singleton is not None:
            return _singleton
        apertures = _load_apertures()
        _singleton = _BrokerSingleton(apertures)
        log.info(
            "CameraSalienceBroker singleton initialized (%d apertures)",
            len(apertures),
        )
        return _singleton


def _load_apertures() -> tuple[ObservationAperture, ...]:
    """Load apertures from the canonical fixture file."""
    try:
        raw = json.loads(BAYESIAN_CAMERA_SALIENCE_FIXTURES.read_text())
        return tuple(ObservationAperture.model_validate(a) for a in raw.get("apertures", []))
    except (FileNotFoundError, json.JSONDecodeError, ValidationError):
        log.warning("Failed to load camera salience fixtures; using empty apertures")
        return ()


def _reset_for_testing() -> None:
    """Reset the singleton — test-only."""
    global _singleton
    with _lock:
        _singleton = None


__all__ = ["broker", "_reset_for_testing"]

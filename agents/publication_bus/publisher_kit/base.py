"""V5 publication-bus Publisher ABC (one-shot publish-on-demand).

Per V5 weave §2.1 PUB-P0-B keystone. Three load-bearing invariants
every v5 publisher enforces, all baked into the superclass
``publish()`` method so subclasses cannot opt out:

1. Allowlist gate (:class:`AllowlistGate.permits`)
2. Legal-name-leak guard (``assert_no_leak``) — only when
   ``requires_legal_name`` is False (rare-case opt-in for formal-
   required surfaces like Zenodo creators array)
3. Counter (Prometheus per-surface per-result)

Subclass shape is ~80 LOC: surface metadata as ClassVar + ``_emit()``
override.

Distinction from v4 ``shared.governance.publisher_kit.BasePublisher``:
- v4 is a JSONL-event-tailing daemon: subclass overrides
  ``compose(event)`` + ``send(composed)``; suitable for cross-surface
  social posting (bsky / mastodon / arena / discord) where events
  stream from a queue.
- v5 (this module) is one-shot publish-on-demand: subclass overrides
  ``_emit(payload)``; suitable for capacity-surface long-form
  publication (Zenodo, OSF, philarchive) where each artifact is
  published once-per-version on operator-trigger.

Both ABCs share the same three invariants. Cross-surface publishers
stay on v4; new long-form publishers use v5.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

try:
    from prometheus_client import REGISTRY, CollectorRegistry, Counter
except ImportError:  # pragma: no cover — prometheus not always installed in dev shells
    Counter = None  # type: ignore[assignment]
    REGISTRY = None  # type: ignore[assignment]
    CollectorRegistry = None  # type: ignore[assignment]

from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    AllowlistViolation,
)
from agents.publication_bus.publisher_kit.legal_name_guard import (
    LegalNameLeak,
    assert_no_leak,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublisherPayload:
    """One publish-event's payload.

    Carries the artifact text + target identifier + optional metadata
    that the subclass ``_emit()`` consumes. The ``target`` is what
    the allowlist gate matches against; the ``text`` is what the
    legal-name guard scans.
    """

    target: str
    text: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PublisherResult:
    """One publish-event's outcome.

    ``ok`` is True for successful emit; ``refused`` is True for
    allowlist-deny or legal-name-leak; ``error`` is True for transient
    transport failures. Exactly one of the three is True.

    ``detail`` is a short human-readable string for observability;
    publishers should not include sensitive content (the legal-name
    guard's match-substring is excluded by the superclass before
    construction).
    """

    ok: bool = False
    refused: bool = False
    error: bool = False
    detail: str = ""


class Publisher(ABC):
    """V5 publication-bus base class.

    Subclasses set the four required ClassVar fields and override
    ``_emit()``. The base owns the three invariants:

    1. Allowlist gate — checked before ``_emit()``
    2. Legal-name-leak guard — checked before ``_emit()`` unless
       ``requires_legal_name`` is True
    3. Counter — incremented on every result outcome

    Subclasses do NOT call ``_emit()`` directly; they call
    ``publish(payload)``, which runs the invariants then dispatches
    to ``_emit()``.
    """

    # ── Required ClassVar metadata ────────────────────────────────

    surface_name: ClassVar[str]
    """Stable per-surface identifier (e.g., ``zenodo-deposit``).
    Used as the Prometheus counter label and the AllowlistGate
    surface_name."""

    allowlist: ClassVar[AllowlistGate]
    """Per-surface allowlist of permitted target identifiers."""

    requires_legal_name: ClassVar[bool] = False
    """When True, the legal-name guard is skipped — the surface
    formally requires the operator's legal name (Zenodo creators,
    ORCID record, CITATION.cff). Default False (most surfaces use
    the operator-referent picker)."""

    # ── Counter wiring (lazy-init via class method) ────────────────

    _counter: ClassVar[object | None] = None

    @classmethod
    def _get_counter(cls):
        """Lazy-init the Prometheus counter for this publisher class.

        Defers Counter construction until first publish() call so
        modules that import Publisher subclasses don't pay the
        registration cost at import time. Per-class counters share
        the same metric name with subclass-specific labels via
        ``surface_name``.
        """
        if Counter is None:
            return None
        if cls._counter is None:
            try:
                cls._counter = Counter(
                    "hapax_publication_bus_publishes_total",
                    "Per-surface publish-event outcome count",
                    ["surface", "result"],
                )
            except ValueError:
                # Counter already registered (e.g., in test re-import); look up.
                cls._counter = REGISTRY._names_to_collectors.get(
                    "hapax_publication_bus_publishes_total"
                )
        return cls._counter

    # ── Public publish() — the load-bearing entry point ────────────

    def publish(self, payload: PublisherPayload) -> PublisherResult:
        """Publish ``payload`` after enforcing the three invariants.

        Returns a :class:`PublisherResult` with exactly one of
        ``ok`` / ``refused`` / ``error`` set. Never raises (subclass
        ``_emit()`` errors are caught and reported as ``error=True``).
        """
        counter = self._get_counter()

        # 1. Allowlist gate
        try:
            self.allowlist.assert_permits(payload.target)
        except AllowlistViolation as exc:
            log.warning("publication_bus: refused — allowlist deny: %s", exc)
            if counter is not None:
                counter.labels(surface=self.surface_name, result="refused").inc()
            return PublisherResult(
                refused=True,
                detail=f"allowlist deny: target {payload.target!r}",
            )

        # 2. Legal-name-leak guard (unless surface formally requires it)
        if not self.requires_legal_name:
            try:
                assert_no_leak(payload.text, segment_id=payload.target)
            except LegalNameLeak:
                log.warning(
                    "publication_bus: refused — legal-name leak on surface %s",
                    self.surface_name,
                    # Note: the exception message includes the matched
                    # substring; do NOT include it in operator-visible
                    # detail to avoid re-emission.
                )
                if counter is not None:
                    counter.labels(surface=self.surface_name, result="refused").inc()
                return PublisherResult(
                    refused=True,
                    detail="legal-name leak detected",
                )

        # 3. Emit (subclass-specific transport)
        try:
            result = self._emit(payload)
        except Exception:
            log.exception("publication_bus: error in subclass _emit")
            if counter is not None:
                counter.labels(surface=self.surface_name, result="error").inc()
            return PublisherResult(error=True, detail="subclass _emit raised")

        # Record outcome on the counter.
        if counter is not None:
            label = "ok" if result.ok else ("refused" if result.refused else "error")
            counter.labels(surface=self.surface_name, result=label).inc()

        return result

    # ── Subclass override ─────────────────────────────────────────

    @abstractmethod
    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        """Subclass-specific transport + serialization.

        Called by ``publish()`` AFTER the allowlist gate and
        legal-name-leak guard pass. Subclass owns: API client setup,
        request composition, response handling. Returns a
        :class:`PublisherResult` reflecting the transport outcome.

        May raise; the superclass catches and reports as
        ``error=True``.
        """


__all__ = [
    "Publisher",
    "PublisherPayload",
    "PublisherResult",
]

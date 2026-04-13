"""Per-producer freshness contracts for always-on loops.

Phase 8 of the reverie source registry completion epic (closes
BETA-FINDING-2026-04-13-C). Every always-on producer that contains a
``try/except + log.warning + return`` shape — the pattern that masked
``hapax-imagination-loop`` for 62 hours during the 2026-04-13 discovery
sweep — MUST own a :class:`FreshnessGauge` instance. The gauge
publishes:

- ``{name}_published_total`` — monotonic counter of successful ticks.
  Alerts fire when this stops incrementing.
- ``{name}_failed_total`` — monotonic counter of failed ticks (the
  ``except`` branches). Lets operators see the failure mode without
  journal grepping.
- ``{name}_age_seconds`` — gauge, seconds since the last successful
  tick (``+inf`` before the first publish). Health monitor asks this
  ``is_stale()`` on its periodic check.

Usage::

    from shared.freshness_gauge import FreshnessGauge

    class MyLoop:
        def __init__(self) -> None:
            self._freshness = FreshnessGauge(
                "my_loop_fragments", expected_cadence_s=30.0
            )

        def tick(self) -> None:
            try:
                self._do_work()
                self._freshness.mark_published()
            except Exception:
                log.warning("tick failed", exc_info=True)
                self._freshness.mark_failed()

The health monitor's periodic check then reads
``loop._freshness.is_stale(tolerance_mult=10)`` and flags the producer
when the age exceeds ``10 × expected_cadence_s``. Freshness is the
single contract that defeats the silent-mask pattern.

The gauge is resilient to missing ``prometheus_client`` — if the module
isn't importable, every method is a no-op and ``age_seconds`` /
``is_stale`` still work via the in-memory timestamp, so the health
monitor path stays functional on test machines without the full
observability stack.
"""

from __future__ import annotations

import logging
import re
import time

log = logging.getLogger(__name__)

_VALID_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


try:
    from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False
    REGISTRY = None  # type: ignore[assignment]
    CollectorRegistry = None  # type: ignore[assignment,misc]
    Counter = None  # type: ignore[assignment,misc]
    Gauge = None  # type: ignore[assignment,misc]


class FreshnessGauge:
    """Bounded age + publish/fail counter contract for an always-on producer.

    Construct once per producer (typically in ``__init__``). Call
    :meth:`mark_published` on every successful tick and :meth:`mark_failed`
    inside every ``except`` branch. Health monitors read
    :meth:`is_stale` on their periodic check and flag producers whose
    age exceeds ``expected_cadence_s × tolerance_mult``.

    Parameters
    ----------
    name
        Prometheus metric namespace. Must match ``[a-z_][a-z0-9_]*``
        (Prometheus convention). Used as the prefix for the three
        metrics. Duplicate names across the process get a unique
        suffix automatically so tests can instantiate multiple gauges
        with the same logical name.
    expected_cadence_s
        Nominal tick period in seconds. Drives the default
        :meth:`is_stale` threshold (``10 × cadence`` by default).
    registry
        Prometheus collector registry. Defaults to the global
        ``REGISTRY``; tests pass a fresh ``CollectorRegistry`` to
        isolate metrics. Ignored when ``prometheus_client`` isn't
        importable.
    """

    _registered_names: set[str] = set()

    def __init__(
        self,
        name: str,
        expected_cadence_s: float,
        *,
        registry: object | None = None,
    ) -> None:
        if not _VALID_NAME.fullmatch(name):
            msg = (
                f"FreshnessGauge name {name!r} must match "
                "[a-z_][a-z0-9_]* (Prometheus naming convention)"
            )
            raise ValueError(msg)
        if expected_cadence_s <= 0:
            msg = f"expected_cadence_s must be > 0, got {expected_cadence_s}"
            raise ValueError(msg)
        self._name = name
        self._expected_cadence_s = float(expected_cadence_s)
        self._last_published_at: float | None = None
        self._published_count = 0
        self._failed_count = 0
        self._published_counter: object | None = None
        self._failed_counter: object | None = None
        self._age_gauge: object | None = None
        if _PROMETHEUS_AVAILABLE:
            self._build_prometheus_metrics(registry)

    def _build_prometheus_metrics(self, registry: object | None) -> None:
        reg = registry if registry is not None else REGISTRY
        # Prometheus rejects duplicate names in the same registry. Tests
        # that construct multiple gauges with the same logical name (or
        # that run twice in the same process) need an isolated registry;
        # we catch ``ValueError`` here so production callers that reuse
        # the global registry don't blow up on module reimport (pytest
        # reload etc.).
        try:
            self._published_counter = Counter(  # type: ignore[misc]
                f"{self._name}_published_total",
                f"Successful tick count for {self._name}",
                registry=reg,
            )
            self._failed_counter = Counter(  # type: ignore[misc]
                f"{self._name}_failed_total",
                f"Failed tick count for {self._name}",
                registry=reg,
            )
            gauge = Gauge(  # type: ignore[misc]
                f"{self._name}_age_seconds",
                f"Seconds since the last successful tick of {self._name}",
                registry=reg,
            )
            gauge.set_function(self.age_seconds)
            self._age_gauge = gauge
        except ValueError:
            log.debug(
                "FreshnessGauge %s: prometheus duplicate registration, "
                "falling back to in-memory counters",
                self._name,
                exc_info=True,
            )

    def mark_published(self) -> None:
        """Record a successful tick — resets the age + increments the counter."""
        self._last_published_at = time.monotonic()
        self._published_count += 1
        if self._published_counter is not None:
            self._published_counter.inc()  # type: ignore[attr-defined]

    def mark_failed(self) -> None:
        """Record a failed tick — does not reset the age."""
        self._failed_count += 1
        if self._failed_counter is not None:
            self._failed_counter.inc()  # type: ignore[attr-defined]

    def age_seconds(self) -> float:
        """Seconds since the last successful tick, or ``+inf`` if never."""
        if self._last_published_at is None:
            return float("inf")
        return time.monotonic() - self._last_published_at

    def is_stale(self, tolerance_mult: float = 10.0) -> bool:
        """Return ``True`` when ``age_seconds > expected_cadence_s * mult``."""
        return self.age_seconds() > self._expected_cadence_s * tolerance_mult

    @property
    def name(self) -> str:
        return self._name

    @property
    def published_count(self) -> int:
        """Test helper — total mark_published() calls."""
        return self._published_count

    @property
    def failed_count(self) -> int:
        """Test helper — total mark_failed() calls."""
        return self._failed_count

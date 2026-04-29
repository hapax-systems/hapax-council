"""Chronicle quality exporter — content-quality Prometheus metrics.

Reads ``/dev/shm/hapax-chronicle/events.jsonl`` on a 30 s tick, computes
rolling-window aggregates over content-quality fields embedded in event
payloads, exports as Prometheus gauges + a histogram on
``http://127.0.0.1:9495/metrics``.

## Metrics

- ``hapax_content_salience_mean_5m``  Gauge — mean salience over a
  5-minute window. ``NaN`` when no events in the window carry a
  salience field (caller-side dashboards should treat NaN as
  "no data" rather than 0).
- ``hapax_content_salience_distribution``  Histogram — salience values
  observed since process start (cumulative; Prometheus histogram
  semantics).
- ``hapax_content_intent_family_cardinality_1h``  Gauge — distinct
  ``intent_family`` values seen in the last 60 minutes.
- ``hapax_content_material_distribution{material}``  Gauge — fraction
  of last-5-minute events per material slot
  (water/fire/earth/air/void). Slots with zero events report 0.0;
  the gauge family is closed over the canonical set so dashboards
  always see all five.
- ``hapax_content_grounding_coverage_5m``  Gauge — fraction of
  last-5-minute events whose payload carries non-null
  ``grounding_provenance``. Quality dimension separate from salience.
- ``hapax_chronicle_event_rate_per_min{source}``  Gauge — events/min
  per chronicle source over the last 5 minutes.
- ``hapax_chronicle_export_tick_duration_seconds``  Histogram —
  exporter's own tick latency (sanity gauge: if tick > 30 s the
  exporter is the slow link, not the chronicle).

The cc-task spec mentions a ``hapax_chronicle_latency_p99_ms`` (event
emit-to-queryable). That requires emit-time + query-time pairing on
each event, which is per-event OTel span instrumentation rather than
post-hoc chronicle analysis — out of scope for this exporter.
Replaced with the simpler tick-duration histogram above; original
metric is filed back to ytb-QM-LATENCY.

## Cost

Tick walks the chronicle file. ~50k events typical (12 h retention,
~70/min average). At 30 s tick rate that's <1% CPU on a single core.
Reuses ``shared.chronicle.query`` so we get the reverse-walk early-exit
optimisation already shipped in drop #23.

## Failure mode

If the chronicle file is missing or unreadable, the tick logs once
(throttled) and reports stale gauges. The exporter never raises out
of its tick loop — Prometheus scrape sees the last known values
until events resume.

Spec: ytb-QM1; depends on chronicle (shipped).
"""

from __future__ import annotations

import logging
import math
import os
import signal as _signal
import threading
import time as _time
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from prometheus_client import REGISTRY, CollectorRegistry, Gauge, Histogram, start_http_server

from shared.chronicle import CHRONICLE_FILE, ChronicleEvent, query

log = logging.getLogger(__name__)

# Default Prometheus scrape port. 9494 is taken by hapax-live-cuepoints
# (see ``systemd/units/hapax-live-cuepoints.service``); next free is 9495.
# Override via ``HAPAX_CHRONICLE_QUALITY_METRICS_PORT`` env var.
METRICS_PORT: int = int(os.environ.get("HAPAX_CHRONICLE_QUALITY_METRICS_PORT", "9495"))

# Tick cadence. 30 s matches the Prometheus default scrape interval —
# faster tick is wasted aggregation, slower would let the gauge lag
# behind one scrape interval.
DEFAULT_TICK_S: float = float(os.environ.get("HAPAX_CHRONICLE_QUALITY_TICK_S", "30"))

# Window sizes per the spec.
WINDOW_5M_S: float = 300.0
WINDOW_1H_S: float = 3600.0

# Canonical material slots (`shared/imagination_state.py` materials map).
# Closed over so the gauge family always reports all five — dashboards
# don't need to special-case "no events" vs "missing slot".
CANONICAL_MATERIALS: tuple[str, ...] = ("water", "fire", "earth", "air", "void")

# Histogram salience buckets — covers the 0.0–1.0 range used everywhere.
_SALIENCE_BUCKETS: tuple[float, ...] = (
    0.05,
    0.1,
    0.2,
    0.3,
    0.4,
    0.5,
    0.6,
    0.7,
    0.8,
    0.9,
    1.0,
)


def _payload_field(event: ChronicleEvent, field: str) -> Any:
    """Pull a top-level payload field, tolerating missing payloads."""
    payload = event.payload if isinstance(event.payload, dict) else {}
    return payload.get(field)


def _coerce_float(value: object) -> float | None:
    """Coerce numeric-looking values to float; reject bool / non-numeric."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _is_grounded(event: ChronicleEvent) -> bool | None:
    """Return True if the event carries real, non-synthetic grounding_provenance.

    Returns None (not False) when the field is absent — events that
    don't even claim to be groundable shouldn't drag the coverage
    fraction down.
    """
    from shared.director_intent import split_grounding_provenance

    prov = _payload_field(event, "grounding_provenance")
    if prov is None:
        return None
    if isinstance(prov, dict):
        return bool(prov)
    if isinstance(prov, str):
        real, _synthetic = split_grounding_provenance([prov])
        return bool(real)
    if isinstance(prov, (list, tuple)):
        real, _synthetic = split_grounding_provenance([str(entry) for entry in prov])
        return bool(real)
    return None


class ChronicleQualityExporter:
    """30 s-tick exporter computing content-quality aggregates.

    Stateless across ticks — every tick reads the chronicle window
    fresh. No in-memory event buffer; the chronicle file IS the
    durable record.

    Tests construct an exporter with ``registry=CollectorRegistry()``
    to avoid clobbering the global Prometheus registry across test
    runs; production passes the global ``REGISTRY``.
    """

    def __init__(
        self,
        *,
        chronicle_path: Path = CHRONICLE_FILE,
        registry: CollectorRegistry = REGISTRY,
        tick_s: float = DEFAULT_TICK_S,
    ) -> None:
        self._path = chronicle_path
        self._tick_s = max(1.0, tick_s)
        self._stop_evt = threading.Event()
        self._chronicle_unreadable_warned = False

        # Gauge / Histogram registration. Use the supplied registry so
        # tests don't accumulate metrics across runs.
        self.salience_mean_5m = Gauge(
            "hapax_content_salience_mean_5m",
            "Mean salience over the last 5 minutes (NaN when no salience-bearing events).",
            registry=registry,
        )
        self.salience_distribution = Histogram(
            "hapax_content_salience_distribution",
            "Salience values observed (cumulative since process start).",
            buckets=_SALIENCE_BUCKETS,
            registry=registry,
        )
        self.intent_family_cardinality_1h = Gauge(
            "hapax_content_intent_family_cardinality_1h",
            "Distinct intent_family values seen in the last 60 minutes.",
            registry=registry,
        )
        self.material_distribution = Gauge(
            "hapax_content_material_distribution",
            "Fraction of last-5-minute events per material slot.",
            ["material"],
            registry=registry,
        )
        self.grounding_coverage_5m = Gauge(
            "hapax_content_grounding_coverage_5m",
            "Fraction of last-5-minute events with non-null grounding_provenance.",
            registry=registry,
        )
        self.event_rate_per_min = Gauge(
            "hapax_chronicle_event_rate_per_min",
            "Chronicle events/min per source over last 5 minutes.",
            ["source"],
            registry=registry,
        )
        self.tick_duration = Histogram(
            "hapax_chronicle_export_tick_duration_seconds",
            "Exporter tick latency. >30s means the exporter is the slow link.",
            registry=registry,
        )

        # Pre-zero material slots so dashboards see all five from t=0.
        for slot in CANONICAL_MATERIALS:
            self.material_distribution.labels(material=slot).set(0.0)

    # ── Public API ────────────────────────────────────────────────────

    def tick_once(self, *, now: float | None = None) -> None:
        """Compute one tick of aggregates and update gauges.

        Tests drive this directly. The daemon loop calls it on a
        timer.
        """
        now = _time.time() if now is None else now
        with self.tick_duration.time():
            try:
                events_5m = query(
                    since=now - WINDOW_5M_S,
                    until=now,
                    limit=100_000,
                    path=self._path,
                )
                events_1h = query(
                    since=now - WINDOW_1H_S,
                    until=now,
                    limit=100_000,
                    path=self._path,
                )
            except Exception:  # noqa: BLE001
                if not self._chronicle_unreadable_warned:
                    log.warning(
                        "chronicle unreadable at %s; reporting stale gauges",
                        self._path,
                        exc_info=True,
                    )
                    self._chronicle_unreadable_warned = True
                return

            self._chronicle_unreadable_warned = False  # recovered
            self._update_salience(events_5m)
            self._update_intent_cardinality(events_1h)
            self._update_material_distribution(events_5m)
            self._update_grounding_coverage(events_5m)
            self._update_event_rate(events_5m)

    def run_forever(self) -> None:
        """Blocking daemon loop — tick on cadence until SIGTERM/SIGINT.

        Sets up SIGTERM/SIGINT handlers that flip the stop event so
        systemd's ``Restart=on-failure`` semantics work cleanly (clean
        exit on stop signal, restart on raise).
        """
        for sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(sig, lambda *_: self._stop_evt.set())
            except ValueError:
                # Not on the main thread — tests use this path.
                pass

        log.info(
            "chronicle quality exporter starting, port=%d tick=%.1fs",
            METRICS_PORT,
            self._tick_s,
        )
        while not self._stop_evt.is_set():
            try:
                self.tick_once()
            except Exception:  # noqa: BLE001
                log.exception("tick failed; continuing on next cadence")
            self._stop_evt.wait(self._tick_s)

    def stop(self) -> None:
        """Signal the daemon loop to exit at the next cadence."""
        self._stop_evt.set()

    # ── Per-metric updates ────────────────────────────────────────────

    def _update_salience(self, events: Iterable[ChronicleEvent]) -> None:
        values: list[float] = []
        for ev in events:
            v = _coerce_float(_payload_field(ev, "salience"))
            if v is not None:
                values.append(v)
                self.salience_distribution.observe(v)
        self.salience_mean_5m.set(sum(values) / len(values) if values else math.nan)

    def _update_intent_cardinality(self, events: Iterable[ChronicleEvent]) -> None:
        seen: set[str] = set()
        for ev in events:
            fam = _payload_field(ev, "intent_family")
            if isinstance(fam, str) and fam:
                seen.add(fam)
        self.intent_family_cardinality_1h.set(float(len(seen)))

    def _update_material_distribution(self, events: Iterable[ChronicleEvent]) -> None:
        counts: Counter[str] = Counter()
        total = 0
        for ev in events:
            mat = _payload_field(ev, "material")
            if isinstance(mat, str) and mat in CANONICAL_MATERIALS:
                counts[mat] += 1
                total += 1
        for slot in CANONICAL_MATERIALS:
            fraction = (counts.get(slot, 0) / total) if total > 0 else 0.0
            self.material_distribution.labels(material=slot).set(fraction)

    def _update_grounding_coverage(self, events: Iterable[ChronicleEvent]) -> None:
        considered = 0
        grounded = 0
        for ev in events:
            verdict = _is_grounded(ev)
            if verdict is None:
                continue
            considered += 1
            if verdict:
                grounded += 1
        self.grounding_coverage_5m.set((grounded / considered) if considered > 0 else math.nan)

    def _update_event_rate(self, events_5m: list[ChronicleEvent]) -> None:
        per_source: Counter[str] = Counter()
        for ev in events_5m:
            per_source[ev.source] += 1
        # 5-minute window → divide by 5 to get events/min.
        for source, count in per_source.items():
            self.event_rate_per_min.labels(source=source).set(count / 5.0)


def main() -> None:
    """Daemon entry point — `python -m agents.quality_observability.chronicle_exporter`."""
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    start_http_server(METRICS_PORT, addr="127.0.0.1")
    exporter = ChronicleQualityExporter()
    exporter.run_forever()


if __name__ == "__main__":
    main()

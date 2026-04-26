"""YouTube Data API v3 quota Prometheus exporter (ytb-001).

60 s tick. Polls Cloud Monitoring via :class:`QuotaClient`, exports
``hapax_broadcast_yt_*`` Prometheus gauges on
``http://127.0.0.1:9497/metrics``.

## Metrics

- ``hapax_broadcast_yt_quota_units_used`` Gauge — daily-cumulative
  units consumed since UTC midnight (resets at GCP quota refresh).
- ``hapax_broadcast_yt_quota_remaining`` Gauge — units remaining
  before today's cap.
- ``hapax_broadcast_yt_quota_rate_per_min`` Gauge — units / minute
  averaged over the last 5 minutes.
- ``hapax_broadcast_yt_quota_exhaustion_estimate_s`` Gauge — seconds
  until projected cap exhaustion at the current rate. ``+Inf`` when
  the rate is zero (no projected exhaustion). ``0`` when the cap is
  already at or past zero.
- ``hapax_broadcast_yt_quota_alert_active`` Gauge — 1 when used /
  cap >= ``alert_threshold`` (default 0.8), else 0. Single-source
  for ntfy alerting via the existing prometheus-alertmanager chain.
- ``hapax_broadcast_yt_quota_export_tick_duration_seconds`` Histogram
  — exporter tick latency.

## Failure mode

Cloud Monitoring read failures are logged once-per-recurrence
(throttled by warning state) and the previous gauge values stay
visible to Prometheus. The tick loop never raises.

## Cost

One Cloud Monitoring read per tick (60 s). Three metric series per
read. Well under any per-minute API quota.
"""

from __future__ import annotations

import logging
import math
import os
import signal as _signal
import threading

from prometheus_client import REGISTRY, CollectorRegistry, Gauge, Histogram, start_http_server

from agents.quota_observability.client import QuotaClient, project_id_from_env

log = logging.getLogger(__name__)

METRICS_PORT: int = int(os.environ.get("HAPAX_QUOTA_METRICS_PORT", "9497"))
DEFAULT_TICK_S: float = float(os.environ.get("HAPAX_QUOTA_TICK_S", "60"))
DEFAULT_ALERT_THRESHOLD: float = float(os.environ.get("HAPAX_QUOTA_ALERT_THRESHOLD", "0.8"))


class QuotaExporter:
    """60 s-tick exporter polling Cloud Monitoring for YouTube quota state.

    Tests construct with a mocked :class:`QuotaClient` and a fresh
    ``CollectorRegistry``; production lets defaults flow through.
    """

    def __init__(
        self,
        *,
        client: QuotaClient,
        registry: CollectorRegistry = REGISTRY,
        tick_s: float = DEFAULT_TICK_S,
        alert_threshold: float = DEFAULT_ALERT_THRESHOLD,
    ) -> None:
        if not 0.0 < alert_threshold <= 1.0:
            raise ValueError("alert_threshold must be in (0, 1]")
        self._client = client
        self._tick_s = max(1.0, tick_s)
        self._alert_threshold = alert_threshold
        self._stop_evt = threading.Event()
        self._read_warned = False

        self.units_used = Gauge(
            "hapax_broadcast_yt_quota_units_used",
            "YouTube Data API v3 units consumed today (resets at UTC midnight).",
            registry=registry,
        )
        self.units_remaining = Gauge(
            "hapax_broadcast_yt_quota_remaining",
            "YouTube Data API v3 units remaining before today's cap.",
            registry=registry,
        )
        self.rate_per_min = Gauge(
            "hapax_broadcast_yt_quota_rate_per_min",
            "YouTube Data API v3 units / minute over the last 5 minutes.",
            registry=registry,
        )
        self.exhaustion_estimate_s = Gauge(
            "hapax_broadcast_yt_quota_exhaustion_estimate_s",
            "Seconds until cap exhaustion at the current rate (+Inf if rate=0).",
            registry=registry,
        )
        self.alert_active = Gauge(
            "hapax_broadcast_yt_quota_alert_active",
            "1 when used/cap >= alert_threshold; consumed by alertmanager → ntfy.",
            registry=registry,
        )
        self.tick_duration = Histogram(
            "hapax_broadcast_yt_quota_export_tick_duration_seconds",
            "Exporter tick latency. >tick_s means cloud monitoring is the slow link.",
            registry=registry,
        )

    # ── Public API ────────────────────────────────────────────────────

    def tick_once(self, *, now: float | None = None) -> None:
        """Pull one quota sample and update gauges.

        Tests drive this directly; the daemon loop fires it on cadence.
        """
        with self.tick_duration.time():
            try:
                sample = self._client.read_sample(now=now)
            except Exception:  # noqa: BLE001
                if not self._read_warned:
                    log.warning(
                        "quota client read failed; reporting stale gauges",
                        exc_info=True,
                    )
                    self._read_warned = True
                return
            self._read_warned = False  # recovered
            self._publish(sample.used_units, sample.daily_cap_units, sample.rate_per_min)

    def run_forever(self) -> None:
        for sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(sig, lambda *_: self._stop_evt.set())
            except ValueError:
                pass

        log.info(
            "quota exporter starting, port=%d tick=%.1fs project=%s",
            METRICS_PORT,
            self._tick_s,
            self._client.project_id,
        )
        while not self._stop_evt.is_set():
            try:
                self.tick_once()
            except Exception:  # noqa: BLE001
                log.exception("tick failed; continuing on next cadence")
            self._stop_evt.wait(self._tick_s)

    def stop(self) -> None:
        self._stop_evt.set()

    # ── Metric publication ────────────────────────────────────────────

    def _publish(self, used: float, cap: float, rate_per_min: float) -> None:
        used = max(0.0, used)
        cap = max(0.0, cap)
        remaining = max(0.0, cap - used)
        self.units_used.set(used)
        self.units_remaining.set(remaining)
        self.rate_per_min.set(max(0.0, rate_per_min))
        self.exhaustion_estimate_s.set(self._estimate_exhaustion(remaining, rate_per_min))
        self.alert_active.set(self._alert_value(used, cap))

    def _estimate_exhaustion(self, remaining: float, rate_per_min: float) -> float:
        if rate_per_min <= 0.0:
            return math.inf
        if remaining <= 0.0:
            return 0.0
        return (remaining / rate_per_min) * 60.0

    def _alert_value(self, used: float, cap: float) -> float:
        if cap <= 0.0:
            return 0.0
        return 1.0 if (used / cap) >= self._alert_threshold else 0.0


def main() -> None:
    """Daemon entry — `python -m agents.quota_observability`."""
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    project_id = project_id_from_env()
    client = QuotaClient(project_id=project_id)
    # 0.0.0.0 so the dockerised Prometheus can scrape via host.docker.internal.
    # Other host-running Hapax exporters (compositor :9482) follow this convention.
    start_http_server(METRICS_PORT, addr="0.0.0.0")  # noqa: S104 — single-user host, firewalled LAN
    exporter = QuotaExporter(client=client)
    exporter.run_forever()


if __name__ == "__main__":
    main()

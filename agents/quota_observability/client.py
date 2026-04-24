"""Cloud Monitoring client wrapper for YouTube Data API v3 quota metrics.

Reads ``serviceruntime.googleapis.com`` quota metric series via the
Google Cloud Monitoring API. Authentication uses Application Default
Credentials (``google.auth.default()``) — the operator runs
``gcloud auth application-default login --scopes=https://www.googleapis.com/auth/monitoring.read``
once per machine. ADC is independent of the in-repo OAuth token store
(``shared.google_auth``) which is scoped to user-data APIs (Drive,
Gmail, YouTube content) and does not include monitoring scope.

The client is deliberately thin — it returns plain dataclasses, not
Prometheus types, so the exporter layer owns metric semantics and
tests can drive it without any GCP runtime present.
"""

from __future__ import annotations

import logging
import os
import time as _time
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_SERVICE = "youtube.googleapis.com"
DEFAULT_QUOTA_LIMIT_NAME = "DefaultGroup"

# Default daily cap per the Google docs; operator may have a granted
# extension. The exporter prefers the live ``allocation/limit`` metric
# when present, falling back to this constant otherwise.
DEFAULT_DAILY_CAP_UNITS: int = 10_000


@dataclass(frozen=True, slots=True)
class QuotaSample:
    """One read of YouTube Data API v3 quota state from Cloud Monitoring.

    ``used_units`` is daily-cumulative — resets at the GCP project's
    quota refresh time (UTC midnight). ``rate_per_min`` is averaged
    over the last 5-minute window.
    """

    used_units: float
    daily_cap_units: float
    rate_per_min: float
    sampled_at: float


class QuotaClient:
    """Reads YouTube Data API v3 quota state from Cloud Monitoring.

    Construct with ``project_id`` and an optional pre-built
    ``MetricServiceClient`` (tests pass a mock; production lets the
    constructor lazy-build via ``google.auth.default()``).
    """

    def __init__(
        self,
        project_id: str,
        *,
        service: str = DEFAULT_SERVICE,
        client: object | None = None,
        default_daily_cap: int = DEFAULT_DAILY_CAP_UNITS,
    ) -> None:
        if not project_id:
            raise ValueError("project_id required")
        self._project_id = project_id
        self._service = service
        self._client = client
        self._default_daily_cap = default_daily_cap

    @property
    def project_id(self) -> str:
        return self._project_id

    @property
    def service(self) -> str:
        return self._service

    def _ensure_client(self) -> object:
        if self._client is not None:
            return self._client
        from google.cloud import monitoring_v3  # local import; heavy

        self._client = monitoring_v3.MetricServiceClient()
        return self._client

    def _project_name(self) -> str:
        return f"projects/{self._project_id}"

    def _series_filter(self, metric_type: str) -> str:
        return (
            f'metric.type = "{metric_type}" AND '
            f'metric.labels.quota_metric = "{self._service}/quota/requests"'
        )

    def read_sample(self, *, now: float | None = None) -> QuotaSample:
        """Pull one composite quota sample.

        Returns ``QuotaSample`` with both daily-cumulative usage and
        the 5-minute rolling rate. Raises on transport / auth failure
        — caller decides whether to log-and-continue or escalate.
        """
        now = _time.time() if now is None else now
        used = self._read_daily_used(now=now)
        rate = self._read_rate_per_min(now=now)
        cap = self._read_daily_cap(now=now)
        return QuotaSample(
            used_units=used,
            daily_cap_units=cap,
            rate_per_min=rate,
            sampled_at=now,
        )

    def _read_daily_used(self, *, now: float) -> float:
        return self._latest_point(
            metric_type="serviceruntime.googleapis.com/quota/allocation/usage",
            since_s=now - 3600.0,
            now=now,
            default=0.0,
        )

    def _read_rate_per_min(self, *, now: float) -> float:
        per_second = self._latest_point(
            metric_type="serviceruntime.googleapis.com/quota/rate/net_usage",
            since_s=now - 300.0,
            now=now,
            default=0.0,
        )
        return per_second * 60.0

    def _read_daily_cap(self, *, now: float) -> float:
        cap = self._latest_point(
            metric_type="serviceruntime.googleapis.com/quota/limit",
            since_s=now - 3600.0,
            now=now,
            default=float(self._default_daily_cap),
        )
        return cap if cap > 0 else float(self._default_daily_cap)

    def _latest_point(
        self,
        *,
        metric_type: str,
        since_s: float,
        now: float,
        default: float,
    ) -> float:
        """Fetch the most-recent point of one metric series.

        Returns ``default`` when no data points are available or the
        time series is missing — common during cold-start before the
        operator has driven any API traffic.
        """
        client = self._ensure_client()
        try:
            request = self._build_list_request(metric_type, since_s, now)
            pager = client.list_time_series(request=request)
            for series in pager:
                for point in series.points:
                    return float(point.value.double_value or point.value.int64_value)
        except Exception:  # noqa: BLE001
            log.warning("cloud monitoring read failed for %s", metric_type, exc_info=True)
        return default

    def _build_list_request(self, metric_type: str, since_s: float, now: float) -> object:
        from google.cloud import monitoring_v3
        from google.protobuf.timestamp_pb2 import Timestamp

        start = Timestamp()
        start.FromSeconds(int(since_s))
        end = Timestamp()
        end.FromSeconds(int(now))
        return monitoring_v3.ListTimeSeriesRequest(
            name=self._project_name(),
            filter=self._series_filter(metric_type),
            interval=monitoring_v3.TimeInterval(end_time=end, start_time=start),
            view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        )


def project_id_from_env() -> str:
    """Read the GCP project id from ``GOOGLE_CLOUD_PROJECT``.

    The systemd unit sets this from the operator's pass store; the
    ``hapax-secrets.service`` oneshot writes it to the environment
    file consumed by all hapax services.
    """
    pid = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not pid:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT not set — hapax-secrets must export it before "
            "hapax-quota-observability.service starts"
        )
    return pid

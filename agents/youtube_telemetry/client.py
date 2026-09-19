"""Thin Analytics + Reporting client wrappers.

``AnalyticsClient`` reads realtime concurrent-viewer + engagement
counts via the YouTube Analytics API. The client is deliberately
thin so tests can inject a mock without depending on
googleapiclient at all.

Auth: ``shared.google_auth.get_google_credentials()`` with the
``yt-analytics.readonly`` scope. Unlike Cloud Monitoring (Application
Default Credentials), Analytics API uses the same OAuth flow as the
other Google content APIs, so we reuse the existing FileStore
pattern (the ``google/token`` secret). The operator must mint a token
with the analytics scope; the
helper documents the scope but does not force-mint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

YT_ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"


@dataclass(frozen=True, slots=True)
class RealtimeReading:
    """One realtime sample of public engagement state.

    All counters are non-negative; ``None`` means the metric isn't
    available for this sample (the API may not return engagement on
    very-low-traffic streams).
    """

    concurrent_viewers: float
    engagement_score: float | None
    sampled_at: float


class AnalyticsClient:
    """Reads YouTube Analytics realtime metrics.

    Tests construct with a mock callable as ``api_call`` matching
    ``(metric, dimensions, filters, ids) -> dict``. Production lets
    the constructor lazy-build via the googleapiclient discovery
    surface.
    """

    def __init__(
        self,
        *,
        channel_id: str,
        api_call: object | None = None,
    ) -> None:
        if not channel_id:
            raise ValueError("channel_id required")
        self._channel_id = channel_id
        self._api_call = api_call

    @property
    def channel_id(self) -> str:
        return self._channel_id

    def _ensure_api_call(self):
        if self._api_call is not None:
            return self._api_call
        from shared.google_auth import get_google_credentials

        creds = get_google_credentials([YT_ANALYTICS_SCOPE])
        if creds is None:
            raise RuntimeError(
                "no google credentials available for analytics — operator must mint "
                "a token with the yt-analytics.readonly scope"
            )
        from googleapiclient.discovery import build

        service = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

        def _call(metric: str, dimensions: str, filters: str, ids: str) -> dict:
            return (
                service.reports()
                .query(metric=metric, dimensions=dimensions, filters=filters, ids=ids)
                .execute()
            )

        self._api_call = _call
        return self._api_call

    def read_realtime(self, *, now: float) -> RealtimeReading:
        """Read concurrent_viewers + engagement_score for the channel."""
        api = self._ensure_api_call()
        ccu = self._scalar(
            api,
            metric="concurrentViewers",
            dimensions="",
            filters="",
            default=0.0,
        )
        engagement = self._scalar_optional(
            api,
            metric="estimatedMinutesWatched",
            dimensions="",
            filters="",
        )
        return RealtimeReading(
            concurrent_viewers=ccu,
            engagement_score=engagement,
            sampled_at=now,
        )

    def _scalar(
        self,
        api_call,
        *,
        metric: str,
        dimensions: str,
        filters: str,
        default: float,
    ) -> float:
        try:
            response = api_call(
                metric=metric,
                dimensions=dimensions,
                filters=filters,
                ids=f"channel=={self._channel_id}",
            )
        except Exception:  # noqa: BLE001
            log.warning("analytics read failed for %s", metric, exc_info=True)
            return default
        rows = response.get("rows") or []
        if not rows or not rows[0]:
            return default
        try:
            return float(rows[0][0])
        except (ValueError, TypeError, IndexError):
            return default

    def _scalar_optional(
        self,
        api_call,
        *,
        metric: str,
        dimensions: str,
        filters: str,
    ) -> float | None:
        try:
            response = api_call(
                metric=metric,
                dimensions=dimensions,
                filters=filters,
                ids=f"channel=={self._channel_id}",
            )
        except Exception:  # noqa: BLE001
            log.debug("analytics optional read failed for %s", metric, exc_info=True)
            return None
        rows = response.get("rows") or []
        if not rows or not rows[0]:
            return None
        try:
            return float(rows[0][0])
        except (ValueError, TypeError, IndexError):
            return None


def channel_id_from_env() -> str:
    """Read the YouTube channel id from ``YOUTUBE_CHANNEL_ID``."""
    import os

    cid = os.environ.get("YOUTUBE_CHANNEL_ID", "").strip()
    if not cid:
        raise RuntimeError(
            "YOUTUBE_CHANNEL_ID not set — hapax-secrets must export it before "
            "hapax-youtube-telemetry.service starts"
        )
    return cid

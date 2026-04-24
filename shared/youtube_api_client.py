"""YouTube Data API v3 client wrapper with resilience + quota accounting.

Single wrapper around ``googleapiclient.discovery.build`` used by every
YouTube-writing daemon in the autonomous-boost epic. Handles credential
loading (sub-channel pass key, fallback to main), exponential-backoff
retry on 5xx + 401, silent-skip on 403 quota-exhausted, and per-call
Prometheus accounting so ytb-001 quota observability can correlate.

Stateless across requests; callers hold one instance per daemon.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from shared.google_auth import (
    YOUTUBE_STREAMING_TOKEN_PASS_KEY,
    get_google_credentials,
)

log = logging.getLogger(__name__)

READONLY_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
WRITE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


@dataclass
class ApiCallOutcome:
    endpoint: str
    result: str
    http_status: int | None
    retries: int = 0
    latency_s: float = 0.0
    quota_cost_hint: int | None = None


try:
    from prometheus_client import Counter

    _API_CALLS_TOTAL = Counter(
        "hapax_broadcast_yt_api_calls_total",
        "YouTube Data API v3 call attempts and their outcomes.",
        ["endpoint", "result"],
    )

    def _record_metric(outcome: ApiCallOutcome) -> None:
        _API_CALLS_TOTAL.labels(endpoint=outcome.endpoint, result=outcome.result).inc()
except ImportError:

    def _record_metric(outcome: ApiCallOutcome) -> None:
        log.debug("prometheus_client unavailable; metric dropped")


class YouTubeApiClient:
    """Resilient wrapper around the YouTube v3 service object.

    Usage::

        client = YouTubeApiClient(scopes=WRITE_SCOPES)
        resp = client.execute(
            client.yt.liveBroadcasts().list(
                part="snippet", mine=True, broadcastStatus="active"
            ),
            endpoint="liveBroadcasts.list",
            quota_cost_hint=1,
        )
    """

    def __init__(
        self,
        scopes: list[str],
        pass_key: str = YOUTUBE_STREAMING_TOKEN_PASS_KEY,
        rate_limiter: Any = None,
        max_retries: int = 3,
        backoff_base_s: float = 1.0,
    ) -> None:
        self._scopes = scopes
        self._pass_key = pass_key
        self._rate_limiter = rate_limiter
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._creds: Any = None
        self._yt: Any = None
        self._reload_service()

    def _reload_service(self) -> None:
        creds = get_google_credentials(self._scopes, pass_key=self._pass_key)
        if not creds:
            log.warning(
                "No credentials at pass_key=%s; client DISABLED. "
                "Operator must mint via scripts/mint-google-token.py --pass-key %s",
                self._pass_key,
                self._pass_key,
            )
            self._creds = None
            self._yt = None
            return
        self._creds = creds
        self._yt = build("youtube", "v3", credentials=creds)

    @property
    def enabled(self) -> bool:
        return self._yt is not None

    @property
    def yt(self) -> Any:
        if self._yt is None:
            raise RuntimeError(
                "YouTubeApiClient disabled — no credentials. Check pass_key + OAuth state."
            )
        return self._yt

    def execute(
        self,
        request: Any,
        *,
        endpoint: str,
        quota_cost_hint: int | None = None,
    ) -> dict | None:
        if not self.enabled:
            log.warning("client disabled; skipping %s", endpoint)
            _record_metric(ApiCallOutcome(endpoint=endpoint, result="disabled", http_status=None))
            return None

        if self._rate_limiter is not None and not self._rate_limiter.try_acquire(
            endpoint=endpoint, cost=quota_cost_hint or 1
        ):
            log.info("rate-limited; skipping %s", endpoint)
            _record_metric(
                ApiCallOutcome(
                    endpoint=endpoint,
                    result="rate_limited",
                    http_status=None,
                    quota_cost_hint=quota_cost_hint,
                )
            )
            return None

        started = time.time()
        for attempt in range(self._max_retries + 1):
            try:
                resp = request.execute()
                _record_metric(
                    ApiCallOutcome(
                        endpoint=endpoint,
                        result="ok",
                        http_status=200,
                        retries=attempt,
                        latency_s=time.time() - started,
                        quota_cost_hint=quota_cost_hint,
                    )
                )
                return resp
            except HttpError as err:
                status = getattr(err.resp, "status", None)
                if status == 401 and attempt == 0:
                    log.info("401; reloading credentials + retrying %s", endpoint)
                    self._reload_service()
                    if not self.enabled:
                        _record_metric(
                            ApiCallOutcome(
                                endpoint=endpoint,
                                result="auth_failed",
                                http_status=401,
                                retries=attempt,
                            )
                        )
                        return None
                    continue
                if status == 403:
                    body = _parse_error_body(err)
                    if _is_quota_error(body):
                        log.warning("quota exhausted on %s; silent-skip", endpoint)
                        _record_metric(
                            ApiCallOutcome(
                                endpoint=endpoint,
                                result="quota_exhausted",
                                http_status=403,
                                retries=attempt,
                            )
                        )
                        return None
                    log.error("permission denied on %s: %s", endpoint, body)
                    _record_metric(
                        ApiCallOutcome(
                            endpoint=endpoint,
                            result="permission_denied",
                            http_status=403,
                            retries=attempt,
                        )
                    )
                    return None
                if status and 500 <= status < 600:
                    if attempt < self._max_retries:
                        sleep_s = self._backoff_base_s * (2**attempt)
                        log.info(
                            "transient %d on %s; retry in %.1fs",
                            status,
                            endpoint,
                            sleep_s,
                        )
                        time.sleep(sleep_s)
                        continue
                    _record_metric(
                        ApiCallOutcome(
                            endpoint=endpoint,
                            result="transient_error",
                            http_status=status,
                            retries=attempt,
                        )
                    )
                    raise
                if status == 429:
                    if attempt < self._max_retries:
                        sleep_s = self._backoff_base_s * (2 ** (attempt + 2))
                        log.warning("429 on %s; backing off %.1fs", endpoint, sleep_s)
                        time.sleep(sleep_s)
                        continue
                    _record_metric(
                        ApiCallOutcome(
                            endpoint=endpoint,
                            result="rate_limited",
                            http_status=429,
                            retries=attempt,
                        )
                    )
                    return None
                log.error("unhandled %s on %s: %s", status, endpoint, err)
                _record_metric(
                    ApiCallOutcome(
                        endpoint=endpoint,
                        result="error",
                        http_status=status,
                        retries=attempt,
                    )
                )
                raise

        _record_metric(
            ApiCallOutcome(
                endpoint=endpoint,
                result="error",
                http_status=None,
                retries=self._max_retries,
            )
        )
        return None


def _parse_error_body(err: Any) -> dict:
    try:
        content = err.content.decode() if isinstance(err.content, bytes) else err.content
        return json.loads(content).get("error", {})
    except (json.JSONDecodeError, AttributeError):
        return {}


def _is_quota_error(body: dict) -> bool:
    for e in body.get("errors", []):
        if e.get("reason") in {
            "quotaExceeded",
            "dailyLimitExceeded",
            "rateLimitExceeded",
            "userRateLimitExceeded",
        }:
            return True
    return False

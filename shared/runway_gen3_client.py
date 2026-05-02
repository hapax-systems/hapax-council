"""Runway Gen-3 REST API client for video generation.

Wraps the asynchronous task model: ``POST /v1/image_to_video`` to
start a generation, then ``GET /v1/tasks/{taskId}`` to poll until
``SUCCEEDED`` / ``FAILED`` / ``CANCELED``.

Big Pitch contest (closes 2026-05-04 10:00 ET) requires:
- Active paid Runway app subscription on the account backing the API
  key (API credits alone are NOT sufficient — operator-physical bootstrap)
- Visible Runway watermark — defaulted to ``True`` here per contest rule
- 1-3 minute video duration
- Original content with no real-world brands/logos/trademarks

The client itself does NOT validate subscription state (the API doesn't
expose that endpoint cleanly); the operator must verify before running
``--live`` mode. Phase 1 ships the typed wrapper and the dry-run path;
Phase 2 will wire the social-hashtag publisher (#RunwayBigPitchContest
on X / Bluesky via existing publication_bus surfaces — there is no
dedicated form-submission endpoint).

Spec: hapax-research/plans/2026-04-29-autonomous-grounding-revenue-doubling-plan.md
Currentness: hapax-research/audits/2026-05-02-runway-gen3-api-currentness.md
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict, Field

#: Runway production API host. The asynchronous task model means
#: every generation goes through ``POST .../image_to_video`` followed
#: by polling ``GET .../tasks/{id}``.
DEFAULT_BASE_URL: Final[str] = "https://api.runwayml.com"

#: Runway API version header — required for stable behavior across
#: cuts. Updated 2026-05-02 per Gemini Jr currentness scout.
DEFAULT_API_VERSION: Final[str] = "2024-11-06"

#: Current Gen-3 model identifier for video generation. Big Pitch
#: contest requires Gen-3 family; ``gen3a_turbo`` is the speed-optimized
#: variant (~1min for 10s video vs ~1-2min for standard Gen-3 Alpha).
DEFAULT_MODEL: Final[str] = "gen3a_turbo"

#: Minimum poll interval per Runway recommendation. Below 5s risks
#: rate-limit response.
MIN_POLL_INTERVAL_S: Final[float] = 5.0

#: Default polling deadline. Runway's official SDK uses 600s (10 min)
#: as a hard timeout for Gen-3 standard; we mirror that since
#: ``gen3a_turbo`` rarely needs more than a minute and standard rarely
#: more than three.
DEFAULT_POLL_TIMEOUT_S: Final[float] = 600.0

#: Big Pitch contest enforces visible watermark — make this the default
#: for any client constructed for the contest path.
CONTEST_WATERMARK_REQUIRED: Final[bool] = True


class RunwayTaskStatus(StrEnum):
    """Lifecycle states the polling endpoint can return."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    RUNNING = "RUNNING"  # legacy alias for IN_PROGRESS in some cuts
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


#: States that terminate the polling loop. The caller checks
#: ``status in TERMINAL_STATUSES`` to know when to stop polling.
TERMINAL_STATUSES: Final[frozenset[RunwayTaskStatus]] = frozenset(
    {RunwayTaskStatus.SUCCEEDED, RunwayTaskStatus.FAILED, RunwayTaskStatus.CANCELED}
)


class RunwayClientError(RuntimeError):
    """Raised when the Runway API returns an unexpected response or
    when the polling loop exhausts its deadline. Distinct exception
    type so callers can ``except RunwayClientError`` without catching
    other RuntimeErrors."""


class GenerateRequest(BaseModel):
    """Body for ``POST /v1/image_to_video``.

    Required by the contest path: ``watermark=True`` (visible Runway
    watermark) and ``duration`` between 1-3 minutes (60-180s).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str = DEFAULT_MODEL
    promptText: str = Field(min_length=1)
    promptImage: str | None = None
    watermark: bool = CONTEST_WATERMARK_REQUIRED
    duration: int = Field(default=10, ge=1, le=180)
    ratio: str = "1280:768"
    seed: int | None = None


class TaskResponse(BaseModel):
    """Response shape from generate (initial) and poll (subsequent) calls."""

    model_config = ConfigDict(extra="ignore")

    id: str
    status: RunwayTaskStatus
    output: list[str] | None = None  # signed URLs once SUCCEEDED
    failure: str | None = None  # error reason once FAILED
    progress: float | None = None  # 0.0-1.0 if reported


def _api_key() -> str:
    """Read RUNWAY_API_KEY from env. Raises ``RunwayClientError`` if
    unset so the failure surfaces with a contextual message instead of
    the bare ``KeyError`` from ``os.environ[...]``.
    """
    key = os.environ.get("RUNWAY_API_KEY", "").strip()
    if not key:
        raise RunwayClientError(
            "RUNWAY_API_KEY env var is unset. Add via: "
            "echo 'export RUNWAY_API_KEY=...' >> ~/.config/hapax/runway.env, "
            "then verify operator has an active Runway app subscription "
            "(API credits alone don't qualify for Big Pitch contest)."
        )
    return key


class RunwayGen3Client:
    """Synchronous client for Runway Gen-3 video generation.

    The client is intentionally thin — it returns ``TaskResponse``
    objects and lets the caller decide what to do with them. The
    only orchestration helper is :meth:`generate_and_wait` which
    starts a generation and polls until terminal state with
    exponential backoff (still respecting the 5s minimum interval).
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        api_version: str = DEFAULT_API_VERSION,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self._api_key = api_key or _api_key()
        self._http = http_client or httpx.Client(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "X-Runway-Version": self.api_version,
            "Content-Type": "application/json",
        }

    def generate(self, request: GenerateRequest) -> TaskResponse:
        """Start a video generation. Returns the task with status
        likely ``PENDING`` or ``IN_PROGRESS``."""
        response = self._http.post(
            f"{self.base_url}/v1/image_to_video",
            headers=self._headers(),
            json=request.model_dump(exclude_none=True),
        )
        if response.status_code >= 400:
            raise RunwayClientError(
                f"generate failed: {response.status_code} {response.text[:300]!r}"
            )
        return TaskResponse.model_validate(response.json())

    def poll(self, task_id: str) -> TaskResponse:
        """Single poll of task status."""
        response = self._http.get(
            f"{self.base_url}/v1/tasks/{task_id}",
            headers=self._headers(),
        )
        if response.status_code >= 400:
            raise RunwayClientError(f"poll failed: {response.status_code} {response.text[:300]!r}")
        return TaskResponse.model_validate(response.json())

    def generate_and_wait(
        self,
        request: GenerateRequest,
        *,
        poll_timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> TaskResponse:
        """Start a generation, poll until terminal state, return final task.

        ``sleeper`` and ``clock`` are injected so tests can run
        deterministically without ``time.sleep`` slowing them down.
        Raises :class:`RunwayClientError` when ``poll_timeout_s``
        elapses without a terminal status.
        """
        initial = self.generate(request)
        if initial.status in TERMINAL_STATUSES:
            return initial

        started_at = clock()
        attempt = 0
        while True:
            elapsed = clock() - started_at
            if elapsed >= poll_timeout_s:
                raise RunwayClientError(
                    f"task {initial.id} did not reach terminal state within "
                    f"{poll_timeout_s}s (last polled at +{elapsed:.1f}s)"
                )
            # Exponential backoff with floor at MIN_POLL_INTERVAL_S
            interval = max(MIN_POLL_INTERVAL_S, min(MIN_POLL_INTERVAL_S * (1.5**attempt), 30.0))
            sleeper(interval)
            attempt += 1

            current = self.poll(initial.id)
            if current.status in TERMINAL_STATUSES:
                return current

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

"""Thin wrapper around the ``liveBroadcasts.cuepoint`` API call.

All calls walk :class:`shared.youtube_api_client.YouTubeApiClient` so
retries, quota silent-skip, and metric accounting are uniform across
the autonomous-boost daemons.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from shared.youtube_api_client import YouTubeApiClient

log = logging.getLogger(__name__)

DEFAULT_CUE_TYPE = "cueTypeAd"


def emit_cuepoint(
    client: YouTubeApiClient,
    *,
    broadcast_id: str,
    cue_type: str = DEFAULT_CUE_TYPE,
    duration_secs: int = 0,
    walltime_ms: int | None = None,
) -> dict | None:
    """Send a cuepoint to the given broadcast.

    ``duration_secs=0`` is the documented-but-unofficial way to request
    a scrub-bar marker without an ad interruption. If YouTube's policy
    ever changes, the orchestrator switches to description-side chapter
    scaffolding via ytb-008 (fallback path; see spec §14).
    """
    if walltime_ms is None:
        walltime_ms = int(time.time() * 1000)
    body: dict[str, Any] = {
        "cueType": cue_type,
        "durationSecs": duration_secs,
        "walltimeMs": walltime_ms,
    }
    return client.execute(
        client.yt.liveBroadcasts().cuepoint(id=broadcast_id, body=body),
        endpoint="liveBroadcasts.cuepoint",
        quota_cost_hint=1,
    )

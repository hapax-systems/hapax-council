"""YouTube API polling — live broadcasts + post-archive videos.

Wraps ``shared.youtube_api_client.YouTubeApiClient`` so the daemon body
doesn't depend on the wire format. Returns plain dicts keyed by id.
"""

from __future__ import annotations

import logging
from typing import Any

from shared.youtube_api_client import YouTubeApiClient

log = logging.getLogger(__name__)

LIVE_PARTS = "snippet,status,contentDetails,monetizationDetails"
VIDEOS_PARTS = "snippet,status,statistics,contentDetails"


def poll_live_broadcasts(client: YouTubeApiClient) -> dict[str, dict]:
    """Return ``{broadcast_id: snapshot_dict}`` for every active broadcast.

    Snapshot is the parsed response item — the change detector reads
    only the fields it cares about so any extra payload is harmless.
    Empty dict on quota exhaustion (``client.execute`` returns None) or
    no active broadcasts.
    """
    if not client.enabled:
        return {}
    request = client.yt.liveBroadcasts().list(
        part=LIVE_PARTS,
        mine=True,
        broadcastStatus="active",
    )
    response = client.execute(request, endpoint="liveBroadcasts.list", quota_cost_hint=1)
    return _index_response(response)


def poll_archived_video(client: YouTubeApiClient, video_id: str) -> dict | None:
    """Return the snapshot dict for ``video_id`` or None on quota / 404."""
    if not client.enabled:
        return None
    request = client.yt.videos().list(part=VIDEOS_PARTS, id=video_id)
    response = client.execute(request, endpoint="videos.list", quota_cost_hint=1)
    items = (response or {}).get("items") if isinstance(response, dict) else None
    if not items:
        return None
    return items[0]


def _index_response(response: Any) -> dict[str, dict]:
    if not isinstance(response, dict):
        return {}
    items = response.get("items")
    if not isinstance(items, list):
        return {}
    out: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        bid = item.get("id")
        if isinstance(bid, str):
            out[bid] = item
    return out

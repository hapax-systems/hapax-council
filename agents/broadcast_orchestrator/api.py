"""Thin API helpers wrapping the six YouTube calls a rotation needs.

Every call goes through :class:`shared.youtube_api_client.YouTubeApiClient`
so retries, quota silent-skip, and metric accounting are uniform.
"""

from __future__ import annotations

import logging

from shared.youtube_api_client import YouTubeApiClient

from .metadata_seed import SeedMetadata

log = logging.getLogger(__name__)


def list_active_broadcasts(client: YouTubeApiClient) -> list[dict]:
    """Return active broadcasts owned by the authenticated channel."""
    if not client.enabled:
        return []
    # YouTube API v3 rejects ``mine`` and ``broadcastStatus`` together
    # ("Incompatible parameters specified in the request: mine, broadcastStatus").
    # ``broadcastStatus`` already scopes to the OAuth-authenticated channel.
    resp = client.execute(
        client.yt.liveBroadcasts().list(
            part="id,snippet,status,contentDetails",
            broadcastStatus="active",
            maxResults=5,
        ),
        endpoint="liveBroadcasts.list",
        quota_cost_hint=1,
    )
    return resp.get("items", []) if resp else []


def discover_stream_id(client: YouTubeApiClient) -> str | None:
    """Return the active liveStream id (RTMP ingest config), if any."""
    if not client.enabled:
        return None
    resp = client.execute(
        client.yt.liveStreams().list(
            part="id,status",
            mine=True,
            maxResults=10,
        ),
        endpoint="liveStreams.list",
        quota_cost_hint=1,
    )
    if not resp:
        return None
    items = resp.get("items", [])
    for item in items:
        if item.get("status", {}).get("streamStatus") == "active":
            return item.get("id")
    if items:
        return items[0].get("id")
    return None


def insert_broadcast(
    client: YouTubeApiClient,
    *,
    seed: SeedMetadata,
    privacy_status: str,
    scheduled_start_iso: str,
) -> dict | None:
    """Create a new broadcast resource."""
    body = {
        "snippet": {
            "title": seed.title,
            "description": seed.description,
            "scheduledStartTime": scheduled_start_iso,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
        "contentDetails": {
            "enableAutoStart": False,
            "enableAutoStop": True,
            "enableDvr": True,
            "enableContentEncryption": False,
            "monitorStream": {"enableMonitorStream": False},
            "recordFromStart": True,
        },
    }
    return client.execute(
        client.yt.liveBroadcasts().insert(part="snippet,status,contentDetails", body=body),
        endpoint="liveBroadcasts.insert",
        quota_cost_hint=50,
    )


def bind_broadcast(client: YouTubeApiClient, *, broadcast_id: str, stream_id: str) -> dict | None:
    return client.execute(
        client.yt.liveBroadcasts().bind(
            part="id,contentDetails", id=broadcast_id, streamId=stream_id
        ),
        endpoint="liveBroadcasts.bind",
        quota_cost_hint=50,
    )


def transition_broadcast(
    client: YouTubeApiClient, *, broadcast_id: str, status: str
) -> dict | None:
    return client.execute(
        client.yt.liveBroadcasts().transition(
            part="id,status", id=broadcast_id, broadcastStatus=status
        ),
        endpoint="liveBroadcasts.transition",
        quota_cost_hint=50,
    )


def update_video_metadata(
    client: YouTubeApiClient, *, broadcast_id: str, seed: SeedMetadata
) -> dict | None:
    body = {
        "id": broadcast_id,
        "snippet": {
            "title": seed.title,
            "description": seed.description,
            "tags": list(seed.tags),
            "categoryId": seed.category_id,
        },
    }
    return client.execute(
        client.yt.videos().update(part="snippet", body=body),
        endpoint="videos.update",
        quota_cost_hint=50,
    )


def vod_url(broadcast_id: str) -> str:
    return f"https://www.youtube.com/watch?v={broadcast_id}"

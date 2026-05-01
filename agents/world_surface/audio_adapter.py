"""World-surface health audio adapter.

Consumes ``VoiceOutputRouter`` route results plus existing
``shared.broadcast_audio_health`` evidence, and projects each audio
attempt onto a world-surface substrate row carrying:

- role (assistant / broadcast / private_monitor / notification)
- sink_name (or None when the route is unavailable)
- provenance (config_role / fallback / unavailable)
- audibility_status (audible / unknown / route_missing)
- audibility_reason (free-form explanation when not audible)
- freshness_seconds (age of the audibility evidence)
- live_at (ISO timestamp of the route result)

cc-task: ``world-surface-health-audio-adapter``.

Why this matters:
The operator's ear can't tell whether a 6-concurrent-uncorked-stream
TTS chain is actually carrying audio on the broadcast bus. After
``voice-output-router-semantic-api`` ships, every audio attempt has a
route choice + provenance. This adapter records that choice and pairs
it with audibility evidence so the answer to "is Hapax heard on
livestream" becomes evidence-shaped, not ear-shaped.

This adapter ships the projection function only. Operator-side wiring
into the world-surface state file (the consumer of these rows) lands
in ``broadcast-audio-health-world-surface`` (the next task in the
chain).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from shared.broadcast_audio_health import (
    DEFAULT_STATE_PATH as BROADCAST_AUDIO_HEALTH_DEFAULT_PATH,
)
from shared.broadcast_audio_health import (
    BroadcastAudioStatus,
    read_broadcast_audio_health_state,
)
from shared.voice_output_router import RouteResult, VoiceRole

AudibilityStatus = Literal["audible", "unknown", "route_missing"]


@dataclass(frozen=True)
class AudioWorldSurfaceRow:
    """One row emitted per audio attempt.

    ``audibility_status`` is the headline operator-facing field:
    ``audible`` when broadcast audio health is SAFE, ``unknown`` when
    the audibility evidence is degraded / missing / stale, and
    ``route_missing`` when the router itself returned ``provenance=
    unavailable`` (no point checking audibility for a route that
    can't fire).
    """

    role: VoiceRole | str
    sink_name: str | None
    provenance: str
    audibility_status: AudibilityStatus
    audibility_reason: str | None
    freshness_seconds: float
    live_at: str


def project_route_to_world_surface_row(
    route: RouteResult,
    *,
    audio_health_path: Path | None = None,
    now: float | None = None,
) -> AudioWorldSurfaceRow:
    """Project one route attempt + audibility evidence onto a world-surface row.

    The audibility check is short-circuited when the route itself is
    unavailable — there's no point reading the audibility state file
    for a role that can't fire. In that case the row carries
    ``audibility_status="route_missing"``.

    For an available route, audibility maps from the existing
    ``BroadcastAudioStatus`` enum:

    - ``SAFE``     → ``"audible"``
    - any other (``DEGRADED`` / ``UNSAFE`` / ``UNKNOWN``) → ``"unknown"``,
      with the underlying status name as ``audibility_reason``.

    The function never raises on missing or malformed audibility
    state — ``read_broadcast_audio_health_state`` already fails-closed
    to ``UNKNOWN`` for those cases, which collapses to
    ``"unknown"`` here.
    """

    if route.provenance == "unavailable":
        return AudioWorldSurfaceRow(
            role=route.role,
            sink_name=None,
            provenance=route.provenance,
            audibility_status="route_missing",
            audibility_reason="role unavailable per VoiceOutputRouter",
            freshness_seconds=0.0,
            live_at=route.live_at,
        )

    health_path = (
        audio_health_path if audio_health_path is not None else BROADCAST_AUDIO_HEALTH_DEFAULT_PATH
    )
    health = read_broadcast_audio_health_state(health_path, now=now)

    if health.status == BroadcastAudioStatus.SAFE:
        return AudioWorldSurfaceRow(
            role=route.role,
            sink_name=route.sink_name,
            provenance=route.provenance,
            audibility_status="audible",
            audibility_reason=None,
            freshness_seconds=health.freshness_s,
            live_at=route.live_at,
        )

    return AudioWorldSurfaceRow(
        role=route.role,
        sink_name=route.sink_name,
        provenance=route.provenance,
        audibility_status="unknown",
        audibility_reason=health.status.value if health.status else None,
        freshness_seconds=health.freshness_s,
        live_at=route.live_at,
    )


__all__ = [
    "AudibilityStatus",
    "AudioWorldSurfaceRow",
    "project_route_to_world_surface_row",
]

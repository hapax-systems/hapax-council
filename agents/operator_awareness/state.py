"""Awareness state model + atomic writer.

Pydantic types for the 13-category operator-awareness state per the
``awareness-state-stream-canonical`` spec. Each block carries a
``public: bool`` field that ``public_filter.py`` (Phase 3) consults
when fanning out to the omg.lol public-safe weblog payload.

Anti-anthropomorphization: state payload uses neutral category names
(golden-signal, posterior-decile, count, last-error) — no narrative
prose surfaced from the spine itself.

## Atomic write

Readers must never see partial JSON. ``write_state_atomic`` writes
to a per-pid tmp file then os.replace()s it into place — POSIX
guarantees rename atomicity within the same filesystem (/dev/shm
qualifies).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "HAPAX_AWARENESS_STATE_PATH",
        "/dev/shm/hapax-awareness/state.json",
    )
)
# Surfaces dim when state.timestamp is older than ttl_seconds. 90s
# matches the spec — long enough to survive a 30s tick miss without
# alarming, short enough that a dead aggregator visibly affects
# downstream surfaces within a couple of minutes.
DEFAULT_TTL_S: int = int(os.environ.get("HAPAX_AWARENESS_TTL_S", "90"))


# ── Block models ───────────────────────────────────────────────────


class _Block(BaseModel):
    """Common base for awareness sub-blocks.

    Every block has a ``public`` flag the public-filter pass consults
    when redacting for omg.lol fanout. Defaults to False (private)
    so a new block added without explicit public=True doesn't leak.
    """

    model_config = ConfigDict(frozen=True)

    public: bool = False


class MarketingOutreachBlock(_Block):
    """Marketing/outreach pipeline state."""

    pending_count: int = 0
    posted_24h: int = 0
    last_post_at: datetime | None = None


class ResearchDispatchBlock(_Block):
    """Research-dispatch agent activity."""

    in_flight_count: int = 0
    completed_24h: int = 0
    last_dispatch_at: datetime | None = None


class MusicBlock(_Block):
    """SoundCloud / vinyl / bed-music routing state."""

    current_track: str = ""
    source: str = ""  # "soundcloud" / "vinyl" / "bed-music" / ""
    is_playing: bool = False


class PublishingBlock(_Block):
    """Publication-bus pipeline state."""

    inbox_count: int = 0
    in_flight_count: int = 0
    published_24h: int = 0
    last_publish_at: datetime | None = None


class HealthBlock(_Block):
    """Whole-system health golden-signal block."""

    overall_status: str = "unknown"  # "healthy" / "degraded" / "critical" / "unknown"
    failed_units: int = 0
    docker_containers_failed: int = 0
    disk_pct_used: float = 0.0
    gpu_vram_pct_used: float = 0.0


class DaimonionBlock(_Block):
    """Voice daemon / stimmung-derived stance."""

    stance: str = "unknown"
    voice_session_active: bool = False
    last_utterance_at: datetime | None = None


class StreamBlock(_Block):
    """Live broadcast indicator."""

    live: bool = False
    chronicle_events_5min: int = 0
    rotation_state: str = ""  # "ACTIVE" / "ROTATING_NEW" / etc.


class CrossAccountBlock(_Block):
    """Bluesky/Mastodon/Are.na/Discord publish counts (24h)."""

    bsky_posts_24h: int = 0
    mastodon_posts_24h: int = 0
    arena_posts_24h: int = 0
    discord_posts_24h: int = 0


class GovernanceBlock(_Block):
    """Axiom + consent state."""

    active_consent_contracts: int = 0
    governance_violations_24h: int = 0
    last_axiom_check_at: datetime | None = None


class ProgrammeBlock(_Block):
    """Active content programme state."""

    active_programme: str = ""
    programme_role: str = ""
    elapsed_in_programme_s: int = 0


class FleetBlock(_Block):
    """Hardware fleet (Pi NoIR + watch + phone) heartbeats."""

    pi_count_online: int = 0
    pi_count_total: int = 0
    watch_last_heartbeat_at: datetime | None = None
    phone_last_heartbeat_at: datetime | None = None


class SprintBlock(_Block):
    """Sprint progress (Obsidian-driven)."""

    sprint_id: str = ""
    sprint_day: int = 0
    completed_measures: int = 0
    blocked_measures: int = 0


class RefusalEvent(BaseModel):
    """One refusal-gate fire — NEVER aggregated; raw individuals.

    Constitutional substrate per the refusal-as-data directive
    (`feedback_full_automation_or_no_engagement`). Readers (waybar,
    sidebar, omg.lol fanout) display individual events; no
    summarisation that loses the per-refusal trace.
    """

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    surface: str  # "twitter" / "linkedin" / etc.
    reason: str  # short rationale string
    refused_artifact_slug: str | None = None


# ── Top-level state ───────────────────────────────────────────────


class AwarenessState(BaseModel):
    """Top-level operator-awareness state.

    Aggregator (Phase 2) constructs an instance per tick and the
    runner (Phase 2) writes it atomically. Surfaces (waybar,
    sidebar, omg.lol fanout — separate tasks) parse the JSON.

    Stale-state semantics: consumers compare ``timestamp`` to wall
    clock; if older than ``ttl_seconds``, the consumer dims its
    rendering rather than displaying empty fields. Spec: 90s
    default leaves a 60s margin past the 30s aggregator tick before
    dimming kicks in.

    ``extra="forbid"`` rejects unknown top-level fields so a writer
    that drifts from the schema fails loudly at validation time
    rather than silently shipping a payload that downstream surfaces
    can't parse.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    timestamp: datetime
    ttl_seconds: int = DEFAULT_TTL_S
    marketing_outreach: MarketingOutreachBlock = Field(default_factory=MarketingOutreachBlock)
    research_dispatches: ResearchDispatchBlock = Field(default_factory=ResearchDispatchBlock)
    music_soundcloud: MusicBlock = Field(default_factory=MusicBlock)
    publishing_pipeline: PublishingBlock = Field(default_factory=PublishingBlock)
    health_system: HealthBlock = Field(default_factory=HealthBlock)
    daimonion_voice: DaimonionBlock = Field(default_factory=DaimonionBlock)
    stream: StreamBlock = Field(default_factory=StreamBlock)
    cross_account: CrossAccountBlock = Field(default_factory=CrossAccountBlock)
    governance: GovernanceBlock = Field(default_factory=GovernanceBlock)
    content_programmes: ProgrammeBlock = Field(default_factory=ProgrammeBlock)
    hardware_fleet: FleetBlock = Field(default_factory=FleetBlock)
    time_sprint: SprintBlock = Field(default_factory=SprintBlock)
    # Raw refusal events — NEVER aggregated. Last 50 from the
    # `/dev/shm/hapax-refusals/log.jsonl` tail.
    refusals_recent: list[RefusalEvent] = Field(default_factory=list)


# ── Atomic write ───────────────────────────────────────────────────


def write_state_atomic(state: AwarenessState, path: Path = DEFAULT_STATE_PATH) -> bool:
    """Atomically write ``state`` to ``path``.

    Writes to ``{path}.tmp.{pid}`` then os.replace()s it into place.
    Readers never see partial JSON. Returns True on success, False
    on any I/O failure (logged at warning).

    POSIX guarantees ``os.replace`` atomicity for renames within the
    same filesystem; ``/dev/shm`` is single-tmpfs so this holds.
    Cross-fs renames would fall back to copy+unlink and lose
    atomicity — keep both paths within /dev/shm.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".json.tmp.{os.getpid()}")
        tmp.write_text(state.model_dump_json(), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        log.warning("awareness state write failed at %s", path, exc_info=True)
        return False


__all__ = [
    "DEFAULT_STATE_PATH",
    "DEFAULT_TTL_S",
    "AwarenessState",
    "CrossAccountBlock",
    "DaimonionBlock",
    "FleetBlock",
    "GovernanceBlock",
    "HealthBlock",
    "MarketingOutreachBlock",
    "MusicBlock",
    "ProgrammeBlock",
    "PublishingBlock",
    "RefusalEvent",
    "ResearchDispatchBlock",
    "SprintBlock",
    "StreamBlock",
    "write_state_atomic",
]

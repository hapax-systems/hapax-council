"""Typed helpers for ResearchVehiclePublicEvent records.

The JSON schema in ``schemas/research-vehicle-public-event.schema.json`` is the
contract authority. These Pydantic models are a small runtime companion so
producer and adapter code can construct that shape without open-coded dicts.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type EventType = Literal[
    "broadcast.boundary",
    "programme.boundary",
    "condition.changed",
    "chronicle.high_salience",
    "aesthetic.frame_capture",
    "caption.segment",
    "cuepoint.candidate",
    "chapter.marker",
    "shorts.candidate",
    "shorts.upload",
    "metadata.update",
    "channel_section.candidate",
    "arena_block.candidate",
    "omg.statuslog",
    "omg.weblog",
    "publication.artifact",
    "archive.segment",
    "monetization.review",
    "fanout.decision",
    "governance.enforcement",
    "velocity.digest",
]

type StateKind = Literal[
    "live_state",
    "programme_state",
    "research_observation",
    "aesthetic_frame",
    "caption_text",
    "cuepoint",
    "chapter",
    "short_form",
    "public_post",
    "archive_artifact",
    "attribution",
    "monetization_state",
    "health_state",
    "governance_state",
]

type RightsClass = Literal[
    "operator_original",
    "operator_controlled",
    "third_party_attributed",
    "third_party_uncleared",
    "platform_embedded",
    "unknown",
]

type PrivacyClass = Literal[
    "operator_private",
    "consent_required",
    "aggregate_only",
    "public_safe",
    "unknown",
]

type Surface = Literal[
    "youtube_description",
    "youtube_cuepoints",
    "youtube_chapters",
    "youtube_captions",
    "youtube_shorts",
    "youtube_channel_sections",
    "youtube_channel_trailer",
    "arena",
    "omg_statuslog",
    "omg_weblog",
    "omg_now",
    "mastodon",
    "bluesky",
    "discord",
    "archive",
    "replay",
    "github_readme",
    "github_profile",
    "github_release",
    "github_package",
    "github_pages",
    "zenodo",
    "captions",
    "cuepoints",
    "health",
    "monetization",
]

type FrameKind = Literal["frame", "clip", "thumbnail", "image"]
type ChapterKind = Literal["programme_boundary", "chapter", "cuepoint"]
type RedactionPolicy = Literal[
    "none",
    "operator_referent",
    "aggregate_only",
    "redact_private",
    "human_review",
]
type FallbackAction = Literal[
    "hold",
    "dry_run",
    "private_only",
    "archive_only",
    "chapter_only",
    "redact",
    "operator_review",
    "deny",
]


class PublicEventSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    producer: str
    substrate_id: str
    task_anchor: str | None
    evidence_ref: str
    freshness_ref: str | None


class PublicEventProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    token: str | None
    generated_at: str
    producer: str
    evidence_refs: list[str] = Field(default_factory=list)
    rights_basis: str
    citation_refs: list[str] = Field(default_factory=list)


class PublicEventFrameRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: FrameKind
    uri: str
    captured_at: str
    source_event_id: str


class PublicEventChapterRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ChapterKind
    label: str
    timecode: str
    source_event_id: str


class PublicEventSurfacePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_surfaces: list[Surface] = Field(default_factory=list)
    denied_surfaces: list[Surface] = Field(default_factory=list)
    claim_live: bool
    claim_archive: bool
    claim_monetizable: bool
    requires_egress_public_claim: bool
    requires_audio_safe: bool
    requires_provenance: bool
    requires_human_review: bool
    rate_limit_key: str | None
    redaction_policy: RedactionPolicy
    fallback_action: FallbackAction
    dry_run_reason: str | None


class ResearchVehiclePublicEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_id: str
    event_type: EventType
    occurred_at: str
    broadcast_id: str | None
    programme_id: str | None
    condition_id: str | None
    source: PublicEventSource
    salience: float = Field(ge=0.0, le=1.0)
    state_kind: StateKind
    rights_class: RightsClass
    privacy_class: PrivacyClass
    provenance: PublicEventProvenance
    public_url: str | None
    frame_ref: PublicEventFrameRef | None
    chapter_ref: PublicEventChapterRef | None
    attribution_refs: list[str] = Field(default_factory=list)
    surface_policy: PublicEventSurfacePolicy

    def to_json_line(self) -> str:
        """Serialize as a deterministic JSONL line."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True) + "\n"


__all__ = [
    "ChapterKind",
    "EventType",
    "FallbackAction",
    "FrameKind",
    "PrivacyClass",
    "PublicEventChapterRef",
    "PublicEventFrameRef",
    "PublicEventProvenance",
    "PublicEventSource",
    "PublicEventSurfacePolicy",
    "RedactionPolicy",
    "ResearchVehiclePublicEvent",
    "RightsClass",
    "StateKind",
    "Surface",
]

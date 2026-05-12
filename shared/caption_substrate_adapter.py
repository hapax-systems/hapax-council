"""Caption substrate adapter — projects CaptionEvent → RVPE caption.segment.

Pattern mirrors `shared/omg_statuslog_public_event_adapter.py`: takes a
stream of fresh, production-owned `CaptionEvent` records (the daimonion
STT pipeline writes these to `/dev/shm/hapax-captions/live.jsonl`,
wired in PR #1901 — `ytb-009-production-wire`) and projects each one
that satisfies the substrate gates into a
`ResearchVehiclePublicEvent` of `event_type="caption.segment"`.

The adapter is the canonical input the YouTube translation ledger,
caption-substrate health surface, and any future caption-aware fanout
(weblog summaries, search index) should consume — supplanting any
hand-rolled per-surface caption traversals.

Out of scope (per `caption-substrate-adapter` cc-task):
  - STT producer wiring (lives in the daimonion via PR #1901).
  - GStreamer in-band CEA-708 path (`agents/live_captions/gstreamer.py`
    is explicitly retired until an STT-JSONL → CEA packetizer exists).
  - YouTube caption upload + broad description copy.

Gates applied (in order):
  1. Routing — `RoutingPolicy.allows(speaker)` must hold; denied → reject.
  2. Freshness — `event.ts` must be within `freshness_ttl_s` of `now`;
     stale → reject. Captions whose audio-clock timestamp lags the
     adapter's now-clock by more than the TTL describe state the public
     surface should not claim is current.
  3. Idempotency — `(ts, text, speaker)` hash must not have been emitted
     recently; duplicates are suppressed.

Public-claim posture:
  - When `av_offset_s is None` (no offset evidence yet) the candidate
    declares `surface_policy.requires_audio_safe=True` AND records
    `av_offset_unavailable_reason` in provenance, so downstream
    publishers that require audio-safe metadata fail closed without
    needing adapter-internal knowledge.
  - The `privacy_class` is derived from the route decision: routed
    speakers → `"public_safe"`; the empty/None speaker (operator
    narration) → `"public_safe"`; explicit unknown speakers reach the
    routing layer rather than the privacy class.

Spec: `docs/superpowers/specs/2026-04-28-livestream-substrate-registry-design.md`
Cc-task: `caption-substrate-adapter`
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from agents.live_captions.reader import CaptionEvent
from agents.live_captions.routing import RoutingPolicy
from shared.livestream_role_state import LivestreamRoleState, PublicMode, SpeechPosture
from shared.research_vehicle_public_event import (
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
)

#: Stable substrate identity in the livestream substrate registry
#: (per the design spec example — `caption_in_band`).
CAPTION_SUBSTRATE_ID: Literal["caption_in_band"] = "caption_in_band"

#: Producer identity recorded on every projected event.
PRODUCER: Literal["shared.caption_substrate_adapter"] = "shared.caption_substrate_adapter"

#: Anchor cc-task whose ACs this adapter satisfies.
TASK_ANCHOR: Literal["caption-substrate-adapter"] = "caption-substrate-adapter"

#: Default freshness window. Live captions whose audio-clock ts
#: trails the adapter clock by more than this are stale: the broadcast
#: scene has already moved on. Override with
#: ``HAPAX_CAPTION_SUBSTRATE_FRESHNESS_TTL_S``.
DEFAULT_FRESHNESS_TTL_S: float = float(
    os.environ.get("HAPAX_CAPTION_SUBSTRATE_FRESHNESS_TTL_S", "30.0")
)


RejectionReason = Literal[
    "denied_routing",
    "stale",
    "duplicate",
    "role_state_blocks_public_caption",
]


@dataclass(frozen=True)
class CaptionSubstrateCandidate:
    """One CaptionEvent cleared to enter the public caption substrate.

    Pairs the projected RVPE record with the upstream caption ts, the
    AV-offset value applied (or ``None`` if no offset evidence exists
    yet), and the idempotency key the publisher should record so a
    re-run of the adapter does not double-emit.
    """

    event: ResearchVehiclePublicEvent
    caption_ts: float
    av_offset_s: float | None
    idempotency_key: str


@dataclass(frozen=True)
class CaptionSubstrateRejection:
    """One CaptionEvent that was considered but is NOT in the substrate.

    Distinct from candidates so the publisher can emit a per-reason
    Prometheus row and operator dashboards can surface why captions
    that look eligible failed the gate.
    """

    caption_ts: float
    text: str
    speaker: str | None
    reason: RejectionReason
    detail: str = ""


def derive_idempotency_key(*, ts: float, text: str, speaker: str | None) -> str:
    """Stable key for `(ts, text, speaker)` — sha256 hex of canonical JSON.

    A double-emit by the upstream STT pipeline (it has been observed
    once historically; see `agents/live_captions/daimonion_bridge.py`
    duplicate-rejection note) presents as the same `(ts, text,
    speaker)` triple. The key is invariant under speaker absence —
    `None` and the empty string yield the same key so a producer that
    flips the field's emptiness representation does not split the
    duplicate.
    """
    payload = f"{ts:.6f}|{text}|{speaker or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def project_caption_substrate(
    events: Iterable[CaptionEvent],
    *,
    routing: RoutingPolicy,
    now: float,
    av_offset_s: float | None,
    freshness_ttl_s: float = DEFAULT_FRESHNESS_TTL_S,
    seen_keys: Iterable[str] = (),
    role_state: LivestreamRoleState | None = None,
) -> tuple[list[CaptionSubstrateCandidate], list[CaptionSubstrateRejection]]:
    """Split a caption stream into (substrate-cleared, rejected).

    Parameters
    ----------
    events:
        The fresh CaptionEvent stream from `CaptionReader.read_pending`.
    routing:
        Loaded `RoutingPolicy` (typically `RoutingPolicy.load()`).
    now:
        Adapter-clock epoch seconds; events whose `ts` is older than
        `now - freshness_ttl_s` are rejected as stale.
    av_offset_s:
        Current moving-average AV offset from `CaptionReader.av_offset_s`,
        or ``None`` when no offset evidence exists yet. The candidate
        carries the offset (or ``None``) so the publisher can decide
        whether to claim audio-aligned timestamps publicly.
    freshness_ttl_s:
        Max acceptable `now - ts` lag. Defaults to
        ``DEFAULT_FRESHNESS_TTL_S``.
    seen_keys:
        Idempotency keys the caller has already emitted (a sliding
        window of recent posts). Caller owns retention policy.

    Returns
    -------
    A pair `(candidates, rejections)`. Each candidate carries the
    projected `ResearchVehiclePublicEvent`, the original caption ts,
    the AV-offset that was applied, and the idempotency key the
    publisher should record on durable success. Rejections carry the
    minimal evidence the publisher needs to telemeter without leaking
    the rejected text into long-lived state.
    """

    candidates: list[CaptionSubstrateCandidate] = []
    rejections: list[CaptionSubstrateRejection] = []
    seen: set[str] = set(seen_keys)

    for event in events:
        # Gate 1 — routing.
        if not routing.allows(event.speaker):
            rejections.append(
                CaptionSubstrateRejection(
                    caption_ts=event.ts,
                    text=event.text,
                    speaker=event.speaker,
                    reason="denied_routing",
                    detail=f"speaker={event.speaker!r} blocked by RoutingPolicy",
                )
            )
            continue

        # Gate 2 — freshness.
        lag_s = now - event.ts
        if lag_s > freshness_ttl_s:
            rejections.append(
                CaptionSubstrateRejection(
                    caption_ts=event.ts,
                    text=event.text,
                    speaker=event.speaker,
                    reason="stale",
                    detail=f"lag_s={lag_s:.2f} exceeds ttl={freshness_ttl_s:.2f}",
                )
            )
            continue

        # Gate 3 — idempotency.
        key = derive_idempotency_key(ts=event.ts, text=event.text, speaker=event.speaker)
        if key in seen:
            rejections.append(
                CaptionSubstrateRejection(
                    caption_ts=event.ts,
                    text=event.text,
                    speaker=event.speaker,
                    reason="duplicate",
                    detail=f"idempotency_key={key[:12]}…",
                )
            )
            continue
        seen.add(key)

        if role_state is not None and not _role_state_allows_public_caption(role_state):
            rejections.append(
                CaptionSubstrateRejection(
                    caption_ts=event.ts,
                    text=event.text,
                    speaker=event.speaker,
                    reason="role_state_blocks_public_caption",
                    detail=(
                        "livestream_role_state="
                        f"{role_state.role_state_id or role_state.public_mode.value} "
                        f"posture={role_state.expected_speech_posture.value}"
                    ),
                )
            )
            continue

        candidates.append(
            CaptionSubstrateCandidate(
                event=_build_caption_segment_event(
                    caption=event,
                    av_offset_s=av_offset_s,
                    now=now,
                    idempotency_key=key,
                    role_state=role_state,
                ),
                caption_ts=event.ts,
                av_offset_s=av_offset_s,
                idempotency_key=key,
            )
        )

    return candidates, rejections


def _build_caption_segment_event(
    *,
    caption: CaptionEvent,
    av_offset_s: float | None,
    now: float,
    idempotency_key: str,
    role_state: LivestreamRoleState | None,
) -> ResearchVehiclePublicEvent:
    """Construct one `caption.segment` RVPE record from a routed caption.

    The surface policy is conservative: live captions are routed only
    to `youtube_captions` + the substrate-level `captions` aperture.
    `requires_audio_safe` is always True (captions describe audio), and
    is reinforced when `av_offset_s is None` because a caller without
    AV-offset evidence cannot claim aligned timestamps publicly.
    `requires_provenance` is True so any downstream that omits the
    provenance footer fails closed.
    """

    # Provenance evidence ref pins the upstream JSONL byte-stream by
    # key + audio-clock ts so an investigation can reproduce the line
    # from the durable caption stream. We avoid pinning the volatile
    # `/dev/shm` path explicitly — the substrate registry is authority
    # for "where does the producer write."
    evidence_ref = f"caption_event:{idempotency_key[:16]}@ts={caption.ts:.6f}"

    av_offset_evidence = (
        f"av_offset_s={av_offset_s:.6f}" if av_offset_s is not None else "av_offset_unavailable"
    )
    role_evidence_refs = (
        (f"livestream_role_state:{role_state.role_state_id}",)
        if role_state is not None and role_state.role_state_id
        else ()
    )

    surface_policy = PublicEventSurfacePolicy(
        allowed_surfaces=["youtube_captions", "captions"],
        denied_surfaces=[],
        claim_live=True,
        claim_archive=True,
        claim_monetizable=False,  # captions per se don't unlock monetization
        requires_egress_public_claim=True,
        requires_audio_safe=True,
        requires_provenance=True,
        requires_human_review=False,
        rate_limit_key="caption.segment",
        redaction_policy="operator_referent",
        fallback_action="dry_run" if av_offset_s is None else "hold",
        dry_run_reason=(
            "av_offset_unavailable: cannot claim audio-aligned ts publicly"
            if av_offset_s is None
            else None
        ),
    )

    return ResearchVehiclePublicEvent(
        event_id=f"caption.segment:{idempotency_key}",
        event_type="caption.segment",
        occurred_at=_iso_from_epoch(caption.ts),
        broadcast_id=None,
        programme_id=None,
        condition_id=None,
        source=PublicEventSource(
            producer=PRODUCER,
            substrate_id=CAPTION_SUBSTRATE_ID,
            task_anchor=TASK_ANCHOR,
            evidence_ref=evidence_ref,
            freshness_ref=f"caption_event.lag_s={(now - caption.ts):.2f}",
        ),
        salience=0.40,  # individual caption segments are routine; non-zero so they remain visible to the gate
        state_kind="caption_text",
        rights_class="operator_original",
        privacy_class="public_safe",
        provenance=PublicEventProvenance(
            token=idempotency_key,
            generated_at=_iso_from_epoch(now),
            producer=PRODUCER,
            evidence_refs=[evidence_ref, av_offset_evidence, *role_evidence_refs],
            rights_basis="operator generated live caption text",
            citation_refs=[],
        ),
        public_url=None,
        frame_ref=None,
        chapter_ref=None,
        attribution_refs=[],
        surface_policy=surface_policy,
    )


def _iso_from_epoch(epoch_s: float) -> str:
    """Return RFC 3339 / ISO 8601 UTC timestamp string for `epoch_s`."""
    from datetime import UTC, datetime

    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()


def _role_state_allows_public_caption(role_state: LivestreamRoleState) -> bool:
    return (
        role_state.public_mode is PublicMode.PUBLIC_LIVE
        and role_state.expected_speech_posture
        in {SpeechPosture.PUBLIC_CAPTION, SpeechPosture.PUBLIC_NARRATION}
    )


__all__ = [
    "CAPTION_SUBSTRATE_ID",
    "CaptionSubstrateCandidate",
    "CaptionSubstrateRejection",
    "DEFAULT_FRESHNESS_TTL_S",
    "PRODUCER",
    "RejectionReason",
    "TASK_ANCHOR",
    "derive_idempotency_key",
    "project_caption_substrate",
]

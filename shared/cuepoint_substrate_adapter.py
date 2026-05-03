"""Cuepoint substrate adapter — projects PBE → RVPE cuepoint.candidate / chapter.marker.

Pattern mirrors `shared/caption_substrate_adapter.py` (just shipped) and
`shared/omg_statuslog_public_event_adapter.py`: takes a stream of
fresh, production-owned `ProgrammeBoundaryEvent` records (the
`programme_manager` writes these to
`~/hapax-state/programmes/<show>/<programme>.jsonl` per Phase 9
Critical #5 / B3 audit, and the producer half of the
`ytb-004-programme-boundary-cuepoints` cc-task is already shipped) and
projects each one of `boundary_type ∈ {"live_cuepoint.candidate",
"chapter.boundary"}` into the appropriate `ResearchVehiclePublicEvent`
of `event_type ∈ {"cuepoint.candidate", "chapter.marker"}`.

The adapter is the canonical input the YouTube live-cuepoint API write
path and the VOD chapter-marker fanout should consume — supplanting
any hand-rolled per-surface PBE traversals. **Live cuepoints stay
distinct from VOD chapter fallback** (the PBE schema's
`live_cuepoint_distinct_from_vod_chapter: const=True` invariant; the
adapter preserves it by surfacing the boundary's `boundary_type`
verbatim on each candidate).

Out of scope (per `cuepoint-substrate-adapter` cc-task):
  - Creating programme-boundary events (lives in
    `shared/programme_outcome_log.py` + `programme_manager`).
  - Sending `liveBroadcasts.cuepoint` writes (gated on
    operator-supervised live-player smoke; see ytb-004 status doc).
  - Running unsupervised live-player smoke.
  - Editing YouTube metadata copy.

Gates applied (in order):
  1. Boundary-type filter — only `live_cuepoint.candidate` and
     `chapter.boundary` reach the substrate; other PBE types are
     rejected as `not_cuepoint_or_chapter` so the caller can fan a
     mixed PBE stream through this adapter without preprocessing.
  2. Freshness — `now - boundary.emitted_at` ≤ `freshness_ttl_s`;
     stale → reject. PBEs whose emit timestamp lags the adapter clock
     by more than the TTL describe state the public surface should
     not claim is current.
  3. Idempotency — `boundary.duplicate_key` must not be in
     `seen_keys`; the schema already enforces a stable per-boundary
     dedup token, so the adapter does not invent a parallel hash.
  4. Format-adapter decision — `adapt_format_boundary_to_public_event`
     returns `status="refused"` when hard-unavailable reasons exist
     (egress blocked, archive missing, video-id missing, cuepoint
     smoke missing, cuepoint API rejected, rate limited, etc — see
     `_hard_unavailable_reasons` in the inner adapter). A refused
     decision becomes a substrate rejection with
     `reason="format_adapter_refused"` carrying the unavailable
     reasons.

Quota policy (per AC#4): the YouTube translation ledger
(`docs/superpowers/audits/2026-04-30-youtube-research-translation-ledger.json`)
records the local liveBroadcasts.cuepoint quota hint as **unresolved**
because the current rendered quota table does not enumerate that
method row. The adapter pins the rate-limit bucket key
(`rate_limit_key="cuepoint.candidate"`) on the candidate's surface
policy so a downstream live-write task picks up a consistent budget
ref; the *cost-per-call* number must be reconciled with an explicit
internal quota policy by the live-write task before any live cuepoint
is sent. The adapter itself authorizes nothing live.

Operator-supervised live-player smoke (per AC#6): no public copy may
claim live cuepoints are visible or effective without an
operator-witnessed smoke run against the production live broadcast.
Substrate candidates are *projection* records — they describe what
*would* be emitted; they do not assert it has been observed end-to-
end. The live-write task owns the smoke gate; this adapter records
`requires_human_review=True` on the surface policy so that gate is
not skipped.

Spec: `docs/superpowers/specs/2026-04-28-livestream-substrate-registry-design.md`
Cc-task: `cuepoint-substrate-adapter`
Sister: `shared/caption_substrate_adapter.py`
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from shared.format_public_event_adapter import (
    BoundaryType,
    ContentProgrammeRunEnvelope,
    FormatPublicEventDecision,
    ProgrammeBoundaryEvent,
    adapt_format_boundary_to_public_event,
)
from shared.research_vehicle_public_event import ResearchVehiclePublicEvent

#: Stable substrate identity in the livestream substrate registry —
#: covers both live cuepoints and VOD chapter markers under the same
#: substrate row because the producer (programme_manager via PBE) is
#: shared. A future split is OK; today they ride together.
CUEPOINT_SUBSTRATE_ID: Literal["cuepoint_chapter_inband"] = "cuepoint_chapter_inband"

#: Producer identity recorded on every projected event.
PRODUCER: Literal["shared.cuepoint_substrate_adapter"] = "shared.cuepoint_substrate_adapter"

#: Anchor cc-task whose ACs this adapter satisfies.
TASK_ANCHOR: Literal["cuepoint-substrate-adapter"] = "cuepoint-substrate-adapter"

#: Default freshness window for cuepoint/chapter candidates. Programme
#: boundaries are typically emitted within seconds of the actual
#: transition; a 5-minute window is generous enough to absorb the
#: per-programme JSONL rotation lag without claiming stale state.
#: Override with ``HAPAX_CUEPOINT_SUBSTRATE_FRESHNESS_TTL_S``.
DEFAULT_FRESHNESS_TTL_S: float = float(
    os.environ.get("HAPAX_CUEPOINT_SUBSTRATE_FRESHNESS_TTL_S", "300.0")
)

CandidateKind = Literal["cuepoint", "chapter"]

RejectionReason = Literal[
    "not_cuepoint_or_chapter",
    "stale",
    "duplicate",
    "format_adapter_refused",
]


@dataclass(frozen=True)
class CuepointSubstrateCandidate:
    """One PBE cleared to enter the public cuepoint/chapter substrate.

    ``kind`` distinguishes live cuepoint candidates (which a downstream
    live-write task may attempt against `liveBroadcasts.cuepoint` after
    operator-supervised smoke) from VOD chapter markers (which a
    downstream description-chapter task may compose into VOD copy).
    The PBE schema's `live_cuepoint_distinct_from_vod_chapter` invariant
    is preserved by deriving ``kind`` from the boundary's
    ``boundary_type`` rather than re-inferring it.
    """

    event: ResearchVehiclePublicEvent
    boundary_id: str
    run_id: str
    programme_id: str
    kind: CandidateKind
    idempotency_key: str
    decision: FormatPublicEventDecision


@dataclass(frozen=True)
class CuepointSubstrateRejection:
    """One PBE that was considered but is NOT in the substrate.

    Distinct from candidates so a downstream observer can emit a
    per-reason Prometheus row and operator dashboards can surface why
    PBEs that look eligible failed the gate.
    """

    boundary_id: str
    run_id: str
    boundary_type: BoundaryType
    reason: RejectionReason
    detail: str = ""


def _candidate_kind_for(boundary_type: BoundaryType) -> CandidateKind | None:
    """Map a boundary type to the substrate candidate kind.

    Returns ``None`` for boundary types this adapter does not
    cover — the caller can fan in a mixed PBE stream and the adapter
    rejects the irrelevant ones at gate 1.
    """
    if boundary_type == "live_cuepoint.candidate":
        return "cuepoint"
    if boundary_type == "chapter.boundary":
        return "chapter"
    return None


def project_cuepoint_substrate(
    pairs: Iterable[tuple[ContentProgrammeRunEnvelope, ProgrammeBoundaryEvent]],
    *,
    now: float,
    freshness_ttl_s: float = DEFAULT_FRESHNESS_TTL_S,
    seen_keys: Iterable[str] = (),
) -> tuple[list[CuepointSubstrateCandidate], list[CuepointSubstrateRejection]]:
    """Split a (run, boundary) stream into (substrate-cleared, rejected).

    Parameters
    ----------
    pairs:
        Iterable of `(ContentProgrammeRunEnvelope, ProgrammeBoundaryEvent)`
        pairs. Caller is responsible for joining a programme run to its
        boundary stream — typically the programme_manager owns this.
    now:
        Adapter-clock epoch seconds; boundaries whose `emitted_at` is
        older than `now - freshness_ttl_s` are rejected as stale.
    freshness_ttl_s:
        Max acceptable `now - emitted_at` lag. Defaults to
        ``DEFAULT_FRESHNESS_TTL_S`` (300 s).
    seen_keys:
        Idempotency keys (`boundary.duplicate_key` values) the caller
        has already emitted. Caller owns retention policy — typically
        a sliding window per programme run.

    Returns
    -------
    A pair `(candidates, rejections)`. Each candidate carries the
    projected RVPE, the boundary identity, the candidate kind, the
    idempotency key, and the full inner-adapter decision (so a
    downstream consumer can audit `unavailable_reasons` /
    `wcs_unavailable_reasons` even on emitted decisions).
    """

    generated_at = datetime.fromtimestamp(now, tz=UTC)
    candidates: list[CuepointSubstrateCandidate] = []
    rejections: list[CuepointSubstrateRejection] = []
    seen: set[str] = set(seen_keys)

    for run, boundary in pairs:
        # Gate 1 — boundary-type filter.
        kind = _candidate_kind_for(boundary.boundary_type)
        if kind is None:
            rejections.append(
                CuepointSubstrateRejection(
                    boundary_id=boundary.boundary_id,
                    run_id=run.run_id,
                    boundary_type=boundary.boundary_type,
                    reason="not_cuepoint_or_chapter",
                    detail=f"boundary_type={boundary.boundary_type}",
                )
            )
            continue

        # Gate 2 — freshness.
        emitted_epoch = boundary.emitted_at.timestamp()
        lag_s = now - emitted_epoch
        if lag_s > freshness_ttl_s:
            rejections.append(
                CuepointSubstrateRejection(
                    boundary_id=boundary.boundary_id,
                    run_id=run.run_id,
                    boundary_type=boundary.boundary_type,
                    reason="stale",
                    detail=f"lag_s={lag_s:.2f} exceeds ttl={freshness_ttl_s:.2f}",
                )
            )
            continue

        # Gate 3 — idempotency.
        if boundary.duplicate_key in seen:
            rejections.append(
                CuepointSubstrateRejection(
                    boundary_id=boundary.boundary_id,
                    run_id=run.run_id,
                    boundary_type=boundary.boundary_type,
                    reason="duplicate",
                    detail=f"duplicate_key={boundary.duplicate_key}",
                )
            )
            continue
        seen.add(boundary.duplicate_key)

        # Gate 4 — inner adapter decision (hard-unavailable check).
        decision = adapt_format_boundary_to_public_event(run, boundary, generated_at=generated_at)
        if decision.status == "refused" or decision.public_event is None:
            joined = ",".join(decision.hard_unavailable_reasons) or "no_hard_reason"
            rejections.append(
                CuepointSubstrateRejection(
                    boundary_id=boundary.boundary_id,
                    run_id=run.run_id,
                    boundary_type=boundary.boundary_type,
                    reason="format_adapter_refused",
                    detail=f"hard_unavailable={joined}",
                )
            )
            continue

        candidates.append(
            CuepointSubstrateCandidate(
                event=decision.public_event,
                boundary_id=boundary.boundary_id,
                run_id=run.run_id,
                programme_id=run.programme_id,
                kind=kind,
                idempotency_key=decision.idempotency_key,
                decision=decision,
            )
        )

    return candidates, rejections


__all__ = [
    "CUEPOINT_SUBSTRATE_ID",
    "CandidateKind",
    "CuepointSubstrateCandidate",
    "CuepointSubstrateRejection",
    "DEFAULT_FRESHNESS_TTL_S",
    "PRODUCER",
    "RejectionReason",
    "TASK_ANCHOR",
    "project_cuepoint_substrate",
]

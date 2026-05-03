"""Replay demo residency kit — typed `ReplayDemoCard` + generator.

Packages Hapax as a rights-safe, replayable, n=1 live epistemic lab for
institutional demos, grants, residencies, and sponsor-safe support
without requiring the operator to perform custom manual presentations.

The generator consumes
``ArchiveReplayPublicLinkDecision`` records produced by the
``archive-replay-public-event-link-adapter`` (`shared/archive_replay_public_events.py`)
and emits one `ReplayDemoCard` per decision that:

  * has `status == "emitted"` AND a non-None public_event;
  * carries a public-safe rights class
    (`operator_original`, `operator_controlled`,
    `third_party_attributed`); AND
  * carries a public-safe privacy class
    (`public_safe`, `aggregate_only`).

Decisions that fail any of those gates are SKIPPED, not surfaced as
"empty" or "private" cards. Fail closed: the kit must not display a
demo whose archive, public-event, rights, or privacy evidence is
missing — institutional viewers see only what was independently
verified by the upstream substrate adapter.

The kit is the canonical input for any institutional surface
(residency application, grant deck, sponsor brief) that wants to
display Hapax replay candidates. It supplants any hand-rolled
per-surface HLS-sidecar traversal — those would re-introduce the
"raw archive capture treated as public replay readiness" leak the
upstream adapter explicitly closes.

Out of scope (per `replay-demo-residency-kit` cc-task):
  - Authoring the institutional-facing markdown narrative (that lives
    in `docs/applications/2026-replay-demo-residency-kit.md`).
  - Producing HLS sidecars, archiving, or rotating media.
  - Mapping decisions to specific surface destinations
    (institutional, residency, grant). The card carries
    `suggested_audience` as a free-text steer; the surface adapter
    decides what to show.

Cc-task: `replay-demo-residency-kit`
Spec: `hapax-research/specs/2026-04-28-livestream-research-vehicle-suitcase-parent-spec.md`
Sister: `shared/archive_replay_public_events.py`
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from shared.archive_replay_public_events import (
    ArchiveReplayPublicLinkDecision,
)
from shared.research_vehicle_public_event import (
    PrivacyClass,
    RightsClass,
)

#: Anchor cc-task whose ACs this module satisfies.
TASK_ANCHOR: Literal["replay-demo-residency-kit"] = "replay-demo-residency-kit"

#: Producer identity recorded on every card.
PRODUCER: Literal["shared.replay_demo_card"] = "shared.replay_demo_card"

#: Rights classes the kit is willing to surface to institutional viewers.
#: Mirrors the upstream archive-replay adapter's `_PUBLIC_SAFE_RIGHTS`
#: set so the kit does not re-relax the gate.
PUBLIC_SAFE_RIGHTS: frozenset[RightsClass] = frozenset(
    {"operator_original", "operator_controlled", "third_party_attributed"}
)

#: Privacy classes the kit is willing to surface. Mirrors the upstream
#: adapter's `_PUBLIC_SAFE_PRIVACY` set.
PUBLIC_SAFE_PRIVACY: frozenset[PrivacyClass] = frozenset({"public_safe", "aggregate_only"})

SkipReason = Literal[
    "decision_status_not_emitted",
    "public_event_missing",
    "rights_class_not_public_safe",
    "privacy_class_not_public_safe",
]


@dataclass(frozen=True)
class ReplayDemoCard:
    """One replay candidate cleared for institutional display.

    Carries everything an institutional surface needs to render or
    embed the replay without re-querying upstream state:

    * ``event_id`` — RVPE event_id; the durable identifier for the
      replay public-event projection.
    * ``public_url`` — the public replay URL (None if the upstream
      decision held back the URL even on `emitted`).
    * ``replay_title`` — human-readable title.
    * ``chapter_label`` / ``chapter_timecode`` — the chapter ref the
      RVPE carries (if any), so a deck slide or page can deep-link
      into a moment.
    * ``frame_uri`` / ``frame_kind`` — the frame ref the RVPE
      carries (if any), for thumbnail or hero-image use.
    * ``provenance_token`` — manifest pointer / event id / artifact
      hash from the upstream adapter.
    * ``provenance_evidence_refs`` — supporting evidence refs
      attached to the RVPE provenance.
    * ``rights_class`` / ``privacy_class`` — verified at the gate
      and re-surfaced for institutional disclosure.
    * ``n1_explanation`` — short prose explaining how this replay
      participates in the n=1 instrument (operator-supplied at
      generation time; no LLM authoring).
    * ``suggested_audience`` — operator-supplied free-text steer for
      which institutional surface this card best fits.
    * ``programme_id`` / ``broadcast_id`` — upstream programme /
      broadcast identifiers for cross-referencing.
    """

    event_id: str
    public_url: str | None
    replay_title: str
    chapter_label: str | None
    chapter_timecode: str | None
    frame_uri: str | None
    frame_kind: str | None
    provenance_token: str | None
    provenance_evidence_refs: tuple[str, ...]
    rights_class: RightsClass
    privacy_class: PrivacyClass
    n1_explanation: str
    suggested_audience: str
    programme_id: str | None
    broadcast_id: str | None


@dataclass(frozen=True)
class ReplayDemoSkip:
    """One decision considered but skipped.

    Distinct from "card returned" so an operator dashboard can show
    *why* an upstream decision did not appear in the kit. The kit
    never silently drops — every input decision is accounted for as
    either a card or a skip.
    """

    decision_id: str
    event_id: str | None
    reason: SkipReason
    detail: str = ""


def generate_demo_cards(
    decisions: Iterable[ArchiveReplayPublicLinkDecision],
    *,
    n1_explanation: str,
    suggested_audience: str,
) -> tuple[list[ReplayDemoCard], list[ReplayDemoSkip]]:
    """Project archive-replay decisions into demo cards (fail closed).

    Parameters
    ----------
    decisions:
        Iterable of `ArchiveReplayPublicLinkDecision` from the
        archive-replay-public-event-link-adapter. Each decision is
        evaluated independently.
    n1_explanation:
        Operator-supplied prose attached to every emitted card,
        explaining how the replay participates in the Hapax n=1
        instrument. NOT generated by an LLM; the operator owns the
        framing for the institutional surface.
    suggested_audience:
        Operator-supplied free-text steer for which institutional
        audience the cards best fit. Same operator-owns-framing
        principle.

    Returns
    -------
    A pair `(cards, skips)`. `cards` is the institutional-display
    set; `skips` accounts for every decision that didn't qualify so
    operator dashboards can surface "why".
    """

    cards: list[ReplayDemoCard] = []
    skips: list[ReplayDemoSkip] = []

    for decision in decisions:
        # Gate 1 — must be a successful emission.
        if decision.status != "emitted":
            skips.append(
                ReplayDemoSkip(
                    decision_id=decision.decision_id,
                    event_id=None,
                    reason="decision_status_not_emitted",
                    detail=(
                        f"status={decision.status} unavailable={list(decision.unavailable_reasons)}"
                    ),
                )
            )
            continue

        # Gate 2 — emission must carry an RVPE public_event.
        event = decision.public_event
        if event is None:
            skips.append(
                ReplayDemoSkip(
                    decision_id=decision.decision_id,
                    event_id=None,
                    reason="public_event_missing",
                    detail="status=emitted but public_event=None",
                )
            )
            continue

        # Gate 3 — rights class must be public-safe.
        if event.rights_class not in PUBLIC_SAFE_RIGHTS:
            skips.append(
                ReplayDemoSkip(
                    decision_id=decision.decision_id,
                    event_id=event.event_id,
                    reason="rights_class_not_public_safe",
                    detail=f"rights_class={event.rights_class}",
                )
            )
            continue

        # Gate 4 — privacy class must be public-safe.
        if event.privacy_class not in PUBLIC_SAFE_PRIVACY:
            skips.append(
                ReplayDemoSkip(
                    decision_id=decision.decision_id,
                    event_id=event.event_id,
                    reason="privacy_class_not_public_safe",
                    detail=f"privacy_class={event.privacy_class}",
                )
            )
            continue

        cards.append(
            _card_from_event(
                event=event,
                n1_explanation=n1_explanation,
                suggested_audience=suggested_audience,
            )
        )

    return cards, skips


def _card_from_event(
    *,
    event,
    n1_explanation: str,
    suggested_audience: str,
) -> ReplayDemoCard:
    """Build a `ReplayDemoCard` from a verified RVPE projection."""

    chapter_label = event.chapter_ref.label if event.chapter_ref else None
    chapter_timecode = event.chapter_ref.timecode if event.chapter_ref else None
    frame_uri = event.frame_ref.uri if event.frame_ref else None
    frame_kind = event.frame_ref.kind if event.frame_ref else None
    return ReplayDemoCard(
        event_id=event.event_id,
        public_url=event.public_url,
        replay_title=_derive_replay_title(event),
        chapter_label=chapter_label,
        chapter_timecode=chapter_timecode,
        frame_uri=frame_uri,
        frame_kind=frame_kind,
        provenance_token=event.provenance.token,
        provenance_evidence_refs=tuple(event.provenance.evidence_refs),
        rights_class=event.rights_class,
        privacy_class=event.privacy_class,
        n1_explanation=n1_explanation,
        suggested_audience=suggested_audience,
        programme_id=event.programme_id,
        broadcast_id=event.broadcast_id,
    )


def _derive_replay_title(event) -> str:
    """Title shown to institutional viewers.

    The RVPE carries a chapter_ref.label that's typically the most
    human-readable handle. Falls back to the event_id when no
    chapter ref exists — the operator can override per-card if a
    cleaner title is needed.
    """
    if event.chapter_ref and event.chapter_ref.label:
        return event.chapter_ref.label
    return event.event_id


__all__ = [
    "PRODUCER",
    "PUBLIC_SAFE_PRIVACY",
    "PUBLIC_SAFE_RIGHTS",
    "ReplayDemoCard",
    "ReplayDemoSkip",
    "SkipReason",
    "TASK_ANCHOR",
    "generate_demo_cards",
]

"""Format archive replay artifact adapter.

Converts eligible content programme runs into replay cards, zines/logbooks,
datasets, artifact bundles, condition editions, and grant/demo evidence.
Fails closed without anonymization/rights and public-event provenance.

Authority case: CASE-AUTONOMOUS-CONTENT-20260429
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)


class RightsClass(StrEnum):
    OPERATOR_OWNED = "operator_owned"
    PUBLIC_DOMAIN = "public_domain"
    LICENSED = "licensed"
    UNCLEARED = "uncleared"


class PrivacyClass(StrEnum):
    FULLY_PUBLIC = "fully_public"
    ANONYMIZED = "anonymized"
    UNANONYMIZED = "unanonymized"


class ArtifactFormat(StrEnum):
    REPLAY_CARD = "replay_card"
    ZINE_LOGBOOK = "zine_logbook"
    DATASET = "dataset"
    ARTIFACT_BUNDLE = "artifact_bundle"
    CONDITION_EDITION = "condition_edition"
    GRANT_DEMO_EVIDENCE = "grant_demo_evidence"


class ArtifactStatus(StrEnum):
    CANDIDATE = "candidate"
    BLOCKED = "blocked"
    PUBLISHED = "published"
    REUSED = "reused"
    SOLD = "sold"
    GRANT_USED = "grant_used"


PUBLISHABLE_RIGHTS: frozenset[RightsClass] = frozenset(
    {RightsClass.OPERATOR_OWNED, RightsClass.PUBLIC_DOMAIN, RightsClass.LICENSED}
)
PUBLISHABLE_PRIVACY: frozenset[PrivacyClass] = frozenset(
    {PrivacyClass.FULLY_PUBLIC, PrivacyClass.ANONYMIZED}
)


class _AdapterModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProgrammeRunRef(_AdapterModel):
    run_id: str = Field(min_length=1)
    programme_id: str = Field(min_length=1)
    broadcast_id: str | None = None
    event_refs: tuple[str, ...] = Field(default_factory=tuple)
    chapter_refs: tuple[str, ...] = Field(default_factory=tuple)
    frame_refs: tuple[str, ...] = Field(default_factory=tuple)
    archive_refs: tuple[str, ...] = Field(default_factory=tuple)
    grounding_question: str | None = None
    rights_class: RightsClass
    privacy_class: PrivacyClass
    provenance_token: str | None = None
    public_event_link: str | None = None


class ReplayCardCandidate(_AdapterModel):
    artifact_id: str = Field(min_length=1)
    format: Literal[ArtifactFormat.REPLAY_CARD] = ArtifactFormat.REPLAY_CARD
    status: ArtifactStatus
    run_ref: ProgrammeRunRef
    title: str = Field(min_length=1)
    blocked_reason: str | None = None


class ZineLogbookCandidate(_AdapterModel):
    artifact_id: str = Field(min_length=1)
    format: Literal[ArtifactFormat.ZINE_LOGBOOK] = ArtifactFormat.ZINE_LOGBOOK
    status: ArtifactStatus
    run_ref: ProgrammeRunRef
    tier_sheets: tuple[str, ...] = Field(default_factory=tuple)
    bracket_paths: tuple[str, ...] = Field(default_factory=tuple)
    review_rubrics: tuple[str, ...] = Field(default_factory=tuple)
    refusal_appendix: str | None = None
    condition_stills: tuple[str, ...] = Field(default_factory=tuple)
    provenance_pages: tuple[str, ...] = Field(default_factory=tuple)
    blocked_reason: str | None = None


class ArtifactAdapterResult(_AdapterModel):
    run_id: str
    replay_card: ReplayCardCandidate | None = None
    zine_logbook: ZineLogbookCandidate | None = None
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)
    generated_at: str


def adapt_programme_run(run: ProgrammeRunRef) -> ArtifactAdapterResult:
    """Convert one programme run into artifact candidates.

    Fails closed: missing rights, privacy, or provenance blocks all outputs.
    """
    now = datetime.now(UTC).isoformat()
    blockers: list[str] = []

    if run.rights_class not in PUBLISHABLE_RIGHTS:
        blockers.append(f"rights_class={run.rights_class.value}")
    if run.privacy_class not in PUBLISHABLE_PRIVACY:
        blockers.append(f"privacy_class={run.privacy_class.value}")
    if not run.provenance_token:
        blockers.append("missing_provenance_token")
    if not run.public_event_link:
        blockers.append("missing_public_event_link")

    if blockers:
        return ArtifactAdapterResult(
            run_id=run.run_id,
            replay_card=ReplayCardCandidate(
                artifact_id=f"rc-{run.run_id}",
                status=ArtifactStatus.BLOCKED,
                run_ref=run,
                title=f"Replay: {run.programme_id}",
                blocked_reason="; ".join(blockers),
            ),
            zine_logbook=ZineLogbookCandidate(
                artifact_id=f"zl-{run.run_id}",
                status=ArtifactStatus.BLOCKED,
                run_ref=run,
                blocked_reason="; ".join(blockers),
            ),
            blocked_reasons=tuple(blockers),
            generated_at=now,
        )

    replay_card = ReplayCardCandidate(
        artifact_id=f"rc-{run.run_id}",
        status=ArtifactStatus.CANDIDATE,
        run_ref=run,
        title=_replay_title(run),
    )

    zine_logbook = ZineLogbookCandidate(
        artifact_id=f"zl-{run.run_id}",
        status=ArtifactStatus.CANDIDATE,
        run_ref=run,
        tier_sheets=run.chapter_refs,
        bracket_paths=run.archive_refs,
        condition_stills=run.frame_refs,
        provenance_pages=(run.provenance_token,) if run.provenance_token else (),
    )

    return ArtifactAdapterResult(
        run_id=run.run_id,
        replay_card=replay_card,
        zine_logbook=zine_logbook,
        generated_at=now,
    )


def _replay_title(run: ProgrammeRunRef) -> str:
    if run.grounding_question:
        return f"Replay: {run.grounding_question}"
    return f"Replay: {run.programme_id} ({run.run_id})"


__all__ = [
    "PUBLISHABLE_PRIVACY",
    "PUBLISHABLE_RIGHTS",
    "ArtifactAdapterResult",
    "ArtifactFormat",
    "ArtifactStatus",
    "ProgrammeRunRef",
    "ReplayCardCandidate",
    "ZineLogbookCandidate",
    "adapt_programme_run",
]

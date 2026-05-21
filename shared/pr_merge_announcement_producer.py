"""PR merge announcement producer for the publication bus.

Converts merged PR metadata into ResearchVehiclePublicEvent payloads
and appends them to the publication bus JSONL file.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from shared.conversion_broker import DEFAULT_PUBLIC_EVENT_PATH
from shared.research_vehicle_public_event import (
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
)

log = logging.getLogger(__name__)

PRODUCER = "shared.pr_merge_announcement_producer"


def build_pr_merge_event(
    *,
    pr_number: int,
    pr_title: str,
    merge_sha: str,
    merged_at: str,
    author: str,
    repo: str = "hapax-systems/hapax-council",
    changed_files: int = 0,
    additions: int = 0,
    deletions: int = 0,
) -> ResearchVehiclePublicEvent:
    event_id = hashlib.sha256(f"pr-merge:{repo}:{pr_number}:{merge_sha}".encode()).hexdigest()[:16]

    summary = _build_technical_note(
        pr_number=pr_number,
        pr_title=pr_title,
        author=author,
        changed_files=changed_files,
        additions=additions,
        deletions=deletions,
    )

    return ResearchVehiclePublicEvent(
        event_id=f"pr-merge-{event_id}",
        event_type="metadata.update",
        occurred_at=merged_at,
        broadcast_id=None,
        programme_id=None,
        condition_id=None,
        source=PublicEventSource(
            producer=PRODUCER,
            substrate_id=f"github:{repo}",
            task_anchor=f"pr/{pr_number}",
            evidence_ref=f"commit:{merge_sha}",
            freshness_ref=None,
        ),
        salience=_compute_salience(changed_files, additions, deletions),
        state_kind="research_observation",
        rights_class="operator_original",
        privacy_class="public_safe",
        provenance=PublicEventProvenance(
            token=None,
            generated_at=merged_at,
            producer=PRODUCER,
            evidence_refs=[f"commit:{merge_sha}"],
            rights_basis="operator_original",
            citation_refs=[f"github:{repo}/pull/{pr_number}", summary],
        ),
        public_url=None,
        frame_ref=None,
        chapter_ref=None,
        surface_policy=PublicEventSurfacePolicy(
            allowed_surfaces=["github_profile", "omg_statuslog"],
            denied_surfaces=[],
            claim_live=False,
            claim_archive=True,
            claim_monetizable=False,
            requires_egress_public_claim=False,
            requires_audio_safe=False,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key=None,
            redaction_policy="none",
            fallback_action="archive_only",
            dry_run_reason=None,
        ),
    )


def _build_technical_note(
    *,
    pr_number: int,
    pr_title: str,
    author: str,
    changed_files: int,
    additions: int,
    deletions: int,
) -> str:
    parts = [f"PR #{pr_number} merged: {pr_title}"]
    if changed_files:
        parts.append(f"{changed_files} files changed (+{additions}/-{deletions})")
    if author:
        parts.append(f"by {author}")
    return ". ".join(parts) + "."


def _compute_salience(changed_files: int, additions: int, deletions: int) -> float:
    total_lines = additions + deletions
    if total_lines > 500 or changed_files > 20:
        return 0.8
    if total_lines > 100 or changed_files > 5:
        return 0.5
    return 0.3


def emit_pr_merge_event(
    event: ResearchVehiclePublicEvent,
    output_path: Path = DEFAULT_PUBLIC_EVENT_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as f:
        f.write(event.to_json_line())
    log.info("pr_merge_announcement: emitted %s to %s", event.event_id, output_path)
    return output_path

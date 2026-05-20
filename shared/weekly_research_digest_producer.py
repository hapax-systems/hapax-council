"""Weekly research digest producer for the publication bus.

Aggregates 7 days of velocity digests and PR merge events into a
thread-formatted social update. Emits ResearchVehiclePublicEvent
payloads to the publication bus. Designed to run via Sunday systemd
timer.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.conversion_broker import DEFAULT_PUBLIC_EVENT_PATH
from shared.research_vehicle_public_event import (
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
)

log = logging.getLogger(__name__)

PRODUCER = "shared.weekly_research_digest_producer"
DEFAULT_PR_EVENTS_PATH = (
    Path.home() / "hapax-state" / "content-programme-runs" / "public-events.jsonl"
)


def load_recent_events(
    events_path: Path = DEFAULT_PR_EVENTS_PATH,
    days: int = 7,
) -> list[dict]:
    if not events_path.exists():
        return []
    cutoff = datetime.now(UTC) - timedelta(days=days)
    cutoff_str = cutoff.isoformat()
    events = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if event.get("occurred_at", "") >= cutoff_str:
                events.append(event)
        except json.JSONDecodeError:
            continue
    return events


def build_digest_thread(events: list[dict], week_ending: str) -> list[str]:
    pr_events = [e for e in events if e.get("event_type") == "metadata.update"]
    other_events = [e for e in events if e.get("event_type") != "metadata.update"]

    thread = [f"Week ending {week_ending}: {len(events)} events across the research vehicle."]

    if pr_events:
        thread.append(f"{len(pr_events)} PRs merged this week.")

    event_types = {}
    for e in other_events:
        et = e.get("event_type", "unknown")
        event_types[et] = event_types.get(et, 0) + 1
    if event_types:
        type_summary = ", ".join(
            f"{v} {k}" for k, v in sorted(event_types.items(), key=lambda x: -x[1])
        )
        thread.append(f"Other activity: {type_summary}.")

    if not events:
        thread = [f"Week ending {week_ending}: quiet week, no publication bus events recorded."]

    return thread


def build_digest_event(
    thread: list[str],
    week_ending: str,
    event_count: int,
    *,
    dry_run: bool = False,
) -> ResearchVehiclePublicEvent:
    digest_text = "\n".join(thread)
    event_id = hashlib.sha256(f"weekly-digest:{week_ending}:{event_count}".encode()).hexdigest()[
        :16
    ]

    return ResearchVehiclePublicEvent(
        event_id=f"weekly-digest-{event_id}",
        event_type="velocity.digest",
        occurred_at=datetime.now(UTC).isoformat(),
        broadcast_id=None,
        programme_id=None,
        condition_id=None,
        source=PublicEventSource(
            producer=PRODUCER,
            substrate_id="weekly-digest",
            task_anchor=f"week-ending-{week_ending}",
            evidence_ref=f"digest:{week_ending}",
            freshness_ref=None,
        ),
        salience=0.6,
        state_kind="research_observation",
        rights_class="operator_original",
        privacy_class="public_safe",
        provenance=PublicEventProvenance(
            token=None,
            generated_at=datetime.now(UTC).isoformat(),
            producer=PRODUCER,
            evidence_refs=[f"digest:{week_ending}"],
            rights_basis="operator_original",
            citation_refs=[digest_text],
        ),
        public_url=None,
        frame_ref=None,
        chapter_ref=None,
        surface_policy=PublicEventSurfacePolicy(
            allowed_surfaces=["omg_statuslog", "omg_weblog", "github_profile"],
            denied_surfaces=[],
            claim_live=False,
            claim_archive=True,
            claim_monetizable=False,
            requires_egress_public_claim=False,
            requires_audio_safe=False,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key="weekly-digest",
            redaction_policy="none",
            fallback_action="archive_only",
            dry_run_reason="dry_run_mode" if dry_run else None,
        ),
    )


def emit_digest(
    event: ResearchVehiclePublicEvent,
    output_path: Path = DEFAULT_PUBLIC_EVENT_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as f:
        f.write(event.to_json_line())
    log.info("weekly_digest: emitted %s to %s", event.event_id, output_path)
    return output_path


def run_weekly_digest(
    *,
    events_path: Path = DEFAULT_PR_EVENTS_PATH,
    output_path: Path = DEFAULT_PUBLIC_EVENT_PATH,
    dry_run: bool = False,
) -> ResearchVehiclePublicEvent:
    week_ending = datetime.now(UTC).strftime("%Y-%m-%d")
    events = load_recent_events(events_path)
    thread = build_digest_thread(events, week_ending)
    digest_event = build_digest_event(thread, week_ending, len(events), dry_run=dry_run)
    if not dry_run:
        emit_digest(digest_event, output_path)
    return digest_event

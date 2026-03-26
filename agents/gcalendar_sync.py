"""Google Calendar RAG sync — event indexing and behavioral tracking.

Usage:
    uv run python -m agents.gcalendar_sync --auth        # OAuth consent
    uv run python -m agents.gcalendar_sync --full-sync    # Full calendar sync
    uv run python -m agents.gcalendar_sync --auto         # Incremental sync
    uv run python -m agents.gcalendar_sync --stats        # Show sync state
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field, computed_field

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

CACHE_DIR = Path.home() / ".cache" / "gcalendar-sync"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "calendar-profile-facts.jsonl"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"
RAG_SOURCES = Path.home() / "documents" / "rag-sources"
GCALENDAR_DIR = RAG_SOURCES / "gcalendar"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
]

# How far back/forward to sync
PAST_DAYS = 30
FUTURE_DAYS = 90
# Events within this window get written as markdown for RAG
RAG_WINDOW_DAYS = 14


# ── Schemas ──────────────────────────────────────────────────────────────────


class CalendarEvent(BaseModel):
    """A calendar event."""

    event_id: str
    summary: str
    start: str  # ISO datetime or date string
    end: str
    all_day: bool = False
    location: str = ""
    description: str = ""
    attendees: list[str] = Field(default_factory=list)
    organizer: str = ""
    recurring: bool = False
    recurrence_rule: str = ""
    status: str = "confirmed"  # confirmed, tentative, cancelled
    calendar_id: str = "primary"
    synced_at: float = 0.0
    local_path: str = ""

    @computed_field
    @property
    def duration_minutes(self) -> int:
        """Compute event duration in minutes."""
        if self.all_day:
            return 0
        try:
            start_dt = datetime.fromisoformat(self.start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(self.end.replace("Z", "+00:00"))
            return int((end_dt - start_dt).total_seconds() / 60)
        except (ValueError, TypeError):
            return 0


class CalendarSyncState(BaseModel):
    """Persistent sync state."""

    sync_token: str = ""
    events: dict[str, CalendarEvent] = Field(default_factory=dict)
    last_full_sync: float = 0.0
    last_sync: float = 0.0
    stats: dict[str, int] = Field(default_factory=dict)


# ── State Management ─────────────────────────────────────────────────────────


def _load_state(path: Path = STATE_FILE) -> CalendarSyncState:
    """Load sync state from disk."""
    if path.exists():
        try:
            return CalendarSyncState.model_validate_json(path.read_text())
        except Exception as exc:
            log.warning("Corrupt state file, starting fresh: %s", exc)
    return CalendarSyncState()


def _save_state(state: CalendarSyncState, path: Path = STATE_FILE) -> None:
    """Persist sync state to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    tmp.rename(path)


# ── Event Formatting ─────────────────────────────────────────────────────────


def _format_event_markdown(e: CalendarEvent) -> str:
    """Generate markdown file for a calendar event with YAML frontmatter."""
    people_str = "[" + ", ".join(e.attendees) + "]"

    # Parse start time for display
    try:
        if e.all_day:
            start_display = e.start
            ts_frontmatter = e.start
        else:
            dt = datetime.fromisoformat(e.start.replace("Z", "+00:00"))
            start_display = dt.strftime("%a %b %d, %H:%M")
            end_dt = datetime.fromisoformat(e.end.replace("Z", "+00:00"))
            start_display += f"–{end_dt.strftime('%H:%M')}"
            ts_frontmatter = dt.strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        start_display = e.start
        ts_frontmatter = e.start

    recurrence_line = ""
    if e.recurring and e.recurrence_rule:
        recurrence_line = f"\n**Recurrence:** {e.recurrence_rule}"

    location_line = f"\n**Location:** {e.location}" if e.location else ""
    description_block = f"\n\n{e.description}" if e.description else ""

    return f"""---
platform: google
service: calendar
content_type: calendar_event
source_service: gcalendar
source_platform: google
record_id: {e.event_id}
timestamp: {ts_frontmatter}
modality_tags: [temporal, social]
people: {people_str}
duration_minutes: {e.duration_minutes}
recurring: {str(e.recurring).lower()}
---

# {e.summary}

**When:** {start_display}
**Attendees:** {", ".join(e.attendees) if e.attendees else "none"}{location_line}{recurrence_line}{description_block}
"""


# ── Calendar API Operations ──────────────────────────────────────────────────


def _get_calendar_service():
    """Build authenticated Calendar API service."""
    from shared.google_auth import build_service

    return build_service("calendar", "v3", SCOPES)


def _parse_api_event(item: dict) -> CalendarEvent | None:
    """Parse a Calendar API event item into a CalendarEvent."""
    if item.get("status") == "cancelled":
        return None

    start_raw = item.get("start", {})
    end_raw = item.get("end", {})
    all_day = "date" in start_raw and "dateTime" not in start_raw

    start = start_raw.get("dateTime") or start_raw.get("date", "")
    end = end_raw.get("dateTime") or end_raw.get("date", "")

    attendees = []
    for a in item.get("attendees", []):
        email = a.get("email", "")
        if email and not a.get("self", False):
            attendees.append(email)

    return CalendarEvent(
        event_id=item["id"],
        summary=item.get("summary", "(no title)"),
        start=start,
        end=end,
        all_day=all_day,
        location=item.get("location", ""),
        description=item.get("description", ""),
        attendees=attendees,
        organizer=item.get("organizer", {}).get("email", ""),
        recurring="recurringEventId" in item,
        recurrence_rule=", ".join(item.get("recurrence", [])),
        status=item.get("status", "confirmed"),
    )


def _full_sync(service, state: CalendarSyncState) -> int:
    """Full sync of calendar events within the time window."""
    log.info("Starting full calendar sync...")

    now = datetime.now(UTC)
    time_min = (now - timedelta(days=PAST_DAYS)).isoformat()
    time_max = (now + timedelta(days=FUTURE_DAYS)).isoformat()

    count = 0
    page_token = None
    while True:
        resp = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=2500,
                pageToken=page_token,
            )
            .execute()
        )

        for item in resp.get("items", []):
            event = _parse_api_event(item)
            if event:
                state.events[event.event_id] = event
                count += 1

        page_token = resp.get("nextPageToken")
        if not page_token:
            state.sync_token = resp.get("nextSyncToken", "")
            break

    state.last_full_sync = time.time()
    log.info("Full sync complete: %d events", count)
    return count


def _incremental_sync(service, state: CalendarSyncState) -> list[str]:
    """Incremental sync using stored sync token. Returns changed event IDs."""
    if not state.sync_token:
        log.warning("No sync token — run --full-sync first")
        return []

    changed_ids: list[str] = []
    page_token = None
    sync_token = state.sync_token

    while True:
        try:
            resp = (
                service.events()
                .list(
                    calendarId="primary",
                    syncToken=sync_token if not page_token else None,
                    pageToken=page_token,
                    maxResults=2500,
                )
                .execute()
            )
        except Exception as exc:
            if "410" in str(exc):
                log.warning("Sync token expired — full sync required")
                state.sync_token = ""
                return []
            raise

        for item in resp.get("items", []):
            eid = item["id"]
            if item.get("status") == "cancelled":
                if eid in state.events:
                    _log_change(state.events[eid], "cancelled")
                    state.events.pop(eid)
                changed_ids.append(eid)
                continue

            old_event = state.events.get(eid)
            event = _parse_api_event(item)
            if event:
                if old_event and old_event.start != event.start:
                    _log_change(event, "rescheduled", {"old_start": old_event.start})
                elif not old_event:
                    _log_change(event, "created")
                state.events[eid] = event
                changed_ids.append(eid)

        page_token = resp.get("nextPageToken")
        if not page_token:
            state.sync_token = resp.get("nextSyncToken", state.sync_token)
            break

    state.last_sync = time.time()
    log.info("Incremental sync: %d changes", len(changed_ids))
    return changed_ids


# ── Behavioral Logging ───────────────────────────────────────────────────────


def _log_change(event: CalendarEvent, change_type: str, extra: dict | None = None) -> None:
    """Append calendar change event to JSONL log."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "service": "gcalendar",
        "event_type": change_type,
        "record_id": event.event_id,
        "name": event.summary,
        "context": {
            "attendees": event.attendees,
            "start": event.start,
            "recurring": event.recurring,
            **(extra or {}),
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }
    with open(CHANGES_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    log.debug("Logged calendar change: %s %s", change_type, event.summary)


# ── File Writing ─────────────────────────────────────────────────────────────


def _write_upcoming_events(state: CalendarSyncState) -> int:
    """Write upcoming events as markdown to rag-sources/gcalendar/."""
    GCALENDAR_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    cutoff = now + timedelta(days=RAG_WINDOW_DAYS)
    written = 0

    # Clean old files first
    for f in GCALENDAR_DIR.glob("*.md"):
        f.unlink()

    for event in state.events.values():
        if event.status == "cancelled":
            continue
        try:
            if event.all_day:
                event_dt = datetime.fromisoformat(event.start + "T00:00:00+00:00")
            else:
                event_dt = datetime.fromisoformat(event.start.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        # Only write events in the upcoming RAG window
        if event_dt < now - timedelta(hours=2) or event_dt > cutoff:
            continue

        md = _format_event_markdown(event)
        safe_name = event.summary.replace("/", "_").replace(" ", "-")[:60]
        date_prefix = event_dt.strftime("%Y-%m-%d")
        filename = f"{date_prefix}-{safe_name}-{event.event_id[:8]}.md"
        filepath = GCALENDAR_DIR / filename
        filepath.write_text(md, encoding="utf-8")
        event.local_path = str(filepath)
        event.synced_at = time.time()
        written += 1

    log.info("Wrote %d upcoming events to %s", written, GCALENDAR_DIR)
    return written


# ── Profiler Integration ─────────────────────────────────────────────────────


def _generate_profile_facts(state: CalendarSyncState) -> list[dict]:
    """Generate deterministic profile facts from calendar state."""
    from collections import Counter

    attendee_counts: Counter[str] = Counter()
    recurring_names: list[str] = []
    total_minutes = 0
    event_count = 0

    for e in state.events.values():
        if e.status == "cancelled":
            continue
        event_count += 1
        total_minutes += e.duration_minutes
        for a in e.attendees:
            attendee_counts[a] += 1
        if e.recurring and e.summary not in recurring_names:
            recurring_names.append(e.summary)

    facts = []
    source = "gcalendar-sync:calendar-profile-facts"

    if event_count:
        weeks = max(1, (PAST_DAYS + FUTURE_DAYS) / 7)
        facts.append(
            {
                "dimension": "work_patterns",
                "key": "calendar_meeting_cadence",
                "value": f"{event_count / weeks:.1f} meetings/week, {total_minutes / event_count:.0f} min avg",
                "confidence": 0.95,
                "source": source,
                "evidence": f"Computed from {event_count} events over {PAST_DAYS + FUTURE_DAYS} day window",
            }
        )

    if attendee_counts:
        top = ", ".join(f"{email} ({n})" for email, n in attendee_counts.most_common(10))
        facts.append(
            {
                "dimension": "communication_patterns",
                "key": "calendar_frequent_attendees",
                "value": top,
                "confidence": 0.95,
                "source": source,
                "evidence": f"Top attendees across {event_count} events",
            }
        )

    if recurring_names:
        facts.append(
            {
                "dimension": "work_patterns",
                "key": "calendar_recurring_commitments",
                "value": ", ".join(recurring_names[:15]),
                "confidence": 0.95,
                "source": source,
                "evidence": f"{len(recurring_names)} recurring events detected",
            }
        )

    # Behavioral patterns from changes log
    if CHANGES_LOG.exists():
        change_counts: Counter[str] = Counter()
        total_changes = 0
        for line in CHANGES_LOG.read_text().splitlines():
            try:
                entry = json.loads(line)
                change_counts[entry.get("event_type", "unknown")] += 1
                total_changes += 1
            except json.JSONDecodeError:
                continue
        if total_changes:
            dist = ", ".join(f"{k} ({v})" for k, v in change_counts.most_common(5))
            facts.append(
                {
                    "dimension": "work_patterns",
                    "key": "calendar_change_patterns",
                    "value": f"{total_changes} changes: {dist}",
                    "confidence": 0.95,
                    "source": source,
                    "evidence": f"Accumulated from {total_changes} calendar change events",
                }
            )

    return facts


def _write_profile_facts(state: CalendarSyncState) -> None:
    """Write profile facts JSONL for profiler bridge consumption."""
    facts = _generate_profile_facts(state)
    if not facts:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROFILE_FACTS_FILE, "w", encoding="utf-8") as fh:
        for fact in facts:
            fh.write(json.dumps(fact) + "\n")
    log.info("Wrote %d profile facts to %s", len(facts), PROFILE_FACTS_FILE)


# ── Sensor Protocol ──────────────────────────────────────────────────────────


def _parse_event_dt(e: CalendarEvent) -> datetime | None:
    """Parse event start to datetime."""
    try:
        if e.all_day:
            return datetime.fromisoformat(e.start + "T00:00:00+00:00")
        return datetime.fromisoformat(e.start.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _find_next_event(state: CalendarSyncState, now: datetime) -> dict | None:
    """Find the next upcoming event."""
    best: tuple[datetime, CalendarEvent] | None = None
    for e in state.events.values():
        if e.status == "cancelled":
            continue
        dt = _parse_event_dt(e)
        if dt is None or dt <= now:
            continue
        if best is None or dt < best[0]:
            best = (dt, e)
    if best is None:
        return None
    return {
        "summary": best[1].summary,
        "start": best[1].start,
        "minutes_until": int((best[0] - now).total_seconds() / 60),
    }


def _write_sensor_snapshot(state: CalendarSyncState) -> None:
    """Write calendar summary to /dev/shm for DMN consumption."""
    from shared.sensor_protocol import write_sensor_state

    now = datetime.now(UTC)
    upcoming = sum(
        1
        for e in state.events.values()
        if e.status != "cancelled" and (dt := _parse_event_dt(e)) is not None and dt > now
    )
    write_sensor_state(
        "gcalendar",
        {
            "total_events": len(state.events),
            "upcoming": upcoming,
            "next_event": _find_next_event(state, now),
            "last_sync": state.last_sync,
        },
    )


# ── Stats ────────────────────────────────────────────────────────────────────


def _print_stats(state: CalendarSyncState) -> None:
    """Print sync statistics."""
    total = len(state.events)
    now = datetime.now(UTC)

    upcoming = 0
    past = 0
    for e in state.events.values():
        try:
            dt = datetime.fromisoformat(e.start.replace("Z", "+00:00"))
            if dt > now:
                upcoming += 1
            else:
                past += 1
        except (ValueError, TypeError):
            pass

    print("Google Calendar Sync State")
    print("=" * 40)
    print(f"Total events:    {total:,}")
    print(f"Upcoming:        {upcoming:,}")
    print(f"Past:            {past:,}")
    print(
        f"Last full sync:  {datetime.fromtimestamp(state.last_full_sync, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_full_sync else 'never'}"
    )
    print(
        f"Last sync:       {datetime.fromtimestamp(state.last_sync, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}"
    )


# ── Orchestration ────────────────────────────────────────────────────────────


def run_auth() -> None:
    """Verify OAuth credentials work for Calendar."""
    print("Authenticating with Google Calendar...")
    service = _get_calendar_service()
    cals = service.calendarList().list(maxResults=5).execute()
    for cal in cals.get("items", []):
        print(f"  Calendar: {cal.get('summary', 'unknown')} ({cal['id']})")
    print("Authentication successful.")


def run_full_sync() -> None:
    """Full calendar sync."""
    from shared.notify import send_notification

    service = _get_calendar_service()
    state = _load_state()

    count = _full_sync(service, state)
    written = _write_upcoming_events(state)
    _save_state(state)
    _write_profile_facts(state)
    _write_sensor_snapshot(state)

    from shared.sensor_protocol import emit_sensor_impingement

    emit_sensor_impingement("gcalendar", "work_patterns", ["full_sync"], strength=0.3)

    msg = f"Calendar sync: {count} events, {written} written to RAG"
    log.info(msg)
    send_notification("GCalendar Sync", msg, tags=["calendar"])


def run_auto() -> None:
    """Incremental sync."""
    from shared.notify import send_notification

    service = _get_calendar_service()
    state = _load_state()

    if not state.sync_token:
        log.info("No sync token — running full sync")
        run_full_sync()
        return

    changed_ids = _incremental_sync(service, state)
    written = _write_upcoming_events(state)
    _save_state(state)
    _write_profile_facts(state)
    _write_sensor_snapshot(state)

    if changed_ids:
        from shared.sensor_protocol import emit_sensor_impingement

        emit_sensor_impingement("gcalendar", "work_patterns", ["event_changes"], strength=0.3)
        msg = f"Calendar: {len(changed_ids)} changes, {written} events in RAG"
        log.info(msg)
        send_notification("GCalendar Sync", msg, tags=["calendar"])
    else:
        log.info("No calendar changes")


def run_stats() -> None:
    """Display sync statistics."""
    state = _load_state()
    if not state.events:
        print("No sync state found. Run --full-sync first.")
        return
    _print_stats(state)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Calendar RAG sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--auth", action="store_true", help="Verify OAuth")
    group.add_argument("--full-sync", action="store_true", help="Full calendar sync")
    group.add_argument("--auto", action="store_true", help="Incremental sync")
    group.add_argument("--stats", action="store_true", help="Show sync statistics")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="gcalendar-sync", level="DEBUG" if args.verbose else None)

    action = (
        "auth" if args.auth else "full_sync" if args.full_sync else "auto" if args.auto else "stats"
    )
    with _tracer.start_as_current_span(
        f"gcalendar_sync.{action}",
        attributes={"agent.name": "gcalendar_sync", "agent.repo": "hapax-council"},
    ):
        if args.auth:
            run_auth()
        elif args.full_sync:
            run_full_sync()
        elif args.auto:
            run_auto()
        elif args.stats:
            run_stats()


if __name__ == "__main__":
    main()

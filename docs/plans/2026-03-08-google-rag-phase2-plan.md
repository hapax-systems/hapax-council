# Google RAG Phase 2 — Calendar + Drive Improvements + Agent Integration

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Google Calendar live sync, improve Drive data consumption across Hapax agents, extract shared Google auth, modify management_prep/meeting_lifecycle/briefing/digest to consume calendar and Drive data, and update documentation across all repos.

**Architecture:** Extract shared Google auth from gdrive_sync into shared/google_auth.py. Build gcalendar_sync.py following the same pattern. Add shared/calendar_context.py as a query interface. Modify ingest.py to auto-tag Drive files. Modify consumer agents to use new data. Update system docs.

**Tech Stack:** google-api-python-client, google-auth-oauthlib, pydantic v2, shared.config, shared.notify, systemd user timers

**Design doc:** `docs/plans/2026-03-08-google-rag-integration-design.md` (in distro-work repo)

---

## Task 1: Extract Shared Google Auth

**Files:**
- Create: `~/projects/ai-agents/shared/google_auth.py`
- Modify: `~/projects/ai-agents/agents/gdrive_sync.py`
- Create: `~/projects/ai-agents/tests/test_google_auth.py`

**Step 1: Write failing test**

Create `~/projects/ai-agents/tests/test_google_auth.py`:

```python
"""Tests for shared Google auth utilities."""
from __future__ import annotations

from unittest.mock import patch, MagicMock


def test_get_credentials_returns_valid_cached(tmp_path):
    """Valid cached token is returned without refresh."""
    from shared.google_auth import get_google_credentials
    mock_creds = MagicMock()
    mock_creds.valid = True

    with patch("shared.google_auth._load_token_from_pass", return_value=mock_creds):
        result = get_google_credentials(["https://www.googleapis.com/auth/drive.readonly"])
    assert result is mock_creds


def test_get_credentials_refreshes_expired(tmp_path):
    """Expired token with refresh_token gets refreshed."""
    from shared.google_auth import get_google_credentials
    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = "refresh_tok"

    with patch("shared.google_auth._load_token_from_pass", return_value=mock_creds), \
         patch("shared.google_auth._save_token_to_pass") as mock_save:
        result = get_google_credentials(["https://www.googleapis.com/auth/drive.readonly"])
    mock_creds.refresh.assert_called_once()
    mock_save.assert_called_once()


def test_build_service():
    """build_service returns a googleapiclient Resource."""
    from shared.google_auth import build_service
    with patch("shared.google_auth.get_google_credentials") as mock_creds, \
         patch("shared.google_auth.discovery_build") as mock_build:
        mock_build.return_value = MagicMock()
        svc = build_service("drive", "v3", ["https://www.googleapis.com/auth/drive.readonly"])
    mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds.return_value)


def test_pass_key_name():
    """Token pass key uses google/token."""
    from shared.google_auth import TOKEN_PASS_KEY, CLIENT_SECRET_PASS_KEY
    assert TOKEN_PASS_KEY == "google/token"
    assert CLIENT_SECRET_PASS_KEY == "google/client-secret"
```

**Step 2: Run tests to verify failure**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_google_auth.py -v
```

Expected: FAIL (module not found).

**Step 3: Create shared/google_auth.py**

```python
"""Shared Google OAuth2 credential management.

All Google service sync agents use this module for authentication.
Credentials stored in pass(1): google/client-secret, google/token.
"""
from __future__ import annotations

import json
import logging
import subprocess

from googleapiclient.discovery import build as discovery_build

log = logging.getLogger(__name__)

TOKEN_PASS_KEY = "google/token"
CLIENT_SECRET_PASS_KEY = "google/client-secret"


def _load_token_from_pass(scopes: list[str]):
    """Load OAuth2 credentials from pass store. Returns Credentials or None."""
    from google.oauth2.credentials import Credentials

    try:
        token_json = subprocess.check_output(
            ["pass", "show", TOKEN_PASS_KEY],
            stderr=subprocess.DEVNULL,
        ).decode()
        return Credentials.from_authorized_user_info(json.loads(token_json), scopes)
    except subprocess.CalledProcessError:
        log.debug("No existing token in pass store")
        return None
    except Exception as exc:
        log.debug("Could not load token: %s", exc)
        return None


def _save_token_to_pass(creds) -> None:
    """Save OAuth token to pass store."""
    token_data = json.dumps({
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    })
    proc = subprocess.run(
        ["pass", "insert", "-m", TOKEN_PASS_KEY],
        input=token_data.encode(),
        capture_output=True,
    )
    if proc.returncode != 0:
        log.warning("Failed to save token to pass: %s", proc.stderr.decode())


def get_google_credentials(scopes: list[str]):
    """Load, refresh, or create OAuth2 credentials.

    Tries cached token first, refreshes if expired, falls back to
    interactive OAuth consent flow (opens browser).
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = _load_token_from_pass(scopes)
    if creds:
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            _save_token_to_pass(creds)
            return creds

    # No valid token — run OAuth flow
    client_json = subprocess.check_output(
        ["pass", "show", CLIENT_SECRET_PASS_KEY],
        stderr=subprocess.DEVNULL,
    ).decode()
    flow = InstalledAppFlow.from_client_config(json.loads(client_json), scopes)
    creds = flow.run_local_server(port=0)
    _save_token_to_pass(creds)
    return creds


def build_service(api: str, version: str, scopes: list[str]):
    """Build an authenticated Google API service client."""
    creds = get_google_credentials(scopes)
    return discovery_build(api, version, credentials=creds)
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_google_auth.py -v
```

Expected: 4 PASS.

**Step 5: Migrate pass keys**

```bash
# Copy existing Drive token to new unified key
pass show gdrive/token | pass insert -m google/token
pass show gdrive/client-secret | pass insert -m google/client-secret
```

**Step 6: Update gdrive_sync.py to use shared auth**

Replace the auth section in `agents/gdrive_sync.py`. Remove `_get_credentials`, `_save_token`, and `_get_drive_service`. Replace with:

```python
# ── Auth ─────────────────────────────────────────────────────────────────────

def _get_drive_service():
    """Build authenticated Drive API service."""
    from shared.google_auth import build_service
    return build_service("drive", "v3", SCOPES)
```

**Step 7: Run all gdrive tests to verify migration**

```bash
uv run pytest tests/test_gdrive_sync.py tests/test_google_auth.py -v
```

Expected: All PASS.

**Step 8: Commit**

```bash
git add shared/google_auth.py tests/test_google_auth.py agents/gdrive_sync.py
git commit -m "refactor: extract shared Google auth from gdrive_sync"
```

---

## Task 2: Drive Auto-Tagging in Ingest Pipeline

**Files:**
- Modify: `~/projects/ai-agents/agents/ingest.py:437-448`
- Modify: `~/projects/ai-agents/tests/test_gdrive_sync.py` (add ingest integration test)

**Step 1: Write failing test**

Add to `~/projects/ai-agents/tests/test_gdrive_sync.py`:

```python
def test_ingest_auto_tags_drive_files():
    """Files from rag-sources/gdrive/ get source_service auto-tagged."""
    from agents.ingest import enrich_payload
    from pathlib import Path

    payload = {
        "source": str(Path.home() / "documents/rag-sources/gdrive/My Drive/Projects/report.pdf"),
        "filename": "report.pdf",
    }
    result = enrich_payload(payload, {})
    assert result.get("source_service") == "gdrive"
    assert result.get("gdrive_folder") == "My Drive"


def test_ingest_auto_tags_calendar_files():
    """Files from rag-sources/gcalendar/ get source_service auto-tagged."""
    from agents.ingest import enrich_payload
    from pathlib import Path

    payload = {
        "source": str(Path.home() / "documents/rag-sources/gcalendar/2026-03-10-standup.md"),
        "filename": "2026-03-10-standup.md",
    }
    result = enrich_payload(payload, {})
    assert result.get("source_service") == "gcalendar"


def test_ingest_no_auto_tag_other_files():
    """Files outside rag-sources service dirs are not auto-tagged."""
    from agents.ingest import enrich_payload

    payload = {
        "source": "/home/user/documents/rag-sources/captures/screenshot.md",
        "filename": "screenshot.md",
    }
    result = enrich_payload(payload, {})
    assert "source_service" not in result or result.get("source_service") == ""
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_gdrive_sync.py -v -k "ingest_auto"
```

Expected: FAIL (no auto-tagging logic yet).

**Step 3: Modify enrich_payload in ingest.py**

At the end of the `enrich_payload` function (after the frontmatter enrichment loop), add source-path auto-detection:

```python
    # Auto-detect source_service from file path if not set by frontmatter
    if "source_service" not in base_payload or not base_payload["source_service"]:
        source_path = base_payload.get("source", "")
        _SERVICE_PATH_PATTERNS = {
            "rag-sources/gdrive": "gdrive",
            "rag-sources/gcalendar": "gcalendar",
            "rag-sources/gmail": "gmail",
            "rag-sources/youtube": "youtube",
            "rag-sources/takeout": "takeout",
            "rag-sources/proton": "proton",
        }
        for pattern, service in _SERVICE_PATH_PATTERNS.items():
            if pattern in source_path:
                base_payload["source_service"] = service
                # Extract top-level subfolder for gdrive
                if service == "gdrive":
                    idx = source_path.find(pattern) + len(pattern) + 1
                    remainder = source_path[idx:]
                    top_folder = remainder.split("/")[0] if remainder else ""
                    if top_folder and top_folder != ".meta":
                        base_payload["gdrive_folder"] = top_folder
                break

    return base_payload
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_gdrive_sync.py -v -k "ingest_auto"
```

Expected: 3 PASS.

**Step 5: Run full ingest test suite to verify no regressions**

```bash
uv run pytest tests/ -v -k "ingest" --timeout=30
```

**Step 6: Commit**

```bash
git add agents/ingest.py tests/test_gdrive_sync.py
git commit -m "feat(ingest): auto-tag source_service from rag-sources path"
```

---

## Task 3: Calendar Sync Agent — Skeleton + Schemas

**Files:**
- Create: `~/projects/ai-agents/agents/gcalendar_sync.py`
- Create: `~/projects/ai-agents/tests/test_gcalendar_sync.py`

**Step 1: Write tests**

Create `~/projects/ai-agents/tests/test_gcalendar_sync.py`:

```python
"""Tests for gcalendar_sync — schemas, event formatting, profiler facts."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone


def test_calendar_event_defaults():
    from agents.gcalendar_sync import CalendarEvent
    e = CalendarEvent(
        event_id="abc",
        summary="Standup",
        start="2026-03-10T09:00:00Z",
        end="2026-03-10T09:30:00Z",
    )
    assert e.attendees == []
    assert e.recurring is False
    assert e.location == ""


def test_calendar_sync_state_empty():
    from agents.gcalendar_sync import CalendarSyncState
    s = CalendarSyncState()
    assert s.sync_token == ""
    assert s.events == {}


def test_event_duration_minutes():
    from agents.gcalendar_sync import CalendarEvent
    e = CalendarEvent(
        event_id="abc",
        summary="Meeting",
        start="2026-03-10T09:00:00Z",
        end="2026-03-10T10:30:00Z",
    )
    assert e.duration_minutes == 90


def test_event_duration_all_day():
    from agents.gcalendar_sync import CalendarEvent
    e = CalendarEvent(
        event_id="abc",
        summary="Holiday",
        start="2026-03-10",
        end="2026-03-11",
        all_day=True,
    )
    assert e.duration_minutes == 0
```

**Step 2: Run to verify failure**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_gcalendar_sync.py -v
```

**Step 3: Create gcalendar_sync.py skeleton**

```python
"""Google Calendar RAG sync — event indexing and behavioral tracking.

Usage:
    uv run python -m agents.gcalendar_sync --auth        # OAuth consent (if new scopes needed)
    uv run python -m agents.gcalendar_sync --full-sync    # Full calendar sync
    uv run python -m agents.gcalendar_sync --auto         # Incremental sync
    uv run python -m agents.gcalendar_sync --stats        # Show sync state
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field, computed_field

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
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_gcalendar_sync.py -v
```

Expected: 4 PASS.

**Step 5: Commit**

```bash
git add agents/gcalendar_sync.py tests/test_gcalendar_sync.py
git commit -m "feat(gcalendar): skeleton module with schemas and constants"
```

---

## Task 4: Calendar Event Formatting + Markdown Generation

**Files:**
- Modify: `~/projects/ai-agents/agents/gcalendar_sync.py`
- Modify: `~/projects/ai-agents/tests/test_gcalendar_sync.py`

**Step 1: Write failing tests**

Add to `tests/test_gcalendar_sync.py`:

```python
def test_format_event_markdown():
    from agents.gcalendar_sync import CalendarEvent, _format_event_markdown
    e = CalendarEvent(
        event_id="ev123",
        summary="1:1 with Alice",
        start="2026-03-10T09:00:00Z",
        end="2026-03-10T09:30:00Z",
        attendees=["alice@company.com"],
        location="Google Meet",
        recurring=True,
        recurrence_rule="RRULE:FREQ=WEEKLY;BYDAY=MO",
    )
    md = _format_event_markdown(e)
    assert "platform: google" in md
    assert "service: calendar" in md
    assert "source_service: gcalendar" in md
    assert "people: [alice@company.com]" in md
    assert "duration_minutes: 30" in md
    assert "1:1 with Alice" in md
    assert "Google Meet" in md


def test_format_event_no_attendees():
    from agents.gcalendar_sync import CalendarEvent, _format_event_markdown
    e = CalendarEvent(
        event_id="ev456",
        summary="Focus Time",
        start="2026-03-10T14:00:00Z",
        end="2026-03-10T16:00:00Z",
    )
    md = _format_event_markdown(e)
    assert "people: []" in md
    assert "Focus Time" in md
    assert "duration_minutes: 120" in md
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_gcalendar_sync.py -v -k "format"
```

**Step 3: Implement event formatting**

Add to `agents/gcalendar_sync.py`:

```python
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
        # Simplify RRULE for display
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
**Attendees:** {', '.join(e.attendees) if e.attendees else 'none'}{location_line}{recurrence_line}{description_block}
"""
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_gcalendar_sync.py -v
```

Expected: 6 PASS.

**Step 5: Commit**

```bash
git add agents/gcalendar_sync.py tests/test_gcalendar_sync.py
git commit -m "feat(gcalendar): state management and event markdown formatting"
```

---

## Task 5: Calendar API Sync + Event Writing

**Files:**
- Modify: `~/projects/ai-agents/agents/gcalendar_sync.py`

**Step 1: Implement Calendar API sync and file writing**

Add to `agents/gcalendar_sync.py`:

```python
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

    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=PAST_DAYS)).isoformat()
    time_max = (now + timedelta(days=FUTURE_DAYS)).isoformat()

    count = 0
    page_token = None
    while True:
        resp = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=2500,
            pageToken=page_token,
        ).execute()

        for item in resp.get("items", []):
            event = _parse_api_event(item)
            if event:
                state.events[event.event_id] = event
                count += 1

        # Capture sync token from the last page
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
            resp = service.events().list(
                calendarId="primary",
                syncToken=sync_token if not page_token else None,
                pageToken=page_token,
                maxResults=2500,
            ).execute()
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(CHANGES_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    log.debug("Logged calendar change: %s %s", change_type, event.summary)


# ── File Writing ─────────────────────────────────────────────────────────────

def _write_upcoming_events(state: CalendarSyncState) -> int:
    """Write upcoming events as markdown to rag-sources/gcalendar/."""
    GCALENDAR_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
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
```

**Step 2: Run existing tests**

```bash
uv run pytest tests/test_gcalendar_sync.py -v
```

Expected: 6 PASS (no regressions).

**Step 3: Commit**

```bash
git add agents/gcalendar_sync.py
git commit -m "feat(gcalendar): API sync, event writing, behavioral logging"
```

---

## Task 6: Calendar Profiler Bridge + Stats + CLI

**Files:**
- Modify: `~/projects/ai-agents/agents/gcalendar_sync.py`
- Modify: `~/projects/ai-agents/tests/test_gcalendar_sync.py`

**Step 1: Write failing test**

Add to `tests/test_gcalendar_sync.py`:

```python
def test_generate_calendar_profile_facts():
    from agents.gcalendar_sync import (
        _generate_profile_facts, CalendarSyncState, CalendarEvent,
    )
    state = CalendarSyncState()
    state.events = {
        "1": CalendarEvent(event_id="1", summary="1:1 with Alice",
             start="2026-03-10T09:00:00Z", end="2026-03-10T09:30:00Z",
             attendees=["alice@company.com"], recurring=True),
        "2": CalendarEvent(event_id="2", summary="Standup",
             start="2026-03-10T10:00:00Z", end="2026-03-10T10:15:00Z",
             attendees=["bob@co.com", "carol@co.com"], recurring=True),
        "3": CalendarEvent(event_id="3", summary="Focus Time",
             start="2026-03-10T14:00:00Z", end="2026-03-10T16:00:00Z"),
    }
    facts = _generate_profile_facts(state)
    assert len(facts) > 0
    dims = {f["dimension"] for f in facts}
    assert "workflow" in dims
    assert all(f["confidence"] == 0.95 for f in facts)
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_gcalendar_sync.py -v -k "profile"
```

**Step 3: Implement profiler bridge, stats, and CLI**

Add to `agents/gcalendar_sync.py`:

```python
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
        facts.append({
            "dimension": "workflow",
            "key": "calendar_meeting_cadence",
            "value": f"{event_count / weeks:.1f} meetings/week, {total_minutes / event_count:.0f} min avg",
            "confidence": 0.95,
            "source": source,
            "evidence": f"Computed from {event_count} events over {PAST_DAYS + FUTURE_DAYS} day window",
        })

    if attendee_counts:
        top = ", ".join(f"{email} ({n})" for email, n in attendee_counts.most_common(10))
        facts.append({
            "dimension": "workflow",
            "key": "calendar_frequent_attendees",
            "value": top,
            "confidence": 0.95,
            "source": source,
            "evidence": f"Top attendees across {event_count} events",
        })

    if recurring_names:
        facts.append({
            "dimension": "workflow",
            "key": "calendar_recurring_commitments",
            "value": ", ".join(recurring_names[:15]),
            "confidence": 0.95,
            "source": source,
            "evidence": f"{len(recurring_names)} recurring events detected",
        })

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
            facts.append({
                "dimension": "workflow",
                "key": "calendar_change_patterns",
                "value": f"{total_changes} changes: {dist}",
                "confidence": 0.95,
                "source": source,
                "evidence": f"Accumulated from {total_changes} calendar change events",
            })

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


# ── Stats ────────────────────────────────────────────────────────────────────

def _print_stats(state: CalendarSyncState) -> None:
    """Print sync statistics."""
    total = len(state.events)
    now = datetime.now(timezone.utc)

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
    print(f"Last full sync:  {datetime.fromtimestamp(state.last_full_sync, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if state.last_full_sync else 'never'}")
    print(f"Last sync:       {datetime.fromtimestamp(state.last_sync, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}")


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

    if changed_ids:
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

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

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
```

**Step 4: Run all tests**

```bash
uv run pytest tests/test_gcalendar_sync.py -v
```

Expected: 7 PASS.

**Step 5: Commit**

```bash
git add agents/gcalendar_sync.py tests/test_gcalendar_sync.py
git commit -m "feat(gcalendar): profiler bridge, stats, CLI entry point"
```

---

## Task 7: Calendar Context Query Module

**Files:**
- Create: `~/projects/ai-agents/shared/calendar_context.py`
- Create: `~/projects/ai-agents/tests/test_calendar_context.py`

**Step 1: Write failing tests**

Create `~/projects/ai-agents/tests/test_calendar_context.py`:

```python
"""Tests for shared calendar context query module."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _make_state():
    """Build a test CalendarSyncState."""
    from agents.gcalendar_sync import CalendarEvent, CalendarSyncState

    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).isoformat()
    tomorrow_end = (now + timedelta(days=1, minutes=30)).isoformat()
    next_week = (now + timedelta(days=7)).isoformat()
    next_week_end = (now + timedelta(days=7, minutes=60)).isoformat()

    return CalendarSyncState(
        events={
            "1": CalendarEvent(
                event_id="1", summary="1:1 with Alice",
                start=tomorrow, end=tomorrow_end,
                attendees=["alice@company.com"],
            ),
            "2": CalendarEvent(
                event_id="2", summary="Team Standup",
                start=tomorrow, end=tomorrow_end,
                attendees=["bob@co.com", "carol@co.com"],
            ),
            "3": CalendarEvent(
                event_id="3", summary="Planning",
                start=next_week, end=next_week_end,
                attendees=["alice@company.com", "dave@co.com"],
            ),
        },
        last_sync=now.timestamp(),
    )


def test_next_meeting_with(tmp_path):
    from shared.calendar_context import CalendarContext
    state = _make_state()
    ctx = CalendarContext(state)
    meeting = ctx.next_meeting_with("alice@company.com")
    assert meeting is not None
    assert meeting.summary == "1:1 with Alice"


def test_next_meeting_with_unknown(tmp_path):
    from shared.calendar_context import CalendarContext
    state = _make_state()
    ctx = CalendarContext(state)
    assert ctx.next_meeting_with("nobody@example.com") is None


def test_meetings_in_range():
    from shared.calendar_context import CalendarContext
    state = _make_state()
    ctx = CalendarContext(state)
    meetings = ctx.meetings_in_range(days=3)
    assert len(meetings) == 2  # tomorrow's meetings, not next week


def test_meeting_count_today():
    from shared.calendar_context import CalendarContext
    from agents.gcalendar_sync import CalendarEvent, CalendarSyncState
    now = datetime.now(timezone.utc)
    today_start = (now + timedelta(hours=1)).isoformat()
    today_end = (now + timedelta(hours=2)).isoformat()
    state = CalendarSyncState(events={
        "t1": CalendarEvent(event_id="t1", summary="Today",
                            start=today_start, end=today_end),
    })
    ctx = CalendarContext(state)
    assert ctx.meeting_count_today() >= 1
```

**Step 2: Run to verify failure**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_calendar_context.py -v
```

**Step 3: Create shared/calendar_context.py**

```python
"""Calendar context query interface for Hapax agents.

Reads synced calendar state — no Google API dependency.
Agents import this to answer scheduling questions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "gcalendar-sync"
STATE_FILE = CACHE_DIR / "state.json"


class CalendarContext:
    """Query interface over synced calendar state."""

    def __init__(self, state=None):
        """Initialize from explicit state or load from disk."""
        if state is not None:
            self._state = state
        else:
            from agents.gcalendar_sync import CalendarSyncState
            if STATE_FILE.exists():
                try:
                    self._state = CalendarSyncState.model_validate_json(
                        STATE_FILE.read_text()
                    )
                except Exception:
                    self._state = CalendarSyncState()
            else:
                self._state = CalendarSyncState()

    def _parse_dt(self, dt_str: str) -> datetime | None:
        """Parse ISO datetime string."""
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def next_meeting_with(self, email: str) -> object | None:
        """Find the next upcoming event with a specific attendee."""
        now = datetime.now(timezone.utc)
        candidates = []
        for e in self._state.events.values():
            if email.lower() in [a.lower() for a in e.attendees]:
                dt = self._parse_dt(e.start)
                if dt and dt > now:
                    candidates.append((dt, e))
        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]
        return None

    def meetings_in_range(self, days: int = 7) -> list:
        """Return events within the next N days, sorted by start time."""
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=days)
        result = []
        for e in self._state.events.values():
            dt = self._parse_dt(e.start)
            if dt and now <= dt <= cutoff:
                result.append(e)
        result.sort(key=lambda e: e.start)
        return result

    def meeting_count_today(self) -> int:
        """Count meetings remaining today."""
        now = datetime.now(timezone.utc)
        end_of_day = now.replace(hour=23, minute=59, second=59)
        count = 0
        for e in self._state.events.values():
            dt = self._parse_dt(e.start)
            if dt and now <= dt <= end_of_day:
                count += 1
        return count

    def is_high_meeting_day(self, threshold: int = 3) -> bool:
        """Check if today has more meetings than threshold."""
        return self.meeting_count_today() >= threshold

    def meetings_needing_prep(self, hours: int = 48) -> list:
        """Find meetings within N hours that may need prep.

        Returns meetings with attendees (likely 1:1s or group meetings,
        not focus blocks).
        """
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours)
        result = []
        for e in self._state.events.values():
            dt = self._parse_dt(e.start)
            if dt and now <= dt <= cutoff and e.attendees:
                result.append(e)
        result.sort(key=lambda e: e.start)
        return result
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_calendar_context.py -v
```

Expected: 4 PASS.

**Step 5: Commit**

```bash
git add shared/calendar_context.py tests/test_calendar_context.py
git commit -m "feat: add shared calendar context query module for agent consumption"
```

---

## Task 8: Modify management_prep.py — Calendar Integration

**Files:**
- Modify: `~/projects/ai-agents/agents/management_prep.py:206-252`

**Step 1: Add calendar context to person context collection**

In `_collect_person_context()`, after the "Recent meetings" section (around line 247), add:

```python
    # Calendar: next scheduled meeting
    try:
        from shared.calendar_context import CalendarContext
        ctx = CalendarContext()
        # Try matching by email patterns for the person
        for e in ctx.meetings_in_range(days=14):
            # Check if person name appears in event summary or attendees
            name_lower = person.name.lower()
            if name_lower in e.summary.lower() or any(
                name_lower.split()[0] in a.lower() for a in e.attendees
            ):
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(e.start.replace("Z", "+00:00"))
                    days_until = (dt - datetime.now(timezone.utc)).days
                    lines.append("## Next Scheduled Meeting")
                    lines.append(f"- Event: {e.summary}")
                    lines.append(f"- When: {dt.strftime('%a %b %d, %H:%M')}")
                    lines.append(f"- Days until: {days_until}")
                    lines.append(f"- Duration: {e.duration_minutes} min")
                    if e.attendees:
                        lines.append(f"- Other attendees: {', '.join(e.attendees)}")
                    lines.append("")
                except (ValueError, TypeError):
                    pass
                break
    except ImportError:
        pass  # calendar_context not available yet
```

**Step 2: Run management prep tests**

```bash
uv run pytest tests/ -v -k "management_prep or prep" --timeout=30
```

Expected: All existing tests still pass.

**Step 3: Commit**

```bash
git add agents/management_prep.py
git commit -m "feat(management-prep): inject next scheduled meeting from calendar"
```

---

## Task 9: Modify meeting_lifecycle.py — Calendar-Aware Prep Trigger

**Files:**
- Modify: `~/projects/ai-agents/agents/meeting_lifecycle.py:154-191`

**Step 1: Add calendar-aware meeting discovery**

In `discover_due_meetings()`, after the existing cadence-based check, add a calendar-based trigger. Before the `return due` statement, add:

```python
    # Calendar-based trigger: meetings within 48h that lack prep
    try:
        from shared.calendar_context import CalendarContext
        ctx = CalendarContext()
        upcoming = ctx.meetings_needing_prep(hours=48)
        for event in upcoming:
            # Try to match event to a person in the snapshot
            for person in snapshot.people:
                if person_filter and person.name.lower() != person_filter.lower():
                    continue
                name_lower = person.name.lower()
                matched = (
                    name_lower in event.summary.lower()
                    or any(name_lower.split()[0] in a.lower() for a in event.attendees)
                )
                if not matched:
                    continue
                # Check if already in the due list
                if any(d.person_name == person.name for d in due):
                    continue
                # Check if prep exists
                slug = person.name.lower().replace(" ", "-")
                event_date = event.start[:10]  # YYYY-MM-DD
                if prep_dir.is_dir() and (prep_dir / f"{slug}-{event_date}.md").exists():
                    continue
                due.append(MeetingDue(
                    person_name=person.name,
                    cadence=person.cadence,
                    days_since_1on1=person.days_since_1on1 or 0,
                    prep_threshold=0,  # calendar-triggered, not cadence
                ))
    except ImportError:
        pass  # calendar_context not available

    return due
```

**Step 2: Run meeting lifecycle tests**

```bash
uv run pytest tests/ -v -k "meeting" --timeout=30
```

**Step 3: Commit**

```bash
git add agents/meeting_lifecycle.py
git commit -m "feat(meeting-lifecycle): calendar-aware prep trigger within 48h"
```

---

## Task 10: Modify briefing.py — Calendar + Drive Sections

**Files:**
- Modify: `~/projects/ai-agents/agents/briefing.py`

**Step 1: Add calendar and Drive activity sections to briefing data collection**

Find the section assembly area (around line 310, after the predictive section). Add two new data collectors:

```python
    # Calendar context
    calendar_section = ""
    try:
        from shared.calendar_context import CalendarContext
        ctx = CalendarContext()
        today_meetings = ctx.meetings_in_range(days=1)
        week_meetings = ctx.meetings_in_range(days=7)
        if today_meetings:
            lines = [f"\n## Today's Schedule ({len(today_meetings)} meetings)"]
            for m in today_meetings:
                try:
                    dt = datetime.fromisoformat(m.start.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M")
                except (ValueError, TypeError):
                    time_str = m.start
                attendee_str = f" — {', '.join(m.attendees)}" if m.attendees else ""
                lines.append(f"- {time_str} {m.summary} ({m.duration_minutes}min){attendee_str}")
            if len(week_meetings) > len(today_meetings):
                lines.append(f"\n{len(week_meetings)} meetings this week total.")
            prep_needed = ctx.meetings_needing_prep(hours=48)
            if prep_needed:
                lines.append(f"\n**Prep needed:** {', '.join(m.summary for m in prep_needed)}")
            calendar_section = "\n".join(lines) + "\n"
    except (ImportError, Exception) as exc:
        log.debug("Calendar context unavailable: %s", exc)

    # Drive activity
    drive_section = ""
    try:
        from shared.config import get_qdrant
        from qdrant_client.models import Filter, FieldCondition, Range, MatchValue
        client = get_qdrant()
        since_ts = time.time() - (hours * 3600)
        results = client.scroll(
            collection_name="documents",
            scroll_filter=Filter(must=[
                FieldCondition(key="ingested_at", range=Range(gte=since_ts)),
                FieldCondition(key="source_service", match=MatchValue(value="gdrive")),
            ]),
            limit=100,
            with_payload=["filename", "gdrive_folder"],
            with_vectors=False,
        )
        points = results[0] if results else []
        if points:
            folders = set()
            for p in points:
                folder = (p.payload or {}).get("gdrive_folder", "")
                if folder:
                    folders.add(folder)
            folder_str = f" from {', '.join(sorted(folders))}" if folders else ""
            drive_section = f"\n## Drive Activity\n{len(points)} new files synced{folder_str}.\n"
    except Exception as exc:
        log.debug("Drive activity check failed: %s", exc)
```

Then include `calendar_section` and `drive_section` in the prompt assembly.

**Step 2: Run briefing tests**

```bash
uv run pytest tests/ -v -k "briefing" --timeout=30
```

**Step 3: Commit**

```bash
git add agents/briefing.py
git commit -m "feat(briefing): add Today's Schedule and Drive Activity sections"
```

---

## Task 11: Register Calendar in Profiler Sources

**Files:**
- Modify: `~/projects/ai-agents/agents/profiler_sources.py:31,36-50`

**Step 1: Add gcalendar to source registries**

In `BRIDGED_SOURCE_TYPES` (line 31), add `"gcalendar"`:

```python
BRIDGED_SOURCE_TYPES = {"proton", "takeout", "management", "gcalendar"}
```

In `SOURCE_TYPE_CHUNK_CAPS` (line 36), add:

```python
    "gcalendar": 50,
```

In the `discover_sources()` function, add discovery of calendar profile facts (follow the pattern used for takeout/proton bridged sources).

**Step 2: Run profiler tests**

```bash
uv run pytest tests/ -v -k "profiler" --timeout=30
```

**Step 3: Commit**

```bash
git add agents/profiler_sources.py
git commit -m "feat(profiler): register gcalendar as bridged source"
```

---

## Task 12: Systemd Timer for Calendar Sync

**Files:**
- Create: `~/.config/systemd/user/gcalendar-sync.service`
- Create: `~/.config/systemd/user/gcalendar-sync.timer`

**Step 1: Create service unit**

```ini
[Unit]
Description=Google Calendar RAG sync (incremental)
After=network-online.target
OnFailure=notify-failure@%n.service

[Service]
Type=oneshot
WorkingDirectory=/home/hapaxlegomenon/projects/ai-agents
ExecStart=/home/hapaxlegomenon/.local/bin/uv run python -m agents.gcalendar_sync --auto
Environment=PATH=/home/hapaxlegomenon/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/hapaxlegomenon
Environment=GNUPGHOME=/home/hapaxlegomenon/.gnupg
Environment=PASSWORD_STORE_DIR=/home/hapaxlegomenon/.password-store
MemoryMax=512M
SyslogIdentifier=gcalendar-sync
```

**Step 2: Create timer (every 30 minutes)**

```ini
[Unit]
Description=Google Calendar RAG sync every 30 minutes

[Timer]
OnCalendar=*-*-* *:00/30:00
Persistent=true
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
```

**Step 3: Reload and verify**

```bash
systemctl --user daemon-reload
systemctl --user list-timers | grep gcalendar
```

**Step 4: Commit**

```bash
cd ~/projects/ai-agents && git add agents/gcalendar_sync.py
git commit -m "feat(gcalendar): systemd timer for 30-minute incremental sync"
```

---

## Task 13: Update Documentation Across Repos

**Files:**
- Modify: `~/projects/hapaxromana/CLAUDE.md` (or relevant architecture doc)
- Modify: `~/projects/hapax-system/rules/system-context.md`
- Modify: `~/projects/distro-work/CLAUDE.md` (if relevant)

**Step 1: Update system-context.md with new agents and timers**

Add to the Management Agents table:

```markdown
| gdrive_sync | No | `--auth`, `--full-scan`, `--auto`, `--fetch ID`, `--stats` |
| gcalendar_sync | No | `--auth`, `--full-sync`, `--auto`, `--stats` |
```

Add to the Management Timers table:

```markdown
| gdrive-sync | Every 2h | Google Drive RAG sync |
| gcalendar-sync | Every 30 min | Google Calendar RAG sync |
```

Add to Qdrant Collections or Key Paths as needed.

**Step 2: Update hapaxromana architecture docs**

Check `~/projects/hapaxromana/` for any architecture docs that list agents, timers, or data sources. Update them to include gdrive_sync, gcalendar_sync, shared/google_auth.py, and shared/calendar_context.py.

**Step 3: Commit in each repo**

```bash
cd ~/projects/hapax-system && git add -A && git commit -m "docs: add gdrive-sync and gcalendar-sync to system context"
cd ~/projects/hapaxromana && git add -A && git commit -m "docs: update architecture with Google service sync agents"
```

---

## Task 14: OAuth Scope Expansion + Integration Test

**Step 1: Add calendar scope to existing Google OAuth token**

```bash
cd ~/projects/ai-agents && uv run python -m agents.gcalendar_sync --auth
```

This will trigger a new OAuth consent flow if the calendar scope is not yet authorized. Approve in browser.

**Step 2: Run calendar full sync**

```bash
uv run python -m agents.gcalendar_sync --full-sync -v
```

Expected: Syncs events, writes upcoming as markdown, generates profile facts.

**Step 3: Verify stats**

```bash
uv run python -m agents.gcalendar_sync --stats
```

**Step 4: Verify rag-ingest picks up calendar files**

```bash
ls ~/documents/rag-sources/gcalendar/
journalctl --user -u rag-ingest --since "5 min ago" --no-pager
```

**Step 5: Enable timer**

```bash
systemctl --user enable --now gcalendar-sync.timer
systemctl --user list-timers | grep gcalendar
```

**Step 6: Run all tests**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_google_auth.py tests/test_gcalendar_sync.py tests/test_calendar_context.py tests/test_gdrive_sync.py -v
```

Expected: All PASS.

**Step 7: Commit**

```bash
git add -A && git commit -m "test(gcalendar): end-to-end integration verification"
```

---

## Summary

| Task | Description | Type |
|------|-------------|------|
| 1 | Extract shared Google auth | Refactor |
| 2 | Drive auto-tagging in ingest | Drive improvement |
| 3 | Calendar skeleton + schemas | Calendar core |
| 4 | Calendar event formatting | Calendar core |
| 5 | Calendar API sync + file writing | Calendar core |
| 6 | Calendar profiler + stats + CLI | Calendar core |
| 7 | Calendar context query module | Integration layer |
| 8 | management_prep calendar injection | Agent modification |
| 9 | meeting_lifecycle calendar trigger | Agent modification |
| 10 | briefing calendar + Drive sections | Agent modification |
| 11 | Register calendar in profiler sources | Integration |
| 12 | Systemd timer for calendar | Operations |
| 13 | Documentation updates across repos | Documentation |
| 14 | OAuth expansion + integration test | Verification |

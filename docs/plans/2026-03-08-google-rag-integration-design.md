# Google Services RAG Integration Design

## Problem

The Hapax system has a mature RAG pipeline (Docling + nomic-embed + Qdrant) and a profiler bridge pattern for zero-cost behavioral fact extraction. Google Drive sync is being built (gdrive_sync.py). But the existing agents don't fully consume Drive data, and Calendar, Gmail, and YouTube have no live API sync — only stale Takeout exports.

The goal is: every Google service integration should be **bi-directional** — data flows in (sync agent), and Hapax agents are modified to consume it where it adds value.

## Constraints

- Single OAuth2 project, personal Gmail account
- All secrets in `pass`, all models through LiteLLM
- Agents run on systemd timers — must be crash-safe and incremental
- Follow existing patterns: profiler bridge (zero LLM cost), frontmatter enrichment, ntfy notifications

---

## Part 1: Google Calendar Integration

### New Module: `agents/gcalendar_sync.py`

Same architecture as gdrive_sync: OAuth2, incremental sync, markdown output, profiler bridge.

### Sync Strategy

- **API:** Google Calendar API v3, `calendar.readonly` scope
- **Incremental:** `events.list` with `syncToken` (persisted in state)
- **Window:** 30 days past to 90 days ahead
- **Timer:** Every 30 minutes (calendars change more than Drive)
- **State:** `~/.cache/gcalendar-sync/state.json`

### Output

**Upcoming events (next 14 days)** written as markdown to `~/documents/rag-sources/gcalendar/`:

```yaml
---
platform: google
service: calendar
content_type: calendar_event
source_service: gcalendar
source_platform: google
record_id: <event_id>
timestamp: 2026-03-10T09:00:00
modality_tags: [temporal, social]
people: [alice@company.com, bob@company.com]
categories: [1:1, Management]
duration_minutes: 30
recurring: true
---

# 1:1 with Alice

**When:** Mon Mar 10, 09:00-09:30
**Attendees:** alice@company.com
**Location:** Google Meet
**Recurrence:** Weekly on Mondays
```

Past events (>14 days ago) are removed from `rag-sources/` on each sync — they've served their RAG purpose. They remain in state for profiler pattern extraction.

**Profiler facts** at `~/.cache/gcalendar-sync/calendar-profile-facts.jsonl`:

- `workflow:meeting_cadence` — meetings/week average
- `workflow:high_meeting_days` — days with 3+ meetings
- `workflow:recurring_commitments` — recurring event names
- `knowledge_domains:meeting_topics` — top event title keywords
- `workflow:attendee_frequency` — most frequent attendees

**Behavioral log** at `~/.cache/gcalendar-sync/changes.jsonl`:

- Cancellations (with original attendees, timing)
- Reschedules (old/new time)
- New recurring series created
- Profiler aggregates: cancellation rate, reschedule patterns

### New Module: `shared/calendar_context.py`

Lightweight query interface that agents import. Reads synced state, no API dependency:

```python
from shared.calendar_context import CalendarContext

ctx = CalendarContext()  # loads state from cache
ctx.next_meeting_with("alice@company.com")  # -> Event | None
ctx.meetings_in_range(days=7)               # -> list[Event]
ctx.meeting_count_today()                   # -> int
ctx.is_high_meeting_day(threshold=3)        # -> bool
ctx.meetings_needing_prep(hours=48)         # -> list[Event] (no prep doc in vault)
```

### Hapax Agent Modifications for Calendar

**management_prep.py** (P0):
- In `_collect_person_context()`: query `CalendarContext.next_meeting_with(person_email)`
- Inject: "Next 1:1 scheduled for [date], [days] days from now"
- Changes prep trigger from "overdue by cadence" to "meeting is in 2 days"

**meeting_lifecycle.py** (P0):
- `discover_due_meetings()`: add calendar-aware trigger — if 1:1 on calendar within 48h and no prep doc, trigger prep
- Transcript routing: use attendee list from calendar state to auto-identify person (instead of filename parsing)

**briefing.py** (P1):
- Add "Today's Schedule" section: meeting count, names, attendees
- Flag high-meeting days as context
- Note meetings without prep docs as action items

---

## Part 2: Google Drive — Backward Improvements

gdrive_sync.py is built and working. These are the Hapax agent modifications needed to fully consume Drive data.

### ingest.py (foundational)

Auto-tag Drive files during ingestion. In `enrich_payload()`:
- If source path contains `rag-sources/gdrive`, set `source_service: "gdrive"`
- Extract top-level folder from path as `gdrive_folder` metadata
- This enables all downstream Qdrant filtering by source

### digest.py

- Add service-aware grouping: when collecting recent documents, group by `source_service`
- Surface Drive-specific observations: "3 new manuals synced from Drive/Hardware folder"
- Read Drive profiler facts to add folder activity context

### briefing.py

- Add "Drive Activity" line to daily briefing: count of files synced since last briefing
- Pull from Qdrant `ingested_at` filter + `source_service: "gdrive"`

### query.py

- Add `--source` filter flag: `query.py "budget" --source gdrive`
- Builds Qdrant `FieldCondition(key="source_service", match=MatchValue(value="gdrive"))`

### knowledge_maint.py

- Read Drive deletion log during pruning: if a Drive file was deleted upstream, mark corresponding Qdrant points for removal
- Report Drive-specific dedup stats separately

---

## Part 3: Gmail Integration (Next)

### Module: `agents/gmail_sync.py`

- **API:** Gmail API v1, `gmail.readonly` scope
- **Incremental:** `history.list` with `historyId`
- **Strategy:** Metadata-first (same philosophy as Drive binary stubs)
  - Tier 1: Email metadata (sender, subject, labels, timestamp, thread length) as markdown stubs
  - Tier 2: Email body text for emails matching criteria (from known contacts, labeled important, etc.)
  - Tier 3: Attachments follow Drive tiering rules (download <25MB, stub >25MB)
- **Output:** `~/documents/rag-sources/gmail/` with YAML frontmatter
- **Profiler facts:** Response times, sender frequency, label usage, thread patterns
- **Behavioral log:** Archive/delete actions, label changes, star/unstar

### Hapax Agent Modifications for Gmail

- **management_prep.py:** Surface recent email threads with the person being prepped for
- **briefing.py:** Unread count, threads needing response, email velocity
- **digest.py:** Notable email topics, new sender patterns

### Privacy Consideration

Email body text is more sensitive than Drive files. Default to metadata-only stubs with opt-in body extraction for specific labels or senders. The `people` frontmatter field enables management_prep to find relevant threads without embedding full email content.

---

## Part 4: YouTube Integration (Last)

### Module: `agents/youtube_sync.py`

- **API:** YouTube Data API v3, `youtube.readonly` scope
- **What to sync:**
  - Liked videos (titles, channels, categories)
  - Subscriptions (channel names, categories)
  - Playlists (titles, video lists)
  - Watch history (limited API access — may need Takeout supplementation)
- **Output:** Markdown files to `~/documents/rag-sources/youtube/`
- **Profiler facts:** Topic interests, channel preferences, watch patterns, subscription churn
- **Behavioral log:** New subscriptions, unsubscribes, playlist curation

### Hapax Agent Modifications for YouTube

- **scout.py:** YouTube subscriptions and watch topics inform horizon scanning — "operator is watching content about [topic], relevant to [component]"
- **profiler:** Music production YouTube channels feed into `music_production` dimension
- **briefing.py:** Optional — new videos from subscribed channels (low priority)

### API Limitation

YouTube Data API has restricted access to watch history for personal accounts. Liked videos and subscriptions are reliable. Watch history may require continued Takeout supplementation. Design the sync to gracefully handle partial data.

---

## Part 5: Shared Infrastructure

### OAuth Consolidation

All four services share one Google Cloud project. Scopes:
- `drive.readonly` (already active)
- `calendar.readonly`
- `gmail.readonly`
- `youtube.readonly`

Token stored in `pass show gdrive/token` — rename to `pass show google/token` and update gdrive_sync to match. Single OAuth consent flow adds all scopes.

### Common Patterns

Extract shared code from gdrive_sync into `shared/google_auth.py`:
- `get_google_credentials(scopes)` — load/refresh from pass
- `save_google_token(creds)` — persist to pass
- Common retry wrapper for API calls (exponential backoff)

### Source Registry

Each sync agent registers in `profiler_sources.py`:
- `gcalendar` — 50 chunk cap, bridged
- `gmail` — 100 chunk cap, bridged
- `youtube` — 50 chunk cap, bridged
- `gdrive` — already implicitly handled via rag-ingest

### Unified Behavioral Log Format

All sync agents write behavioral events to `~/.cache/<service>-sync/changes.jsonl` with common schema:

```json
{
  "service": "gcalendar",
  "event_type": "cancelled",
  "record_id": "...",
  "name": "1:1 with Alice",
  "context": {"original_time": "...", "attendees": ["..."]},
  "timestamp": "2026-03-10T10:00:00Z"
}
```

---

## Implementation Order

1. **Drive backward improvements** (ingest.py auto-tagging, digest/briefing consumption)
2. **Shared Google auth extraction** (from gdrive_sync into shared/google_auth.py)
3. **Calendar sync agent + calendar_context.py**
4. **Calendar agent modifications** (management_prep, meeting_lifecycle, briefing)
5. **Gmail sync agent + agent modifications**
6. **YouTube sync agent + agent modifications**

## Scheduling

| Timer | Schedule | Purpose |
|-------|----------|---------|
| gdrive-sync | Every 2h | Drive file sync |
| gcalendar-sync | Every 30min | Calendar event sync |
| gmail-sync | Every 1h | Email metadata sync |
| youtube-sync | Every 6h | Subscription/likes sync |

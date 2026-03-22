# Google RAG Phase 3 — Gmail + YouTube Sync + Agent Integration

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Gmail metadata sync and YouTube subscription/likes sync, integrate both into Hapax agents (management_prep, briefing, digest, scout), expand OAuth scopes, and update documentation.

**Architecture:** Gmail sync follows the metadata-first pattern (sender, subject, labels as markdown stubs — body text opt-in). YouTube sync captures liked videos, subscriptions, and playlists. Both follow the established pattern: Pydantic schemas, incremental sync, markdown RAG output, profiler bridge, behavioral logging, systemd timer. Consumer agents get graceful calendar-style integration.

**Tech Stack:** google-api-python-client, google-auth-oauthlib, pydantic v2, shared.google_auth, shared.config, shared.notify, systemd user timers

**Design doc:** `docs/plans/2026-03-08-google-rag-integration-design.md` (in distro-work repo)

---

## Task 1: Gmail Sync — Skeleton + Schemas

**Files:**
- Create: `~/projects/ai-agents/agents/gmail_sync.py`
- Create: `~/projects/ai-agents/tests/test_gmail_sync.py`

**Step 1: Write failing tests**

Create `~/projects/ai-agents/tests/test_gmail_sync.py`:

```python
"""Tests for gmail_sync — schemas, formatting, profiler facts."""
from __future__ import annotations


def test_email_metadata_defaults():
    from agents.gmail_sync import EmailMetadata
    e = EmailMetadata(
        message_id="abc123",
        thread_id="thread1",
        subject="Test Subject",
        sender="alice@company.com",
        timestamp="2026-03-10T09:00:00Z",
    )
    assert e.labels == []
    assert e.recipients == []
    assert e.is_unread is False
    assert e.thread_length == 1
    assert e.has_attachments is False


def test_gmail_sync_state_empty():
    from agents.gmail_sync import GmailSyncState
    s = GmailSyncState()
    assert s.history_id == ""
    assert s.messages == {}


def test_email_metadata_with_labels():
    from agents.gmail_sync import EmailMetadata
    e = EmailMetadata(
        message_id="def456",
        thread_id="thread2",
        subject="Important",
        sender="boss@company.com",
        timestamp="2026-03-10T10:00:00Z",
        labels=["IMPORTANT", "INBOX"],
        is_unread=True,
    )
    assert "IMPORTANT" in e.labels
    assert e.is_unread is True
```

**Step 2: Run tests to verify failure**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_gmail_sync.py -v
```

Expected: FAIL (module not found).

**Step 3: Create gmail_sync.py skeleton**

```python
"""Gmail RAG sync — email metadata indexing and behavioral tracking.

Privacy-first: defaults to metadata-only stubs (sender, subject, labels).
Email body extraction is opt-in for specific labels or senders.

Usage:
    uv run python -m agents.gmail_sync --auth        # OAuth consent
    uv run python -m agents.gmail_sync --full-sync    # Full metadata sync
    uv run python -m agents.gmail_sync --auto         # Incremental sync
    uv run python -m agents.gmail_sync --stats        # Show sync state
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

CACHE_DIR = Path.home() / ".cache" / "gmail-sync"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "gmail-profile-facts.jsonl"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"
RAG_SOURCES = Path.home() / "documents" / "rag-sources"
GMAIL_DIR = RAG_SOURCES / "gmail"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
]

# How many messages to fetch on full sync
MAX_FULL_SYNC = 500
# Only write recent threads to RAG (rolling window)
RAG_WINDOW_DAYS = 30
# Labels that opt-in to body extraction
BODY_EXTRACT_LABELS = {"IMPORTANT", "STARRED"}


# ── Schemas ──────────────────────────────────────────────────────────────────

class EmailMetadata(BaseModel):
    """Email message metadata."""
    message_id: str
    thread_id: str
    subject: str
    sender: str
    timestamp: str  # ISO datetime
    recipients: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    is_unread: bool = False
    is_starred: bool = False
    thread_length: int = 1
    has_attachments: bool = False
    snippet: str = ""
    body_extracted: bool = False
    local_path: str = ""
    synced_at: float = 0.0


class GmailSyncState(BaseModel):
    """Persistent sync state."""
    history_id: str = ""
    messages: dict[str, EmailMetadata] = Field(default_factory=dict)
    last_full_sync: float = 0.0
    last_sync: float = 0.0
    stats: dict[str, int] = Field(default_factory=dict)
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_gmail_sync.py -v
```

Expected: 3 PASS.

**Step 5: Commit**

```bash
git add agents/gmail_sync.py tests/test_gmail_sync.py
git commit -m "feat(gmail): skeleton module with schemas and constants"
```

---

## Task 2: Gmail Message Formatting + Markdown Generation

**Files:**
- Modify: `~/projects/ai-agents/agents/gmail_sync.py`
- Modify: `~/projects/ai-agents/tests/test_gmail_sync.py`

**Step 1: Write failing tests**

Add to `tests/test_gmail_sync.py`:

```python
def test_format_email_markdown_metadata_only():
    from agents.gmail_sync import EmailMetadata, _format_email_markdown
    e = EmailMetadata(
        message_id="msg1",
        thread_id="thread1",
        subject="Q1 Budget Review",
        sender="alice@company.com",
        timestamp="2026-03-10T09:00:00Z",
        recipients=["bob@company.com"],
        labels=["INBOX", "IMPORTANT"],
        is_unread=True,
        snippet="Please review the attached budget...",
    )
    md = _format_email_markdown(e)
    assert "platform: google" in md
    assert "service: gmail" in md
    assert "source_service: gmail" in md
    assert "people: [alice@company.com]" in md
    assert "Q1 Budget Review" in md
    assert "alice@company.com" in md


def test_format_email_no_recipients():
    from agents.gmail_sync import EmailMetadata, _format_email_markdown
    e = EmailMetadata(
        message_id="msg2",
        thread_id="thread2",
        subject="Newsletter",
        sender="news@example.com",
        timestamp="2026-03-10T12:00:00Z",
        labels=["CATEGORY_PROMOTIONS"],
    )
    md = _format_email_markdown(e)
    assert "Newsletter" in md
    assert "people: [news@example.com]" in md
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_gmail_sync.py -v -k "format"
```

**Step 3: Implement state management and formatting**

Add to `agents/gmail_sync.py`:

```python
# ── State Management ─────────────────────────────────────────────────────────

def _load_state(path: Path = STATE_FILE) -> GmailSyncState:
    """Load sync state from disk."""
    if path.exists():
        try:
            return GmailSyncState.model_validate_json(path.read_text())
        except Exception as exc:
            log.warning("Corrupt state file, starting fresh: %s", exc)
    return GmailSyncState()


def _save_state(state: GmailSyncState, path: Path = STATE_FILE) -> None:
    """Persist sync state to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    tmp.rename(path)


# ── Email Formatting ─────────────────────────────────────────────────────────

def _format_email_markdown(e: EmailMetadata) -> str:
    """Generate markdown for an email metadata stub with YAML frontmatter."""
    people = [e.sender] + [r for r in e.recipients if r != e.sender]
    people_str = "[" + ", ".join(people) + "]"

    # Parse timestamp for frontmatter
    try:
        dt = datetime.fromisoformat(e.timestamp.replace("Z", "+00:00"))
        ts_frontmatter = dt.strftime("%Y-%m-%dT%H:%M:%S")
        date_display = dt.strftime("%a %b %d, %H:%M")
    except (ValueError, TypeError):
        ts_frontmatter = e.timestamp
        date_display = e.timestamp

    labels_str = "[" + ", ".join(e.labels) + "]"

    snippet_block = f"\n\n> {e.snippet}" if e.snippet else ""

    return f"""---
platform: google
service: gmail
content_type: email_metadata
source_service: gmail
source_platform: google
record_id: {e.message_id}
thread_id: {e.thread_id}
timestamp: {ts_frontmatter}
modality_tags: [communication, social]
people: {people_str}
labels: {labels_str}
is_unread: {str(e.is_unread).lower()}
thread_length: {e.thread_length}
has_attachments: {str(e.has_attachments).lower()}
---

# {e.subject}

**From:** {e.sender}
**To:** {', '.join(e.recipients) if e.recipients else 'me'}
**Date:** {date_display}
**Labels:** {', '.join(e.labels) if e.labels else 'none'}
**Thread:** {e.thread_length} message{'s' if e.thread_length != 1 else ''}{snippet_block}
"""
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_gmail_sync.py -v
```

Expected: 5 PASS.

**Step 5: Commit**

```bash
git add agents/gmail_sync.py tests/test_gmail_sync.py
git commit -m "feat(gmail): state management and email markdown formatting"
```

---

## Task 3: Gmail API Sync + Message Writing

**Files:**
- Modify: `~/projects/ai-agents/agents/gmail_sync.py`

**Step 1: Implement Gmail API sync and file writing**

Add to `agents/gmail_sync.py`:

```python
# ── Gmail API Operations ─────────────────────────────────────────────────────

def _get_gmail_service():
    """Build authenticated Gmail API service."""
    from shared.google_auth import build_service
    return build_service("gmail", "v1", SCOPES)


def _parse_headers(headers: list[dict]) -> dict[str, str]:
    """Extract useful headers from Gmail message payload."""
    result = {}
    for h in headers:
        name = h.get("name", "").lower()
        if name in ("from", "to", "subject", "date"):
            result[name] = h.get("value", "")
    return result


def _parse_message(msg: dict) -> EmailMetadata | None:
    """Parse a Gmail API message into EmailMetadata."""
    payload = msg.get("payload", {})
    headers = _parse_headers(payload.get("headers", []))

    labels = msg.get("labelIds", [])
    sender = headers.get("from", "")
    # Clean sender: "Name <email>" -> email
    if "<" in sender and ">" in sender:
        sender = sender[sender.index("<") + 1:sender.index(">")]

    to_raw = headers.get("to", "")
    recipients = [r.strip() for r in to_raw.split(",") if r.strip()] if to_raw else []
    # Clean recipients the same way
    clean_recipients = []
    for r in recipients:
        if "<" in r and ">" in r:
            r = r[r.index("<") + 1:r.index(">")]
        clean_recipients.append(r)

    # Parse internal date (ms since epoch)
    internal_date = msg.get("internalDate", "0")
    try:
        dt = datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc)
        timestamp = dt.isoformat()
    except (ValueError, TypeError):
        timestamp = ""

    # Check for attachments
    has_attachments = False
    parts = payload.get("parts", [])
    for part in parts:
        if part.get("filename"):
            has_attachments = True
            break

    return EmailMetadata(
        message_id=msg["id"],
        thread_id=msg.get("threadId", ""),
        subject=headers.get("subject", "(no subject)"),
        sender=sender,
        timestamp=timestamp,
        recipients=clean_recipients,
        labels=labels,
        is_unread="UNREAD" in labels,
        is_starred="STARRED" in labels,
        has_attachments=has_attachments,
        snippet=msg.get("snippet", ""),
    )


def _full_sync(service, state: GmailSyncState) -> int:
    """Full sync of recent email metadata."""
    log.info("Starting full Gmail sync...")

    count = 0
    page_token = None

    while count < MAX_FULL_SYNC:
        resp = service.users().messages().list(
            userId="me",
            maxResults=min(100, MAX_FULL_SYNC - count),
            pageToken=page_token,
        ).execute()

        msg_ids = resp.get("messages", [])
        for msg_ref in msg_ids:
            msg = service.users().messages().get(
                userId="me",
                id=msg_ref["id"],
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()

            email = _parse_message(msg)
            if email:
                state.messages[email.message_id] = email
                count += 1

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    # Get current historyId for incremental sync
    profile = service.users().getProfile(userId="me").execute()
    state.history_id = str(profile.get("historyId", ""))
    state.last_full_sync = time.time()
    log.info("Full sync complete: %d messages", count)
    return count


def _incremental_sync(service, state: GmailSyncState) -> list[str]:
    """Incremental sync using historyId. Returns changed message IDs."""
    if not state.history_id:
        log.warning("No historyId — run --full-sync first")
        return []

    changed_ids: list[str] = []
    page_token = None

    while True:
        try:
            resp = service.users().history().list(
                userId="me",
                startHistoryId=state.history_id,
                historyTypes=["messageAdded", "labelAdded", "labelRemoved"],
                pageToken=page_token,
            ).execute()
        except Exception as exc:
            if "404" in str(exc):
                log.warning("historyId expired — full sync required")
                state.history_id = ""
                return []
            raise

        for record in resp.get("history", []):
            for added in record.get("messagesAdded", []):
                msg_id = added["message"]["id"]
                try:
                    msg = service.users().messages().get(
                        userId="me",
                        id=msg_id,
                        format="metadata",
                        metadataHeaders=["From", "To", "Subject", "Date"],
                    ).execute()
                    email = _parse_message(msg)
                    if email:
                        is_new = msg_id not in state.messages
                        state.messages[msg_id] = email
                        changed_ids.append(msg_id)
                        if is_new:
                            _log_change(email, "received")
                except Exception as exc:
                    log.debug("Could not fetch message %s: %s", msg_id, exc)

            # Track label changes
            for label_change in record.get("labelsAdded", []) + record.get("labelsRemoved", []):
                msg_data = label_change.get("message", {})
                msg_id = msg_data.get("id", "")
                if msg_id and msg_id in state.messages:
                    _log_change(state.messages[msg_id], "label_change", {
                        "labels": msg_data.get("labelIds", []),
                    })

        state.history_id = str(resp.get("historyId", state.history_id))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    state.last_sync = time.time()
    log.info("Incremental sync: %d changes", len(changed_ids))
    return changed_ids


# ── Behavioral Logging ───────────────────────────────────────────────────────

def _log_change(email: EmailMetadata, change_type: str, extra: dict | None = None) -> None:
    """Append email change to JSONL log."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "service": "gmail",
        "event_type": change_type,
        "record_id": email.message_id,
        "name": email.subject,
        "context": {
            "sender": email.sender,
            "labels": email.labels,
            "thread_id": email.thread_id,
            **(extra or {}),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(CHANGES_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    log.debug("Logged gmail change: %s %s", change_type, email.subject[:40])


# ── File Writing ─────────────────────────────────────────────────────────────

def _write_recent_emails(state: GmailSyncState) -> int:
    """Write recent email metadata as markdown to rag-sources/gmail/."""
    GMAIL_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RAG_WINDOW_DAYS)
    written = 0

    # Clean old files first
    for f in GMAIL_DIR.glob("*.md"):
        f.unlink()

    for email in state.messages.values():
        try:
            dt = datetime.fromisoformat(email.timestamp.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        if dt < cutoff:
            continue

        md = _format_email_markdown(email)
        safe_subject = email.subject.replace("/", "_").replace(" ", "-")[:50]
        date_prefix = dt.strftime("%Y-%m-%d")
        filename = f"{date_prefix}-{safe_subject}-{email.message_id[:8]}.md"
        filepath = GMAIL_DIR / filename
        filepath.write_text(md, encoding="utf-8")
        email.local_path = str(filepath)
        email.synced_at = time.time()
        written += 1

    log.info("Wrote %d recent emails to %s", written, GMAIL_DIR)
    return written
```

**Step 2: Run existing tests**

```bash
uv run pytest tests/test_gmail_sync.py -v
```

Expected: 5 PASS (no regressions).

**Step 3: Commit**

```bash
git add agents/gmail_sync.py
git commit -m "feat(gmail): API sync, message writing, behavioral logging"
```

---

## Task 4: Gmail Profiler Bridge + Stats + CLI

**Files:**
- Modify: `~/projects/ai-agents/agents/gmail_sync.py`
- Modify: `~/projects/ai-agents/tests/test_gmail_sync.py`

**Step 1: Write failing test**

Add to `tests/test_gmail_sync.py`:

```python
def test_generate_gmail_profile_facts():
    from agents.gmail_sync import (
        _generate_profile_facts, GmailSyncState, EmailMetadata,
    )
    state = GmailSyncState()
    state.messages = {
        "1": EmailMetadata(message_id="1", thread_id="t1",
             subject="Budget Review", sender="alice@company.com",
             timestamp="2026-03-10T09:00:00Z", labels=["INBOX", "IMPORTANT"]),
        "2": EmailMetadata(message_id="2", thread_id="t2",
             subject="Standup Notes", sender="bob@company.com",
             timestamp="2026-03-10T10:00:00Z", labels=["INBOX"]),
        "3": EmailMetadata(message_id="3", thread_id="t1",
             subject="Re: Budget Review", sender="alice@company.com",
             timestamp="2026-03-10T11:00:00Z", labels=["INBOX"]),
    }
    facts = _generate_profile_facts(state)
    assert len(facts) > 0
    dims = {f["dimension"] for f in facts}
    assert "communication" in dims
    assert all(f["confidence"] == 0.95 for f in facts)
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_gmail_sync.py -v -k "profile"
```

**Step 3: Implement profiler bridge, stats, and CLI**

Add to `agents/gmail_sync.py`:

```python
# ── Profiler Integration ─────────────────────────────────────────────────────

def _generate_profile_facts(state: GmailSyncState) -> list[dict]:
    """Generate deterministic profile facts from Gmail state."""
    from collections import Counter

    sender_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    thread_sizes: Counter[str] = Counter()
    unread = 0

    for e in state.messages.values():
        sender_counts[e.sender] += 1
        for label in e.labels:
            if not label.startswith("CATEGORY_"):
                label_counts[label] += 1
        thread_sizes[e.thread_id] += 1
        if e.is_unread:
            unread += 1

    facts = []
    source = "gmail-sync:gmail-profile-facts"
    total = len(state.messages)

    if total:
        facts.append({
            "dimension": "communication",
            "key": "email_volume",
            "value": f"{total} messages synced, {unread} unread",
            "confidence": 0.95,
            "source": source,
            "evidence": f"From {total} synced messages",
        })

    if sender_counts:
        top = ", ".join(f"{email} ({n})" for email, n in sender_counts.most_common(10))
        facts.append({
            "dimension": "communication",
            "key": "email_frequent_senders",
            "value": top,
            "confidence": 0.95,
            "source": source,
            "evidence": f"Top senders across {total} messages",
        })

    # Thread depth indicates conversation patterns
    long_threads = {tid: count for tid, count in thread_sizes.items() if count >= 3}
    if long_threads:
        facts.append({
            "dimension": "communication",
            "key": "email_thread_patterns",
            "value": f"{len(long_threads)} threads with 3+ messages (max {max(thread_sizes.values())})",
            "confidence": 0.95,
            "source": source,
            "evidence": f"Thread analysis across {len(thread_sizes)} threads",
        })

    return facts


def _write_profile_facts(state: GmailSyncState) -> None:
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

def _print_stats(state: GmailSyncState) -> None:
    """Print sync statistics."""
    from collections import Counter

    total = len(state.messages)
    unread = sum(1 for e in state.messages.values() if e.is_unread)
    starred = sum(1 for e in state.messages.values() if e.is_starred)
    threads = len({e.thread_id for e in state.messages.values()})

    print("Gmail Sync State")
    print("=" * 40)
    print(f"Total messages:  {total:,}")
    print(f"Unread:          {unread:,}")
    print(f"Starred:         {starred:,}")
    print(f"Threads:         {threads:,}")
    print(f"Last full sync:  {datetime.fromtimestamp(state.last_full_sync, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if state.last_full_sync else 'never'}")
    print(f"Last sync:       {datetime.fromtimestamp(state.last_sync, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}")

    # Top senders
    sender_counts: Counter[str] = Counter()
    for e in state.messages.values():
        sender_counts[e.sender] += 1
    if sender_counts:
        print("\nTop senders:")
        for sender, count in sender_counts.most_common(5):
            print(f"  {sender}: {count}")


# ── Orchestration ────────────────────────────────────────────────────────────

def run_auth() -> None:
    """Verify OAuth credentials work for Gmail."""
    print("Authenticating with Gmail...")
    service = _get_gmail_service()
    profile = service.users().getProfile(userId="me").execute()
    print(f"  Email: {profile.get('emailAddress', 'unknown')}")
    print(f"  Messages: {profile.get('messagesTotal', 0):,}")
    print(f"  Threads: {profile.get('threadsTotal', 0):,}")
    print("Authentication successful.")


def run_full_sync() -> None:
    """Full Gmail metadata sync."""
    from shared.notify import send_notification

    service = _get_gmail_service()
    state = _load_state()

    count = _full_sync(service, state)
    written = _write_recent_emails(state)
    _save_state(state)
    _write_profile_facts(state)

    msg = f"Gmail sync: {count} messages, {written} written to RAG"
    log.info(msg)
    send_notification("Gmail Sync", msg, tags=["email"])


def run_auto() -> None:
    """Incremental Gmail sync."""
    from shared.notify import send_notification

    service = _get_gmail_service()
    state = _load_state()

    if not state.history_id:
        log.info("No historyId — running full sync")
        run_full_sync()
        return

    changed_ids = _incremental_sync(service, state)
    written = _write_recent_emails(state)
    _save_state(state)
    _write_profile_facts(state)

    if changed_ids:
        msg = f"Gmail: {len(changed_ids)} changes, {written} emails in RAG"
        log.info(msg)
        send_notification("Gmail Sync", msg, tags=["email"])
    else:
        log.info("No Gmail changes")


def run_stats() -> None:
    """Display sync statistics."""
    state = _load_state()
    if not state.messages:
        print("No sync state found. Run --full-sync first.")
        return
    _print_stats(state)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Gmail RAG sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--auth", action="store_true", help="Verify OAuth")
    group.add_argument("--full-sync", action="store_true", help="Full metadata sync")
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
uv run pytest tests/test_gmail_sync.py -v
```

Expected: 6 PASS.

**Step 5: Commit**

```bash
git add agents/gmail_sync.py tests/test_gmail_sync.py
git commit -m "feat(gmail): profiler bridge, stats, CLI entry point"
```

---

## Task 5: YouTube Sync — Skeleton + Schemas

**Files:**
- Create: `~/projects/ai-agents/agents/youtube_sync.py`
- Create: `~/projects/ai-agents/tests/test_youtube_sync.py`

**Step 1: Write failing tests**

Create `~/projects/ai-agents/tests/test_youtube_sync.py`:

```python
"""Tests for youtube_sync — schemas, formatting, profiler facts."""
from __future__ import annotations


def test_liked_video_defaults():
    from agents.youtube_sync import LikedVideo
    v = LikedVideo(
        video_id="abc123",
        title="Cool Beat Tutorial",
        channel="Producer Channel",
        published_at="2026-03-01T10:00:00Z",
    )
    assert v.category == ""
    assert v.tags == []
    assert v.liked_at == ""


def test_subscription_defaults():
    from agents.youtube_sync import Subscription
    s = Subscription(
        channel_id="ch123",
        channel_name="Music Theory",
    )
    assert s.description == ""
    assert s.subscribed_at == ""


def test_youtube_sync_state_empty():
    from agents.youtube_sync import YouTubeSyncState
    s = YouTubeSyncState()
    assert s.liked_videos == {}
    assert s.subscriptions == {}
    assert s.playlists == {}
```

**Step 2: Run to verify failure**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_youtube_sync.py -v
```

**Step 3: Create youtube_sync.py skeleton**

```python
"""YouTube RAG sync — subscriptions, likes, and playlists.

Captures YouTube engagement signals for profiler and scout integration.
Watch history is limited via API; syncs liked videos and subscriptions reliably.

Usage:
    uv run python -m agents.youtube_sync --auth        # OAuth consent
    uv run python -m agents.youtube_sync --full-sync    # Full sync
    uv run python -m agents.youtube_sync --auto         # Incremental sync
    uv run python -m agents.youtube_sync --stats        # Show sync state
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

CACHE_DIR = Path.home() / ".cache" / "youtube-sync"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "youtube-profile-facts.jsonl"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"
RAG_SOURCES = Path.home() / "documents" / "rag-sources"
YOUTUBE_DIR = RAG_SOURCES / "youtube"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
]


# ── Schemas ──────────────────────────────────────────────────────────────────

class LikedVideo(BaseModel):
    """A liked YouTube video."""
    video_id: str
    title: str
    channel: str
    published_at: str = ""
    liked_at: str = ""
    category: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    duration: str = ""  # ISO 8601 duration
    view_count: int = 0


class Subscription(BaseModel):
    """A YouTube channel subscription."""
    channel_id: str
    channel_name: str
    description: str = ""
    subscribed_at: str = ""
    video_count: int = 0


class PlaylistInfo(BaseModel):
    """A YouTube playlist."""
    playlist_id: str
    title: str
    video_count: int = 0
    description: str = ""


class YouTubeSyncState(BaseModel):
    """Persistent sync state."""
    liked_videos: dict[str, LikedVideo] = Field(default_factory=dict)
    subscriptions: dict[str, Subscription] = Field(default_factory=dict)
    playlists: dict[str, PlaylistInfo] = Field(default_factory=dict)
    last_full_sync: float = 0.0
    last_sync: float = 0.0
    stats: dict[str, int] = Field(default_factory=dict)
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_youtube_sync.py -v
```

Expected: 3 PASS.

**Step 5: Commit**

```bash
git add agents/youtube_sync.py tests/test_youtube_sync.py
git commit -m "feat(youtube): skeleton module with schemas and constants"
```

---

## Task 6: YouTube Formatting + API Sync

**Files:**
- Modify: `~/projects/ai-agents/agents/youtube_sync.py`
- Modify: `~/projects/ai-agents/tests/test_youtube_sync.py`

**Step 1: Write failing test**

Add to `tests/test_youtube_sync.py`:

```python
def test_format_liked_video_markdown():
    from agents.youtube_sync import LikedVideo, _format_liked_video_markdown
    v = LikedVideo(
        video_id="abc123",
        title="Making Lo-Fi Beats on SP-404",
        channel="Beat Producer",
        published_at="2026-02-15T10:00:00Z",
        liked_at="2026-03-01T20:00:00Z",
        category="Music",
        tags=["sp-404", "lo-fi", "beats"],
    )
    md = _format_liked_video_markdown(v)
    assert "platform: google" in md
    assert "service: youtube" in md
    assert "source_service: youtube" in md
    assert "content_type: liked_video" in md
    assert "Making Lo-Fi Beats" in md
    assert "Beat Producer" in md


def test_format_subscriptions_markdown():
    from agents.youtube_sync import Subscription, _format_subscriptions_markdown
    subs = [
        Subscription(channel_id="ch1", channel_name="Music Theory",
                     description="Learn music theory", video_count=150),
        Subscription(channel_id="ch2", channel_name="Beat Making",
                     description="Hip hop production", video_count=80),
    ]
    md = _format_subscriptions_markdown(subs)
    assert "source_service: youtube" in md
    assert "Music Theory" in md
    assert "Beat Making" in md
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_youtube_sync.py -v -k "format"
```

**Step 3: Implement state management, formatting, API sync, profiler, and CLI**

Add to `agents/youtube_sync.py`:

```python
# ── State Management ─────────────────────────────────────────────────────────

def _load_state(path: Path = STATE_FILE) -> YouTubeSyncState:
    """Load sync state from disk."""
    if path.exists():
        try:
            return YouTubeSyncState.model_validate_json(path.read_text())
        except Exception as exc:
            log.warning("Corrupt state file, starting fresh: %s", exc)
    return YouTubeSyncState()


def _save_state(state: YouTubeSyncState, path: Path = STATE_FILE) -> None:
    """Persist sync state to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    tmp.rename(path)


# ── Formatting ───────────────────────────────────────────────────────────────

def _format_liked_video_markdown(v: LikedVideo) -> str:
    """Generate markdown for a liked video."""
    tags_str = "[" + ", ".join(v.tags) + "]"

    return f"""---
platform: google
service: youtube
content_type: liked_video
source_service: youtube
source_platform: google
record_id: {v.video_id}
timestamp: {v.liked_at or v.published_at}
modality_tags: [media, learning]
channel: {v.channel}
category: {v.category}
tags: {tags_str}
---

# {v.title}

**Channel:** {v.channel}
**Category:** {v.category or 'uncategorized'}
**Published:** {v.published_at}
**Tags:** {', '.join(v.tags) if v.tags else 'none'}
"""


def _format_subscriptions_markdown(subs: list[Subscription]) -> str:
    """Generate a single markdown doc listing all subscriptions."""
    channels = []
    for s in sorted(subs, key=lambda s: s.channel_name):
        desc = f" — {s.description[:80]}" if s.description else ""
        channels.append(f"- **{s.channel_name}** ({s.video_count} videos){desc}")

    return f"""---
platform: google
service: youtube
content_type: subscription_list
source_service: youtube
source_platform: google
record_id: subscriptions
timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')}
modality_tags: [media, preferences]
---

# YouTube Subscriptions ({len(subs)} channels)

{chr(10).join(channels)}
"""


# ── YouTube API Operations ───────────────────────────────────────────────────

def _get_youtube_service():
    """Build authenticated YouTube API service."""
    from shared.google_auth import build_service
    return build_service("youtube", "v3", SCOPES)


def _sync_liked_videos(service, state: YouTubeSyncState) -> int:
    """Sync liked videos."""
    count = 0
    page_token = None

    while True:
        resp = service.videos().list(
            part="snippet,contentDetails,statistics",
            myRating="like",
            maxResults=50,
            pageToken=page_token,
        ).execute()

        for item in resp.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})
            vid = item["id"]

            video = LikedVideo(
                video_id=vid,
                title=snippet.get("title", "(untitled)"),
                channel=snippet.get("channelTitle", ""),
                published_at=snippet.get("publishedAt", ""),
                category=snippet.get("categoryId", ""),
                description=snippet.get("description", "")[:200],
                tags=snippet.get("tags", [])[:10],
                duration=content.get("duration", ""),
                view_count=int(stats.get("viewCount", 0)),
            )

            if vid not in state.liked_videos:
                video.liked_at = datetime.now(timezone.utc).isoformat()
                _log_change("liked", video.title, {"channel": video.channel})
            state.liked_videos[vid] = video
            count += 1

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    log.info("Synced %d liked videos", count)
    return count


def _sync_subscriptions(service, state: YouTubeSyncState) -> int:
    """Sync channel subscriptions."""
    old_subs = set(state.subscriptions.keys())
    count = 0
    page_token = None

    while True:
        resp = service.subscriptions().list(
            part="snippet",
            mine=True,
            maxResults=50,
            pageToken=page_token,
        ).execute()

        for item in resp.get("items", []):
            snippet = item.get("snippet", {})
            resource = snippet.get("resourceId", {})
            channel_id = resource.get("channelId", "")
            if not channel_id:
                continue

            sub = Subscription(
                channel_id=channel_id,
                channel_name=snippet.get("title", ""),
                description=snippet.get("description", "")[:200],
                subscribed_at=snippet.get("publishedAt", ""),
            )

            if channel_id not in old_subs:
                _log_change("subscribed", sub.channel_name, {"channel_id": channel_id})
            state.subscriptions[channel_id] = sub
            count += 1

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    # Detect unsubscribes
    current_subs = set(state.subscriptions.keys())
    for unsub_id in old_subs - current_subs:
        name = state.subscriptions.get(unsub_id, Subscription(channel_id=unsub_id, channel_name="unknown")).channel_name
        _log_change("unsubscribed", name, {"channel_id": unsub_id})

    log.info("Synced %d subscriptions", count)
    return count


def _sync_playlists(service, state: YouTubeSyncState) -> int:
    """Sync user playlists."""
    count = 0
    page_token = None

    while True:
        resp = service.playlists().list(
            part="snippet,contentDetails",
            mine=True,
            maxResults=50,
            pageToken=page_token,
        ).execute()

        for item in resp.get("items", []):
            snippet = item.get("snippet", {})
            content = item.get("contentDetails", {})
            pid = item["id"]

            playlist = PlaylistInfo(
                playlist_id=pid,
                title=snippet.get("title", ""),
                video_count=content.get("itemCount", 0),
                description=snippet.get("description", "")[:200],
            )
            state.playlists[pid] = playlist
            count += 1

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    log.info("Synced %d playlists", count)
    return count


def _full_sync(service, state: YouTubeSyncState) -> dict[str, int]:
    """Full sync of all YouTube data."""
    log.info("Starting full YouTube sync...")
    counts = {
        "liked": _sync_liked_videos(service, state),
        "subs": _sync_subscriptions(service, state),
        "playlists": _sync_playlists(service, state),
    }
    state.last_full_sync = time.time()
    return counts


# ── Behavioral Logging ───────────────────────────────────────────────────────

def _log_change(change_type: str, name: str, extra: dict | None = None) -> None:
    """Append YouTube change to JSONL log."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "service": "youtube",
        "event_type": change_type,
        "record_id": "",
        "name": name,
        "context": extra or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(CHANGES_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# ── File Writing ─────────────────────────────────────────────────────────────

def _write_youtube_files(state: YouTubeSyncState) -> int:
    """Write YouTube data as markdown to rag-sources/youtube/."""
    YOUTUBE_DIR.mkdir(parents=True, exist_ok=True)
    written = 0

    # Clean old files
    for f in YOUTUBE_DIR.glob("*.md"):
        f.unlink()

    # Write liked videos (recent 50 only)
    recent_liked = sorted(
        state.liked_videos.values(),
        key=lambda v: v.liked_at or v.published_at,
        reverse=True,
    )[:50]
    for video in recent_liked:
        md = _format_liked_video_markdown(video)
        safe_title = video.title.replace("/", "_").replace(" ", "-")[:50]
        filename = f"liked-{safe_title}-{video.video_id[:8]}.md"
        (YOUTUBE_DIR / filename).write_text(md, encoding="utf-8")
        written += 1

    # Write subscriptions as single file
    if state.subscriptions:
        md = _format_subscriptions_markdown(list(state.subscriptions.values()))
        (YOUTUBE_DIR / "subscriptions.md").write_text(md, encoding="utf-8")
        written += 1

    log.info("Wrote %d YouTube files to %s", written, YOUTUBE_DIR)
    return written


# ── Profiler Integration ─────────────────────────────────────────────────────

def _generate_profile_facts(state: YouTubeSyncState) -> list[dict]:
    """Generate profile facts from YouTube state."""
    from collections import Counter

    facts = []
    source = "youtube-sync:youtube-profile-facts"

    # Topic interests from liked video tags and categories
    if state.liked_videos:
        tag_counts: Counter[str] = Counter()
        channel_counts: Counter[str] = Counter()
        for v in state.liked_videos.values():
            for tag in v.tags:
                tag_counts[tag.lower()] += 1
            channel_counts[v.channel] += 1

        if tag_counts:
            top_tags = ", ".join(f"{t} ({n})" for t, n in tag_counts.most_common(15))
            facts.append({
                "dimension": "interests",
                "key": "youtube_topic_interests",
                "value": top_tags,
                "confidence": 0.95,
                "source": source,
                "evidence": f"Tags from {len(state.liked_videos)} liked videos",
            })

        if channel_counts:
            top_channels = ", ".join(f"{ch} ({n})" for ch, n in channel_counts.most_common(10))
            facts.append({
                "dimension": "interests",
                "key": "youtube_favorite_channels",
                "value": top_channels,
                "confidence": 0.95,
                "source": source,
                "evidence": f"Channels across {len(state.liked_videos)} liked videos",
            })

    if state.subscriptions:
        facts.append({
            "dimension": "interests",
            "key": "youtube_subscriptions",
            "value": f"{len(state.subscriptions)} channels subscribed",
            "confidence": 0.95,
            "source": source,
            "evidence": f"Active YouTube subscriptions",
        })

    return facts


def _write_profile_facts(state: YouTubeSyncState) -> None:
    """Write profile facts JSONL."""
    facts = _generate_profile_facts(state)
    if not facts:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROFILE_FACTS_FILE, "w", encoding="utf-8") as fh:
        for fact in facts:
            fh.write(json.dumps(fact) + "\n")
    log.info("Wrote %d profile facts to %s", len(facts), PROFILE_FACTS_FILE)


# ── Stats ────────────────────────────────────────────────────────────────────

def _print_stats(state: YouTubeSyncState) -> None:
    """Print sync statistics."""
    print("YouTube Sync State")
    print("=" * 40)
    print(f"Liked videos:    {len(state.liked_videos):,}")
    print(f"Subscriptions:   {len(state.subscriptions):,}")
    print(f"Playlists:       {len(state.playlists):,}")
    print(f"Last full sync:  {datetime.fromtimestamp(state.last_full_sync, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if state.last_full_sync else 'never'}")
    print(f"Last sync:       {datetime.fromtimestamp(state.last_sync, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}")


# ── Orchestration ────────────────────────────────────────────────────────────

def run_auth() -> None:
    """Verify OAuth credentials work for YouTube."""
    print("Authenticating with YouTube...")
    service = _get_youtube_service()
    resp = service.channels().list(part="snippet", mine=True).execute()
    for ch in resp.get("items", []):
        print(f"  Channel: {ch['snippet'].get('title', 'unknown')}")
    print("Authentication successful.")


def run_full_sync() -> None:
    """Full YouTube sync."""
    from shared.notify import send_notification

    service = _get_youtube_service()
    state = _load_state()

    counts = _full_sync(service, state)
    written = _write_youtube_files(state)
    _save_state(state)
    _write_profile_facts(state)

    msg = f"YouTube sync: {counts['liked']} liked, {counts['subs']} subs, {counts['playlists']} playlists"
    log.info(msg)
    send_notification("YouTube Sync", msg, tags=["youtube"])


def run_auto() -> None:
    """Incremental YouTube sync (re-syncs everything — YouTube has no delta API)."""
    run_full_sync()


def run_stats() -> None:
    """Display sync statistics."""
    state = _load_state()
    if not state.liked_videos and not state.subscriptions:
        print("No sync state found. Run --full-sync first.")
        return
    _print_stats(state)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube RAG sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--auth", action="store_true", help="Verify OAuth")
    group.add_argument("--full-sync", action="store_true", help="Full sync")
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
uv run pytest tests/test_youtube_sync.py -v
```

Expected: 5 PASS.

**Step 5: Commit**

```bash
git add agents/youtube_sync.py tests/test_youtube_sync.py
git commit -m "feat(youtube): formatting, API sync, profiler, CLI"
```

---

## Task 7: Agent Modifications — management_prep + briefing + digest

**Files:**
- Modify: `~/projects/ai-agents/agents/management_prep.py:253-278` (after calendar block)
- Modify: `~/projects/ai-agents/agents/briefing.py:396-423` (after Drive section)
- Modify: `~/projects/ai-agents/agents/digest.py:186-198` (doc formatting)

**Step 1: Add Gmail context to management_prep.py**

After the calendar context block (around line 278), add:

```python
    # Gmail: recent email threads with this person
    try:
        gmail_state_path = Path.home() / ".cache" / "gmail-sync" / "state.json"
        if gmail_state_path.exists():
            from agents.gmail_sync import GmailSyncState
            gmail_state = GmailSyncState.model_validate_json(gmail_state_path.read_text())
            name_lower = person.name.lower()
            recent_threads = []
            for e in gmail_state.messages.values():
                if name_lower.split()[0] in e.sender.lower() or any(
                    name_lower.split()[0] in r.lower() for r in e.recipients
                ):
                    recent_threads.append(e)
            recent_threads.sort(key=lambda e: e.timestamp, reverse=True)
            if recent_threads[:5]:
                lines.append("## Recent Email Threads")
                for t in recent_threads[:5]:
                    lines.append(f"- {t.timestamp[:10]}: {t.subject} (from {t.sender})")
                lines.append("")
    except (ImportError, Exception) as exc:
        log.debug("Gmail context unavailable: %s", exc)
```

**Step 2: Add Gmail stats to briefing.py**

After the Drive activity section (around line 423), add:

```python
    # Gmail activity
    gmail_section = ""
    try:
        gmail_state_path = Path.home() / ".cache" / "gmail-sync" / "state.json"
        if gmail_state_path.exists():
            from agents.gmail_sync import GmailSyncState
            gmail_state = GmailSyncState.model_validate_json(gmail_state_path.read_text())
            unread = sum(1 for e in gmail_state.messages.values() if e.is_unread)
            if unread or gmail_state.messages:
                gmail_section = f"\n## Email\n{unread} unread messages, {len(gmail_state.messages)} total synced.\n"
    except (ImportError, Exception) as exc:
        log.debug("Gmail context unavailable: %s", exc)
```

Include `gmail_section` in the prompt assembly alongside `calendar_section` and `drive_section`.

**Step 3: Add service-aware grouping to digest.py**

In the doc formatting section (around line 186), the source_service is already shown per doc. Add a summary line before the document list. After `docs_section = "## Recently Ingested Documents\n"` line, add:

```python
        # Group by source service
        service_counts = {}
        for doc in recent_docs:
            svc = doc.get("source_service", "other")
            service_counts[svc] = service_counts.get(svc, 0) + 1
        if service_counts:
            svc_summary = ", ".join(f"{svc}: {n}" for svc, n in sorted(service_counts.items()))
            docs_section += f"Sources: {svc_summary}\n\n"
```

**Step 4: Run tests**

```bash
uv run pytest tests/ -v -k "management_prep or briefing or digest" --timeout=30
```

**Step 5: Commit**

```bash
git add agents/management_prep.py agents/briefing.py agents/digest.py
git commit -m "feat: integrate Gmail and YouTube into management_prep, briefing, digest"
```

---

## Task 8: Register Gmail + YouTube in Profiler + Update OAuth Scopes

**Files:**
- Modify: `~/projects/ai-agents/agents/profiler_sources.py:31,36-51`
- Modify: `~/projects/ai-agents/shared/google_auth.py:22-25`

**Step 1: Add to profiler_sources.py**

Add `"gmail"` and `"youtube"` to `BRIDGED_SOURCE_TYPES` (line 31):

```python
BRIDGED_SOURCE_TYPES = {"proton", "takeout", "management", "gcalendar", "gmail", "youtube"}
```

Add to `SOURCE_TYPE_CHUNK_CAPS` (line 36):

```python
    "gmail": 100,
    "youtube": 50,
```

**Step 2: Add scopes to ALL_SCOPES in google_auth.py**

Update `ALL_SCOPES` (line 22):

```python
ALL_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]
```

**Step 3: Run tests**

```bash
uv run pytest tests/ -v -k "profiler or google_auth" --timeout=30
```

**Step 4: Commit**

```bash
git add agents/profiler_sources.py shared/google_auth.py
git commit -m "feat: register gmail+youtube as bridged sources, expand OAuth scopes"
```

---

## Task 9: Systemd Timers for Gmail + YouTube

**Files:**
- Create: `~/.config/systemd/user/gmail-sync.service`
- Create: `~/.config/systemd/user/gmail-sync.timer`
- Create: `~/.config/systemd/user/youtube-sync.service`
- Create: `~/.config/systemd/user/youtube-sync.timer`

**Step 1: Create gmail-sync.service**

```ini
[Unit]
Description=Gmail RAG sync (incremental)
After=network-online.target
OnFailure=notify-failure@%n.service

[Service]
Type=oneshot
WorkingDirectory=/home/hapaxlegomenon/projects/ai-agents
ExecStart=/home/hapaxlegomenon/.local/bin/uv run python -m agents.gmail_sync --auto
Environment=PATH=/home/hapaxlegomenon/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/hapaxlegomenon
Environment=GNUPGHOME=/home/hapaxlegomenon/.gnupg
Environment=PASSWORD_STORE_DIR=/home/hapaxlegomenon/.password-store
MemoryMax=512M
SyslogIdentifier=gmail-sync
```

**Step 2: Create gmail-sync.timer (every 1 hour)**

```ini
[Unit]
Description=Gmail RAG sync every hour

[Timer]
OnCalendar=*-*-* *:05:00
Persistent=true
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
```

**Step 3: Create youtube-sync.service**

```ini
[Unit]
Description=YouTube RAG sync
After=network-online.target
OnFailure=notify-failure@%n.service

[Service]
Type=oneshot
WorkingDirectory=/home/hapaxlegomenon/projects/ai-agents
ExecStart=/home/hapaxlegomenon/.local/bin/uv run python -m agents.youtube_sync --auto
Environment=PATH=/home/hapaxlegomenon/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/hapaxlegomenon
Environment=GNUPGHOME=/home/hapaxlegomenon/.gnupg
Environment=PASSWORD_STORE_DIR=/home/hapaxlegomenon/.password-store
MemoryMax=512M
SyslogIdentifier=youtube-sync
```

**Step 4: Create youtube-sync.timer (every 6 hours)**

```ini
[Unit]
Description=YouTube RAG sync every 6 hours

[Timer]
OnCalendar=*-*-* 00/6:30:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

**Step 5: Reload systemd**

```bash
systemctl --user daemon-reload
systemctl --user list-timers | grep -E "gmail|youtube"
```

---

## Task 10: Documentation Updates

**Files:**
- Modify: `~/projects/hapax-system/rules/system-context.md`
- Modify: `~/projects/hapaxromana/CLAUDE.md`

**Step 1: Update system-context.md**

Add to Management Agents table:

```markdown
| gmail_sync | No | `--auth`, `--full-sync`, `--auto`, `--stats` |
| youtube_sync | No | `--auth`, `--full-sync`, `--auto`, `--stats` |
```

Add to Management Timers table:

```markdown
| gmail-sync | Every 1h | Gmail metadata RAG sync |
| youtube-sync | Every 6h | YouTube subscriptions/likes sync |
```

**Step 2: Update hapaxromana CLAUDE.md**

Add gmail_sync and youtube_sync to the Tier 2 agents table and timers to Tier 3 services.

**Step 3: Commit in each repo**

```bash
cd ~/projects/hapax-system && git add -A && git commit -m "docs: add gmail-sync and youtube-sync to system context"
cd ~/projects/hapaxromana && git add -A && git commit -m "docs: update architecture with Gmail and YouTube sync agents"
```

---

## Task 11: OAuth Expansion + Integration Test

**Step 1: Re-auth with expanded scopes**

```bash
cd ~/projects/ai-agents && uv run python -m agents.gmail_sync --auth
```

This will trigger a new OAuth consent to add `gmail.readonly`. Enable Gmail API in Google Cloud console if needed: `https://console.developers.google.com/apis/api/gmail.googleapis.com/overview?project=502232723265`

**Step 2: Gmail full sync**

```bash
uv run python -m agents.gmail_sync --full-sync -v
uv run python -m agents.gmail_sync --stats
```

**Step 3: YouTube auth + sync**

```bash
uv run python -m agents.youtube_sync --auth
```

Enable YouTube Data API if needed: `https://console.developers.google.com/apis/api/youtube.googleapis.com/overview?project=502232723265`

```bash
uv run python -m agents.youtube_sync --full-sync -v
uv run python -m agents.youtube_sync --stats
```

**Step 4: Verify rag-ingest picks up files**

```bash
ls ~/documents/rag-sources/gmail/
ls ~/documents/rag-sources/youtube/
```

**Step 5: Enable timers**

```bash
systemctl --user enable --now gmail-sync.timer
systemctl --user enable --now youtube-sync.timer
systemctl --user list-timers | grep -E "gmail|youtube|gcalendar|gdrive"
```

**Step 6: Run all tests**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_google_auth.py tests/test_gmail_sync.py tests/test_youtube_sync.py tests/test_gcalendar_sync.py tests/test_calendar_context.py tests/test_gdrive_sync.py -v
```

---

## Summary

| Task | Description | Type |
|------|-------------|------|
| 1 | Gmail skeleton + schemas | Gmail core |
| 2 | Gmail formatting + markdown | Gmail core |
| 3 | Gmail API sync + message writing | Gmail core |
| 4 | Gmail profiler + stats + CLI | Gmail core |
| 5 | YouTube skeleton + schemas | YouTube core |
| 6 | YouTube formatting + API sync + profiler + CLI | YouTube core |
| 7 | Agent modifications (management_prep, briefing, digest) | Integration |
| 8 | Register in profiler + expand OAuth scopes | Integration |
| 9 | Systemd timers for Gmail + YouTube | Operations |
| 10 | Documentation updates across repos | Documentation |
| 11 | OAuth expansion + integration test | Verification |

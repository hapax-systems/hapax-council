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
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from shared.governance.consent import ConsentRegistry

try:
    from agents import _langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

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

MAX_FULL_SYNC = 500
RAG_WINDOW_DAYS = 30
BODY_EXTRACT_LABELS = {"IMPORTANT", "STARRED"}


# ── Schemas ──────────────────────────────────────────────────────────────────


class EmailMetadata(BaseModel):
    """Email message metadata."""

    message_id: str
    thread_id: str
    subject: str
    sender: str
    timestamp: str
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


# ── State Management ─────────────────────────────────────────────────────────


def _load_state(path: Path = STATE_FILE) -> GmailSyncState:
    if path.exists():
        try:
            return GmailSyncState.model_validate_json(path.read_text())
        except Exception as exc:
            log.warning("Corrupt state file, starting fresh: %s", exc)
    return GmailSyncState()


def _save_state(state: GmailSyncState, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    tmp.rename(path)


# ── Email Formatting ─────────────────────────────────────────────────────────


def _format_email_markdown(e: EmailMetadata) -> str:
    people = [e.sender] + [r for r in e.recipients if r != e.sender]
    people_str = "[" + ", ".join(people) + "]"

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
**To:** {", ".join(e.recipients) if e.recipients else "me"}
**Date:** {date_display}
**Labels:** {", ".join(e.labels) if e.labels else "none"}
**Thread:** {e.thread_length} message{"s" if e.thread_length != 1 else ""}{snippet_block}
"""


# ── Gmail API Operations ────────────────────────────────────────────────────


def _get_gmail_service():
    """Build authenticated Gmail API service."""
    from agents._google_auth import build_service

    return build_service("gmail", "v1", SCOPES)


def _parse_headers(headers: list[dict]) -> dict[str, str]:
    """Extract from/to/subject/date from Gmail API header list."""
    result: dict[str, str] = {}
    wanted = {"From", "To", "Subject", "Date"}
    for h in headers:
        name = h.get("name", "")
        if name in wanted:
            result[name.lower()] = h.get("value", "")
    return result


def _clean_email_address(raw: str) -> str:
    """Extract bare email from 'Name <email>' format."""
    if "<" in raw and ">" in raw:
        return raw.split("<")[1].split(">")[0].strip()
    return raw.strip()


def _parse_message(msg: dict) -> EmailMetadata:
    """Convert a Gmail API message (metadata format) to EmailMetadata."""
    payload = msg.get("payload", {})
    headers = _parse_headers(payload.get("headers", []))

    sender_raw = headers.get("from", "")
    sender = _clean_email_address(sender_raw)

    recipients_raw = headers.get("to", "")
    recipients = [_clean_email_address(r) for r in recipients_raw.split(",") if r.strip()]

    # Convert internalDate (ms epoch) to ISO timestamp
    internal_date_ms = int(msg.get("internalDate", "0"))
    timestamp = datetime.fromtimestamp(internal_date_ms / 1000, tz=UTC).isoformat()

    # Detect attachments from payload parts
    has_attachments = False
    for part in payload.get("parts", []):
        if part.get("filename"):
            has_attachments = True
            break

    labels = msg.get("labelIds", [])
    is_unread = "UNREAD" in labels
    is_starred = "STARRED" in labels

    return EmailMetadata(
        message_id=msg["id"],
        thread_id=msg.get("threadId", ""),
        subject=headers.get("subject", "(no subject)"),
        sender=sender,
        timestamp=timestamp,
        recipients=recipients,
        labels=labels,
        is_unread=is_unread,
        is_starred=is_starred,
        has_attachments=has_attachments,
        snippet=msg.get("snippet", ""),
        synced_at=time.time(),
    )


def _full_sync(service, state: GmailSyncState) -> int:
    """Full sync of email metadata. Fetches up to MAX_FULL_SYNC messages."""
    log.info("Starting full Gmail sync...")

    # Get current historyId from profile for incremental sync baseline
    profile = service.users().getProfile(userId="me").execute()
    state.history_id = profile.get("historyId", "")

    # List message IDs
    message_ids: list[str] = []
    page_token = None
    while len(message_ids) < MAX_FULL_SYNC:
        resp = (
            service.users()
            .messages()
            .list(
                userId="me",
                maxResults=min(100, MAX_FULL_SYNC - len(message_ids)),
                pageToken=page_token,
            )
            .execute()
        )

        for m in resp.get("messages", []):
            message_ids.append(m["id"])

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    # Fetch metadata for each message
    count = 0
    for mid in message_ids:
        try:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=mid,
                    format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"],
                )
                .execute()
            )
            email = _parse_message(msg)
            state.messages[email.message_id] = email
            count += 1
        except Exception as exc:
            log.warning("Failed to fetch message %s: %s", mid, exc)

    state.last_full_sync = time.time()
    state.last_sync = time.time()
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
            resp = (
                service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=state.history_id,
                    historyTypes=["messageAdded", "labelAdded", "labelRemoved"],
                    pageToken=page_token,
                )
                .execute()
            )
        except Exception as exc:
            if "404" in str(exc) or "notFound" in str(exc):
                log.warning("historyId expired — full sync required")
                state.history_id = ""
                return []
            raise

        for record in resp.get("history", []):
            # Handle new messages
            for added in record.get("messagesAdded", []):
                mid = added["message"]["id"]
                if mid not in changed_ids:
                    changed_ids.append(mid)

            # Handle label changes on existing messages
            for label_change in record.get("labelsAdded", []) + record.get("labelsRemoved", []):
                mid = label_change["message"]["id"]
                if mid not in changed_ids:
                    changed_ids.append(mid)

        page_token = resp.get("nextPageToken")
        if not page_token:
            state.history_id = resp.get("historyId", state.history_id)
            break

    # Fetch updated metadata for changed messages
    for mid in changed_ids:
        try:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=mid,
                    format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"],
                )
                .execute()
            )
            email = _parse_message(msg)
            old = state.messages.get(mid)
            if old:
                _log_change(email, "updated", {"old_labels": old.labels})
            else:
                _log_change(email, "added")
            state.messages[email.message_id] = email
        except Exception as exc:
            log.warning("Failed to fetch message %s: %s", mid, exc)

    state.last_sync = time.time()
    log.info("Incremental sync: %d changes", len(changed_ids))
    return changed_ids


# ── Behavioral Logging ───────────────────────────────────────────────────────


def _log_change(email: EmailMetadata, change_type: str, extra: dict | None = None) -> None:
    """Append email change event to JSONL log."""
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
        "timestamp": datetime.now(UTC).isoformat(),
    }
    with open(CHANGES_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    log.debug("Logged gmail change: %s %s", change_type, email.subject)


# ── File Writing ─────────────────────────────────────────────────────────────


def _write_recent_emails(state: GmailSyncState) -> int:
    """Write recent email metadata as markdown stubs to rag-sources/gmail/."""
    # Load consent registry for sender/recipient filtering
    _consent_registry = ConsentRegistry()
    _consent_registry.load()

    GMAIL_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=RAG_WINDOW_DAYS)
    written = 0

    # Clean old files first
    for f in GMAIL_DIR.glob("*.md"):
        f.unlink()

    for email in state.messages.values():
        try:
            email_dt = datetime.fromisoformat(email.timestamp.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        if email_dt < cutoff:
            continue

        # Consent gate: strip unconsented sender/recipients
        update: dict = {}
        if email.sender and not _consent_registry.contract_check(email.sender, "email"):
            update["sender"] = "[redacted]"
        if email.recipients:
            update["recipients"] = [
                r if _consent_registry.contract_check(r, "email") else "[redacted]"
                for r in email.recipients
            ]
        if update:
            email = email.model_copy(update=update)

        md = _format_email_markdown(email)
        safe_subject = email.subject.replace("/", "_").replace(" ", "-")[:60]
        date_prefix = email_dt.strftime("%Y-%m-%d")
        filename = f"{date_prefix}-{safe_subject}-{email.message_id[:8]}.md"
        filepath = GMAIL_DIR / filename
        filepath.write_text(md, encoding="utf-8")
        email.local_path = str(filepath)
        written += 1

    log.info("Wrote %d recent emails to %s", written, GMAIL_DIR)
    return written


# ── Profiler Integration ─────────────────────────────────────────────────────


def _generate_profile_facts(state: GmailSyncState) -> list[dict]:
    """Generate deterministic profile facts from email state."""
    from collections import Counter

    sender_counts: Counter[str] = Counter()
    thread_ids: set[str] = set()
    total = 0

    for e in state.messages.values():
        total += 1
        sender_counts[e.sender] += 1
        thread_ids.add(e.thread_id)

    facts = []
    source = "gmail-sync:gmail-profile-facts"

    if total:
        facts.append(
            {
                "dimension": "communication_patterns",
                "key": "email_volume",
                "value": f"{total} emails synced, {len(thread_ids)} threads",
                "confidence": 0.95,
                "source": source,
                "evidence": f"Computed from {total} messages across {len(thread_ids)} threads",
            }
        )

    if sender_counts:
        top = ", ".join(f"{email} ({n})" for email, n in sender_counts.most_common(10))
        facts.append(
            {
                "dimension": "communication_patterns",
                "key": "email_frequent_senders",
                "value": top,
                "confidence": 0.95,
                "source": source,
                "evidence": f"Top senders across {total} emails",
            }
        )

    # Thread patterns: threads with multiple messages indicate active conversations
    thread_lengths: Counter[str] = Counter()
    for e in state.messages.values():
        thread_lengths[e.thread_id] += 1
    multi_msg_threads = {tid: cnt for tid, cnt in thread_lengths.items() if cnt > 1}
    if multi_msg_threads:
        avg_len = sum(multi_msg_threads.values()) / len(multi_msg_threads)
        facts.append(
            {
                "dimension": "communication_patterns",
                "key": "email_thread_patterns",
                "value": f"{len(multi_msg_threads)} active threads, avg {avg_len:.1f} messages",
                "confidence": 0.95,
                "source": source,
                "evidence": f"Threads with >1 message out of {len(thread_ids)} total",
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
                    "dimension": "communication_patterns",
                    "key": "email_change_patterns",
                    "value": f"{total_changes} changes: {dist}",
                    "confidence": 0.95,
                    "source": source,
                    "evidence": f"Accumulated from {total_changes} email change events",
                }
            )

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
    thread_ids = {e.thread_id for e in state.messages.values()}

    sender_counts: Counter[str] = Counter()
    for e in state.messages.values():
        sender_counts[e.sender] += 1

    print("Gmail Sync State")
    print("=" * 40)
    print(f"Total messages:  {total:,}")
    print(f"Unread:          {unread:,}")
    print(f"Starred:         {starred:,}")
    print(f"Threads:         {len(thread_ids):,}")
    print(
        f"Last full sync:  {datetime.fromtimestamp(state.last_full_sync, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_full_sync else 'never'}"
    )
    print(
        f"Last sync:       {datetime.fromtimestamp(state.last_sync, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}"
    )

    if sender_counts:
        print("\nTop senders:")
        for email, count in sender_counts.most_common(10):
            print(f"  {email}: {count}")


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
    from agents._notify import send_notification

    service = _get_gmail_service()
    state = _load_state()

    count = _full_sync(service, state)
    written = _write_recent_emails(state)
    _save_state(state)
    _write_profile_facts(state)

    # Sensor protocol — write state + impingement
    from agents._sensor_protocol import emit_sensor_impingement, write_sensor_state

    unread = sum(1 for e in state.messages.values() if e.is_unread)
    write_sensor_state("gmail", {"unread_count": unread, "last_sync": time.time()})
    emit_sensor_impingement("gmail", "communication_patterns", ["email_sync"])

    msg = f"Gmail sync: {count} messages, {written} written to RAG"
    log.info(msg)
    send_notification("Gmail Sync", msg, tags=["gmail"])


def run_auto() -> None:
    """Incremental Gmail sync."""
    from agents._notify import send_notification

    service = _get_gmail_service()
    state = _load_state()

    if not state.history_id:
        log.info("No historyId — running full sync")
        run_full_sync()
        return

    changed_ids = _incremental_sync(service, state)

    # If historyId expired, _incremental_sync clears it — fall back to full
    if not state.history_id:
        run_full_sync()
        return

    written = _write_recent_emails(state)
    _save_state(state)
    _write_profile_facts(state)

    # Sensor protocol — write state + impingement on changes
    from agents._sensor_protocol import emit_sensor_impingement, write_sensor_state

    unread = sum(1 for e in state.messages.values() if e.is_unread)
    write_sensor_state("gmail", {"unread_count": unread, "last_sync": time.time()})
    if changed_ids:
        emit_sensor_impingement("gmail", "communication_patterns", ["email_sync"])

    if changed_ids:
        msg = f"Gmail: {len(changed_ids)} changes, {written} emails in RAG"
        log.info(msg)
        send_notification("Gmail Sync", msg, tags=["gmail"])
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

    from agents._log_setup import configure_logging

    configure_logging(agent="gmail-sync", level="DEBUG" if args.verbose else None)

    action = (
        "auth" if args.auth else "full_sync" if args.full_sync else "auto" if args.auto else "stats"
    )
    with _tracer.start_as_current_span(
        f"gmail_sync.{action}",
        attributes={"agent.name": "gmail_sync", "agent.repo": "hapax-council"},
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

"""Chrome RAG sync — browsing history and bookmarks.

Reads Chrome's local SQLite History database and Bookmarks JSON file,
writes domain summaries and bookmarks to rag-sources/chrome/ for RAG ingestion.

Usage:
    uv run python -m agents.chrome_sync --full-sync    # Full history sync
    uv run python -m agents.chrome_sync --auto         # Incremental sync
    uv run python -m agents.chrome_sync --stats        # Show sync state
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

CHROME_HISTORY_DB = Path.home() / ".config" / "google-chrome" / "Default" / "History"
CHROME_BOOKMARKS_FILE = Path.home() / ".config" / "google-chrome" / "Default" / "Bookmarks"

CACHE_DIR = Path.home() / ".cache" / "chrome-sync"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "chrome-profile-facts.jsonl"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"
SNAPSHOT_DB = CACHE_DIR / "history-snapshot.db"

RAG_SOURCES = Path.home() / "documents" / "rag-sources"
CHROME_DIR = RAG_SOURCES / "chrome"

WEBKIT_EPOCH_OFFSET = 11644473600
MIN_DOMAIN_VISITS = 3

SKIP_DOMAINS: set[str] = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "chrome://",
    "chrome-extension://",
    "newtab",
    "mail.google.com",
    "calendar.google.com",
    "drive.google.com",
    "docs.google.com",
    "youtube.com",
    "www.youtube.com",
    "music.youtube.com",
    "accounts.google.com",
    "myaccount.google.com",
}


# ── Schemas ──────────────────────────────────────────────────────────────────


class HistoryEntry(BaseModel):
    """A visited URL from Chrome history."""

    url: str
    title: str = ""
    domain: str = ""
    visit_count: int = 0
    last_visit: datetime | None = None
    first_visit: datetime | None = None


class BookmarkEntry(BaseModel):
    """A Chrome bookmark."""

    url: str
    title: str = ""
    folder: str = ""
    added_at: datetime | None = None


class ChromeSyncState(BaseModel):
    """Persistent sync state."""

    last_visit_time: int = 0
    domains: dict[str, int] = Field(default_factory=dict)
    bookmark_hash: str = ""
    last_sync: float = 0.0
    stats: dict[str, int] = Field(default_factory=dict)


# ── Timestamp Conversion ────────────────────────────────────────────────────


def _webkit_to_datetime(webkit_ts: int) -> datetime:
    """Convert WebKit microseconds timestamp to Python datetime (UTC)."""
    if webkit_ts <= 0:
        return datetime(1970, 1, 1, tzinfo=UTC)
    unix_seconds = webkit_ts / 1_000_000 - WEBKIT_EPOCH_OFFSET
    return datetime.fromtimestamp(unix_seconds, tz=UTC)


# ── Domain Filtering ────────────────────────────────────────────────────────


def _should_skip_domain(domain: str) -> bool:
    """Check if a domain should be skipped (noise domains)."""
    if not domain:
        return True
    domain_lower = domain.lower()
    return any(domain_lower == skip or domain_lower.startswith(skip) for skip in SKIP_DOMAINS)


# ── State Management ─────────────────────────────────────────────────────────


def _load_state(path: Path = STATE_FILE) -> ChromeSyncState:
    """Load sync state from disk."""
    if path.exists():
        try:
            return ChromeSyncState.model_validate_json(path.read_text())
        except Exception as exc:
            log.warning("Corrupt state file, starting fresh: %s", exc)
    return ChromeSyncState()


def _save_state(state: ChromeSyncState, path: Path = STATE_FILE) -> None:
    """Persist sync state to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    tmp.rename(path)


# ── History DB Operations ────────────────────────────────────────────────────


def _copy_history_db() -> Path | None:
    """Copy Chrome History DB to temp location (Chrome locks the original)."""
    if not CHROME_HISTORY_DB.exists():
        log.error("Chrome History DB not found: %s", CHROME_HISTORY_DB)
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(CHROME_HISTORY_DB, SNAPSHOT_DB)
        log.debug("Copied History DB to %s", SNAPSHOT_DB)
        return SNAPSHOT_DB
    except Exception as exc:
        log.error("Failed to copy History DB: %s", exc)
        return None


def _query_history(db_path: Path, since_webkit_ts: int = 0) -> list[HistoryEntry]:
    """Query Chrome history for URLs visited since the given WebKit timestamp."""
    entries: list[HistoryEntry] = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.execute(
            """SELECT url, title, visit_count, last_visit_time,
                      (SELECT MIN(visit_time) FROM visits WHERE visits.url = urls.id) as first_visit_time
               FROM urls
               WHERE last_visit_time > ?
               ORDER BY last_visit_time DESC""",
            (since_webkit_ts,),
        )
        for row in cursor:
            url, title, visit_count, last_visit_time, first_visit_time = row
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.scheme

            if _should_skip_domain(domain):
                continue

            entries.append(
                HistoryEntry(
                    url=url,
                    title=title or "",
                    domain=domain,
                    visit_count=visit_count or 0,
                    last_visit=_webkit_to_datetime(last_visit_time) if last_visit_time else None,
                    first_visit=_webkit_to_datetime(first_visit_time) if first_visit_time else None,
                )
            )
        conn.close()
    except Exception as exc:
        log.error("Failed to query history: %s", exc)
    return entries


# ── Bookmarks ────────────────────────────────────────────────────────────────


def _read_bookmarks(path: Path = CHROME_BOOKMARKS_FILE) -> list[BookmarkEntry]:
    """Read Chrome bookmarks JSON, recursively walking the tree."""
    if not path.exists():
        log.warning("Bookmarks file not found: %s", path)
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("Failed to read bookmarks: %s", exc)
        return []

    bookmarks: list[BookmarkEntry] = []

    def walk(node: dict, folder: str = "") -> None:
        node_type = node.get("type", "")
        if node_type == "url":
            url = node.get("url", "")
            # Chrome stores bookmark timestamps as WebKit microseconds in string form
            added_raw = node.get("date_added", "0")
            try:
                added_ts = int(added_raw)
                added_dt = _webkit_to_datetime(added_ts) if added_ts > 0 else None
            except (ValueError, TypeError):
                added_dt = None

            bookmarks.append(
                BookmarkEntry(
                    url=url,
                    title=node.get("name", ""),
                    folder=folder,
                    added_at=added_dt,
                )
            )
        elif node_type == "folder":
            name = node.get("name", "")
            subfolder = f"{folder}/{name}" if folder else name
            for child in node.get("children", []):
                walk(child, subfolder)

    roots = data.get("roots", {})
    for root_name, root_node in roots.items():
        if isinstance(root_node, dict):
            walk(root_node, root_name)

    return bookmarks


# ── Formatting ───────────────────────────────────────────────────────────────


def _format_domain_markdown(domain: str, entries: list[HistoryEntry], total_visits: int) -> str:
    """Format a domain's history as a markdown document for RAG ingestion."""
    # Sort entries by visit count descending
    sorted_entries = sorted(entries, key=lambda e: e.visit_count, reverse=True)

    lines = [
        "---",
        "platform: chrome",
        "source_service: chrome",
        "content_type: browsing_domain",
        f"domain: {domain}",
        f"total_visits: {total_visits}",
        f"unique_pages: {len(entries)}",
        "---",
        "",
        f"# {domain}",
        "",
        f"Total visits: {total_visits} across {len(entries)} pages",
        "",
        "## Most Visited Pages",
        "",
    ]

    for entry in sorted_entries[:20]:
        title = entry.title or entry.url
        lines.append(f"- **{title}** ({entry.visit_count} visits)")
        lines.append(f"  {entry.url}")

    lines.append("")
    return "\n".join(lines)


def _format_bookmarks_markdown(bookmarks: list[BookmarkEntry]) -> str:
    """Format bookmarks as a markdown document grouped by folder."""
    # Group by folder
    by_folder: dict[str, list[BookmarkEntry]] = {}
    for bm in bookmarks:
        folder = bm.folder or "Unfiled"
        by_folder.setdefault(folder, []).append(bm)

    lines = [
        "---",
        "platform: chrome",
        "source_service: chrome",
        "content_type: bookmarks",
        f"bookmark_count: {len(bookmarks)}",
        f"folder_count: {len(by_folder)}",
        "---",
        "",
        "# Chrome Bookmarks",
        "",
        f"Total: {len(bookmarks)} bookmarks in {len(by_folder)} folders",
        "",
    ]

    for folder in sorted(by_folder.keys()):
        items = by_folder[folder]
        lines.append(f"## {folder}")
        lines.append("")
        for bm in items:
            lines.append(f"- [{bm.title or bm.url}]({bm.url})")
        lines.append("")

    return "\n".join(lines)


# ── File Writing ─────────────────────────────────────────────────────────────


def _write_domain_files(entries: list[HistoryEntry], state: ChromeSyncState) -> int:
    """Group entries by domain, write files for domains with MIN_DOMAIN_VISITS+ visits."""
    by_domain: dict[str, list[HistoryEntry]] = {}
    for entry in entries:
        by_domain.setdefault(entry.domain, []).append(entry)

    # Update state domain counts (merge with existing)
    for domain, domain_entries in by_domain.items():
        total = sum(e.visit_count for e in domain_entries)
        state.domains[domain] = state.domains.get(domain, 0) + total

    # Write files for qualifying domains
    CHROME_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for domain, domain_entries in by_domain.items():
        total_visits = state.domains.get(domain, 0)
        if total_visits < MIN_DOMAIN_VISITS:
            continue

        safe_domain = domain.replace("/", "_").replace(":", "_")
        path = CHROME_DIR / f"domain-{safe_domain}.md"
        content = _format_domain_markdown(domain, domain_entries, total_visits)
        path.write_text(content, encoding="utf-8")
        written += 1

    log.info("Wrote %d domain files to %s", written, CHROME_DIR)
    return written


def _write_bookmarks_file(bookmarks: list[BookmarkEntry], state: ChromeSyncState) -> bool:
    """Write bookmarks markdown if content changed (MD5 hash check)."""
    if not bookmarks:
        return False

    content = _format_bookmarks_markdown(bookmarks)
    content_hash = hashlib.md5(content.encode("utf-8"), usedforsecurity=False).hexdigest()

    if content_hash == state.bookmark_hash:
        log.debug("Bookmarks unchanged (hash: %s)", content_hash)
        return False

    CHROME_DIR.mkdir(parents=True, exist_ok=True)
    path = CHROME_DIR / "bookmarks.md"
    path.write_text(content, encoding="utf-8")
    state.bookmark_hash = content_hash
    log.info("Wrote bookmarks to %s", path)
    return True


# ── Sync Operations ──────────────────────────────────────────────────────────


def _full_sync(state: ChromeSyncState) -> tuple[int, bool]:
    """Full sync: all history + bookmarks. Returns (domains_written, bookmarks_updated)."""
    db_path = _copy_history_db()
    if not db_path:
        return 0, False

    # Query all history (since_webkit_ts=0 for full)
    entries = _query_history(db_path, since_webkit_ts=0)
    log.info("Full sync: %d history entries", len(entries))

    # Track high-water mark
    if entries:
        max_visit = max(
            int((e.last_visit.timestamp() + WEBKIT_EPOCH_OFFSET) * 1_000_000)
            for e in entries
            if e.last_visit
        )
        state.last_visit_time = max(state.last_visit_time, max_visit)

    # Reset domain counts for full sync
    state.domains = {}
    domains_written = _write_domain_files(entries, state)

    # Bookmarks
    bookmarks = _read_bookmarks()
    bookmarks_updated = _write_bookmarks_file(bookmarks, state)

    state.last_sync = time.time()
    state.stats = {
        "history_entries": len(entries),
        "domains_written": domains_written,
        "bookmarks": len(bookmarks),
    }

    return domains_written, bookmarks_updated


def _incremental_sync(state: ChromeSyncState) -> tuple[int, bool]:
    """Incremental sync: only new history since last visit time."""
    db_path = _copy_history_db()
    if not db_path:
        return 0, False

    entries = _query_history(db_path, since_webkit_ts=state.last_visit_time)
    log.info("Incremental sync: %d new entries since last sync", len(entries))

    if entries:
        max_visit = max(
            int((e.last_visit.timestamp() + WEBKIT_EPOCH_OFFSET) * 1_000_000)
            for e in entries
            if e.last_visit
        )
        state.last_visit_time = max(state.last_visit_time, max_visit)

    domains_written = _write_domain_files(entries, state)

    bookmarks = _read_bookmarks()
    bookmarks_updated = _write_bookmarks_file(bookmarks, state)

    state.last_sync = time.time()
    state.stats = {
        "history_entries": len(entries),
        "domains_written": domains_written,
        "bookmarks": len(bookmarks),
    }

    return domains_written, bookmarks_updated


# ── Profiler Integration ─────────────────────────────────────────────────────


def _generate_profile_facts(state: ChromeSyncState) -> list[dict]:
    """Generate deterministic profile facts from Chrome browsing state."""
    facts: list[dict] = []
    source = "chrome-sync:chrome-profile-facts"

    if state.domains:
        # Top domains by visit count
        sorted_domains = sorted(state.domains.items(), key=lambda x: x[1], reverse=True)
        top = ", ".join(f"{d} ({n})" for d, n in sorted_domains[:15])
        facts.append(
            {
                "dimension": "information_seeking",
                "key": "browsing_top_domains",
                "value": top,
                "confidence": 0.85,
                "source": source,
                "evidence": f"Top domains across {sum(state.domains.values())} total visits to {len(state.domains)} domains",
            }
        )

    return facts


def _write_profile_facts(state: ChromeSyncState) -> None:
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


def _print_stats(state: ChromeSyncState) -> None:
    """Print sync statistics."""
    total_visits = sum(state.domains.values())
    print("Chrome Sync State")
    print("=" * 40)
    print(f"Tracked domains: {len(state.domains):,}")
    print(f"Total visits:    {total_visits:,}")
    print(f"Bookmark hash:   {state.bookmark_hash or 'none'}")
    print(
        f"Last sync:       {datetime.fromtimestamp(state.last_sync, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}"
    )

    if state.domains:
        sorted_domains = sorted(state.domains.items(), key=lambda x: x[1], reverse=True)
        print("\nTop domains:")
        for domain, count in sorted_domains[:15]:
            print(f"  {domain}: {count}")


# ── Orchestration ────────────────────────────────────────────────────────────


def run_full_sync() -> None:
    """Full sync of Chrome history and bookmarks."""
    from shared.notify import send_notification

    state = _load_state()
    domains_written, bookmarks_updated = _full_sync(state)
    _save_state(state)
    _write_profile_facts(state)

    msg = (
        f"Chrome sync: {len(state.domains)} domains tracked, "
        f"{domains_written} domain files written, "
        f"bookmarks {'updated' if bookmarks_updated else 'unchanged'}"
    )
    log.info(msg)
    send_notification("Chrome Sync", msg, tags=["chrome"])


def run_auto() -> None:
    """Incremental Chrome sync."""
    from shared.notify import send_notification

    state = _load_state()

    if state.last_visit_time == 0:
        log.info("No prior sync — running full sync")
        run_full_sync()
        return

    domains_written, bookmarks_updated = _incremental_sync(state)
    _save_state(state)
    _write_profile_facts(state)

    if domains_written or bookmarks_updated:
        msg = (
            f"Chrome: {domains_written} domains updated, "
            f"bookmarks {'updated' if bookmarks_updated else 'unchanged'}"
        )
        log.info(msg)
        send_notification("Chrome Sync", msg, tags=["chrome"])
    else:
        log.info("No Chrome changes")


def run_stats() -> None:
    """Display sync statistics."""
    state = _load_state()
    if not state.domains:
        print("No sync state found. Run --full-sync first.")
        return
    _print_stats(state)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Chrome RAG sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full-sync", action="store_true", help="Full history + bookmarks sync")
    group.add_argument("--auto", action="store_true", help="Incremental sync")
    group.add_argument("--stats", action="store_true", help="Show sync statistics")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="chrome-sync", level="DEBUG" if args.verbose else None)

    if args.full_sync:
        run_full_sync()
    elif args.auto:
        run_auto()
    elif args.stats:
        run_stats()


if __name__ == "__main__":
    main()

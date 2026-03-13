"""Obsidian vault RAG sync — scan vault, write changed notes with metadata.

Read-only against the vault. Writes RAG-formatted markdown to rag-sources/obsidian/.
Extracts frontmatter, inline #tags, [[wikilinks]], and folder structure.

Usage:
    uv run python -m agents.obsidian_sync --full-sync    # Full vault sync
    uv run python -m agents.obsidian_sync --auto          # Incremental (changed files)
    uv run python -m agents.obsidian_sync --stats         # Show sync state
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

VAULT_PATH = Path.home() / "Documents" / "Personal"
CACHE_DIR = Path.home() / ".cache" / "obsidian-sync"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "obsidian-profile-facts.jsonl"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"
RAG_SOURCES = Path.home() / "documents" / "rag-sources"
OBSIDIAN_DIR = RAG_SOURCES / "obsidian"

MIN_FILE_SIZE = 50

INCLUDE_DIRS = {
    "00-inbox",
    "20-personal",
    "20 Projects",
    "30 Areas",
    "31 Fleeting notes",
    "32 Literature notes",
    "33 Permanent notes",
    "34 MOCs",
    "35 Contacts",
    "36 People",
    "37 Meeting notes",
    "38 Bookmarks",
    "50 Resources",
    "Periodic Notes",
    "Day Planners",
}

EXCLUDE_DIRS = {
    "90-attachments",
    "50-templates",
    "Templates",
    "60-archive",
    "60 Archives",
    ".obsidian",
    "smart-chats",
    "textgenerator",
    "configs",
    "docs",
    "scripts",
    "research",
}


# ── Schemas ──────────────────────────────────────────────────────────────────


class VaultNote(BaseModel):
    """An Obsidian vault note with extracted metadata."""

    relative_path: str
    title: str
    folder: str
    content_hash: str
    size: int
    mtime: float
    has_frontmatter: bool = False
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)


class ObsidianSyncState(BaseModel):
    """Persistent sync state."""

    notes: dict[str, VaultNote] = Field(default_factory=dict)
    last_sync: float = 0.0
    stats: dict[str, int] = Field(default_factory=dict)


# ── Path Filtering ───────────────────────────────────────────────────────────


def _should_include(relative_path: str) -> bool:
    """Check whether a vault path should be synced.

    Rules:
    - Must be a .md file
    - Root-level .md files are always included
    - First path component must match INCLUDE_DIRS (or be a child of one)
    - Any path component in EXCLUDE_DIRS causes exclusion
    """
    if not relative_path.endswith(".md"):
        return False

    parts = Path(relative_path).parts

    # Root-level .md file (no subdirectory)
    if len(parts) == 1:
        return True

    # Check for excluded directories in any component
    for part in parts[:-1]:  # all directory components
        if part in EXCLUDE_DIRS:
            return False

    # First directory must be in INCLUDE_DIRS
    first_dir = parts[0]
    if first_dir in INCLUDE_DIRS:
        return True

    # Check if any subdirectory is in INCLUDE_DIRS (e.g. "30 Areas/33 Permanent notes/")
    return any(part in INCLUDE_DIRS for part in parts[:-1])


# ── State Management ─────────────────────────────────────────────────────────


def _load_state(path: Path = STATE_FILE) -> ObsidianSyncState:
    """Load sync state from disk."""
    if path.exists():
        try:
            return ObsidianSyncState.model_validate_json(path.read_text())
        except Exception as exc:
            log.warning("Corrupt state file, starting fresh: %s", exc)
    return ObsidianSyncState()


def _save_state(state: ObsidianSyncState, path: Path = STATE_FILE) -> None:
    """Persist sync state to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    tmp.rename(path)


# ── Metadata Extraction ─────────────────────────────────────────────────────


def _extract_metadata(content: str, relative_path: str) -> dict:
    """Extract metadata from an Obsidian note.

    Returns dict with: has_frontmatter, tags, links, title.
    """
    has_frontmatter = False
    fm_tags: list[str] = []
    title = ""

    # Parse YAML frontmatter
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            has_frontmatter = True
            try:
                fm = yaml.safe_load(parts[1])
                if isinstance(fm, dict):
                    raw_tags = fm.get("tags", [])
                    if isinstance(raw_tags, list):
                        fm_tags = [str(t).strip() for t in raw_tags if str(t).strip()]
                    elif isinstance(raw_tags, str):
                        # Comma or space separated
                        fm_tags = [t.strip() for t in re.split(r"[,\s]+", raw_tags) if t.strip()]
                    fm_title = fm.get("title", "")
                    if fm_title:
                        title = str(fm_title)
            except yaml.YAMLError:
                pass
            body = parts[2]

    # Extract inline #tags (not inside code blocks or frontmatter)
    inline_tags = re.findall(r"(?:^|\s)#([a-zA-Z][\w/\-]*)", body)

    # Extract [[wikilinks]] — handle [[target|alias]] format
    raw_links = re.findall(r"\[\[([^\]]+)\]\]", body)
    links = []
    for link in raw_links:
        # Strip alias: [[Target|alias]] → Target
        target = link.split("|")[0].strip()
        # Strip heading/block refs: [[Note#heading]] → Note
        target = target.split("#")[0].strip()
        if target and target not in links:
            links.append(target)

    # Title: prefer H1 from body, then frontmatter title, then filename
    h1_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if h1_match:
        title = h1_match.group(1).strip()
    elif not title:
        # Derive from filename
        title = Path(relative_path).stem

    # Combine and deduplicate tags
    all_tags = list(dict.fromkeys(fm_tags + inline_tags))

    return {
        "has_frontmatter": has_frontmatter,
        "tags": all_tags,
        "links": links,
        "title": title,
    }


def _content_hash(content: str) -> str:
    """Compute MD5 hex digest of content."""
    return hashlib.md5(content.encode("utf-8"), usedforsecurity=False).hexdigest()


# ── Formatting ───────────────────────────────────────────────────────────────


def _strip_vault_frontmatter(content: str) -> str:
    """Remove YAML frontmatter from vault content."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].lstrip("\n")
    return content


def _format_note_markdown(note: VaultNote, original_content: str) -> str:
    """Format a vault note as RAG-ingestion markdown.

    Adds RAG frontmatter and strips vault frontmatter from the body.
    """
    tags_str = "[" + ", ".join(note.tags) + "]" if note.tags else "[]"
    links_str = "[" + ", ".join(note.links) + "]" if note.links else "[]"

    body = _strip_vault_frontmatter(original_content)

    return f"""---
platform: obsidian
source_service: obsidian
content_type: vault_note
record_id: {note.relative_path}
vault_folder: {note.folder}
tags: {tags_str}
links: {links_str}
has_frontmatter: {str(note.has_frontmatter).lower()}
---

{body}"""


# ── Vault Scanning ───────────────────────────────────────────────────────────


def _scan_vault(vault_path: Path = VAULT_PATH) -> list[tuple[str, Path]]:
    """Scan vault for includable .md files.

    Returns list of (relative_path, full_path) tuples.
    """
    results: list[tuple[str, Path]] = []
    for full_path in vault_path.rglob("*.md"):
        try:
            rel = str(full_path.relative_to(vault_path))
        except ValueError:
            continue

        if not _should_include(rel):
            continue

        # Skip tiny files (stubs)
        try:
            if full_path.stat().st_size < MIN_FILE_SIZE:
                continue
        except OSError:
            continue

        results.append((rel, full_path))

    return results


# ── Sync Operations ─────────────────────────────────────────────────────────


def _sync_note(
    rel_path: str,
    full_path: Path,
    state: ObsidianSyncState,
    force: bool = False,
) -> bool:
    """Sync a single note. Returns True if written (new or changed)."""
    try:
        content = full_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("Cannot read %s: %s", rel_path, exc)
        return False

    chash = _content_hash(content)
    stat = full_path.stat()

    # Skip if unchanged
    existing = state.notes.get(rel_path)
    if not force and existing and existing.content_hash == chash:
        return False

    # Extract metadata
    meta = _extract_metadata(content, rel_path)

    # Determine folder (innermost known directory)
    parts = Path(rel_path).parts
    folder = parts[0] if len(parts) > 1 else ""
    # Use the most specific directory component
    for part in reversed(parts[:-1]):
        if part in INCLUDE_DIRS:
            folder = part
            break
    if not folder and len(parts) > 1:
        folder = parts[0]

    note = VaultNote(
        relative_path=rel_path,
        title=meta["title"],
        folder=folder,
        content_hash=chash,
        size=stat.st_size,
        mtime=stat.st_mtime,
        has_frontmatter=meta["has_frontmatter"],
        tags=meta["tags"],
        links=meta["links"],
    )

    # Write RAG file
    rag_path = OBSIDIAN_DIR / rel_path
    rag_path.parent.mkdir(parents=True, exist_ok=True)
    formatted = _format_note_markdown(note, content)
    rag_path.write_text(formatted, encoding="utf-8")

    change_type = "updated" if existing else "added"
    _log_change(change_type, rel_path, {"title": meta["title"], "folder": folder})

    state.notes[rel_path] = note
    return True


def _detect_deletions(state: ObsidianSyncState, current_paths: set[str]) -> int:
    """Remove RAG files for notes no longer in the vault. Returns count."""
    deleted = 0
    stale = [p for p in state.notes if p not in current_paths]
    for rel_path in stale:
        rag_path = OBSIDIAN_DIR / rel_path
        if rag_path.exists():
            rag_path.unlink()
            log.debug("Deleted RAG file: %s", rag_path)
        _log_change("deleted", rel_path)
        del state.notes[rel_path]
        deleted += 1
    return deleted


def _full_sync(
    vault_path: Path = VAULT_PATH,
    state: ObsidianSyncState | None = None,
) -> tuple[int, int]:
    """Full vault sync. Returns (written, deleted)."""
    if state is None:
        state = _load_state()

    scanned = _scan_vault(vault_path)
    current_paths = {rel for rel, _ in scanned}

    written = 0
    for rel_path, full_path in scanned:
        if _sync_note(rel_path, full_path, state, force=True):
            written += 1

    deleted = _detect_deletions(state, current_paths)

    state.last_sync = time.time()
    state.stats = {
        "total_notes": len(state.notes),
        "written": written,
        "deleted": deleted,
    }

    return written, deleted


def _incremental_sync(
    vault_path: Path = VAULT_PATH,
    state: ObsidianSyncState | None = None,
) -> tuple[int, int]:
    """Incremental sync — only changed files. Returns (written, deleted)."""
    if state is None:
        state = _load_state()

    scanned = _scan_vault(vault_path)
    current_paths = {rel for rel, _ in scanned}

    written = 0
    for rel_path, full_path in scanned:
        if _sync_note(rel_path, full_path, state, force=False):
            written += 1

    deleted = _detect_deletions(state, current_paths)

    state.last_sync = time.time()
    state.stats = {
        "total_notes": len(state.notes),
        "written": written,
        "deleted": deleted,
    }

    return written, deleted


# ── Behavioral Logging ───────────────────────────────────────────────────────


def _log_change(change_type: str, name: str, extra: dict | None = None) -> None:
    """Append behavioral change event to JSONL log."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    entry: dict = {
        "service": "obsidian",
        "change_type": change_type,
        "name": name,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if extra:
        entry.update(extra)
    with open(CHANGES_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    log.debug("Logged change: %s — %s", change_type, name)


# ── Profiler Integration ────────────────────────────────────────────────────


def _generate_profile_facts(state: ObsidianSyncState) -> list[dict]:
    """Generate deterministic profile facts from vault state."""
    from collections import Counter

    facts: list[dict] = []
    source = "obsidian-sync:obsidian-profile-facts"

    if not state.notes:
        return facts

    # Active areas — folder distribution
    folder_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()

    for note in state.notes.values():
        if note.folder:
            folder_counts[note.folder] += 1
        for tag in note.tags:
            tag_counts[tag.lower()] += 1

    if folder_counts:
        top_folders = ", ".join(
            f"{folder} ({count})" for folder, count in folder_counts.most_common(10)
        )
        facts.append(
            {
                "dimension": "information_seeking",
                "key": "obsidian_active_areas",
                "value": top_folders,
                "confidence": 0.90,
                "source": source,
                "evidence": f"Folder distribution across {len(state.notes)} vault notes",
            }
        )

    # Note volume
    total = len(state.notes)
    total_size = sum(n.size for n in state.notes.values())
    facts.append(
        {
            "dimension": "information_seeking",
            "key": "obsidian_note_volume",
            "value": f"{total} notes, {total_size / 1024:.0f} KB total",
            "confidence": 0.95,
            "source": source,
            "evidence": f"Computed from {total} synced vault notes",
        }
    )

    # Frequent tags
    if tag_counts:
        top_tags = ", ".join(f"{tag} ({count})" for tag, count in tag_counts.most_common(15))
        facts.append(
            {
                "dimension": "information_seeking",
                "key": "obsidian_frequent_tags",
                "value": top_tags,
                "confidence": 0.85,
                "source": source,
                "evidence": f"Tag frequency across {total} vault notes",
            }
        )

    return facts


def _write_profile_facts(state: ObsidianSyncState) -> None:
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


def _print_stats(state: ObsidianSyncState) -> None:
    """Print sync statistics."""
    from collections import Counter

    total = len(state.notes)
    total_size = sum(n.size for n in state.notes.values())

    folder_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    fm_count = 0

    for note in state.notes.values():
        if note.folder:
            folder_counts[note.folder] += 1
        for tag in note.tags:
            tag_counts[tag.lower()] += 1
        if note.has_frontmatter:
            fm_count += 1

    print("Obsidian Vault Sync State")
    print("=" * 40)
    print(f"Total notes:     {total:,}")
    print(f"Total size:      {total_size / 1024:.0f} KB")
    print(f"With frontmatter: {fm_count:,}")
    print(
        f"Last sync:       {datetime.fromtimestamp(state.last_sync, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}"
    )

    if folder_counts:
        print("\nFolders:")
        for folder, count in folder_counts.most_common(15):
            print(f"  {folder}: {count}")

    if tag_counts:
        print("\nTop tags:")
        for tag, count in tag_counts.most_common(15):
            print(f"  #{tag}: {count}")


# ── Orchestration ────────────────────────────────────────────────────────────


def run_full_sync() -> None:
    """Full vault sync."""
    from shared.notify import send_notification

    state = _load_state()
    written, deleted = _full_sync(state=state)
    _save_state(state)
    _write_profile_facts(state)

    msg = f"Obsidian sync: {len(state.notes)} notes, {written} written, {deleted} deleted"
    log.info(msg)
    send_notification("Obsidian Sync", msg, tags=["obsidian"])


def run_auto() -> None:
    """Incremental vault sync — only changed files."""
    from shared.notify import send_notification

    state = _load_state()

    if not state.notes:
        log.info("No prior state — running full sync")
        run_full_sync()
        return

    written, deleted = _incremental_sync(state=state)
    _save_state(state)
    _write_profile_facts(state)

    if written or deleted:
        msg = f"Obsidian sync: {written} written, {deleted} deleted ({len(state.notes)} total)"
        log.info(msg)
        send_notification("Obsidian Sync", msg, tags=["obsidian"])
    else:
        log.info("No vault changes")


def run_stats() -> None:
    """Display sync statistics."""
    state = _load_state()
    if not state.notes:
        print("No sync state found. Run --full-sync first.")
        return
    _print_stats(state)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Obsidian vault RAG sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full-sync", action="store_true", help="Full vault sync")
    group.add_argument("--auto", action="store_true", help="Incremental sync")
    group.add_argument("--stats", action="store_true", help="Show sync statistics")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="obsidian-sync", level="DEBUG" if args.verbose else None)

    action = "full_sync" if args.full_sync else "auto" if args.auto else "stats"
    with _tracer.start_as_current_span(
        f"obsidian_sync.{action}",
        attributes={"agent.name": "obsidian_sync", "agent.repo": "hapax-council"},
    ):
        if args.full_sync:
            run_full_sync()
        elif args.auto:
            run_auto()
        elif args.stats:
            run_stats()


if __name__ == "__main__":
    main()

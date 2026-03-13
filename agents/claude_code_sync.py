"""Claude Code transcript sync — JSONL transcript parsing for RAG.

Scans ~/.claude/projects/ for JSONL transcript files, extracts user and
assistant text messages, writes per-session markdown to rag-sources/claude-code/.

Usage:
    uv run python -m agents.claude_code_sync --full-sync    # Full sync
    uv run python -m agents.claude_code_sync --auto         # Incremental sync
    uv run python -m agents.claude_code_sync --stats        # Show sync state
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
CACHE_DIR = Path.home() / ".cache" / "claude-code-sync"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "claude-code-profile-facts.jsonl"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"
RAG_SOURCES = Path.home() / "documents" / "rag-sources"
CLAUDE_CODE_DIR = RAG_SOURCES / "claude-code"

ACTIVE_SESSION_SECONDS = 600  # Re-process sessions active within this window


# ── Schemas ──────────────────────────────────────────────────────────────────


class TranscriptMetadata(BaseModel):
    """Metadata for a single transcript JSONL file."""

    session_id: str = ""
    project_path: str = ""
    project_name: str = ""
    message_count: int = 0
    first_message_at: str = ""
    last_message_at: str = ""
    file_size: int = 0
    file_mtime: float = 0.0


class ClaudeCodeSyncState(BaseModel):
    """Persistent sync state."""

    sessions: dict[str, TranscriptMetadata] = Field(default_factory=dict)
    last_sync: float = 0.0
    stats: dict[str, int] = Field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _decode_project_dir(dirname: str) -> str:
    """Decode a Claude Code project directory name to a filesystem path.

    Claude encodes paths by replacing '/' with '-' and stripping the leading '/'.
    Example: '-home-user-projects-ai-agents' → '/home/user/projects/hapax-council'

    Since '-' is ambiguous (could be path separator or literal dash in component),
    we use greedy filesystem probing: try replacing dashes left-to-right, preferring
    the longest existing path prefix that matches real directories.
    """
    if not dirname.startswith("-"):
        return dirname

    # Split on dashes, skipping the leading empty segment from the first dash
    parts = dirname[1:].split("-")
    # parts for '-home-user-projects-ai-agents' = ['home', 'user', 'projects', 'ai', 'agents']

    # Greedy left-to-right: try to build the path by checking filesystem
    # At each step, try consuming the next part as a new path component first,
    # then fall back to appending it with a dash to the current component.
    result_parts: list[str] = [parts[0]]

    for part in parts[1:]:
        # Option 1: this part is a new path component (the dash was a /)
        candidate_new = "/" + "/".join(result_parts) + "/" + part
        # Option 2: this part continues the previous component (literal dash)
        candidate_joined = "/" + "/".join(result_parts[:-1] + [result_parts[-1] + "-" + part])

        # Prefer the path where a directory actually exists
        if Path(candidate_joined).exists() and not Path(candidate_new).exists():
            result_parts[-1] = result_parts[-1] + "-" + part
        else:
            # Default: treat as new path component (dash = /)
            result_parts.append(part)

    return "/" + "/".join(result_parts)


def _load_state(path: Path = STATE_FILE) -> ClaudeCodeSyncState:
    """Load sync state from disk."""
    if path.exists():
        try:
            return ClaudeCodeSyncState.model_validate_json(path.read_text())
        except Exception as exc:
            log.warning("Corrupt state file, starting fresh: %s", exc)
    return ClaudeCodeSyncState()


def _save_state(state: ClaudeCodeSyncState, path: Path = STATE_FILE) -> None:
    """Persist sync state to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    tmp.rename(path)


# ── Behavioral Logging ──────────────────────────────────────────────────────


def _log_change(change_type: str, name: str, extra: dict | None = None) -> None:
    """Append behavioral change event to JSONL log."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    entry: dict = {
        "change_type": change_type,
        "name": name,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if extra:
        entry.update(extra)
    with open(CHANGES_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    log.debug("Logged change: %s — %s", change_type, name)


# ── Transcript Parsing ──────────────────────────────────────────────────────


def _parse_transcript(path: Path) -> list[tuple[str, str, str]]:
    """Parse a JSONL transcript file, extracting user and assistant text.

    Returns a list of (role, text, timestamp) tuples. Only includes:
    - type="user" entries with string content
    - type="assistant" entries, extracting only text blocks (skips tool_use, thinking)
    """
    messages: list[tuple[str, str, str]] = []

    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type", "")
                timestamp = entry.get("timestamp", "")

                if entry_type == "user":
                    msg = entry.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, str) and content.strip():
                        messages.append(("user", content.strip(), timestamp))
                    elif isinstance(content, list):
                        # User messages can also have list content
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                        combined = "\n".join(t for t in text_parts if t)
                        if combined.strip():
                            messages.append(("user", combined.strip(), timestamp))

                elif entry_type == "assistant":
                    msg = entry.get("message", {})
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                        combined = "\n".join(t for t in text_parts if t)
                        if combined.strip():
                            messages.append(("assistant", combined.strip(), timestamp))
                    elif isinstance(content, str) and content.strip():
                        messages.append(("assistant", content.strip(), timestamp))

    except (OSError, UnicodeDecodeError) as exc:
        log.warning("Failed to read transcript %s: %s", path, exc)

    return messages


# ── Formatting ──────────────────────────────────────────────────────────────


def _format_session_markdown(meta: TranscriptMetadata, messages: list[tuple[str, str, str]]) -> str:
    """Format a transcript session as markdown with YAML frontmatter."""
    lines = [
        "---",
        "platform: claude",
        "source_service: claude-code",
        f"project: {meta.project_name}",
        f"project_path: {meta.project_path}",
        f"session_id: {meta.session_id}",
        f"message_count: {meta.message_count}",
        f"first_message_at: {meta.first_message_at}",
        f"last_message_at: {meta.last_message_at}",
        "modality_tags: [conversation, development]",
        "---",
        "",
        f"# Claude Code Session — {meta.project_name}",
        "",
    ]

    for role, text, timestamp in messages:
        ts_display = ""
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                ts_display = f" ({dt.strftime('%H:%M')})"
            except (ValueError, TypeError):
                pass

        if role == "user":
            lines.append(f"## User{ts_display}")
        else:
            lines.append(f"## Assistant{ts_display}")
        lines.append("")
        lines.append(text)
        lines.append("")

    return "\n".join(lines)


# ── Discovery ───────────────────────────────────────────────────────────────


def _discover_projects(base_dir: Path = CLAUDE_PROJECTS_DIR) -> list[tuple[str, str, list[Path]]]:
    """Auto-discover all Claude Code project directories with JSONL files.

    Returns list of (project_name, project_path, [jsonl_files]).
    """
    projects: list[tuple[str, str, list[Path]]] = []

    if not base_dir.is_dir():
        log.warning("Claude projects directory not found: %s", base_dir)
        return projects

    for project_dir in sorted(base_dir.iterdir()):
        if not project_dir.is_dir():
            continue

        jsonl_files = sorted(project_dir.glob("*.jsonl"))
        if not jsonl_files:
            continue

        dirname = project_dir.name
        project_path = _decode_project_dir(dirname)
        # Derive a short project name from the last path component
        project_name = (
            project_path.rstrip("/").rsplit("/", 1)[-1] if "/" in project_path else dirname
        )

        projects.append((project_name, project_path, jsonl_files))

    return projects


# ── Sync Logic ──────────────────────────────────────────────────────────────


def _sync_transcript(
    path: Path,
    project_name: str,
    project_path: str,
    state: ClaudeCodeSyncState,
    force: bool = False,
) -> bool:
    """Sync a single transcript file. Returns True if file was processed.

    Uses mtime + size for change detection. Re-processes files that are
    still active (modified within ACTIVE_SESSION_SECONDS).
    """
    try:
        stat = path.stat()
    except OSError:
        return False

    file_key = str(path)
    existing = state.sessions.get(file_key)

    # Check if file needs processing
    if not force and existing:
        size_match = existing.file_size == stat.st_size
        mtime_match = existing.file_mtime == stat.st_mtime
        recently_active = (time.time() - stat.st_mtime) < ACTIVE_SESSION_SECONDS

        if size_match and mtime_match and not recently_active:
            return False

    # Parse transcript
    messages = _parse_transcript(path)
    if not messages:
        return False

    # Extract session ID from filename (stem is typically the session UUID)
    session_id = path.stem

    # Build timestamps
    timestamps = [ts for _, _, ts in messages if ts]
    first_ts = min(timestamps) if timestamps else ""
    last_ts = max(timestamps) if timestamps else ""

    meta = TranscriptMetadata(
        session_id=session_id,
        project_path=project_path,
        project_name=project_name,
        message_count=len(messages),
        first_message_at=first_ts,
        last_message_at=last_ts,
        file_size=stat.st_size,
        file_mtime=stat.st_mtime,
    )

    # Write markdown
    md = _format_session_markdown(meta, messages)
    out_dir = CLAUDE_CODE_DIR / project_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{session_id}.md"
    out_path.write_text(md, encoding="utf-8")

    # Update state
    is_new = file_key not in state.sessions
    state.sessions[file_key] = meta

    change_type = "new_session" if is_new else "updated_session"
    _log_change(
        change_type,
        f"{project_name}/{session_id}",
        {
            "messages": len(messages),
            "project": project_name,
        },
    )

    log.debug("Synced %s/%s (%d messages)", project_name, session_id, len(messages))
    return True


def _full_sync(state: ClaudeCodeSyncState) -> dict[str, int]:
    """Full sync of all transcript files."""
    projects = _discover_projects()
    total_files = 0
    processed = 0
    total_messages = 0

    for project_name, project_path, jsonl_files in projects:
        for path in jsonl_files:
            total_files += 1
            if _sync_transcript(path, project_name, project_path, state, force=True):
                processed += 1
                meta = state.sessions.get(str(path))
                if meta:
                    total_messages += meta.message_count

    state.last_sync = time.time()
    state.stats = {
        "projects": len(projects),
        "total_files": total_files,
        "processed": processed,
        "total_messages": total_messages,
        "total_sessions": len(state.sessions),
    }

    return {
        "projects": len(projects),
        "files": total_files,
        "processed": processed,
        "messages": total_messages,
    }


def _incremental_sync(state: ClaudeCodeSyncState) -> dict[str, int]:
    """Incremental sync — only process changed or active files."""
    projects = _discover_projects()
    total_files = 0
    processed = 0
    total_messages = 0

    for project_name, project_path, jsonl_files in projects:
        for path in jsonl_files:
            total_files += 1
            if _sync_transcript(path, project_name, project_path, state, force=False):
                processed += 1
                meta = state.sessions.get(str(path))
                if meta:
                    total_messages += meta.message_count

    state.last_sync = time.time()
    state.stats = {
        "projects": len(projects),
        "total_files": total_files,
        "processed": processed,
        "total_messages": total_messages,
        "total_sessions": len(state.sessions),
    }

    return {
        "projects": len(projects),
        "files": total_files,
        "processed": processed,
        "messages": total_messages,
    }


# ── Profiler Integration ─────────────────────────────────────────────────────


def _generate_profile_facts(state: ClaudeCodeSyncState) -> list[dict]:
    """Generate deterministic profile facts from Claude Code state."""
    from collections import Counter

    facts: list[dict] = []
    source = "claude-code-sync:claude-code-profile-facts"

    if not state.sessions:
        return facts

    # Collect project activity
    project_counts: Counter[str] = Counter()
    total_messages = 0

    for meta in state.sessions.values():
        project_counts[meta.project_name] += 1
        total_messages += meta.message_count

    # claude_code_projects fact
    if project_counts:
        top_projects = ", ".join(
            f"{name} ({count} sessions)" for name, count in project_counts.most_common(10)
        )
        facts.append(
            {
                "dimension": "tool_usage",
                "key": "claude_code_projects",
                "value": top_projects,
                "confidence": 0.95,
                "source": source,
                "evidence": f"Top projects across {len(state.sessions)} sessions",
            }
        )

    # claude_code_activity fact
    facts.append(
        {
            "dimension": "tool_usage",
            "key": "claude_code_activity",
            "value": f"{len(state.sessions)} sessions, {total_messages} messages across {len(project_counts)} projects",
            "confidence": 0.95,
            "source": source,
            "evidence": f"Aggregated from {len(state.sessions)} transcript files",
        }
    )

    return facts


def _write_profile_facts(state: ClaudeCodeSyncState) -> None:
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


def _print_stats(state: ClaudeCodeSyncState) -> None:
    """Print sync statistics."""
    from collections import Counter

    project_counts: Counter[str] = Counter()
    total_messages = 0

    for meta in state.sessions.values():
        project_counts[meta.project_name] += 1
        total_messages += meta.message_count

    print("Claude Code Sync State")
    print("=" * 40)
    print(f"Total sessions:  {len(state.sessions):,}")
    print(f"Total messages:  {total_messages:,}")
    print(f"Projects:        {len(project_counts):,}")
    print(
        f"Last sync:       {datetime.fromtimestamp(state.last_sync, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}"
    )

    if project_counts:
        print("\nTop projects:")
        for name, count in project_counts.most_common(15):
            print(f"  {name}: {count} sessions")


# ── Orchestration ────────────────────────────────────────────────────────────


def run_full_sync() -> None:
    """Full sync of all Claude Code transcripts."""
    from shared.notify import send_notification

    state = _load_state()
    summary = _full_sync(state)
    _save_state(state)
    _write_profile_facts(state)

    msg = (
        f"Claude Code sync: {summary['projects']} projects, "
        f"{summary['processed']}/{summary['files']} files, "
        f"{summary['messages']} messages"
    )
    log.info(msg)
    send_notification("Claude Code Sync", msg, tags=["robot"])


def run_auto() -> None:
    """Incremental sync of changed/active transcripts."""
    from shared.notify import send_notification

    state = _load_state()
    summary = _incremental_sync(state)
    _save_state(state)
    _write_profile_facts(state)

    if summary["processed"] > 0:
        msg = (
            f"Claude Code sync: {summary['processed']} files updated, "
            f"{summary['messages']} messages"
        )
        log.info(msg)
        send_notification("Claude Code Sync", msg, tags=["robot"])
    else:
        log.info("No Claude Code transcript changes")


def run_stats() -> None:
    """Display sync statistics."""
    state = _load_state()
    if not state.sessions:
        print("No sync state found. Run --full-sync first.")
        return
    _print_stats(state)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code transcript RAG sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full-sync", action="store_true", help="Full transcript sync")
    group.add_argument("--auto", action="store_true", help="Incremental sync")
    group.add_argument("--stats", action="store_true", help="Show sync statistics")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="claude-code-sync", level="DEBUG" if args.verbose else None)

    action = "full_sync" if args.full_sync else "auto" if args.auto else "stats"
    with _tracer.start_as_current_span(
        f"claude_code_sync.{action}",
        attributes={"agent.name": "claude_code_sync", "agent.repo": "hapax-council"},
    ):
        if args.full_sync:
            run_full_sync()
        elif args.auto:
            run_auto()
        elif args.stats:
            run_stats()


if __name__ == "__main__":
    main()

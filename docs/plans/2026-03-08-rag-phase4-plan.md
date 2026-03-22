# RAG Phase 4 — Claude Code, Obsidian, Chrome Sync Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add three new RAG sync agents — Claude Code transcripts, Obsidian vault notes, Chrome browsing history + bookmarks — with profiler bridges, agent integrations, systemd timers, and documentation.

**Architecture:** Each agent follows the established pattern from Phases 1-3: Pydantic schemas, state tracking, markdown output with YAML frontmatter, profiler bridge (JSONL facts), behavioral logging, CLI with `--full-sync`/`--auto`/`--stats`, and systemd user timer. All work in `~/projects/ai-agents/`.

**Tech Stack:** Python 3, Pydantic v2, pathlib, sqlite3 (Chrome), hashlib (Obsidian), systemd user timers

**Design doc:** `docs/plans/2026-03-08-rag-phase4-design.md` (in distro-work repo)

---

## Task 1: Claude Code Sync — Skeleton + Schemas

**Files:**
- Create: `~/projects/ai-agents/agents/claude_code_sync.py`
- Create: `~/projects/ai-agents/tests/test_claude_code_sync.py`

**Step 1: Write failing tests**

Create `~/projects/ai-agents/tests/test_claude_code_sync.py`:

```python
"""Tests for claude_code_sync — schemas, parsing, formatting, profiler facts."""
from __future__ import annotations


def test_transcript_metadata_defaults():
    from agents.claude_code_sync import TranscriptMetadata
    t = TranscriptMetadata(
        session_id="abc-123",
        project_path="/home/user/projects/test",
        project_name="test",
        message_count=10,
        first_message_at="2026-03-08T10:00:00Z",
        last_message_at="2026-03-08T11:00:00Z",
        file_size=1024,
        file_mtime=1741400000.0,
    )
    assert t.session_id == "abc-123"
    assert t.project_name == "test"


def test_sync_state_empty():
    from agents.claude_code_sync import ClaudeCodeSyncState
    s = ClaudeCodeSyncState()
    assert s.sessions == {}
    assert s.last_sync == 0.0


def test_decode_project_dir():
    from agents.claude_code_sync import _decode_project_dir
    assert _decode_project_dir("-home-hapaxlegomenon-projects-ai-agents") == "/home/hapaxlegomenon/projects/ai-agents"
    assert _decode_project_dir("-home-hapaxlegomenon-projects-distro-work") == "/home/hapaxlegomenon/projects/distro-work"
```

**Step 2: Run tests to verify failure**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_claude_code_sync.py -v
```

Expected: FAIL (module not found).

**Step 3: Create claude_code_sync.py skeleton**

```python
"""Claude Code transcript sync — session conversations to RAG pipeline.

Scans ~/.claude/projects/ for JSONL transcript files, extracts user+assistant
messages, writes per-session markdown to rag-sources/claude-code/.
Auto-discovers new project directories on each run.

Usage:
    uv run python -m agents.claude_code_sync --full-sync   # Process all transcripts
    uv run python -m agents.claude_code_sync --auto         # Incremental (new/changed)
    uv run python -m agents.claude_code_sync --stats        # Show sync state
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
CACHE_DIR = Path.home() / ".cache" / "claude-code-sync"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "claude-code-profile-facts.jsonl"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"
RAG_SOURCES = Path.home() / "documents" / "rag-sources"
CLAUDE_CODE_DIR = RAG_SOURCES / "claude-code"

# Sessions with mtime within this window are considered "active" and re-processed
ACTIVE_SESSION_SECONDS = 600  # 10 minutes


# ── Schemas ──────────────────────────────────────────────────────────────────

class TranscriptMetadata(BaseModel):
    """Metadata for a Claude Code session transcript."""
    session_id: str
    project_path: str
    project_name: str
    message_count: int
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
    """Decode Claude Code project directory name to filesystem path.

    Claude Code encodes paths by replacing '/' with '-', e.g.:
    '-home-hapaxlegomenon-projects-ai-agents' -> '/home/hapaxlegomenon/projects/ai-agents'
    """
    # The dirname starts with '-' which represents the leading '/'
    # Each subsequent '-' is a '/' separator
    # But we need to handle multi-word directory names — Claude Code
    # only encodes the path separators, not hyphens in names.
    # The encoding is: strip leading '-', split on '-', rejoin with '/'.
    # This works because the actual paths don't contain hyphens at the
    # relevant levels (home, username, projects, repo-name).
    if dirname.startswith("-"):
        dirname = dirname[1:]
    return "/" + dirname.replace("-", "/")
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_claude_code_sync.py -v
```

Expected: 3 PASS.

**Step 5: Commit**

```bash
git add agents/claude_code_sync.py tests/test_claude_code_sync.py
git commit -m "feat(claude-code): skeleton module with schemas and constants"
```

---

## Task 2: Claude Code Sync — Transcript Parsing + Markdown Formatting

**Files:**
- Modify: `~/projects/ai-agents/agents/claude_code_sync.py`
- Modify: `~/projects/ai-agents/tests/test_claude_code_sync.py`

**Step 1: Write failing tests**

Add to `tests/test_claude_code_sync.py`:

```python
def test_parse_transcript_messages():
    import json, tempfile
    from pathlib import Path
    from agents.claude_code_sync import _parse_transcript

    # Create a minimal JSONL transcript
    lines = [
        json.dumps({"type": "user", "message": {"role": "user", "content": "Hello"}, "timestamp": "2026-03-08T10:00:00Z", "sessionId": "sess-1"}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Hi there!"}]}, "timestamp": "2026-03-08T10:00:05Z", "sessionId": "sess-1"}),
        json.dumps({"type": "progress", "data": "some progress"}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Read", "input": {}}]}, "timestamp": "2026-03-08T10:00:10Z", "sessionId": "sess-1"}),
        json.dumps({"type": "user", "message": {"role": "user", "content": "Thanks"}, "timestamp": "2026-03-08T10:00:20Z", "sessionId": "sess-1"}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "You're welcome!"}]}, "timestamp": "2026-03-08T10:00:25Z", "sessionId": "sess-1"}),
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write("\n".join(lines))
        tmp = Path(f.name)
    try:
        messages = _parse_transcript(tmp)
        assert len(messages) == 4  # 2 user + 2 assistant with text (skip tool-only)
        assert messages[0] == ("user", "Hello", "2026-03-08T10:00:00Z")
        assert messages[1] == ("assistant", "Hi there!", "2026-03-08T10:00:05Z")
        assert messages[2] == ("user", "Thanks", "2026-03-08T10:00:20Z")
        assert messages[3] == ("assistant", "You're welcome!", "2026-03-08T10:00:25Z")
    finally:
        tmp.unlink()


def test_format_session_markdown():
    from agents.claude_code_sync import _format_session_markdown, TranscriptMetadata
    meta = TranscriptMetadata(
        session_id="abc-123",
        project_path="/home/user/projects/test",
        project_name="test",
        message_count=2,
        first_message_at="2026-03-08T10:00:00Z",
        last_message_at="2026-03-08T10:00:05Z",
        file_size=500,
        file_mtime=1741400000.0,
    )
    messages = [
        ("user", "What does this function do?", "2026-03-08T10:00:00Z"),
        ("assistant", "It calculates the sum.", "2026-03-08T10:00:05Z"),
    ]
    md = _format_session_markdown(meta, messages)
    assert "platform: claude" in md
    assert "source_service: claude-code" in md
    assert "project: test" in md
    assert "session_id: abc-123" in md
    assert "## User" in md
    assert "What does this function do?" in md
    assert "It calculates the sum." in md
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_claude_code_sync.py -v -k "parse or format"
```

**Step 3: Implement parsing and formatting**

Add to `agents/claude_code_sync.py`:

```python
# ── State Management ─────────────────────────────────────────────────────────

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


# ── Transcript Parsing ───────────────────────────────────────────────────────

def _parse_transcript(path: Path) -> list[tuple[str, str, str]]:
    """Parse a JSONL transcript, extracting user+assistant text messages.

    Returns list of (role, text, timestamp) tuples.
    Skips: tool_use-only assistant messages, progress, file-history-snapshot,
    system, queue-operation, last-prompt entries.
    """
    messages: list[tuple[str, str, str]] = []

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = obj.get("type")
            timestamp = obj.get("timestamp", "")
            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue

            if msg_type == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    messages.append(("user", content.strip(), timestamp))
                elif isinstance(content, list):
                    # User messages can also have content blocks
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block["text"])
                        elif isinstance(block, str):
                            text_parts.append(block)
                    if text_parts:
                        messages.append(("user", "\n".join(text_parts).strip(), timestamp))

            elif msg_type == "assistant":
                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text:
                            text_parts.append(text)
                # Skip assistant messages that only contain tool_use or thinking
                if text_parts:
                    messages.append(("assistant", "\n\n".join(text_parts), timestamp))

    return messages


# ── Markdown Formatting ──────────────────────────────────────────────────────

def _format_session_markdown(
    meta: TranscriptMetadata,
    messages: list[tuple[str, str, str]],
) -> str:
    """Generate markdown for a session with YAML frontmatter."""
    # Parse date for display
    try:
        dt = datetime.fromisoformat(meta.first_message_at.replace("Z", "+00:00"))
        date_display = dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        date_display = meta.first_message_at[:10] if meta.first_message_at else "unknown"

    lines = [
        "---",
        "platform: claude",
        "service: claude-code",
        "content_type: conversation",
        "source_service: claude-code",
        f"project: {meta.project_name}",
        f"project_path: {meta.project_path}",
        f"session_id: {meta.session_id}",
        f"timestamp: {meta.first_message_at}",
        f"message_count: {meta.message_count}",
        "---",
        "",
        f"# Claude Code Session: {meta.project_name} ({date_display})",
        "",
    ]

    for role, text, ts in messages:
        # Extract just the time portion for display
        time_str = ""
        if ts:
            try:
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                time_str = f" ({t.strftime('%H:%M:%S')})"
            except (ValueError, TypeError):
                pass
        role_display = "User" if role == "user" else "Assistant"
        lines.append(f"## {role_display}{time_str}")
        lines.append("")
        lines.append(text)
        lines.append("")

    return "\n".join(lines)
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_claude_code_sync.py -v
```

Expected: 5 PASS.

**Step 5: Commit**

```bash
git add agents/claude_code_sync.py tests/test_claude_code_sync.py
git commit -m "feat(claude-code): transcript parsing and markdown formatting"
```

---

## Task 3: Claude Code Sync — Discovery, Sync Logic, Profiler, CLI

**Files:**
- Modify: `~/projects/ai-agents/agents/claude_code_sync.py`
- Modify: `~/projects/ai-agents/tests/test_claude_code_sync.py`

**Step 1: Write failing tests**

Add to `tests/test_claude_code_sync.py`:

```python
def test_discover_projects():
    import tempfile
    from pathlib import Path
    from agents.claude_code_sync import _discover_projects

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        # Create fake project dirs with JSONL files
        p1 = base / "-home-user-projects-alpha"
        p1.mkdir()
        (p1 / "session1.jsonl").write_text("{}")
        (p1 / "session2.jsonl").write_text("{}")
        p2 = base / "-home-user-projects-beta"
        p2.mkdir()
        (p2 / "session3.jsonl").write_text("{}")
        # Dir with no jsonl files — should be skipped
        p3 = base / "-home-user-projects-empty"
        p3.mkdir()

        projects = _discover_projects(base)
        assert len(projects) == 2
        assert any(p[0] == "alpha" for p in projects)
        assert any(p[0] == "beta" for p in projects)
        # Check file counts
        alpha = [p for p in projects if p[0] == "alpha"][0]
        assert len(alpha[2]) == 2  # 2 jsonl files


def test_generate_profile_facts():
    from agents.claude_code_sync import _generate_profile_facts, ClaudeCodeSyncState, TranscriptMetadata
    state = ClaudeCodeSyncState()
    state.sessions = {
        "s1": TranscriptMetadata(
            session_id="s1", project_path="/p/ai-agents", project_name="ai-agents",
            message_count=20, first_message_at="2026-03-08T10:00:00Z",
            last_message_at="2026-03-08T11:00:00Z", file_size=5000, file_mtime=0),
        "s2": TranscriptMetadata(
            session_id="s2", project_path="/p/ai-agents", project_name="ai-agents",
            message_count=10, first_message_at="2026-03-07T10:00:00Z",
            last_message_at="2026-03-07T10:30:00Z", file_size=3000, file_mtime=0),
        "s3": TranscriptMetadata(
            session_id="s3", project_path="/p/distro-work", project_name="distro-work",
            message_count=5, first_message_at="2026-03-06T10:00:00Z",
            last_message_at="2026-03-06T10:15:00Z", file_size=1000, file_mtime=0),
    }
    facts = _generate_profile_facts(state)
    assert len(facts) > 0
    dims = {f["dimension"] for f in facts}
    assert "workflow" in dims
    assert all(f["confidence"] == 0.95 for f in facts)
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_claude_code_sync.py -v -k "discover or profile"
```

**Step 3: Implement discovery, sync, profiler, and CLI**

Add to `agents/claude_code_sync.py`:

```python
# ── Project Discovery ────────────────────────────────────────────────────────

def _discover_projects(
    base_dir: Path = CLAUDE_PROJECTS_DIR,
) -> list[tuple[str, str, list[Path]]]:
    """Discover all Claude Code project directories and their transcripts.

    Returns list of (project_name, project_path, [jsonl_files]).
    Skips directories with no .jsonl files.
    """
    if not base_dir.exists():
        return []

    projects = []
    for d in sorted(base_dir.iterdir()):
        if not d.is_dir():
            continue
        jsonl_files = sorted(d.glob("*.jsonl"))
        if not jsonl_files:
            continue
        project_path = _decode_project_dir(d.name)
        project_name = project_path.rstrip("/").rsplit("/", 1)[-1]
        projects.append((project_name, project_path, jsonl_files))

    return projects


# ── File Writing ─────────────────────────────────────────────────────────────

def _write_session_file(
    meta: TranscriptMetadata,
    messages: list[tuple[str, str, str]],
) -> Path | None:
    """Write a session markdown file to rag-sources/claude-code/."""
    if not messages:
        return None

    project_dir = CLAUDE_CODE_DIR / meta.project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    out_path = project_dir / f"{meta.session_id}.md"
    md = _format_session_markdown(meta, messages)
    out_path.write_text(md, encoding="utf-8")
    return out_path


# ── Sync Logic ───────────────────────────────────────────────────────────────

def _sync_transcript(
    jsonl_path: Path,
    project_name: str,
    project_path: str,
    state: ClaudeCodeSyncState,
    force: bool = False,
) -> bool:
    """Process a single transcript file. Returns True if written/updated."""
    session_id = jsonl_path.stem
    stat = jsonl_path.stat()
    file_size = stat.st_size
    file_mtime = stat.st_mtime

    # Check if already processed and unchanged
    if not force and session_id in state.sessions:
        existing = state.sessions[session_id]
        is_active = (time.time() - file_mtime) < ACTIVE_SESSION_SECONDS
        if existing.file_size == file_size and existing.file_mtime == file_mtime and not is_active:
            return False

    # Parse and write
    messages = _parse_transcript(jsonl_path)
    if not messages:
        return False

    # Extract timestamps
    timestamps = [ts for _, _, ts in messages if ts]
    first_ts = timestamps[0] if timestamps else ""
    last_ts = timestamps[-1] if timestamps else ""

    meta = TranscriptMetadata(
        session_id=session_id,
        project_path=project_path,
        project_name=project_name,
        message_count=len(messages),
        first_message_at=first_ts,
        last_message_at=last_ts,
        file_size=file_size,
        file_mtime=file_mtime,
    )

    written = _write_session_file(meta, messages)
    if written:
        state.sessions[session_id] = meta
        return True
    return False


def _full_sync(state: ClaudeCodeSyncState) -> int:
    """Process all transcripts from all discovered projects."""
    projects = _discover_projects()
    total = 0
    for project_name, project_path, jsonl_files in projects:
        log.info("Scanning %s (%d transcripts)", project_name, len(jsonl_files))
        for jsonl_path in jsonl_files:
            try:
                if _sync_transcript(jsonl_path, project_name, project_path, state, force=True):
                    total += 1
            except Exception as exc:
                log.warning("Failed to process %s: %s", jsonl_path.name, exc)
    state.last_sync = time.time()
    state.stats["total_sessions"] = len(state.sessions)
    state.stats["total_projects"] = len({s.project_name for s in state.sessions.values()})
    return total


def _incremental_sync(state: ClaudeCodeSyncState) -> int:
    """Process only new or changed transcripts."""
    projects = _discover_projects()
    total = 0
    for project_name, project_path, jsonl_files in projects:
        for jsonl_path in jsonl_files:
            try:
                if _sync_transcript(jsonl_path, project_name, project_path, state):
                    total += 1
            except Exception as exc:
                log.warning("Failed to process %s: %s", jsonl_path.name, exc)
    state.last_sync = time.time()
    state.stats["total_sessions"] = len(state.sessions)
    state.stats["total_projects"] = len({s.project_name for s in state.sessions.values()})
    return total


# ── Behavioral Logging ───────────────────────────────────────────────────────

def _log_change(change_type: str, session_id: str, extra: dict | None = None) -> None:
    """Append change to JSONL log."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "service": "claude-code",
        "event_type": change_type,
        "record_id": session_id,
        "context": extra or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(CHANGES_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# ── Profiler Integration ─────────────────────────────────────────────────────

def _generate_profile_facts(state: ClaudeCodeSyncState) -> list[dict]:
    """Generate profile facts from Claude Code session state."""
    from collections import Counter

    facts = []
    source = "claude-code-sync:claude-code-profile-facts"
    sessions = list(state.sessions.values())

    if not sessions:
        return facts

    # Project frequency
    project_counts: Counter[str] = Counter()
    total_messages = 0
    for s in sessions:
        project_counts[s.project_name] += 1
        total_messages += s.message_count

    top_projects = ", ".join(f"{name} ({n})" for name, n in project_counts.most_common(10))
    facts.append({
        "dimension": "workflow",
        "key": "claude_code_projects",
        "value": top_projects,
        "confidence": 0.95,
        "source": source,
        "evidence": f"Project frequency across {len(sessions)} sessions",
    })

    facts.append({
        "dimension": "workflow",
        "key": "claude_code_activity",
        "value": f"{len(sessions)} sessions, {total_messages} messages across {len(project_counts)} projects",
        "confidence": 0.95,
        "source": source,
        "evidence": f"Aggregate Claude Code usage stats",
    })

    return facts


def _write_profile_facts(state: ClaudeCodeSyncState) -> None:
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

def _print_stats(state: ClaudeCodeSyncState) -> None:
    """Print sync statistics."""
    from collections import Counter

    sessions = list(state.sessions.values())
    project_counts: Counter[str] = Counter()
    total_messages = 0
    for s in sessions:
        project_counts[s.project_name] += 1
        total_messages += s.message_count

    print("Claude Code Sync State")
    print("=" * 40)
    print(f"Total sessions:  {len(sessions):,}")
    print(f"Total messages:  {total_messages:,}")
    print(f"Projects:        {len(project_counts):,}")
    print(f"Last sync:       {datetime.fromtimestamp(state.last_sync, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}")

    if project_counts:
        print("\nSessions by project:")
        for name, count in project_counts.most_common(10):
            print(f"  {name}: {count}")


# ── Orchestration ────────────────────────────────────────────────────────────

def run_full_sync() -> None:
    """Full transcript sync."""
    from shared.notify import send_notification

    state = _load_state()
    count = _full_sync(state)
    _save_state(state)
    _write_profile_facts(state)

    msg = f"Claude Code sync: {count} sessions processed, {len(state.sessions)} total"
    log.info(msg)
    send_notification("Claude Code Sync", msg, tags=["claude-code"])


def run_auto() -> None:
    """Incremental transcript sync."""
    from shared.notify import send_notification

    state = _load_state()
    count = _incremental_sync(state)
    _save_state(state)
    _write_profile_facts(state)

    if count:
        msg = f"Claude Code: {count} new/updated sessions"
        log.info(msg)
        send_notification("Claude Code Sync", msg, tags=["claude-code"])
    else:
        log.info("No new Claude Code sessions")


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
    group.add_argument("--full-sync", action="store_true", help="Process all transcripts")
    group.add_argument("--auto", action="store_true", help="Incremental sync")
    group.add_argument("--stats", action="store_true", help="Show sync statistics")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.full_sync:
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
uv run pytest tests/test_claude_code_sync.py -v
```

Expected: 7 PASS.

**Step 5: Commit**

```bash
git add agents/claude_code_sync.py tests/test_claude_code_sync.py
git commit -m "feat(claude-code): discovery, sync logic, profiler bridge, CLI"
```

---

## Task 4: Obsidian Sync — Skeleton + Schemas

**Files:**
- Create: `~/projects/ai-agents/agents/obsidian_sync.py`
- Create: `~/projects/ai-agents/tests/test_obsidian_sync.py`

**Step 1: Write failing tests**

Create `~/projects/ai-agents/tests/test_obsidian_sync.py`:

```python
"""Tests for obsidian_sync — schemas, filtering, formatting, profiler facts."""
from __future__ import annotations


def test_vault_note_defaults():
    from agents.obsidian_sync import VaultNote
    n = VaultNote(
        relative_path="30 Areas/37 Meeting notes/alice.md",
        title="Alice 1:1",
        folder="30 Areas",
        content_hash="abc123",
        size=500,
        mtime=1741400000.0,
    )
    assert n.tags == []
    assert n.links == []
    assert n.has_frontmatter is False


def test_obsidian_sync_state_empty():
    from agents.obsidian_sync import ObsidianSyncState
    s = ObsidianSyncState()
    assert s.notes == {}
    assert s.last_sync == 0.0


def test_should_include_path():
    from agents.obsidian_sync import _should_include
    assert _should_include("30 Areas/37 Meeting notes/alice.md") is True
    assert _should_include("20 Projects/something.md") is True
    assert _should_include("00-inbox/quick-note.md") is True
    assert _should_include("50 Resources/article.md") is True
    assert _should_include("90-attachments/image.png") is False
    assert _should_include("50-templates/template.md") is False
    assert _should_include("Templates/daily.md") is False
    assert _should_include("60-archive/old.md") is False
    assert _should_include("60 Archives/old.md") is False
    assert _should_include(".obsidian/config.json") is False
    assert _should_include("smart-chats/chat.md") is False
    assert _should_include("textgenerator/out.md") is False
```

**Step 2: Run to verify failure**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_obsidian_sync.py -v
```

**Step 3: Create obsidian_sync.py skeleton**

```python
"""Obsidian vault sync — notes to RAG pipeline.

Scans the Obsidian vault, writes changed/new notes as markdown stubs to
rag-sources/obsidian/ with RAG metadata. Read-only: never modifies vault files.

Usage:
    uv run python -m agents.obsidian_sync --full-sync   # Process all notes
    uv run python -m agents.obsidian_sync --auto         # Incremental (changed only)
    uv run python -m agents.obsidian_sync --stats        # Show sync state
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

VAULT_PATH = Path.home() / "Documents" / "Personal"
CACHE_DIR = Path.home() / ".cache" / "obsidian-sync"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "obsidian-profile-facts.jsonl"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"
RAG_SOURCES = Path.home() / "documents" / "rag-sources"
OBSIDIAN_DIR = RAG_SOURCES / "obsidian"

MIN_FILE_SIZE = 50  # Skip files smaller than this (empty stubs)

# Directories to include (relative to vault root)
INCLUDE_DIRS = {
    "00-inbox",
    "20-personal",
    "20 Projects",
    "30 Areas",
    "50 Resources",
    "Periodic Notes",
    "Day Planners",
}

# Directories to exclude (checked as prefixes of relative path)
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
    """Metadata for an Obsidian vault note."""
    relative_path: str
    title: str
    folder: str              # Top-level vault folder
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


# ── Filtering ────────────────────────────────────────────────────────────────

def _should_include(relative_path: str) -> bool:
    """Check if a vault path should be included in sync."""
    # Check excludes first (prefix match)
    parts = relative_path.split("/")
    for part in parts:
        if part in EXCLUDE_DIRS:
            return False

    # Root-level .md files are included
    if "/" not in relative_path and relative_path.endswith(".md"):
        return True

    # Check if top-level dir is in INCLUDE_DIRS
    top_dir = parts[0] if parts else ""
    return top_dir in INCLUDE_DIRS
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_obsidian_sync.py -v
```

Expected: 3 PASS.

**Step 5: Commit**

```bash
git add agents/obsidian_sync.py tests/test_obsidian_sync.py
git commit -m "feat(obsidian): skeleton module with schemas and filtering"
```

---

## Task 5: Obsidian Sync — Parsing, Formatting, Sync Logic, Profiler, CLI

**Files:**
- Modify: `~/projects/ai-agents/agents/obsidian_sync.py`
- Modify: `~/projects/ai-agents/tests/test_obsidian_sync.py`

**Step 1: Write failing tests**

Add to `tests/test_obsidian_sync.py`:

```python
def test_extract_obsidian_metadata():
    from agents.obsidian_sync import _extract_metadata
    content = """---
title: Test Note
tags: [project, planning]
---

# My Test Note

This links to [[Alice Bregger]] and [[Q1 Goals]].
Also has #inline-tag and #another.
"""
    meta = _extract_metadata(content, "20 Projects/test.md")
    assert meta["has_frontmatter"] is True
    assert "alice-bregger" in [l.lower().replace(" ", "-") for l in meta["links"]] or "Alice Bregger" in meta["links"]
    assert "Q1 Goals" in meta["links"]
    assert "inline-tag" in meta["tags"] or "project" in meta["tags"]


def test_format_note_markdown():
    from agents.obsidian_sync import _format_note_markdown, VaultNote
    note = VaultNote(
        relative_path="30 Areas/37 Meeting notes/alice.md",
        title="Alice 1:1",
        folder="30 Areas",
        content_hash="abc123",
        size=200,
        mtime=1741400000.0,
        tags=["meeting", "1on1"],
        links=["Alice Bregger"],
    )
    original = "# Alice 1:1\n\nDiscussed Q1 goals."
    md = _format_note_markdown(note, original)
    assert "platform: obsidian" in md
    assert "source_service: obsidian" in md
    assert "vault_folder: 30 Areas" in md
    assert "Alice 1:1" in md
    assert "Discussed Q1 goals." in md


def test_generate_obsidian_profile_facts():
    from agents.obsidian_sync import _generate_profile_facts, ObsidianSyncState, VaultNote
    state = ObsidianSyncState()
    state.notes = {
        "30 Areas/37 Meeting notes/alice.md": VaultNote(
            relative_path="30 Areas/37 Meeting notes/alice.md",
            title="Alice", folder="30 Areas", content_hash="a", size=100, mtime=1741400000.0,
            tags=["meeting", "1on1"]),
        "20 Projects/roadmap.md": VaultNote(
            relative_path="20 Projects/roadmap.md",
            title="Roadmap", folder="20 Projects", content_hash="b", size=200, mtime=1741300000.0,
            tags=["project", "planning"]),
        "50 Resources/article.md": VaultNote(
            relative_path="50 Resources/article.md",
            title="Article", folder="50 Resources", content_hash="c", size=300, mtime=1741200000.0,
            tags=["reference"]),
    }
    facts = _generate_profile_facts(state)
    assert len(facts) > 0
    dims = {f["dimension"] for f in facts}
    assert "knowledge" in dims
    assert all(f["confidence"] == 0.95 for f in facts)
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_obsidian_sync.py -v -k "extract or format_note or profile"
```

**Step 3: Implement parsing, formatting, sync, profiler, and CLI**

Add to `agents/obsidian_sync.py`:

```python
# ── State Management ─────────────────────────────────────────────────────────

def _load_state(path: Path = STATE_FILE) -> ObsidianSyncState:
    if path.exists():
        try:
            return ObsidianSyncState.model_validate_json(path.read_text())
        except Exception as exc:
            log.warning("Corrupt state file, starting fresh: %s", exc)
    return ObsidianSyncState()


def _save_state(state: ObsidianSyncState, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    tmp.rename(path)


# ── Content Parsing ──────────────────────────────────────────────────────────

def _extract_metadata(content: str, relative_path: str) -> dict:
    """Extract metadata from note content: frontmatter, tags, wikilinks."""
    has_frontmatter = content.startswith("---\n")
    tags: list[str] = []
    links: list[str] = []

    # Extract YAML frontmatter tags
    if has_frontmatter:
        end = content.find("\n---\n", 4)
        if end > 0:
            fm = content[4:end]
            # Simple tag extraction from frontmatter
            for line in fm.split("\n"):
                if line.strip().startswith("tags:"):
                    # tags: [a, b] or tags:\n  - a\n  - b
                    rest = line.split(":", 1)[1].strip()
                    if rest.startswith("["):
                        tags.extend(t.strip().strip("\"'") for t in rest.strip("[]").split(",") if t.strip())
                elif line.strip().startswith("- ") and tags:
                    # Continuation of tags list
                    tags.append(line.strip().lstrip("- ").strip("\"'"))

    # Extract inline #tags (not inside code blocks)
    for match in re.finditer(r"(?<!\w)#([\w-]+)", content):
        tag = match.group(1)
        if tag not in tags:
            tags.append(tag)

    # Extract [[wikilinks]]
    for match in re.finditer(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]", content):
        link = match.group(1).strip()
        if link and link not in links:
            links.append(link)

    # Title: first H1 or filename
    title = Path(relative_path).stem
    for line in content.split("\n"):
        if line.startswith("# "):
            title = line[2:].strip()
            break

    return {
        "has_frontmatter": has_frontmatter,
        "tags": tags,
        "links": links,
        "title": title,
    }


def _content_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


# ── Markdown Formatting ──────────────────────────────────────────────────────

def _format_note_markdown(note: VaultNote, original_content: str) -> str:
    """Generate RAG markdown with frontmatter wrapping original content."""
    tags_str = "[" + ", ".join(note.tags) + "]" if note.tags else "[]"
    links_str = "[" + ", ".join(note.links) + "]" if note.links else "[]"

    try:
        dt = datetime.fromtimestamp(note.mtime, tz=timezone.utc)
        ts = dt.strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, OSError):
        ts = ""

    # Strip existing frontmatter from original content to avoid duplication
    body = original_content
    if body.startswith("---\n"):
        end = body.find("\n---\n", 4)
        if end > 0:
            body = body[end + 5:]

    return f"""---
platform: obsidian
service: obsidian-vault
content_type: note
source_service: obsidian
vault_folder: {note.folder}
vault_path: {note.relative_path}
tags: {tags_str}
links: {links_str}
timestamp: {ts}
---

{body.strip()}
"""


# ── Sync Logic ───────────────────────────────────────────────────────────────

def _scan_vault(vault_path: Path = VAULT_PATH) -> list[tuple[str, Path]]:
    """Scan vault for eligible .md files. Returns (relative_path, full_path) pairs."""
    results = []
    for md_file in vault_path.rglob("*.md"):
        rel = str(md_file.relative_to(vault_path))
        if _should_include(rel) and md_file.stat().st_size >= MIN_FILE_SIZE:
            results.append((rel, md_file))
    return results


def _sync_note(
    relative_path: str,
    full_path: Path,
    state: ObsidianSyncState,
    force: bool = False,
) -> bool:
    """Process a single vault note. Returns True if written/updated."""
    content = full_path.read_text(encoding="utf-8", errors="replace")
    h = _content_hash(content)

    # Check if unchanged
    if not force and relative_path in state.notes:
        if state.notes[relative_path].content_hash == h:
            return False

    stat = full_path.stat()
    meta_info = _extract_metadata(content, relative_path)
    parts = relative_path.split("/")
    folder = parts[0] if len(parts) > 1 else ""

    note = VaultNote(
        relative_path=relative_path,
        title=meta_info["title"],
        folder=folder,
        content_hash=h,
        size=stat.st_size,
        mtime=stat.st_mtime,
        has_frontmatter=meta_info["has_frontmatter"],
        tags=meta_info["tags"],
        links=meta_info["links"],
    )

    # Write to rag-sources
    slug = folder.lower().replace(" ", "-") if folder else "root"
    out_dir = OBSIDIAN_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(relative_path).name
    out_path = out_dir / safe_name
    md = _format_note_markdown(note, content)
    out_path.write_text(md, encoding="utf-8")

    state.notes[relative_path] = note
    return True


def _detect_deletions(state: ObsidianSyncState, current_paths: set[str]) -> int:
    """Remove RAG files for notes deleted from vault."""
    deleted = 0
    stale = [p for p in state.notes if p not in current_paths]
    for rel_path in stale:
        note = state.notes.pop(rel_path)
        slug = note.folder.lower().replace(" ", "-") if note.folder else "root"
        out_path = OBSIDIAN_DIR / slug / Path(rel_path).name
        if out_path.exists():
            out_path.unlink()
        _log_change("deleted", rel_path, {"title": note.title})
        deleted += 1
    return deleted


def _full_sync(state: ObsidianSyncState) -> tuple[int, int]:
    """Full vault sync. Returns (written, deleted)."""
    vault_files = _scan_vault()
    current_paths = {rel for rel, _ in vault_files}
    written = 0
    for rel_path, full_path in vault_files:
        try:
            if _sync_note(rel_path, full_path, state, force=True):
                written += 1
        except Exception as exc:
            log.warning("Failed to process %s: %s", rel_path, exc)
    deleted = _detect_deletions(state, current_paths)
    state.last_sync = time.time()
    state.stats["total_notes"] = len(state.notes)
    return written, deleted


def _incremental_sync(state: ObsidianSyncState) -> tuple[int, int]:
    """Process only changed/new notes. Returns (written, deleted)."""
    vault_files = _scan_vault()
    current_paths = {rel for rel, _ in vault_files}
    written = 0
    for rel_path, full_path in vault_files:
        try:
            if _sync_note(rel_path, full_path, state):
                written += 1
        except Exception as exc:
            log.warning("Failed to process %s: %s", rel_path, exc)
    deleted = _detect_deletions(state, current_paths)
    state.last_sync = time.time()
    state.stats["total_notes"] = len(state.notes)
    return written, deleted


# ── Behavioral Logging ───────────────────────────────────────────────────────

def _log_change(change_type: str, path: str, extra: dict | None = None) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "service": "obsidian",
        "event_type": change_type,
        "record_id": path,
        "context": extra or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(CHANGES_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# ── Profiler Integration ─────────────────────────────────────────────────────

def _generate_profile_facts(state: ObsidianSyncState) -> list[dict]:
    from collections import Counter

    facts = []
    source = "obsidian-sync:obsidian-profile-facts"
    notes = list(state.notes.values())

    if not notes:
        return facts

    # Active areas
    folder_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    for n in notes:
        if n.folder:
            folder_counts[n.folder] += 1
        for tag in n.tags:
            tag_counts[tag] += 1

    if folder_counts:
        top_folders = ", ".join(f"{f} ({c})" for f, c in folder_counts.most_common(10))
        facts.append({
            "dimension": "knowledge",
            "key": "obsidian_active_areas",
            "value": top_folders,
            "confidence": 0.95,
            "source": source,
            "evidence": f"Folder distribution across {len(notes)} notes",
        })

    facts.append({
        "dimension": "knowledge",
        "key": "obsidian_note_volume",
        "value": f"{len(notes)} notes in vault",
        "confidence": 0.95,
        "source": source,
        "evidence": "Total synced note count",
    })

    if tag_counts:
        top_tags = ", ".join(f"{t} ({c})" for t, c in tag_counts.most_common(15))
        facts.append({
            "dimension": "knowledge",
            "key": "obsidian_frequent_tags",
            "value": top_tags,
            "confidence": 0.95,
            "source": source,
            "evidence": f"Tag frequency across {len(notes)} notes",
        })

    return facts


def _write_profile_facts(state: ObsidianSyncState) -> None:
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
    from collections import Counter

    notes = list(state.notes.values())
    folder_counts: Counter[str] = Counter()
    for n in notes:
        if n.folder:
            folder_counts[n.folder] += 1

    print("Obsidian Vault Sync State")
    print("=" * 40)
    print(f"Total notes:     {len(notes):,}")
    print(f"Last sync:       {datetime.fromtimestamp(state.last_sync, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}")

    if folder_counts:
        print("\nNotes by folder:")
        for name, count in folder_counts.most_common(10):
            print(f"  {name}: {count}")


# ── Orchestration ────────────────────────────────────────────────────────────

def run_full_sync() -> None:
    from shared.notify import send_notification

    state = _load_state()
    written, deleted = _full_sync(state)
    _save_state(state)
    _write_profile_facts(state)

    msg = f"Obsidian sync: {written} notes written, {deleted} deleted, {len(state.notes)} total"
    log.info(msg)
    send_notification("Obsidian Sync", msg, tags=["obsidian"])


def run_auto() -> None:
    from shared.notify import send_notification

    state = _load_state()
    written, deleted = _incremental_sync(state)
    _save_state(state)
    _write_profile_facts(state)

    if written or deleted:
        msg = f"Obsidian: {written} updated, {deleted} deleted"
        log.info(msg)
        send_notification("Obsidian Sync", msg, tags=["obsidian"])
    else:
        log.info("No Obsidian vault changes")


def run_stats() -> None:
    state = _load_state()
    if not state.notes:
        print("No sync state found. Run --full-sync first.")
        return
    _print_stats(state)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Obsidian vault RAG sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full-sync", action="store_true", help="Process all notes")
    group.add_argument("--auto", action="store_true", help="Incremental sync")
    group.add_argument("--stats", action="store_true", help="Show sync statistics")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.full_sync:
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
uv run pytest tests/test_obsidian_sync.py -v
```

Expected: 6 PASS.

**Step 5: Commit**

```bash
git add agents/obsidian_sync.py tests/test_obsidian_sync.py
git commit -m "feat(obsidian): parsing, formatting, sync logic, profiler, CLI"
```

---

## Task 6: Chrome Sync — Skeleton + Schemas

**Files:**
- Create: `~/projects/ai-agents/agents/chrome_sync.py`
- Create: `~/projects/ai-agents/tests/test_chrome_sync.py`

**Step 1: Write failing tests**

Create `~/projects/ai-agents/tests/test_chrome_sync.py`:

```python
"""Tests for chrome_sync — schemas, domain filtering, formatting, profiler facts."""
from __future__ import annotations


def test_history_entry_defaults():
    from agents.chrome_sync import HistoryEntry
    h = HistoryEntry(
        url="https://example.com/page",
        title="Example Page",
        domain="example.com",
        visit_count=5,
        last_visit="2026-03-08T10:00:00",
        first_visit="2026-03-01T08:00:00",
    )
    assert h.domain == "example.com"
    assert h.visit_count == 5


def test_bookmark_entry_defaults():
    from agents.chrome_sync import BookmarkEntry
    b = BookmarkEntry(
        url="https://example.com",
        title="Example",
        folder="Bookmarks bar",
        added_at="2026-01-15T12:00:00",
    )
    assert b.folder == "Bookmarks bar"


def test_chrome_sync_state_empty():
    from agents.chrome_sync import ChromeSyncState
    s = ChromeSyncState()
    assert s.last_visit_time == 0
    assert s.domains == {}
    assert s.bookmark_hash == ""


def test_should_skip_domain():
    from agents.chrome_sync import _should_skip_domain
    assert _should_skip_domain("localhost") is True
    assert _should_skip_domain("127.0.0.1") is True
    assert _should_skip_domain("chrome") is True
    assert _should_skip_domain("mail.google.com") is True
    assert _should_skip_domain("calendar.google.com") is True
    assert _should_skip_domain("github.com") is False
    assert _should_skip_domain("stackoverflow.com") is False


def test_webkit_timestamp_conversion():
    from agents.chrome_sync import _webkit_to_datetime
    # WebKit timestamp for 2026-01-01T00:00:00 UTC
    # WebKit epoch = 1601-01-01, offset = 11644473600 seconds
    # 2026-01-01 = 1767225600 Unix epoch
    # WebKit microseconds = (1767225600 + 11644473600) * 1_000_000
    wk = (1767225600 + 11644473600) * 1_000_000
    dt = _webkit_to_datetime(wk)
    assert dt.year == 2026
    assert dt.month == 1
    assert dt.day == 1
```

**Step 2: Run to verify failure**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_chrome_sync.py -v
```

**Step 3: Create chrome_sync.py skeleton**

```python
"""Chrome history + bookmarks sync — browsing data to RAG pipeline.

Reads Chrome's local SQLite History database (via copy to avoid locks)
and Bookmarks JSON. Writes domain summaries and bookmarks to rag-sources/chrome/.

Usage:
    uv run python -m agents.chrome_sync --full-sync   # Full history sync
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
from datetime import datetime, timezone
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
RAG_SOURCES = Path.home() / "documents" / "rag-sources"
CHROME_DIR = RAG_SOURCES / "chrome"
SNAPSHOT_DB = CACHE_DIR / "history-snapshot.db"

# WebKit epoch offset: seconds between 1601-01-01 and 1970-01-01
WEBKIT_EPOCH_OFFSET = 11644473600

# Minimum visits for a domain to get its own summary file
MIN_DOMAIN_VISITS = 3

# Domains to skip (already covered by other agents or noise)
SKIP_DOMAINS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "chrome",
    "chrome-extension",
    "mail.google.com",
    "calendar.google.com",
    "drive.google.com",
    "docs.google.com",
    "youtube.com",
    "www.youtube.com",
    "music.youtube.com",
    "accounts.google.com",
    "myaccount.google.com",
    "newtab",
}


# ── Schemas ──────────────────────────────────────────────────────────────────

class HistoryEntry(BaseModel):
    url: str
    title: str
    domain: str
    visit_count: int
    last_visit: str
    first_visit: str


class BookmarkEntry(BaseModel):
    url: str
    title: str
    folder: str
    added_at: str


class ChromeSyncState(BaseModel):
    last_visit_time: int = 0      # WebKit microsecond high-water mark
    domains: dict[str, int] = Field(default_factory=dict)
    bookmark_hash: str = ""
    last_sync: float = 0.0
    stats: dict[str, int] = Field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _webkit_to_datetime(webkit_ts: int) -> datetime:
    """Convert Chrome WebKit timestamp (microseconds since 1601-01-01) to datetime."""
    unix_seconds = (webkit_ts / 1_000_000) - WEBKIT_EPOCH_OFFSET
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc)


def _should_skip_domain(domain: str) -> bool:
    """Check if a domain should be excluded from sync."""
    if not domain:
        return True
    # Check exact matches and prefixes
    if domain in SKIP_DOMAINS:
        return True
    # Strip www. and check again
    bare = domain.removeprefix("www.")
    if bare in SKIP_DOMAINS:
        return True
    # Skip chrome:// and chrome-extension://
    if domain.startswith("chrome"):
        return True
    return False
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_chrome_sync.py -v
```

Expected: 5 PASS.

**Step 5: Commit**

```bash
git add agents/chrome_sync.py tests/test_chrome_sync.py
git commit -m "feat(chrome): skeleton module with schemas and filtering"
```

---

## Task 7: Chrome Sync — History Query, Formatting, Bookmarks, Profiler, CLI

**Files:**
- Modify: `~/projects/ai-agents/agents/chrome_sync.py`
- Modify: `~/projects/ai-agents/tests/test_chrome_sync.py`

**Step 1: Write failing tests**

Add to `tests/test_chrome_sync.py`:

```python
def test_format_domain_markdown():
    from agents.chrome_sync import _format_domain_markdown, HistoryEntry
    entries = [
        HistoryEntry(url="https://github.com/anthropics", title="Anthropic", domain="github.com",
                     visit_count=50, last_visit="2026-03-08T10:00:00", first_visit="2025-06-01T08:00:00"),
        HistoryEntry(url="https://github.com/issues", title="Issues", domain="github.com",
                     visit_count=20, last_visit="2026-03-07T15:00:00", first_visit="2025-08-01T09:00:00"),
    ]
    md = _format_domain_markdown("github.com", entries, 70)
    assert "platform: chrome" in md
    assert "source_service: chrome" in md
    assert "domain: github.com" in md
    assert "total_visits: 70" in md
    assert "Anthropic" in md


def test_format_bookmarks_markdown():
    from agents.chrome_sync import _format_bookmarks_markdown, BookmarkEntry
    bookmarks = [
        BookmarkEntry(url="https://example.com", title="Example", folder="Dev", added_at="2026-01-01T00:00:00"),
        BookmarkEntry(url="https://test.com", title="Test", folder="Dev/Sub", added_at="2026-02-01T00:00:00"),
    ]
    md = _format_bookmarks_markdown(bookmarks)
    assert "platform: chrome" in md
    assert "source_service: chrome" in md
    assert "bookmark_count: 2" in md
    assert "Example" in md


def test_generate_chrome_profile_facts():
    from agents.chrome_sync import _generate_profile_facts, ChromeSyncState
    state = ChromeSyncState()
    state.domains = {"github.com": 150, "stackoverflow.com": 80, "reddit.com": 50, "example.com": 10}
    facts = _generate_profile_facts(state)
    assert len(facts) > 0
    dims = {f["dimension"] for f in facts}
    assert "interests" in dims
    assert all(f["confidence"] == 0.95 for f in facts)
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_chrome_sync.py -v -k "format or profile"
```

**Step 3: Implement history query, formatting, bookmarks, profiler, and CLI**

Add to `agents/chrome_sync.py`:

```python
# ── State Management ─────────────────────────────────────────────────────────

def _load_state(path: Path = STATE_FILE) -> ChromeSyncState:
    if path.exists():
        try:
            return ChromeSyncState.model_validate_json(path.read_text())
        except Exception as exc:
            log.warning("Corrupt state file, starting fresh: %s", exc)
    return ChromeSyncState()


def _save_state(state: ChromeSyncState, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    tmp.rename(path)


# ── History Query ────────────────────────────────────────────────────────────

def _copy_history_db() -> Path | None:
    """Copy Chrome History DB to avoid lock conflicts. Returns snapshot path or None."""
    if not CHROME_HISTORY_DB.exists():
        log.warning("Chrome History DB not found at %s", CHROME_HISTORY_DB)
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(CHROME_HISTORY_DB, SNAPSHOT_DB)
        return SNAPSHOT_DB
    except Exception as exc:
        log.warning("Failed to copy History DB: %s", exc)
        return None


def _query_history(db_path: Path, since_webkit_ts: int = 0) -> list[HistoryEntry]:
    """Query Chrome history from snapshot DB."""
    entries = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT url, title, visit_count, last_visit_time,
                   (SELECT MIN(visit_time) FROM visits WHERE visits.url = urls.id) as first_visit_time
            FROM urls
            WHERE last_visit_time > ?
            ORDER BY last_visit_time DESC
        """, (since_webkit_ts,))

        for row in cursor:
            url = row["url"]
            parsed = urlparse(url)
            domain = parsed.hostname or parsed.scheme or ""

            if _should_skip_domain(domain):
                continue

            try:
                last_dt = _webkit_to_datetime(row["last_visit_time"])
                first_dt = _webkit_to_datetime(row["first_visit_time"]) if row["first_visit_time"] else last_dt
            except (ValueError, OSError):
                continue

            entries.append(HistoryEntry(
                url=url,
                title=row["title"] or url,
                domain=domain,
                visit_count=row["visit_count"] or 1,
                last_visit=last_dt.isoformat(),
                first_visit=first_dt.isoformat(),
            ))

        conn.close()
    except Exception as exc:
        log.error("Failed to query history: %s", exc)

    return entries


# ── Bookmark Reading ─────────────────────────────────────────────────────────

def _read_bookmarks() -> list[BookmarkEntry]:
    """Read Chrome bookmarks from JSON file."""
    if not CHROME_BOOKMARKS_FILE.exists():
        return []

    try:
        data = json.loads(CHROME_BOOKMARKS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Failed to read bookmarks: %s", exc)
        return []

    bookmarks: list[BookmarkEntry] = []

    def _walk(node: dict, folder: str = "") -> None:
        if node.get("type") == "url":
            url = node.get("url", "")
            # Chrome stores add time as WebKit microseconds string
            added_raw = int(node.get("date_added", "0"))
            try:
                added_dt = _webkit_to_datetime(added_raw) if added_raw else datetime.min.replace(tzinfo=timezone.utc)
                added_str = added_dt.isoformat()
            except (ValueError, OSError):
                added_str = ""
            bookmarks.append(BookmarkEntry(
                url=url,
                title=node.get("name", url),
                folder=folder,
                added_at=added_str,
            ))
        elif node.get("type") == "folder":
            child_folder = f"{folder}/{node['name']}" if folder else node.get("name", "")
            for child in node.get("children", []):
                _walk(child, child_folder)

    roots = data.get("roots", {})
    for key in ("bookmark_bar", "other", "synced"):
        if key in roots and isinstance(roots[key], dict):
            _walk(roots[key])

    return bookmarks


# ── Formatting ───────────────────────────────────────────────────────────────

def _format_domain_markdown(domain: str, entries: list[HistoryEntry], total_visits: int) -> str:
    """Generate markdown summary for a domain."""
    first_seen = min(e.first_visit for e in entries) if entries else ""
    last_seen = max(e.last_visit for e in entries) if entries else ""

    lines = [
        "---",
        "platform: chrome",
        "service: chrome-history",
        "content_type: browsing_history",
        "source_service: chrome",
        f"domain: {domain}",
        f"total_visits: {total_visits}",
        f"first_seen: {first_seen}",
        f"last_seen: {last_seen}",
        f"page_count: {len(entries)}",
        "---",
        "",
        f"# {domain} ({total_visits} visits)",
        "",
        "## Pages",
    ]

    # Sort by visit count, show top 50
    sorted_entries = sorted(entries, key=lambda e: e.visit_count, reverse=True)[:50]
    for e in sorted_entries:
        last_date = e.last_visit[:10] if e.last_visit else ""
        lines.append(f"- {e.title} ({e.visit_count} visits, last: {last_date})")

    lines.append("")
    return "\n".join(lines)


def _format_bookmarks_markdown(bookmarks: list[BookmarkEntry]) -> str:
    """Generate markdown for all bookmarks."""
    lines = [
        "---",
        "platform: chrome",
        "service: chrome-bookmarks",
        "content_type: bookmarks",
        "source_service: chrome",
        f"bookmark_count: {len(bookmarks)}",
        "---",
        "",
        "# Chrome Bookmarks",
        "",
    ]

    # Group by folder
    by_folder: dict[str, list[BookmarkEntry]] = {}
    for bm in bookmarks:
        folder = bm.folder or "Unsorted"
        by_folder.setdefault(folder, []).append(bm)

    for folder in sorted(by_folder.keys()):
        lines.append(f"## {folder}")
        for bm in by_folder[folder]:
            lines.append(f"- [{bm.title}]({bm.url})")
        lines.append("")

    return "\n".join(lines)


# ── Sync Logic ───────────────────────────────────────────────────────────────

def _write_domain_files(entries: list[HistoryEntry], state: ChromeSyncState) -> int:
    """Group entries by domain and write summary files."""
    CHROME_DIR.mkdir(parents=True, exist_ok=True)
    by_domain: dict[str, list[HistoryEntry]] = {}
    domain_visits: dict[str, int] = {}

    for e in entries:
        by_domain.setdefault(e.domain, []).append(e)
        domain_visits[e.domain] = domain_visits.get(e.domain, 0) + e.visit_count

    # Merge with existing domain counts
    for domain, count in domain_visits.items():
        state.domains[domain] = state.domains.get(domain, 0) + count

    written = 0
    for domain, domain_entries in by_domain.items():
        total = state.domains.get(domain, sum(e.visit_count for e in domain_entries))
        if total < MIN_DOMAIN_VISITS:
            continue
        safe_domain = domain.replace("/", "_").replace(":", "_")
        out_path = CHROME_DIR / f"domain-{safe_domain}.md"
        md = _format_domain_markdown(domain, domain_entries, total)
        out_path.write_text(md, encoding="utf-8")
        written += 1

    return written


def _write_bookmarks_file(bookmarks: list[BookmarkEntry], state: ChromeSyncState) -> bool:
    """Write bookmarks file if changed."""
    if not bookmarks:
        return False
    bm_json = json.dumps([b.model_dump() for b in bookmarks], sort_keys=True)
    h = hashlib.md5(bm_json.encode()).hexdigest()
    if h == state.bookmark_hash:
        return False
    state.bookmark_hash = h
    CHROME_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CHROME_DIR / "bookmarks.md"
    md = _format_bookmarks_markdown(bookmarks)
    out_path.write_text(md, encoding="utf-8")
    return True


def _full_sync(state: ChromeSyncState) -> tuple[int, bool]:
    """Full history + bookmarks sync. Returns (domains_written, bookmarks_updated)."""
    db_path = _copy_history_db()
    domains_written = 0
    if db_path:
        entries = _query_history(db_path, since_webkit_ts=0)
        log.info("Read %d history entries", len(entries))
        # Update high-water mark
        if entries:
            max_wk = max(
                int((datetime.fromisoformat(e.last_visit).timestamp() + WEBKIT_EPOCH_OFFSET) * 1_000_000)
                for e in entries
            )
            state.last_visit_time = max_wk
        # Reset domain counts for full sync
        state.domains = {}
        domains_written = _write_domain_files(entries, state)
        db_path.unlink(missing_ok=True)

    bookmarks = _read_bookmarks()
    bm_updated = _write_bookmarks_file(bookmarks, state)

    state.last_sync = time.time()
    state.stats["total_domains"] = len(state.domains)
    state.stats["total_bookmarks"] = len(bookmarks)
    return domains_written, bm_updated


def _incremental_sync(state: ChromeSyncState) -> tuple[int, bool]:
    """Incremental history sync from high-water mark."""
    db_path = _copy_history_db()
    domains_written = 0
    if db_path:
        entries = _query_history(db_path, since_webkit_ts=state.last_visit_time)
        log.info("Read %d new history entries", len(entries))
        if entries:
            max_wk = max(
                int((datetime.fromisoformat(e.last_visit).timestamp() + WEBKIT_EPOCH_OFFSET) * 1_000_000)
                for e in entries
            )
            state.last_visit_time = max_wk
            domains_written = _write_domain_files(entries, state)
        db_path.unlink(missing_ok=True)

    bookmarks = _read_bookmarks()
    bm_updated = _write_bookmarks_file(bookmarks, state)

    state.last_sync = time.time()
    state.stats["total_domains"] = len(state.domains)
    state.stats["total_bookmarks"] = len(bookmarks)
    return domains_written, bm_updated


# ── Profiler Integration ─────────────────────────────────────────────────────

def _generate_profile_facts(state: ChromeSyncState) -> list[dict]:
    facts = []
    source = "chrome-sync:chrome-profile-facts"

    if state.domains:
        sorted_domains = sorted(state.domains.items(), key=lambda x: -x[1])
        top_domains = ", ".join(f"{d} ({n})" for d, n in sorted_domains[:20])
        facts.append({
            "dimension": "interests",
            "key": "browsing_top_domains",
            "value": top_domains,
            "confidence": 0.95,
            "source": source,
            "evidence": f"Visit counts across {len(state.domains)} domains",
        })

    if state.stats.get("total_bookmarks"):
        facts.append({
            "dimension": "interests",
            "key": "bookmark_count",
            "value": f"{state.stats['total_bookmarks']} bookmarks saved",
            "confidence": 0.95,
            "source": source,
            "evidence": "Chrome bookmarks",
        })

    return facts


def _write_profile_facts(state: ChromeSyncState) -> None:
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
    print("Chrome Sync State")
    print("=" * 40)
    print(f"Domains tracked:  {len(state.domains):,}")
    print(f"Bookmarks:        {state.stats.get('total_bookmarks', 0):,}")
    print(f"Last sync:        {datetime.fromtimestamp(state.last_sync, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}")

    if state.domains:
        print("\nTop domains:")
        for domain, count in sorted(state.domains.items(), key=lambda x: -x[1])[:10]:
            print(f"  {domain}: {count}")


# ── Orchestration ────────────────────────────────────────────────────────────

def run_full_sync() -> None:
    from shared.notify import send_notification

    state = _load_state()
    domains, bm = _full_sync(state)
    _save_state(state)
    _write_profile_facts(state)

    msg = f"Chrome sync: {domains} domain files, {len(state.domains)} domains tracked"
    if bm:
        msg += ", bookmarks updated"
    log.info(msg)
    send_notification("Chrome Sync", msg, tags=["chrome"])


def run_auto() -> None:
    from shared.notify import send_notification

    state = _load_state()
    domains, bm = _incremental_sync(state)
    _save_state(state)
    _write_profile_facts(state)

    if domains or bm:
        msg = f"Chrome: {domains} domains updated"
        if bm:
            msg += ", bookmarks changed"
        log.info(msg)
        send_notification("Chrome Sync", msg, tags=["chrome"])
    else:
        log.info("No new Chrome activity")


def run_stats() -> None:
    state = _load_state()
    if not state.domains:
        print("No sync state found. Run --full-sync first.")
        return
    _print_stats(state)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Chrome history + bookmarks RAG sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full-sync", action="store_true", help="Full history sync")
    group.add_argument("--auto", action="store_true", help="Incremental sync")
    group.add_argument("--stats", action="store_true", help="Show sync statistics")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.full_sync:
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
uv run pytest tests/test_chrome_sync.py -v
```

Expected: 8 PASS.

**Step 5: Commit**

```bash
git add agents/chrome_sync.py tests/test_chrome_sync.py
git commit -m "feat(chrome): history query, bookmarks, formatting, profiler, CLI"
```

---

## Task 8: Agent Modifications — briefing + management_prep

**Files:**
- Modify: `~/projects/ai-agents/agents/briefing.py:436` (prompt assembly line)
- Modify: `~/projects/ai-agents/agents/management_prep.py:300-302` (after Gmail block)

**Step 1: Add Claude Code activity to briefing.py**

After the `gmail_section` block (around line 436), add:

```python
    # Claude Code activity
    claude_code_section = ""
    try:
        cc_state_path = Path.home() / ".cache" / "claude-code-sync" / "state.json"
        if cc_state_path.exists():
            from agents.claude_code_sync import ClaudeCodeSyncState
            cc_state = ClaudeCodeSyncState.model_validate_json(cc_state_path.read_text())
            since = time.time() - (hours * 3600)
            recent = [s for s in cc_state.sessions.values() if s.file_mtime > since]
            if recent:
                projects = set(s.project_name for s in recent)
                claude_code_section = f"\n## Claude Code Activity\n{len(recent)} sessions in lookback: {', '.join(sorted(projects))}.\n"
    except (ImportError, Exception) as exc:
        log.debug("Claude Code context unavailable: %s", exc)

    # Obsidian vault activity
    obsidian_section = ""
    try:
        obs_state_path = Path.home() / ".cache" / "obsidian-sync" / "state.json"
        if obs_state_path.exists():
            from agents.obsidian_sync import ObsidianSyncState
            obs_state = ObsidianSyncState.model_validate_json(obs_state_path.read_text())
            since = time.time() - (hours * 3600)
            recent = [n for n in obs_state.notes.values() if n.mtime > since]
            if recent:
                obsidian_section = f"\n## Vault Activity\n{len(recent)} notes modified: {', '.join(n.title for n in recent[:10])}.\n"
    except (ImportError, Exception) as exc:
        log.debug("Obsidian context unavailable: %s", exc)
```

Add `{claude_code_section}{obsidian_section}` to the prompt assembly line after `{gmail_section}`.

**Step 2: Add Obsidian meeting notes to management_prep.py**

After the Gmail block (around line 300), before `return "\n".join(lines)`:

```python
    # Obsidian: meeting notes matching this person
    try:
        obs_state_path = Path.home() / ".cache" / "obsidian-sync" / "state.json"
        if obs_state_path.exists():
            from agents.obsidian_sync import ObsidianSyncState
            obs_state = ObsidianSyncState.model_validate_json(obs_state_path.read_text())
            name_lower = person.name.lower()
            matching = []
            for n in obs_state.notes.values():
                if "meeting" in n.relative_path.lower() and (
                    name_lower in n.title.lower() or name_lower.split()[0] in n.title.lower()
                ):
                    matching.append(n)
            matching.sort(key=lambda n: n.mtime, reverse=True)
            if matching[:3]:
                lines.append("## Obsidian Meeting Notes")
                for n in matching[:3]:
                    dt = datetime.fromtimestamp(n.mtime, tz=timezone.utc)
                    lines.append(f"- {dt.strftime('%Y-%m-%d')}: {n.title} (vault: {n.relative_path})")
                lines.append("")
    except (ImportError, Exception) as exc:
        log.debug("Obsidian context unavailable: %s", exc)
```

**Step 3: Run tests**

```bash
uv run pytest tests/ -v -k "briefing or management_prep" --timeout=30
```

**Step 4: Commit**

```bash
git add agents/briefing.py agents/management_prep.py
git commit -m "feat: integrate Claude Code and Obsidian context into briefing and management_prep"
```

---

## Task 9: Ingest Auto-tagging + Profiler Registration

**Files:**
- Modify: `~/projects/ai-agents/agents/ingest.py:346-353`
- Modify: `~/projects/ai-agents/agents/profiler_sources.py:31,36-53`

**Step 1: Update ingest.py _SERVICE_PATH_PATTERNS**

Add three new entries to `_SERVICE_PATH_PATTERNS` (around line 346):

```python
        _SERVICE_PATH_PATTERNS = {
            "rag-sources/gdrive": "gdrive",
            "rag-sources/gcalendar": "gcalendar",
            "rag-sources/gmail": "gmail",
            "rag-sources/youtube": "youtube",
            "rag-sources/takeout": "takeout",
            "rag-sources/proton": "proton",
            "rag-sources/claude-code": "claude-code",
            "rag-sources/obsidian": "obsidian",
            "rag-sources/chrome": "chrome",
        }
```

**Step 2: Update profiler_sources.py**

Add to `BRIDGED_SOURCE_TYPES` (line 31):

```python
BRIDGED_SOURCE_TYPES = {"proton", "takeout", "management", "gcalendar", "gmail", "youtube", "claude-code", "obsidian", "chrome"}
```

Add to `SOURCE_TYPE_CHUNK_CAPS` (after youtube line):

```python
    "claude-code": 200,
    "obsidian": 200,
    "chrome": 50,
```

**Step 3: Run tests**

```bash
uv run pytest tests/test_google_auth.py tests/test_gdrive_sync.py -v -k "ingest_auto_tag or profiler"
```

Also verify:

```bash
uv run python -c "from agents.profiler_sources import BRIDGED_SOURCE_TYPES, SOURCE_TYPE_CHUNK_CAPS; print('claude-code' in BRIDGED_SOURCE_TYPES, 'obsidian' in BRIDGED_SOURCE_TYPES, 'chrome' in BRIDGED_SOURCE_TYPES)"
```

Expected: `True True True`

**Step 4: Commit**

```bash
git add agents/ingest.py agents/profiler_sources.py
git commit -m "feat: register claude-code, obsidian, chrome as ingest and profiler sources"
```

---

## Task 10: Systemd Timers

**Files:**
- Create: `~/.config/systemd/user/claude-code-sync.service`
- Create: `~/.config/systemd/user/claude-code-sync.timer`
- Create: `~/.config/systemd/user/obsidian-sync.service`
- Create: `~/.config/systemd/user/obsidian-sync.timer`
- Create: `~/.config/systemd/user/chrome-sync.service`
- Create: `~/.config/systemd/user/chrome-sync.timer`

**Step 1: Create service + timer files**

All services follow the established pattern:

`claude-code-sync.service`:
```ini
[Unit]
Description=Claude Code transcript RAG sync
After=network-online.target
OnFailure=notify-failure@%n.service

[Service]
Type=oneshot
WorkingDirectory=/home/hapaxlegomenon/projects/ai-agents
ExecStart=/home/hapaxlegomenon/.local/bin/uv run python -m agents.claude_code_sync --auto
Environment=PATH=/home/hapaxlegomenon/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/hapaxlegomenon
Environment=GNUPGHOME=/home/hapaxlegomenon/.gnupg
Environment=PASSWORD_STORE_DIR=/home/hapaxlegomenon/.password-store
MemoryMax=512M
SyslogIdentifier=claude-code-sync
```

`claude-code-sync.timer`:
```ini
[Unit]
Description=Claude Code transcript sync every 2 hours

[Timer]
OnCalendar=*-*-* 00/2:15:00
Persistent=true
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
```

`obsidian-sync.service`:
```ini
[Unit]
Description=Obsidian vault RAG sync
OnFailure=notify-failure@%n.service

[Service]
Type=oneshot
WorkingDirectory=/home/hapaxlegomenon/projects/ai-agents
ExecStart=/home/hapaxlegomenon/.local/bin/uv run python -m agents.obsidian_sync --auto
Environment=PATH=/home/hapaxlegomenon/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/hapaxlegomenon
MemoryMax=512M
SyslogIdentifier=obsidian-sync
```

`obsidian-sync.timer`:
```ini
[Unit]
Description=Obsidian vault sync every 30 minutes

[Timer]
OnCalendar=*-*-* *:10/30:00
Persistent=true
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
```

`chrome-sync.service`:
```ini
[Unit]
Description=Chrome history + bookmarks RAG sync
OnFailure=notify-failure@%n.service

[Service]
Type=oneshot
WorkingDirectory=/home/hapaxlegomenon/projects/ai-agents
ExecStart=/home/hapaxlegomenon/.local/bin/uv run python -m agents.chrome_sync --auto
Environment=PATH=/home/hapaxlegomenon/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/hapaxlegomenon
MemoryMax=512M
SyslogIdentifier=chrome-sync
```

`chrome-sync.timer`:
```ini
[Unit]
Description=Chrome history sync every hour

[Timer]
OnCalendar=*-*-* *:20:00
Persistent=true
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
```

**Step 2: Reload systemd and verify**

```bash
systemctl --user daemon-reload
systemctl --user list-unit-files | grep -E "claude-code|obsidian-sync|chrome-sync"
```

Do NOT enable timers yet — Task 12 handles that after integration testing.

---

## Task 11: Documentation Updates

**Files:**
- Modify: `~/projects/hapax-system/rules/system-context.md`
- Modify: `~/projects/hapaxromana/CLAUDE.md`
- Modify: `~/projects/ai-agents/README.md`
- Modify: `~/projects/ai-agents/CLAUDE.md`

**Step 1: Update system-context.md**

Add to Management Agents table:
```
| claude_code_sync | No | `--full-sync`, `--auto`, `--stats` |
| obsidian_sync | No | `--full-sync`, `--auto`, `--stats` |
| chrome_sync | No | `--full-sync`, `--auto`, `--stats` |
```

Add to Management Timers table:
```
| claude-code-sync | Every 2h | Claude Code transcript RAG sync |
| obsidian-sync | Every 30min | Obsidian vault RAG sync |
| chrome-sync | Every 1h | Chrome history + bookmarks sync |
```

**Step 2: Update hapaxromana CLAUDE.md**

Add agents to Tier 2 and timers to Tier 3 sections.

**Step 3: Update ai-agents README.md and CLAUDE.md**

Add agents and timers.

**Step 4: Commit in each repo**

```bash
cd ~/projects/hapax-system && git add -A && git commit -m "docs: add claude-code-sync, obsidian-sync, chrome-sync to system context"
cd ~/projects/hapaxromana && git add -A && git commit -m "docs: update architecture with Phase 4 sync agents"
cd ~/projects/ai-agents && git add -A && git commit -m "docs: update README and CLAUDE.md with Phase 4 agents"
```

---

## Task 12: Integration Test — Full Sync + Enable Timers

**Step 1: Run Claude Code full sync**

```bash
cd ~/projects/ai-agents && uv run python -m agents.claude_code_sync --full-sync -v
uv run python -m agents.claude_code_sync --stats
```

Verify: `rag-sources/claude-code/` has subdirectories per project with `.md` files.

**Step 2: Run Obsidian full sync**

```bash
uv run python -m agents.obsidian_sync --full-sync -v
uv run python -m agents.obsidian_sync --stats
```

Verify: `rag-sources/obsidian/` has subdirectories with note files.

**Step 3: Run Chrome full sync**

```bash
uv run python -m agents.chrome_sync --full-sync -v
uv run python -m agents.chrome_sync --stats
```

Verify: `rag-sources/chrome/` has domain files and bookmarks.md.

**Step 4: Verify rag-ingest picks up files**

```bash
ls ~/documents/rag-sources/claude-code/ | head -5
ls ~/documents/rag-sources/obsidian/ | head -5
ls ~/documents/rag-sources/chrome/ | head -5
```

**Step 5: Enable timers**

```bash
systemctl --user enable --now claude-code-sync.timer
systemctl --user enable --now obsidian-sync.timer
systemctl --user enable --now chrome-sync.timer
systemctl --user list-timers | grep -E "claude-code|obsidian|chrome|gdrive|gcalendar|gmail|youtube"
```

**Step 6: Run all tests**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_claude_code_sync.py tests/test_obsidian_sync.py tests/test_chrome_sync.py tests/test_google_auth.py tests/test_gmail_sync.py tests/test_youtube_sync.py tests/test_gcalendar_sync.py tests/test_calendar_context.py tests/test_gdrive_sync.py -v
```

---

## Summary

| Task | Description | Type |
|------|-------------|------|
| 1 | Claude Code skeleton + schemas | Core |
| 2 | Claude Code parsing + formatting | Core |
| 3 | Claude Code discovery, sync, profiler, CLI | Core |
| 4 | Obsidian skeleton + schemas | Core |
| 5 | Obsidian parsing, formatting, sync, profiler, CLI | Core |
| 6 | Chrome skeleton + schemas | Core |
| 7 | Chrome history, bookmarks, formatting, profiler, CLI | Core |
| 8 | Agent modifications (briefing, management_prep) | Integration |
| 9 | Ingest auto-tagging + profiler registration | Integration |
| 10 | Systemd timers (6 files) | Operations |
| 11 | Documentation updates across repos | Documentation |
| 12 | Integration test + enable timers | Verification |

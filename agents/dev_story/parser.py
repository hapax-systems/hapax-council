"""Streaming JSONL parser for Claude Code session transcripts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from agents.dev_story.models import (
    FileChange,
    Message,
    Session,
    ToolCall,
)

log = logging.getLogger(__name__)


@dataclass
class ParsedSession:
    """Result of parsing a single session JSONL file."""

    session: Session
    messages: list[Message] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    file_changes: list[FileChange] = field(default_factory=list)


def extract_project_path(encoded: str) -> str:
    """Decode Claude Code's project directory encoding.

    Claude encodes /home/user/projects/foo as -home-user-projects-foo.
    Since `-` encodes both `/` and literal hyphens, we try the naive decode
    first, then progressively rejoin segments to find a path that exists.

    For deleted/renamed directories, returns the best-effort decode even
    if the path no longer exists on disk.
    """
    from pathlib import Path as _Path

    segments = encoded.lstrip("-").split("-")
    # Naive: every - is a /
    naive = "/" + "/".join(segments)
    if _Path(naive).is_dir():
        return naive

    # Try combining adjacent segments with hyphens to find existing paths
    # Strategy: build path from left, at each step try extending current
    # segment with a hyphen before trying a new directory level
    resolved = _resolve_path_segments(segments)
    if _Path(resolved).is_dir():
        return resolved

    # Path doesn't exist — likely renamed/deleted. Try re-hyphenating
    # the project name from the deepest existing ancestor. Only do this
    # when the ancestor is deep enough (at least 3 levels, e.g.,
    # /home/user/projects) to avoid false merges on short/unknown paths.
    return _resolve_deleted_path(segments, resolved)


def _resolve_path_segments(segments: list[str]) -> str:
    """Resolve ambiguous path segments by checking filesystem."""
    from pathlib import Path as _Path

    if not segments:
        return "/"

    # Build path greedily: at each position, try extending with hyphen first
    # (to preserve names like "ai-agents"), fall back to directory separator
    result_parts: list[str] = [segments[0]]

    for seg in segments[1:]:
        # Try joining with hyphen (keeping as part of current name)
        candidate_hyphen = "/" + "/".join(result_parts[:-1] + [result_parts[-1] + "-" + seg])
        # Try as new directory level
        candidate_slash = "/" + "/".join(result_parts + [seg])

        if _Path(candidate_hyphen).exists() or _Path(candidate_hyphen).parent.is_dir():
            # Check if the hyphenated version leads to a valid path
            hyphen_parent = _Path(candidate_hyphen).parent
            _Path(candidate_slash).parent
            # Prefer hyphen if the parent exists and has this entry
            if _Path(candidate_hyphen).is_dir():
                result_parts[-1] = result_parts[-1] + "-" + seg
                continue
            elif _Path(candidate_slash).is_dir():
                result_parts.append(seg)
                continue
            # Neither is a directory yet — check which parent path is more viable
            if hyphen_parent.is_dir() and (hyphen_parent / (result_parts[-1] + "-" + seg)).exists():
                result_parts[-1] = result_parts[-1] + "-" + seg
            else:
                result_parts.append(seg)
        else:
            result_parts.append(seg)

    return "/" + "/".join(result_parts)


def _resolve_deleted_path(segments: list[str], fallback: str) -> str:
    """Handle paths for renamed/deleted directories.

    When a project directory no longer exists, we can't use filesystem checks
    to disambiguate. Strategy: find the deepest existing parent directory,
    then try joining remaining segments with hyphens (since project names
    like 'hapax-containerization' are common).

    Only re-hyphenates when the deepest existing parent is at least 3 levels
    deep (e.g., /home/user/projects), to avoid false merges on unknown paths.
    """
    from pathlib import Path as _Path

    # Build path from left, finding the deepest existing directory
    known_parts: list[str] = []
    remaining_start = 0

    for i, seg in enumerate(segments):
        candidate = "/" + "/".join(known_parts + [seg])
        if _Path(candidate).is_dir():
            known_parts.append(seg)
            remaining_start = i + 1
        else:
            break

    if remaining_start >= len(segments):
        return "/" + "/".join(known_parts)

    # Only re-hyphenate if we found a deep enough parent (at least 3 levels).
    # For shallow paths (e.g., /home is the only known dir), the fallback
    # from _resolve_path_segments is already the best guess.
    if len(known_parts) < 3:
        return fallback

    remaining = segments[remaining_start:]
    if not remaining:
        return fallback

    parent = "/" + "/".join(known_parts)

    # Join all remaining segments with hyphens — most likely a single
    # hyphenated project name (e.g., "hapax-containerization")
    return parent + "/" + "-".join(remaining)


def _extract_content_text(content) -> str:
    """Extract plain text from message content (string or list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


def _extract_tool_calls(message_id: str, content) -> list[ToolCall]:
    """Extract tool_use blocks from assistant message content."""
    if not isinstance(content, list):
        return []
    calls = []
    for i, block in enumerate(content):
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = block.get("name", "unknown")
            inp = block.get("input", {})
            # Summarize arguments: file_path for file tools, command for Bash, pattern for Grep
            summary = inp.get("file_path") or inp.get("command") or inp.get("pattern")
            calls.append(
                ToolCall(
                    message_id=message_id,
                    tool_name=name,
                    arguments_summary=summary,
                    sequence_position=i,
                )
            )
    return calls


def _extract_file_changes(entry: dict) -> list[FileChange]:
    """Extract file changes from a file-history-snapshot entry."""
    snapshot = entry.get("snapshot", {})
    message_id = entry.get("messageId", "")
    backups = snapshot.get("trackedFileBackups", {})
    changes = []
    for file_path, info in backups.items():
        version = info.get("version", 0)
        backup_time = info.get("backupTime", snapshot.get("timestamp", ""))
        change_type = "created" if version <= 1 else "modified"
        changes.append(
            FileChange(
                message_id=message_id,
                file_path=file_path,
                version=version,
                change_type=change_type,
                timestamp=backup_time,
            )
        )
    return changes


def parse_session(path: Path, project_path: str) -> ParsedSession:
    """Parse a session JSONL file into structured data.

    Streams line-by-line to handle large files (some are 27MB+).
    """
    messages: list[Message] = []
    tool_calls: list[ToolCall] = []
    file_changes: list[FileChange] = []

    session_id: str | None = None
    git_branch: str | None = None
    first_ts: str | None = None
    last_ts: str | None = None
    total_tokens_in = 0
    total_tokens_out = 0
    model_counts: dict[str, int] = {}

    with open(path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                log.debug("Skipping malformed line %d in %s", line_num, path.name)
                continue

            entry_type = entry.get("type")
            ts = entry.get("timestamp")

            if ts:
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts

            if session_id is None:
                session_id = entry.get("sessionId")
            if git_branch is None:
                git_branch = entry.get("gitBranch")

            if entry_type in ("user", "assistant"):
                msg_data = entry.get("message", {})
                uuid = entry.get("uuid", f"line-{line_num}")
                content = msg_data.get("content", "")
                content_text = _extract_content_text(content)

                usage = msg_data.get("usage", {})
                t_in = usage.get("input_tokens", 0) or 0
                t_out = usage.get("output_tokens", 0) or 0
                model = msg_data.get("model")

                if model:
                    model_counts[model] = model_counts.get(model, 0) + 1

                messages.append(
                    Message(
                        id=uuid,
                        session_id=session_id or path.stem,
                        parent_id=entry.get("parentUuid"),
                        role=msg_data.get("role", entry_type),
                        timestamp=ts or "",
                        content_text=content_text,
                        model=model,
                        tokens_in=t_in,
                        tokens_out=t_out,
                    )
                )

                total_tokens_in += t_in
                total_tokens_out += t_out

                # Extract tool calls from assistant messages
                if entry_type == "assistant":
                    tool_calls.extend(_extract_tool_calls(uuid, content))

            elif entry_type == "file-history-snapshot":
                file_changes.extend(_extract_file_changes(entry))

    # Determine primary model
    model_primary = None
    if model_counts:
        model_primary = max(model_counts, key=model_counts.get)

    project_name = Path(project_path).name if project_path else path.parent.name

    session = Session(
        id=session_id or path.stem,
        project_path=project_path,
        project_name=project_name,
        started_at=first_ts or "",
        ended_at=last_ts,
        git_branch=git_branch,
        message_count=len(messages),
        total_tokens_in=total_tokens_in,
        total_tokens_out=total_tokens_out,
        model_primary=model_primary,
    )

    return ParsedSession(
        session=session,
        messages=messages,
        tool_calls=tool_calls,
        file_changes=file_changes,
    )

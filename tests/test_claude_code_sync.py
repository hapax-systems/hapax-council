"""Tests for claude_code_sync — parsing, discovery, formatting, profiler facts."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


def test_transcript_metadata_defaults():
    from agents.claude_code_sync import TranscriptMetadata

    m = TranscriptMetadata()
    assert m.session_id == ""
    assert m.project_path == ""
    assert m.project_name == ""
    assert m.message_count == 0
    assert m.first_message_at == ""
    assert m.last_message_at == ""
    assert m.file_size == 0
    assert m.file_mtime == 0.0


def test_sync_state_empty():
    from agents.claude_code_sync import ClaudeCodeSyncState

    s = ClaudeCodeSyncState()
    assert s.sessions == {}
    assert s.last_sync == 0.0
    assert s.stats == {}


def test_decode_project_dir():
    from agents.claude_code_sync import _decode_project_dir

    # Synthetic path — decoder splits on dashes and tries to find existing dirs.
    # /tmp always exists, so -tmp should decode to /tmp.
    decoded = _decode_project_dir("-tmp")
    assert decoded == "/tmp"

    # Edge case: non-existent path falls back to slash-joining all parts
    decoded2 = _decode_project_dir("-nonexistent-path-segments")
    assert decoded2.startswith("/")

    # Edge case: dirname without leading dash
    assert _decode_project_dir("plainname") == "plainname"


def test_parse_transcript_messages():
    from agents.claude_code_sync import _parse_transcript

    lines = [
        # User message (string content)
        json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": "How do I fix this bug?"},
                "timestamp": "2026-03-08T10:00:00Z",
                "sessionId": "sess-123",
            }
        ),
        # Assistant message (list content with text + tool_use + thinking)
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "text": "Let me think about this..."},
                        {"type": "text", "text": "Here is the fix."},
                        {"type": "tool_use", "name": "read_file", "input": {"path": "/tmp/foo"}},
                        {"type": "text", "text": "You should also check the config."},
                    ],
                },
                "timestamp": "2026-03-08T10:00:05Z",
            }
        ),
        # Progress entry (should be skipped)
        json.dumps(
            {
                "type": "progress",
                "message": "Processing...",
                "timestamp": "2026-03-08T10:00:03Z",
            }
        ),
        # file-history-snapshot (should be skipped)
        json.dumps(
            {
                "type": "file-history-snapshot",
                "files": ["/tmp/foo.py"],
            }
        ),
        # Another user message
        json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": "Thanks!"},
                "timestamp": "2026-03-08T10:01:00Z",
            }
        ),
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        for line in lines:
            f.write(line + "\n")
        tmp_path = Path(f.name)

    try:
        messages = _parse_transcript(tmp_path)

        # Should have 3 messages: user, assistant (text only), user
        assert len(messages) == 3

        # First message: user
        assert messages[0][0] == "user"
        assert messages[0][1] == "How do I fix this bug?"
        assert messages[0][2] == "2026-03-08T10:00:00Z"

        # Second message: assistant (only text blocks, no thinking/tool_use)
        assert messages[1][0] == "assistant"
        assert "Here is the fix." in messages[1][1]
        assert "You should also check the config." in messages[1][1]
        assert "Let me think" not in messages[1][1]
        assert "read_file" not in messages[1][1]

        # Third message: user
        assert messages[2][0] == "user"
        assert messages[2][1] == "Thanks!"
    finally:
        tmp_path.unlink()


def test_format_session_markdown():
    from agents.claude_code_sync import TranscriptMetadata, _format_session_markdown

    meta = TranscriptMetadata(
        session_id="abc-123",
        project_path="/home/user/projects/myapp",
        project_name="myapp",
        message_count=2,
        first_message_at="2026-03-08T10:00:00Z",
        last_message_at="2026-03-08T10:05:00Z",
    )

    messages = [
        ("user", "How do I fix this?", "2026-03-08T10:00:00Z"),
        ("assistant", "Here is the fix.", "2026-03-08T10:05:00Z"),
    ]

    md = _format_session_markdown(meta, messages)

    # Check frontmatter fields
    assert "platform: claude" in md
    assert "source_service: claude-code" in md
    assert "project: myapp" in md
    assert "session_id: abc-123" in md
    # Check content
    assert "## User" in md
    assert "## Assistant" in md
    assert "How do I fix this?" in md
    assert "Here is the fix." in md


def test_discover_projects():
    from agents.claude_code_sync import _discover_projects

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)

        # Create project dirs with JSONL files
        proj1 = base / "-home-user-projects-alpha"
        proj1.mkdir()
        (proj1 / "session1.jsonl").write_text('{"type":"user"}\n')
        (proj1 / "session2.jsonl").write_text('{"type":"user"}\n')

        proj2 = base / "-home-user-projects-beta"
        proj2.mkdir()
        (proj2 / "session3.jsonl").write_text('{"type":"user"}\n')

        # Empty dir (no JSONL) — should be skipped
        empty = base / "-home-user-projects-gamma"
        empty.mkdir()

        # Non-directory file — should be skipped
        (base / "stray-file.txt").write_text("noise")

        projects = _discover_projects(base)

        assert len(projects) == 2
        names = {p[0] for p in projects}
        assert "alpha" in names
        assert "beta" in names

        # Check file counts
        for name, _path, files in projects:
            if name == "alpha":
                assert len(files) == 2
            elif name == "beta":
                assert len(files) == 1


def test_generate_profile_facts():
    from agents.claude_code_sync import (
        ClaudeCodeSyncState,
        TranscriptMetadata,
        _generate_profile_facts,
    )

    state = ClaudeCodeSyncState()
    state.sessions = {
        "/path/sess1.jsonl": TranscriptMetadata(
            session_id="sess1",
            project_name="ai-agents",
            project_path="/home/user/projects/ai-agents",
            message_count=42,
        ),
        "/path/sess2.jsonl": TranscriptMetadata(
            session_id="sess2",
            project_name="ai-agents",
            project_path="/home/user/projects/ai-agents",
            message_count=18,
        ),
        "/path/sess3.jsonl": TranscriptMetadata(
            session_id="sess3",
            project_name="hapax-logos",
            project_path="/home/user/projects/hapax-logos",
            message_count=30,
        ),
    }

    facts = _generate_profile_facts(state)
    assert len(facts) >= 2

    dims = {f["dimension"] for f in facts}
    assert "tool_usage" in dims

    keys = {f["key"] for f in facts}
    assert "claude_code_projects" in keys
    assert "claude_code_activity" in keys

    # Check activity fact includes correct totals
    activity = next(f for f in facts if f["key"] == "claude_code_activity")
    assert "3 sessions" in activity["value"]
    assert "90 messages" in activity["value"]
    assert "2 projects" in activity["value"]

    # Check projects fact mentions top project
    projects_fact = next(f for f in facts if f["key"] == "claude_code_projects")
    assert "ai-agents" in projects_fact["value"]

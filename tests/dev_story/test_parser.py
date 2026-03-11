"""Tests for JSONL session transcript parser."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agents.dev_story.parser import (
    parse_session,
    extract_project_path,
    ParsedSession,
)


def _write_jsonl(lines: list[dict], path: Path) -> None:
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def test_extract_project_path_from_encoded_dirname():
    assert extract_project_path("-home-user-projects-foo") == "/home/user/projects/foo"


def test_extract_project_path_preserves_simple():
    assert extract_project_path("-home-user-myproject") == "/home/user/myproject"


def test_parse_session_empty_file():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w") as f:
        f.write("")
        f.flush()
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert result.messages == []
    assert result.tool_calls == []
    assert result.file_changes == []


def test_parse_session_extracts_user_message():
    lines = [
        {
            "type": "user",
            "uuid": "u1",
            "parentUuid": None,
            "sessionId": "sess-1",
            "timestamp": "2026-03-10T10:00:00.000Z",
            "message": {"role": "user", "content": "hello world"},
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        _write_jsonl(lines, Path(f.name))
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert len(result.messages) == 1
    assert result.messages[0].role == "user"
    assert result.messages[0].content_text == "hello world"
    assert result.messages[0].id == "u1"


def test_parse_session_extracts_assistant_message_strips_tool_use():
    lines = [
        {
            "type": "assistant",
            "uuid": "a1",
            "parentUuid": "u1",
            "sessionId": "sess-1",
            "timestamp": "2026-03-10T10:00:01.000Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-5-20250514",
                "content": [
                    {"type": "text", "text": "Let me check that."},
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/tmp/foo.py"}},
                ],
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        _write_jsonl(lines, Path(f.name))
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert len(result.messages) == 1
    msg = result.messages[0]
    assert msg.content_text == "Let me check that."
    assert msg.model == "claude-sonnet-4-5-20250514"
    assert msg.tokens_in == 100
    assert msg.tokens_out == 50


def test_parse_session_extracts_tool_calls():
    lines = [
        {
            "type": "assistant",
            "uuid": "a1",
            "sessionId": "sess-1",
            "timestamp": "2026-03-10T10:00:01.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/tmp/foo.py"}},
                    {"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "/tmp/foo.py", "old_string": "a", "new_string": "b"}},
                ],
            },
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        _write_jsonl(lines, Path(f.name))
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0].tool_name == "Read"
    assert result.tool_calls[0].sequence_position == 0
    assert result.tool_calls[0].arguments_summary == "/tmp/foo.py"
    assert result.tool_calls[1].tool_name == "Edit"
    assert result.tool_calls[1].sequence_position == 1


def test_parse_session_extracts_file_history_snapshot():
    lines = [
        {
            "type": "file-history-snapshot",
            "messageId": "m1",
            "snapshot": {
                "trackedFileBackups": {
                    "shared/config.py": {
                        "backupFileName": "abc123@v2",
                        "version": 2,
                        "backupTime": "2026-03-10T10:00:02.000Z",
                    },
                    "agents/foo.py": {
                        "backupFileName": "def456@v1",
                        "version": 1,
                        "backupTime": "2026-03-10T10:00:01.000Z",
                    },
                },
                "timestamp": "2026-03-10T10:00:03.000Z",
            },
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        _write_jsonl(lines, Path(f.name))
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert len(result.file_changes) == 2
    paths = {fc.file_path for fc in result.file_changes}
    assert "shared/config.py" in paths
    assert "agents/foo.py" in paths


def test_parse_session_computes_session_metadata():
    lines = [
        {
            "type": "user",
            "uuid": "u1",
            "sessionId": "sess-1",
            "timestamp": "2026-03-10T10:00:00.000Z",
            "gitBranch": "main",
            "message": {"role": "user", "content": "start"},
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "sessionId": "sess-1",
            "timestamp": "2026-03-10T10:05:00.000Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-5-20250514",
                "content": [{"type": "text", "text": "done"}],
                "usage": {"input_tokens": 200, "output_tokens": 100},
            },
        },
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        _write_jsonl(lines, Path(f.name))
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert result.session.id == "sess-1"
    assert result.session.started_at == "2026-03-10T10:00:00.000Z"
    assert result.session.ended_at == "2026-03-10T10:05:00.000Z"
    assert result.session.message_count == 2
    assert result.session.git_branch == "main"
    assert result.session.total_tokens_in == 200
    assert result.session.total_tokens_out == 100


def test_parse_session_handles_malformed_lines():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        f.write("not valid json\n")
        f.write(json.dumps({"type": "user", "uuid": "u1", "sessionId": "s1",
                            "timestamp": "2026-03-10T10:00:00Z",
                            "message": {"role": "user", "content": "ok"}}) + "\n")
        f.flush()
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert len(result.messages) == 1


def test_parse_session_content_list_with_text_blocks():
    """User messages can have content as list of blocks."""
    lines = [
        {
            "type": "user",
            "uuid": "u1",
            "sessionId": "sess-1",
            "timestamp": "2026-03-10T10:00:00.000Z",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "part one "},
                    {"type": "text", "text": "part two"},
                ],
            },
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        _write_jsonl(lines, Path(f.name))
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert result.messages[0].content_text == "part one part two"

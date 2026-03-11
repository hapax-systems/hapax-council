"""Tests for shared.llm_export_converter — platform parsers, markdown rendering, CLI.

No LLM calls, no network. All tests use tmp_path and in-memory ZIPs.
"""
import json
import zipfile
from pathlib import Path

import pytest

from shared.llm_export_converter import (
    Conversation,
    ConvertResult,
    Message,
    convert_export,
    conversation_to_markdown,
    parse_claude_zip,
    parse_gemini_zip,
    sanitize_filename,
)
from agents.profiler_sources import (
    DiscoveredSources,
    SourceChunk,
    _short_path,
    list_source_ids,
    read_llm_export,
    LLM_EXPORT_DIR,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_zip(tmp_path: Path, filename: str, files: dict[str, str]) -> Path:
    """Create a ZIP file with the given name→content mapping."""
    zip_path = tmp_path / filename
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return zip_path


def _make_claude_zip(tmp_path: Path, conversations: list[dict]) -> Path:
    return _make_zip(tmp_path, "claude-export.zip", {
        "conversations.json": json.dumps(conversations),
    })


def _make_gemini_zip(tmp_path: Path, conv_files: dict[str, dict]) -> Path:
    files = {name: json.dumps(data) for name, data in conv_files.items()}
    return _make_zip(tmp_path, "gemini-takeout.zip", files)


# ── Data model tests ────────────────────────────────────────────────────────

def test_message_defaults():
    msg = Message(role="user", content="Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"
    assert msg.timestamp == ""
    assert msg.attachments == []


def test_conversation_defaults():
    conv = Conversation(id="abc", title="Test", platform="claude",
                        created_at="", updated_at="")
    assert conv.messages == []
    assert conv.platform == "claude"


def test_convert_result_fields():
    result = ConvertResult(total=10, written=8, skipped=2, output_dir=Path("/tmp"))
    assert result.total == 10
    assert result.written == 8
    assert result.skipped == 2


# ── Filename sanitization tests ─────────────────────────────────────────────

def test_sanitize_uuid_passthrough():
    assert sanitize_filename("abc-123-def") == "abc-123-def"


def test_sanitize_special_chars():
    result = sanitize_filename("hello world/foo:bar")
    assert "/" not in result
    assert ":" not in result
    assert " " not in result


def test_sanitize_truncation():
    long_name = "a" * 100
    result = sanitize_filename(long_name)
    assert len(result) <= 64


def test_sanitize_empty():
    assert sanitize_filename("") == "untitled"


def test_sanitize_only_special_chars():
    assert sanitize_filename("///") == "untitled"


def test_sanitize_collapses_hyphens():
    result = sanitize_filename("a   b   c")
    assert "--" not in result


# ── Markdown rendering tests ────────────────────────────────────────────────

def test_markdown_basic_conversation():
    conv = Conversation(
        id="test-1", title="Test Conv", platform="claude",
        created_at="2025-01-01T00:00:00Z", updated_at="2025-01-01T01:00:00Z",
        messages=[
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
        ],
    )
    md = conversation_to_markdown(conv)
    assert "---" in md
    assert "platform: claude" in md
    assert 'title: "Test Conv"' in md
    assert "message_count: 2" in md
    assert "## User" in md
    assert "## Assistant" in md
    assert "Hello" in md
    assert "Hi there" in md


def test_markdown_frontmatter_fields():
    conv = Conversation(
        id="abc-123", title="My Chat", platform="gemini",
        created_at="2025-06-15T10:00:00Z", updated_at="2025-06-15T11:00:00Z",
        messages=[],
    )
    md = conversation_to_markdown(conv)
    assert "conversation_id: abc-123" in md
    assert "platform: gemini" in md
    assert "created_at: 2025-06-15T10:00:00Z" in md


def test_markdown_with_attachments():
    conv = Conversation(
        id="att-1", title="Attachments", platform="claude",
        created_at="", updated_at="",
        messages=[
            Message(role="user", content="See file",
                    attachments=["data.csv", "notes.txt"]),
        ],
    )
    md = conversation_to_markdown(conv)
    assert "**Attachments:**" in md
    assert "- data.csv" in md
    assert "- notes.txt" in md


def test_markdown_with_timestamp():
    conv = Conversation(
        id="ts-1", title="Timestamps", platform="claude",
        created_at="", updated_at="",
        messages=[
            Message(role="user", content="Hello",
                    timestamp="2025-01-01T00:00:00Z"),
        ],
    )
    md = conversation_to_markdown(conv)
    assert "## User (2025-01-01T00:00:00Z)" in md


def test_markdown_special_chars_in_title():
    conv = Conversation(
        id="sc-1", title='Title with "quotes" and stuff',
        platform="gemini", created_at="", updated_at="",
        messages=[],
    )
    md = conversation_to_markdown(conv)
    assert '\\"quotes\\"' in md


# ── Claude parser tests ─────────────────────────────────────────────────────

def test_claude_minimal(tmp_path):
    zp = _make_claude_zip(tmp_path, [{
        "uuid": "conv-1",
        "name": "Test Chat",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T01:00:00Z",
        "chat_messages": [
            {"sender": "user", "text": "Hello", "created_at": "2025-01-01T00:00:00Z"},
            {"sender": "assistant", "text": "Hi", "created_at": "2025-01-01T00:01:00Z"},
        ],
    }])
    convs = parse_claude_zip(zp)
    assert len(convs) == 1
    assert convs[0].id == "conv-1"
    assert convs[0].title == "Test Chat"
    assert convs[0].platform == "claude"
    assert len(convs[0].messages) == 2
    assert convs[0].messages[0].role == "user"
    assert convs[0].messages[1].role == "assistant"


def test_claude_human_sender(tmp_path):
    """Older Claude exports use 'human' instead of 'user'."""
    zp = _make_claude_zip(tmp_path, [{
        "uuid": "conv-2",
        "name": "Old Export",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T01:00:00Z",
        "chat_messages": [
            {"sender": "human", "text": "Hello old format"},
        ],
    }])
    convs = parse_claude_zip(zp)
    assert convs[0].messages[0].role == "user"
    assert convs[0].messages[0].content == "Hello old format"


def test_claude_with_attachments(tmp_path):
    zp = _make_claude_zip(tmp_path, [{
        "uuid": "conv-3",
        "name": "Attachments",
        "created_at": "",
        "updated_at": "",
        "chat_messages": [
            {
                "sender": "user",
                "text": "Check this file",
                "attachments": [
                    {"file_name": "report.pdf"},
                    {"file_name": "data.csv"},
                ],
            },
        ],
    }])
    convs = parse_claude_zip(zp)
    assert convs[0].messages[0].attachments == ["report.pdf", "data.csv"]


def test_claude_empty_export(tmp_path):
    zp = _make_claude_zip(tmp_path, [])
    convs = parse_claude_zip(zp)
    assert convs == []


def test_claude_missing_fields(tmp_path):
    zp = _make_claude_zip(tmp_path, [{
        "uuid": "conv-4",
        "chat_messages": [
            {"sender": "user", "text": "Minimal"},
        ],
    }])
    convs = parse_claude_zip(zp)
    assert len(convs) == 1
    assert convs[0].title == "Untitled"
    assert convs[0].messages[0].content == "Minimal"


def test_claude_skips_empty_text(tmp_path):
    zp = _make_claude_zip(tmp_path, [{
        "uuid": "conv-5",
        "name": "Empty msgs",
        "created_at": "",
        "updated_at": "",
        "chat_messages": [
            {"sender": "user", "text": ""},
            {"sender": "assistant", "text": "Real answer"},
        ],
    }])
    convs = parse_claude_zip(zp)
    assert len(convs[0].messages) == 1
    assert convs[0].messages[0].role == "assistant"


def test_claude_no_conversations_json(tmp_path):
    zp = _make_zip(tmp_path, "bad.zip", {"other.txt": "hello"})
    convs = parse_claude_zip(zp)
    assert convs == []


# ── Gemini parser tests ──────────────────────────────────────────────────────

def test_gemini_basic(tmp_path):
    zp = _make_gemini_zip(tmp_path, {
        "Takeout/Gemini/conversation1.json": {
            "id": "gem-1",
            "title": "Gemini Chat",
            "create_time": "2025-02-01T00:00:00Z",
            "update_time": "2025-02-01T01:00:00Z",
            "messages": [
                {"author": "user", "content": "Hello Gemini"},
                {"author": "model", "content": "Hello! How can I help?"},
            ],
        },
    })
    convs = parse_gemini_zip(zp)
    assert len(convs) == 1
    assert convs[0].platform == "gemini"
    assert convs[0].title == "Gemini Chat"
    assert len(convs[0].messages) == 2
    assert convs[0].messages[0].role == "user"
    assert convs[0].messages[1].role == "assistant"  # "model" → "assistant"


def test_gemini_with_parts(tmp_path):
    zp = _make_gemini_zip(tmp_path, {
        "Takeout/Gemini/conv2.json": {
            "id": "gem-2",
            "title": "Parts Format",
            "messages": [
                {"author": "user", "parts": [{"text": "Multi"}, {"text": "part"}]},
            ],
        },
    })
    convs = parse_gemini_zip(zp)
    assert convs[0].messages[0].content == "Multi part"


def test_gemini_empty_zip(tmp_path):
    zp = _make_zip(tmp_path, "empty.zip", {"readme.txt": "nothing"})
    convs = parse_gemini_zip(zp)
    assert convs == []


def test_gemini_multiple_files(tmp_path):
    zp = _make_gemini_zip(tmp_path, {
        "Takeout/Gemini/conv1.json": {
            "id": "g1", "title": "First",
            "messages": [{"author": "user", "content": "A"}],
        },
        "Takeout/Gemini/conv2.json": {
            "id": "g2", "title": "Second",
            "messages": [{"author": "user", "content": "B"}],
        },
    })
    convs = parse_gemini_zip(zp)
    assert len(convs) == 2


def test_gemini_skips_empty_content(tmp_path):
    zp = _make_gemini_zip(tmp_path, {
        "Takeout/Gemini/conv.json": {
            "id": "g3", "title": "Empty",
            "messages": [
                {"author": "user", "content": ""},
                {"author": "model", "content": "Real answer"},
            ],
        },
    })
    convs = parse_gemini_zip(zp)
    assert len(convs[0].messages) == 1
    assert convs[0].messages[0].role == "assistant"


# ── End-to-end conversion tests ─────────────────────────────────────────────

def test_e2e_files_written(tmp_path):
    zp = _make_claude_zip(tmp_path, [{
        "uuid": "e2e-1",
        "name": "E2E Test",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T01:00:00Z",
        "chat_messages": [
            {"sender": "user", "text": "Hello"},
        ],
    }])
    out_dir = tmp_path / "output"
    result = convert_export(zp, "claude", out_dir)
    assert result.written == 1
    assert result.total == 1
    assert result.skipped == 0
    # Check file exists
    md_files = list((out_dir / "claude").glob("*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text()
    assert "platform: claude" in content
    assert "Hello" in content


def test_e2e_idempotent(tmp_path):
    zp = _make_claude_zip(tmp_path, [{
        "uuid": "idem-1",
        "name": "Idempotent",
        "created_at": "",
        "updated_at": "",
        "chat_messages": [
            {"sender": "user", "text": "Same content"},
        ],
    }])
    out_dir = tmp_path / "output"
    convert_export(zp, "claude", out_dir)
    convert_export(zp, "claude", out_dir)
    # Should still be exactly 1 file (overwritten, not duplicated)
    md_files = list((out_dir / "claude").glob("*.md"))
    assert len(md_files) == 1


def test_e2e_since_filter(tmp_path):
    zp = _make_claude_zip(tmp_path, [
        {
            "uuid": "old-1",
            "name": "Old Chat",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T01:00:00Z",
            "chat_messages": [{"sender": "user", "text": "Old"}],
        },
        {
            "uuid": "new-1",
            "name": "New Chat",
            "created_at": "2025-06-01T00:00:00Z",
            "updated_at": "2025-06-01T01:00:00Z",
            "chat_messages": [{"sender": "user", "text": "New"}],
        },
    ])
    out_dir = tmp_path / "output"
    result = convert_export(zp, "claude", out_dir, since="2025-01-01")
    assert result.written == 1
    assert result.skipped == 1


def test_e2e_dry_run(tmp_path):
    zp = _make_claude_zip(tmp_path, [{
        "uuid": "dry-1",
        "name": "Dry Run",
        "created_at": "",
        "updated_at": "",
        "chat_messages": [{"sender": "user", "text": "Test"}],
    }])
    out_dir = tmp_path / "output"
    result = convert_export(zp, "claude", out_dir, dry_run=True)
    assert result.written == 1
    # But no files should actually be written
    assert not (out_dir / "claude").exists()


def test_e2e_empty_conversations_skipped(tmp_path):
    zp = _make_claude_zip(tmp_path, [{
        "uuid": "empty-1",
        "name": "No Messages",
        "created_at": "",
        "updated_at": "",
        "chat_messages": [],
    }])
    out_dir = tmp_path / "output"
    result = convert_export(zp, "claude", out_dir)
    assert result.written == 0
    assert result.skipped == 1


def test_e2e_unknown_platform(tmp_path):
    zp = _make_zip(tmp_path, "test.zip", {"a.txt": "hi"})
    with pytest.raises(ValueError, match="Unknown platform"):
        convert_export(zp, "chatgpt", tmp_path / "out")


def test_e2e_gemini(tmp_path):
    zp = _make_gemini_zip(tmp_path, {
        "Takeout/Gemini/conv.json": {
            "id": "gem-e2e",
            "title": "E2E Gemini",
            "create_time": "2025-01-01T00:00:00Z",
            "messages": [
                {"author": "user", "content": "Hello"},
                {"author": "model", "content": "World"},
            ],
        },
    })
    out_dir = tmp_path / "output"
    result = convert_export(zp, "gemini", out_dir)
    assert result.written == 1
    content = (out_dir / "gemini" / "gem-e2e.md").read_text()
    assert "platform: gemini" in content
    assert "## Assistant" in content  # "model" mapped to "assistant"


# ── Profiler integration tests ──────────────────────────────────────────────

def test_profiler_discovery_finds_md_files(tmp_path, monkeypatch):
    """Discovery should find .md files under LLM_EXPORT_DIR."""
    import agents.profiler_sources as ps

    export_dir = tmp_path / "llm-conversations"
    claude_dir = export_dir / "claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "conv-1.md").write_text("---\nplatform: claude\n---\n## User\nHello")
    (claude_dir / "conv-2.md").write_text("---\nplatform: claude\n---\n## User\nWorld")

    monkeypatch.setattr(ps, "LLM_EXPORT_DIR", export_dir)
    # Prevent scanning real filesystem
    monkeypatch.setattr(ps, "CLAUDE_DIR", tmp_path / "nonexistent-claude")
    monkeypatch.setattr(ps, "PROJECTS_DIR", tmp_path / "nonexistent-projects")
    monkeypatch.setattr(ps, "HOME", tmp_path)
    monkeypatch.setattr(ps, "_check_langfuse_available", lambda: False)

    sources = ps.discover_sources()
    assert len(sources.llm_export_files) == 2

    ids = ps.list_source_ids(sources)
    llm_ids = [i for i in ids if i.startswith("llm-export:")]
    assert len(llm_ids) == 2


def test_profiler_reader_produces_chunks(tmp_path):
    """read_llm_export should produce SourceChunks with correct source_type."""
    md_file = tmp_path / "test.md"
    md_file.write_text("---\nplatform: claude\n---\n## User\nHello world")

    chunks = read_llm_export(md_file)
    assert len(chunks) >= 1
    assert chunks[0].source_type == "llm-export"
    assert "llm-export:" in chunks[0].source_id
    assert "Hello world" in chunks[0].text


def test_profiler_read_all_sources_llm_export(tmp_path, monkeypatch):
    """read_all_sources with source_filter='llm-export' should read only llm exports."""
    import agents.profiler_sources as ps

    export_dir = tmp_path / "llm-conversations"
    claude_dir = export_dir / "claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "conv-1.md").write_text("---\nplatform: claude\n---\n## User\nTest content")

    monkeypatch.setattr(ps, "LLM_EXPORT_DIR", export_dir)
    monkeypatch.setattr(ps, "CLAUDE_DIR", tmp_path / "nonexistent-claude")
    monkeypatch.setattr(ps, "PROJECTS_DIR", tmp_path / "nonexistent-projects")
    monkeypatch.setattr(ps, "HOME", tmp_path)
    monkeypatch.setattr(ps, "_check_langfuse_available", lambda: False)

    sources = ps.discover_sources()
    chunks = ps.read_all_sources(sources, source_filter="llm-export")
    assert len(chunks) >= 1
    assert all(c.source_type == "llm-export" for c in chunks)


def test_profiler_read_all_sources_skips_known(tmp_path, monkeypatch):
    """read_all_sources should skip already-processed source IDs."""
    import agents.profiler_sources as ps

    export_dir = tmp_path / "llm-conversations"
    claude_dir = export_dir / "claude"
    claude_dir.mkdir(parents=True)
    md_path = claude_dir / "conv-1.md"
    md_path.write_text("---\nplatform: claude\n---\n## User\nTest")

    monkeypatch.setattr(ps, "LLM_EXPORT_DIR", export_dir)
    monkeypatch.setattr(ps, "CLAUDE_DIR", tmp_path / "nonexistent-claude")
    monkeypatch.setattr(ps, "PROJECTS_DIR", tmp_path / "nonexistent-projects")
    monkeypatch.setattr(ps, "HOME", tmp_path)
    monkeypatch.setattr(ps, "_check_langfuse_available", lambda: False)

    sources = ps.discover_sources()
    sid = f"llm-export:{ps._short_path(md_path)}"
    chunks = ps.read_all_sources(sources, source_filter="llm-export",
                                  skip_source_ids={sid})
    assert len(chunks) == 0

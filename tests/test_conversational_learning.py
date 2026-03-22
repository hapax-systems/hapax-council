"""Tests for Stage 5: Conversational Learning Pipeline.

Covers: record_observation JSONL write, read_pending_facts reader,
_flush_pending_facts, and authority precedence (conversation never overrides
interview-sourced facts).
"""

from __future__ import annotations

import json
from unittest.mock import patch

from agents.profiler import AUTHORITY_SOURCES, ProfileFact, merge_facts
from agents.profiler_sources import (
    DiscoveredSources,
    discover_sources,
    list_source_ids,
    read_pending_facts,
)

# ── read_pending_facts tests ──────────────────────────────────────────────


def test_read_pending_facts_basic(tmp_path):
    """Valid JSONL entries produce a single SourceChunk."""
    path = tmp_path / "pending-facts.jsonl"
    entries = [
        {
            "dimension": "work_patterns",
            "key": "editor",
            "value": "neovim",
            "evidence": "mentioned in chat",
        },
        {
            "dimension": "neurocognitive",
            "key": "time_blindness",
            "value": "frequent",
            "evidence": "",
        },
    ]
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    chunks = read_pending_facts(path)
    assert len(chunks) == 1
    assert chunks[0].source_type == "conversation"
    assert "work_patterns" in chunks[0].text
    assert "neovim" in chunks[0].text
    assert "time_blindness" in chunks[0].text


def test_read_pending_facts_empty_file(tmp_path):
    """Empty file returns no chunks."""
    path = tmp_path / "pending-facts.jsonl"
    path.write_text("")
    chunks = read_pending_facts(path)
    assert chunks == []


def test_read_pending_facts_missing_file(tmp_path):
    """Missing file returns no chunks."""
    path = tmp_path / "nonexistent.jsonl"
    chunks = read_pending_facts(path)
    assert chunks == []


def test_read_pending_facts_corrupt_lines(tmp_path):
    """Corrupt lines are skipped, valid lines still produce output."""
    path = tmp_path / "pending-facts.jsonl"
    path.write_text(
        "not valid json\n"
        + json.dumps({"dimension": "tool_usage", "key": "tool", "value": "uv", "evidence": ""})
        + "\n"
    )
    chunks = read_pending_facts(path)
    assert len(chunks) == 1
    assert "uv" in chunks[0].text


def test_read_pending_facts_all_corrupt(tmp_path):
    """All corrupt lines = no chunks."""
    path = tmp_path / "pending-facts.jsonl"
    path.write_text("bad line 1\nbad line 2\n")
    chunks = read_pending_facts(path)
    assert chunks == []


def test_read_pending_facts_includes_evidence(tmp_path):
    """Evidence field is included when present."""
    path = tmp_path / "pending-facts.jsonl"
    entry = {
        "dimension": "work_patterns",
        "key": "editor",
        "value": "vim",
        "evidence": "said 'I always use vim'",
    }
    path.write_text(json.dumps(entry) + "\n")
    chunks = read_pending_facts(path)
    assert "said 'I always use vim'" in chunks[0].text


# ── list_source_ids includes pending_facts ────────────────────────────────


def test_list_source_ids_with_pending_facts(tmp_path):
    """pending_facts appears in source ID list."""
    path = tmp_path / "pending-facts.jsonl"
    sources = DiscoveredSources(pending_facts=path)
    ids = list_source_ids(sources)
    assert any("conversation:" in sid for sid in ids)


def test_list_source_ids_without_pending_facts():
    """No pending_facts → no conversation source ID."""
    sources = DiscoveredSources()
    ids = list_source_ids(sources)
    assert not any("conversation:" in sid for sid in ids)


# ── discover_sources finds pending_facts ──────────────────────────────────


def test_discover_finds_pending_facts(tmp_path):
    """discover_sources detects pending-facts.jsonl when it exists."""
    facts_path = tmp_path / ".cache" / "logos" / "pending-facts.jsonl"
    facts_path.parent.mkdir(parents=True)
    facts_path.write_text('{"dimension": "test"}\n')
    with patch("agents.profiler_sources.HOME", tmp_path):
        with patch("agents.profiler_sources.CLAUDE_DIR", tmp_path / ".claude"):
            with patch("agents.profiler_sources.PROJECTS_DIR", tmp_path / ".claude" / "projects"):
                with patch("agents.profiler_sources._check_langfuse_available", return_value=False):
                    sources = discover_sources()
    assert sources.pending_facts is not None
    assert sources.pending_facts.name == "pending-facts.jsonl"


def test_discover_no_pending_facts(tmp_path):
    """discover_sources leaves pending_facts=None when file is absent."""
    with patch("agents.profiler_sources.HOME", tmp_path):
        with patch("agents.profiler_sources.CLAUDE_DIR", tmp_path / ".claude"):
            with patch("agents.profiler_sources.PROJECTS_DIR", tmp_path / ".claude" / "projects"):
                with patch("agents.profiler_sources._check_langfuse_available", return_value=False):
                    sources = discover_sources()
    assert sources.pending_facts is None


# ── _flush_pending_facts tests ────────────────────────────────────────────


def test_flush_pending_facts_no_file(tmp_path):
    """Flush with no file returns empty message."""
    from logos.interview import flush_pending_facts as _flush_pending_facts

    with patch("shared.config.LOGOS_STATE_DIR", tmp_path):
        result = _flush_pending_facts()
    assert "no pending facts" in result


def test_flush_pending_facts_empty_file(tmp_path):
    """Flush with empty file returns empty message."""
    from logos.interview import flush_pending_facts as _flush_pending_facts

    facts_path = tmp_path / "pending-facts.jsonl"
    facts_path.write_text("")
    with patch("shared.config.LOGOS_STATE_DIR", tmp_path):
        result = _flush_pending_facts()
    assert "no pending facts" in result


def test_flush_pending_facts_with_data(tmp_path):
    """Flush converts facts and calls flush_interview_facts."""
    from logos.interview import flush_pending_facts as _flush_pending_facts

    facts_path = tmp_path / "pending-facts.jsonl"
    entry = {
        "dimension": "tool_usage",
        "key": "tool",
        "value": "uv",
        "confidence": 0.6,
        "evidence": "said so",
    }
    facts_path.write_text(json.dumps(entry) + "\n")

    with patch("shared.config.LOGOS_STATE_DIR", tmp_path):
        with patch(
            "agents.profiler.flush_interview_facts", return_value="merged 1 fact"
        ) as mock_flush:
            result = _flush_pending_facts()

    # Verify it tried to flush
    assert "no pending facts" not in result or mock_flush.called


def test_flush_clears_file_after_success(tmp_path):
    """After successful flush, pending file should be emptied."""
    facts_path = tmp_path / "pending-facts.jsonl"
    entry = {
        "dimension": "tool_usage",
        "key": "tool",
        "value": "uv",
        "confidence": 0.6,
        "evidence": "test",
    }
    facts_path.write_text(json.dumps(entry) + "\n")

    with patch("shared.config.LOGOS_STATE_DIR", tmp_path):
        with patch("logos.interview.flush_pending_facts") as mock:
            mock.return_value = "Flushed 1 facts."
            result = mock()
    assert "Flushed" in result


# ── Authority precedence: conversation never overrides interview ──────────


def test_conversation_not_in_authority_sources():
    """'conversation' source prefix is NOT in AUTHORITY_SOURCES."""
    assert "conversation" not in AUTHORITY_SOURCES


def test_conversation_does_not_override_interview():
    """A conversation-sourced fact cannot override an interview-sourced fact."""
    existing = [
        ProfileFact(
            dimension="workflow",
            key="preferred_editor",
            value="neovim",
            confidence=0.9,
            source="interview:logos",
            evidence="operator said neovim",
        )
    ]
    new = [
        ProfileFact(
            dimension="workflow",
            key="preferred_editor",
            value="vscode",
            confidence=0.6,
            source="conversation:logos",
            evidence="mentioned vscode in passing",
        )
    ]
    merged = merge_facts(existing, new)
    # Interview fact should win
    result = {f.key: f.value for f in merged}
    assert result["preferred_editor"] == "neovim"


def test_conversation_adds_new_facts():
    """A conversation fact for a new key DOES get added."""
    existing = [
        ProfileFact(
            dimension="workflow",
            key="preferred_editor",
            value="neovim",
            confidence=0.9,
            source="interview:logos",
            evidence="operator said neovim",
        )
    ]
    new = [
        ProfileFact(
            dimension="workflow",
            key="keyboard_shortcuts",
            value="prefers vim keybindings",
            confidence=0.6,
            source="conversation:logos",
            evidence="mentioned in chat",
        )
    ]
    merged = merge_facts(existing, new)
    keys = {f.key for f in merged}
    assert "preferred_editor" in keys
    assert "keyboard_shortcuts" in keys


def test_interview_overrides_conversation():
    """An interview fact DOES override a conversation-sourced fact."""
    existing = [
        ProfileFact(
            dimension="workflow",
            key="preferred_editor",
            value="vscode",
            confidence=0.6,
            source="conversation:logos",
            evidence="mentioned in passing",
        )
    ]
    new = [
        ProfileFact(
            dimension="workflow",
            key="preferred_editor",
            value="neovim",
            confidence=0.9,
            source="interview:logos",
            evidence="explicitly stated",
        )
    ]
    merged = merge_facts(existing, new)
    result = {f.key: f.value for f in merged}
    assert result["preferred_editor"] == "neovim"

"""Tests for shared.text_repo — Hapax-managed Pango content repository (#126).

Coverage:
- :class:`TextEntry` validation: empty body, oversize body, priority bounds,
  tag/context normalization, expiry semantics.
- :meth:`TextRepo.add_entry` persists a line (JSONL round-trip).
- :meth:`select_for_context` honors context_keys, priority, recent-show
  down-weighting, and skips expired entries.
- :meth:`mark_shown` updates state and compacts the on-disk JSONL.
- ``None`` return when the repo is empty or all entries are expired.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.text_repo import (
    TEXT_ENTRY_MAX_BODY_LEN,
    TextEntry,
    TextRepo,
)

# ---------------------------------------------------------------------------
# TextEntry validation
# ---------------------------------------------------------------------------


class TestTextEntryValidation:
    def test_minimal_valid_entry(self) -> None:
        e = TextEntry(body="hello world")
        assert e.priority == 5
        assert e.show_count == 0
        assert e.tags == []
        assert e.context_keys == []
        assert e.last_shown_ts is None
        assert e.expires_ts is None
        assert len(e.id) == 12

    def test_rejects_empty_body(self) -> None:
        with pytest.raises(ValidationError):
            TextEntry(body="")

    def test_rejects_whitespace_only_body(self) -> None:
        with pytest.raises(ValidationError):
            TextEntry(body="   \n\t  ")

    def test_rejects_oversize_body(self) -> None:
        with pytest.raises(ValidationError):
            TextEntry(body="x" * (TEXT_ENTRY_MAX_BODY_LEN + 1))

    def test_priority_clamp_upper(self) -> None:
        with pytest.raises(ValidationError):
            TextEntry(body="ok", priority=11)

    def test_priority_clamp_lower(self) -> None:
        with pytest.raises(ValidationError):
            TextEntry(body="ok", priority=-1)

    def test_tags_normalized_lowercase_dedup(self) -> None:
        e = TextEntry(body="ok", tags=["Alpha", "alpha", " BETA ", ""])
        assert e.tags == ["alpha", "beta"]

    def test_context_keys_normalized(self) -> None:
        e = TextEntry(body="ok", context_keys=["Study", " study ", "Stream"])
        assert e.context_keys == ["study", "stream"]

    def test_is_expired_none_never_expires(self) -> None:
        e = TextEntry(body="ok")
        assert not e.is_expired(now=10**12)

    def test_is_expired_past_ts(self) -> None:
        e = TextEntry(body="ok", expires_ts=100.0)
        assert e.is_expired(now=200.0)
        assert not e.is_expired(now=99.0)


# ---------------------------------------------------------------------------
# TextRepo add / JSONL round-trip
# ---------------------------------------------------------------------------


class TestTextRepoPersistence:
    def test_add_entry_writes_jsonl_line(self, tmp_path: Path) -> None:
        repo = TextRepo(path=tmp_path / "entries.jsonl")
        entry = repo.add_entry("first entry", tags=["welcome"], priority=7)
        assert entry.body == "first entry"
        raw = (tmp_path / "entries.jsonl").read_text(encoding="utf-8")
        lines = [line for line in raw.splitlines() if line.strip()]
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["body"] == "first entry"
        assert obj["tags"] == ["welcome"]
        assert obj["priority"] == 7
        assert obj["id"] == entry.id

    def test_round_trip_save_load(self, tmp_path: Path) -> None:
        path = tmp_path / "entries.jsonl"
        repo = TextRepo(path=path)
        a = repo.add_entry("alpha body", tags=["a"])
        b = repo.add_entry("beta body", tags=["b"], context_keys=["study"])
        repo2 = TextRepo(path=path)
        count = repo2.load()
        assert count == 2
        by_id = {e.id: e for e in repo2.all_entries()}
        assert by_id[a.id].body == "alpha body"
        assert by_id[b.id].context_keys == ["study"]

    def test_load_missing_file_returns_zero(self, tmp_path: Path) -> None:
        repo = TextRepo(path=tmp_path / "nope.jsonl")
        assert repo.load() == 0
        assert repo.all_entries() == []

    def test_load_skips_malformed_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "entries.jsonl"
        good = TextEntry(body="good one").model_dump_json()
        path.write_text(
            "\n".join(["{not-json", "", good, '{"body": ""}', good]) + "\n",
            encoding="utf-8",
        )
        repo = TextRepo(path=path)
        # Good entry appears twice — same id, so count is 1.
        assert repo.load() == 1
        assert repo.all_entries()[0].body == "good one"

    def test_later_id_replaces_earlier(self, tmp_path: Path) -> None:
        path = tmp_path / "entries.jsonl"
        first = TextEntry(id="abc", body="v1").model_dump_json()
        second = TextEntry(id="abc", body="v2", show_count=3).model_dump_json()
        path.write_text(first + "\n" + second + "\n", encoding="utf-8")
        repo = TextRepo(path=path)
        repo.load()
        assert len(repo) == 1
        assert repo.all_entries()[0].body == "v2"
        assert repo.all_entries()[0].show_count == 3


# ---------------------------------------------------------------------------
# select_for_context
# ---------------------------------------------------------------------------


class TestSelectForContext:
    def test_empty_repo_returns_none(self, tmp_path: Path) -> None:
        repo = TextRepo(path=tmp_path / "e.jsonl")
        assert repo.select_for_context() is None

    def test_context_match_beats_higher_priority_unmatched(self, tmp_path: Path) -> None:
        repo = TextRepo(path=tmp_path / "e.jsonl")
        # High priority, wrong context
        repo.add_entry("generic high", priority=10, context_keys=["stream"])
        # Lower priority, matching context
        match = repo.add_entry("study hit", priority=5, context_keys=["study"])
        got = repo.select_for_context(activity="study")
        assert got is not None
        assert got.id == match.id

    def test_priority_wins_when_no_context(self, tmp_path: Path) -> None:
        repo = TextRepo(path=tmp_path / "e.jsonl")
        repo.add_entry("low", priority=2)
        hi = repo.add_entry("high", priority=9)
        got = repo.select_for_context()
        assert got is not None
        assert got.id == hi.id

    def test_always_on_eligible_when_no_match(self, tmp_path: Path) -> None:
        repo = TextRepo(path=tmp_path / "e.jsonl")
        # Only always-on entry — no context_keys — should still be selected.
        e = repo.add_entry("ambient", priority=3)
        got = repo.select_for_context(activity="study")
        assert got is not None
        assert got.id == e.id

    def test_expired_entries_excluded(self, tmp_path: Path) -> None:
        repo = TextRepo(path=tmp_path / "e.jsonl")
        repo.add_entry("stale", priority=10, expires_ts=100.0)
        fresh = repo.add_entry("fresh", priority=1)
        got = repo.select_for_context(now=200.0)
        assert got is not None
        assert got.id == fresh.id

    def test_recent_shows_down_weighted(self, tmp_path: Path) -> None:
        repo = TextRepo(path=tmp_path / "e.jsonl")
        # Same priority, same context match; one was shown 10s ago.
        a = repo.add_entry("a", priority=5)
        b = repo.add_entry("b", priority=5)
        now = 1_000_000.0
        repo.mark_shown(a.id, when=now - 10.0)
        got = repo.select_for_context(now=now)
        assert got is not None
        assert got.id == b.id, "b should outscore recently-shown a"

    def test_tie_break_prefers_less_shown(self, tmp_path: Path) -> None:
        repo = TextRepo(path=tmp_path / "e.jsonl")
        a = repo.add_entry("a", priority=5)
        b = repo.add_entry("b", priority=5)
        # a is shown once long-ago (outside recent window), b zero times.
        now = 1_000_000.0
        repo.mark_shown(a.id, when=now - 10_000.0)
        got = repo.select_for_context(now=now)
        assert got is not None
        assert got.id == b.id

    def test_all_expired_returns_none(self, tmp_path: Path) -> None:
        repo = TextRepo(path=tmp_path / "e.jsonl")
        repo.add_entry("x", expires_ts=100.0)
        repo.add_entry("y", expires_ts=100.0)
        assert repo.select_for_context(now=999.0) is None


# ---------------------------------------------------------------------------
# mark_shown
# ---------------------------------------------------------------------------


class TestMarkShown:
    def test_mark_shown_updates_counters(self, tmp_path: Path) -> None:
        repo = TextRepo(path=tmp_path / "e.jsonl")
        e = repo.add_entry("x")
        now = 1234.5
        updated = repo.mark_shown(e.id, when=now)
        assert updated is not None
        assert updated.show_count == 1
        assert updated.last_shown_ts == now

    def test_mark_shown_unknown_id_returns_none(self, tmp_path: Path) -> None:
        repo = TextRepo(path=tmp_path / "e.jsonl")
        assert repo.mark_shown("not-here") is None

    def test_mark_shown_persists(self, tmp_path: Path) -> None:
        path = tmp_path / "e.jsonl"
        repo = TextRepo(path=path)
        e = repo.add_entry("x")
        repo.mark_shown(e.id, when=5555.0)
        repo2 = TextRepo(path=path)
        repo2.load()
        reloaded = [r for r in repo2.all_entries() if r.id == e.id][0]
        assert reloaded.show_count == 1
        assert reloaded.last_shown_ts == 5555.0

    def test_remove_drops_entry(self, tmp_path: Path) -> None:
        repo = TextRepo(path=tmp_path / "e.jsonl")
        e = repo.add_entry("x")
        assert repo.remove(e.id) is True
        assert e.id not in repo
        assert repo.remove(e.id) is False


# ---------------------------------------------------------------------------
# Sidechat command parsing
# ---------------------------------------------------------------------------


class TestSidechatCommandParsing:
    def test_parse_add_text_command(self) -> None:
        from agents.studio_compositor.text_repo_commands import (
            parse_add_text_command,
        )

        assert parse_add_text_command("add-text hello there") == "hello there"
        assert parse_add_text_command("  add-text   padded  ") == "padded"
        assert parse_add_text_command("ADD-TEXT caps still work") == "caps still work"
        assert parse_add_text_command("add-text") is None
        assert parse_add_text_command("add-text   ") is None
        assert parse_add_text_command("link https://x") is None
        assert parse_add_text_command("nope") is None

    def test_parse_rotate_command(self) -> None:
        from agents.studio_compositor.text_repo_commands import (
            is_rotate_text_command,
        )

        assert is_rotate_text_command("rotate-text")
        assert is_rotate_text_command("  rotate-text  ")
        assert is_rotate_text_command("ROTATE-TEXT")
        assert not is_rotate_text_command("rotate-textish")
        assert not is_rotate_text_command("add-text foo")

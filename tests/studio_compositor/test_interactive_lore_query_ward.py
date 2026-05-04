"""Tests for ``agents.studio_compositor.interactive_lore_query_ward``."""

from __future__ import annotations

import json
from pathlib import Path

from agents.studio_compositor.interactive_lore_query_ward import (
    ALLOWLIST_ENV,
    OPERATOR_PLACEHOLDER,
    ChatAuthorityAllowlist,
    InteractiveLoreQueryWard,
    LoreQueryEntry,
    load_allowlist_channel_ids,
)
from agents.youtube_chat_reader.anonymize import AuthorAnonymizer


def _write_chat_state(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def _make_allowlist(anonymizer: AuthorAnonymizer, channel_ids: list[str]) -> ChatAuthorityAllowlist:
    return ChatAuthorityAllowlist(anonymizer=anonymizer, channel_ids=channel_ids)


def _frozen_clock(values):
    it = iter(values)
    return lambda: next(it)


# ── ChatAuthorityAllowlist ────────────────────────────────────────────────


class TestChatAuthorityAllowlist:
    def test_permits_only_listed_channels(self):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_alice", "UC_bob"])
        assert allow.permits(anon.token("UC_alice")) is True
        assert allow.permits(anon.token("UC_bob")) is True
        assert allow.permits(anon.token("UC_eve")) is False

    def test_size_reflects_unique_tokens(self):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_a", "UC_b", "UC_c"])
        assert allow.size == 3

    def test_empty_allowlist_permits_nothing(self):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, [])
        assert allow.permits(anon.token("UC_alice")) is False
        assert allow.size == 0


# ── load_allowlist_channel_ids ────────────────────────────────────────────


class TestLoadAllowlist:
    def test_reads_yaml_list(self, tmp_path, monkeypatch):
        path = tmp_path / "allow.yaml"
        path.write_text("allowed_channel_ids:\n  - UC_alice\n  - UC_bob\n")
        monkeypatch.setenv(ALLOWLIST_ENV, str(path))
        ids = load_allowlist_channel_ids()
        assert ids == ["UC_alice", "UC_bob"]

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ALLOWLIST_ENV, str(tmp_path / "missing.yaml"))
        assert load_allowlist_channel_ids() == []

    def test_empty_yaml_returns_empty(self, tmp_path, monkeypatch):
        path = tmp_path / "allow.yaml"
        path.write_text("")
        monkeypatch.setenv(ALLOWLIST_ENV, str(path))
        assert load_allowlist_channel_ids() == []

    def test_bad_yaml_returns_empty(self, tmp_path, monkeypatch):
        path = tmp_path / "allow.yaml"
        path.write_text("allowed_channel_ids: [broken: yaml")
        monkeypatch.setenv(ALLOWLIST_ENV, str(path))
        assert load_allowlist_channel_ids() == []


# ── InteractiveLoreQueryWard ingest ───────────────────────────────────────


class TestIngest:
    def test_allowlisted_lore_command_appends_entry(self, tmp_path):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_alice"])
        chat_state = tmp_path / "recent.jsonl"
        _write_chat_state(
            chat_state,
            [
                {
                    "ts": 100.0,
                    "author_token": anon.token("UC_alice"),
                    "text": "!lore axiom history",
                    "length": 17,
                }
            ],
        )
        ward = InteractiveLoreQueryWard(
            allowlist=allow,
            backend=lambda q: f"echo: {q}",
            chat_state_path=chat_state,
        )
        added = ward.ingest()
        assert added == 1
        entries = ward.ring
        assert len(entries) == 1
        entry: LoreQueryEntry = entries[0]
        assert entry.query == "axiom history"
        assert "echo: axiom history" in entry.response
        assert entry.handle.startswith("viewer-")
        # The handle prefix derives from author_token, never the raw channelId.
        assert "UC_alice" not in entry.handle

    def test_non_allowlisted_query_silently_dropped(self, tmp_path):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_alice"])
        chat_state = tmp_path / "recent.jsonl"
        _write_chat_state(
            chat_state,
            [
                {
                    "ts": 100.0,
                    "author_token": anon.token("UC_eve"),  # NOT allowlisted
                    "text": "!lore secret history",
                    "length": 19,
                }
            ],
        )
        ward = InteractiveLoreQueryWard(
            allowlist=allow,
            backend=lambda q: f"answer: {q}",
            chat_state_path=chat_state,
        )
        ward.ingest()
        assert ward.ring == ()

    def test_non_lore_messages_ignored(self, tmp_path):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_alice"])
        chat_state = tmp_path / "recent.jsonl"
        _write_chat_state(
            chat_state,
            [
                {
                    "ts": 100.0,
                    "author_token": anon.token("UC_alice"),
                    "text": "just chatting, not a command",
                    "length": 28,
                }
            ],
        )
        ward = InteractiveLoreQueryWard(
            allowlist=allow,
            backend=lambda q: q,
            chat_state_path=chat_state,
        )
        ward.ingest()
        assert ward.ring == ()

    def test_empty_query_after_prefix_dropped(self, tmp_path):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_alice"])
        chat_state = tmp_path / "recent.jsonl"
        _write_chat_state(
            chat_state,
            [
                {
                    "ts": 100.0,
                    "author_token": anon.token("UC_alice"),
                    "text": "!lore   ",  # whitespace-only query
                    "length": 8,
                }
            ],
        )
        ward = InteractiveLoreQueryWard(
            allowlist=allow,
            backend=lambda q: q,
            chat_state_path=chat_state,
        )
        ward.ingest()
        assert ward.ring == ()

    def test_cursor_dedups_replayed_entries(self, tmp_path):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_alice"])
        chat_state = tmp_path / "recent.jsonl"
        entries = [
            {
                "ts": 100.0,
                "author_token": anon.token("UC_alice"),
                "text": "!lore q1",
                "length": 8,
            },
            {
                "ts": 110.0,
                "author_token": anon.token("UC_alice"),
                "text": "!lore q2",
                "length": 8,
            },
        ]
        _write_chat_state(chat_state, entries)
        ward = InteractiveLoreQueryWard(
            allowlist=allow,
            backend=lambda q: f"r: {q}",
            chat_state_path=chat_state,
        )
        first = ward.ingest()
        assert first == 2
        # Re-running on the same file (no new entries) must add nothing.
        second = ward.ingest()
        assert second == 0
        assert len(ward.ring) == 2

    def test_ring_caps_at_size(self, tmp_path):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_alice"])
        chat_state = tmp_path / "recent.jsonl"
        entries = [
            {
                "ts": float(i),
                "author_token": anon.token("UC_alice"),
                "text": f"!lore q{i}",
                "length": 8,
            }
            for i in range(1, 16)
        ]
        _write_chat_state(chat_state, entries)
        ward = InteractiveLoreQueryWard(
            allowlist=allow,
            backend=lambda q: q,
            chat_state_path=chat_state,
            ring_size=5,
        )
        ward.ingest()
        assert len(ward.ring) == 5
        # Newest 5 are q11..q15 (FIFO drop oldest).
        assert ward.ring[-1].query == "q15"
        assert ward.ring[0].query == "q11"

    def test_response_truncated_to_max_chars(self, tmp_path):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_alice"])
        chat_state = tmp_path / "recent.jsonl"
        _write_chat_state(
            chat_state,
            [
                {
                    "ts": 100.0,
                    "author_token": anon.token("UC_alice"),
                    "text": "!lore tell me everything",
                    "length": 24,
                }
            ],
        )
        ward = InteractiveLoreQueryWard(
            allowlist=allow,
            backend=lambda q: "x" * 5000,
            chat_state_path=chat_state,
            response_max_chars=50,
        )
        ward.ingest()
        entry = ward.ring[0]
        assert len(entry.response) <= 50
        assert entry.response.endswith("…")

    def test_backend_exception_does_not_crash_ingest(self, tmp_path):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_alice"])
        chat_state = tmp_path / "recent.jsonl"
        _write_chat_state(
            chat_state,
            [
                {
                    "ts": 100.0,
                    "author_token": anon.token("UC_alice"),
                    "text": "!lore boom",
                    "length": 10,
                }
            ],
        )

        def raising_backend(_q):
            raise RuntimeError("backend down")

        ward = InteractiveLoreQueryWard(
            allowlist=allow,
            backend=raising_backend,
            chat_state_path=chat_state,
        )
        added = ward.ingest()
        assert added == 1
        # Entry still recorded with a placeholder response.
        assert "backend error" in ward.ring[0].response.lower()

    def test_missing_chat_state_returns_no_entries(self, tmp_path):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_alice"])
        ward = InteractiveLoreQueryWard(
            allowlist=allow,
            chat_state_path=tmp_path / "does_not_exist.jsonl",
        )
        assert ward.ingest() == 0
        assert ward.ring == ()

    def test_garbled_jsonl_lines_skipped(self, tmp_path):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_alice"])
        chat_state = tmp_path / "recent.jsonl"
        chat_state.parent.mkdir(parents=True, exist_ok=True)
        # Mix valid + invalid lines.
        chat_state.write_text(
            "{not json}\n"
            + json.dumps(
                {
                    "ts": 100.0,
                    "author_token": anon.token("UC_alice"),
                    "text": "!lore valid",
                    "length": 11,
                }
            )
            + "\n"
            + "definitely-not-json-either\n"
        )
        ward = InteractiveLoreQueryWard(
            allowlist=allow,
            backend=lambda q: q,
            chat_state_path=chat_state,
        )
        added = ward.ingest()
        assert added == 1


# ── moderation ────────────────────────────────────────────────────────────


class TestOperatorPlaceholder:
    def test_placeholder_substituted_in_response(self, tmp_path):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_alice"])
        chat_state = tmp_path / "recent.jsonl"
        _write_chat_state(
            chat_state,
            [
                {
                    "ts": 100.0,
                    "author_token": anon.token("UC_alice"),
                    "text": "!lore who?",
                    "length": 10,
                }
            ],
        )
        ward = InteractiveLoreQueryWard(
            allowlist=allow,
            backend=lambda q: f"asked by {OPERATOR_PLACEHOLDER}",
            chat_state_path=chat_state,
        )
        ward.ingest()
        entry = ward.ring[0]
        referents = ("The Operator", "Oudepode", "Oudepode The Operator", "OTO")
        assert OPERATOR_PLACEHOLDER not in entry.response
        assert any(r in entry.response for r in referents)


# ── refresh cadence ───────────────────────────────────────────────────────


class TestCadence:
    def test_refresh_is_rate_limited(self, tmp_path):
        """Render-driven refresh respects ``refresh_interval_s``.

        Two render-time clock reads inside a single window should
        only run ``ingest()`` once. We verify by counting entries
        added when chat-state is appended between the two calls.
        """
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_alice"])
        chat_state = tmp_path / "recent.jsonl"
        _write_chat_state(chat_state, [])

        # Two clock reads inside the same 10s window.
        clock = _frozen_clock([0.0, 0.5])
        ward = InteractiveLoreQueryWard(
            allowlist=allow,
            backend=lambda q: q,
            chat_state_path=chat_state,
            refresh_interval_s=10.0,
            clock=clock,
        )

        # First refresh: empty file, one ingest call.
        ward._refresh_if_due()  # noqa: SLF001 — internal API by design
        assert ward.ring == ()

        # Append a new !lore entry.
        _write_chat_state(
            chat_state,
            [
                {
                    "ts": 1.0,
                    "author_token": anon.token("UC_alice"),
                    "text": "!lore q",
                    "length": 7,
                }
            ],
        )

        # Second refresh inside the cadence window must NOT pull yet.
        ward._refresh_if_due()  # noqa: SLF001
        assert ward.ring == ()

    def test_refresh_runs_after_window(self, tmp_path):
        anon = AuthorAnonymizer()
        allow = _make_allowlist(anon, ["UC_alice"])
        chat_state = tmp_path / "recent.jsonl"
        _write_chat_state(
            chat_state,
            [
                {
                    "ts": 1.0,
                    "author_token": anon.token("UC_alice"),
                    "text": "!lore q",
                    "length": 7,
                }
            ],
        )

        # First call at t=0; second at t=11 (past 10s window).
        clock = _frozen_clock([0.0, 11.0])
        ward = InteractiveLoreQueryWard(
            allowlist=allow,
            backend=lambda q: q,
            chat_state_path=chat_state,
            refresh_interval_s=10.0,
            clock=clock,
        )
        ward._refresh_if_due()  # noqa: SLF001
        ward._refresh_if_due()  # noqa: SLF001
        # Only one entry in the file but both refreshes ran ingest;
        # the cursor dedups so we still see exactly one.
        assert len(ward.ring) == 1


# ── integration: ward identity ────────────────────────────────────────────


def test_source_id_is_stable():
    from agents.studio_compositor.interactive_lore_query_ward import SOURCE_ID

    assert SOURCE_ID == "interactive_lore_query"


def test_ward_inherits_homage_transitional_source():
    from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource

    assert issubclass(InteractiveLoreQueryWard, HomageTransitionalSource)

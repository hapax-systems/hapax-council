"""Tests for agents.studio_compositor.chat_contribution (task #146).

Coverage:

* Rolling 60s window prunes stale events.
* Per-author diminishing returns (5th = 0.5x, 10th+ = 0.1x).
* Rising-edge threshold crossing — doesn't re-trigger while sustained.
* Salt env var respected.
* Hypothesis pin: author hashes are never equal to the raw author name.
* Debug logs never leak names or message bodies (caplog assertion).
* EmojiSpewEffect lifecycle — trigger, advance frames, terminate cleanly.
"""

from __future__ import annotations

import logging

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agents.studio_compositor.chat_contribution import (
    ChatContributionLedger,
    hash_author,
    resolve_salt,
)
from agents.studio_compositor.token_pole import EmojiSpewEffect, cascade_marker_text

# ---------------------------------------------------------------------------
# Ledger — rolling window + scoring
# ---------------------------------------------------------------------------


class TestRollingWindow:
    def test_prune_drops_events_older_than_60s(self) -> None:
        ledger = ChatContributionLedger(window_seconds=60.0)
        ledger.record_chat("alice", 10, ts=0.0)
        ledger.record_chat("bob", 10, ts=30.0)
        # At t=70 the event at t=0 is outside the window.
        total = ledger.get_contribution_total(now=70.0)
        # Only bob's score remains (which should be 1.0 base + ~0.25 bonus).
        assert 1.0 <= total <= 2.0

    def test_empty_window_returns_zero(self) -> None:
        ledger = ChatContributionLedger()
        assert ledger.get_contribution_total(now=100.0) == 0.0
        assert ledger.unique_contributor_count(now=100.0) == 0


class TestScoring:
    def test_base_score_for_short_message(self) -> None:
        ledger = ChatContributionLedger()
        score = ledger.record_chat("alice", 5, ts=0.0)
        # Short message: base 1.0 + tiny length bonus (~0.125).
        assert 1.0 <= score <= 1.2

    def test_length_bonus_caps_at_5(self) -> None:
        ledger = ChatContributionLedger()
        score = ledger.record_chat("alice", 500, ts=0.0)
        # 1.0 base + 5.0 cap = 6.0
        assert score == pytest.approx(6.0, rel=0.01)

    def test_diminishing_returns_fifth_message(self) -> None:
        ledger = ChatContributionLedger()
        # First 4 messages: full score (base 1.0 + bonus 0.25 = 1.25).
        for i in range(4):
            score = ledger.record_chat("alice", 10, ts=float(i))
            assert score == pytest.approx(1.25, rel=0.01)
        # 5th message: 0.5x multiplier -> 1.25 * 0.5 = 0.625.
        fifth = ledger.record_chat("alice", 10, ts=4.0)
        assert fifth == pytest.approx(0.625, rel=0.01)
        # Ratio check: 5th is exactly half of 1st.
        assert fifth == pytest.approx(1.25 * 0.5, rel=0.01)

    def test_diminishing_returns_tenth_message(self) -> None:
        ledger = ChatContributionLedger()
        for i in range(9):
            ledger.record_chat("alice", 10, ts=float(i))
        tenth = ledger.record_chat("alice", 10, ts=9.0)
        # 0.1x multiplier -> 1.25 * 0.1 = 0.125.
        assert tenth == pytest.approx(0.125, rel=0.02)

    def test_different_authors_dont_share_diminishing(self) -> None:
        ledger = ChatContributionLedger()
        for i in range(10):
            ledger.record_chat("spammer", 10, ts=float(i))
        # Bob is fresh -> full score.
        bob_score = ledger.record_chat("bob", 10, ts=10.0)
        assert bob_score > 0.9


# ---------------------------------------------------------------------------
# Rising-edge threshold
# ---------------------------------------------------------------------------


class TestThresholdCrossing:
    def test_below_threshold_returns_none(self) -> None:
        ledger = ChatContributionLedger(reward_threshold=50.0)
        ledger.record_chat("alice", 10, ts=0.0)
        assert ledger.cross_reward_threshold(now=0.0) is None

    def test_rising_edge_fires_once(self) -> None:
        ledger = ChatContributionLedger(reward_threshold=5.0)
        # Accumulate enough from distinct authors (avoid diminishing).
        for i in range(10):
            ledger.record_chat(f"user_{i}", 10, ts=float(i))
        snap = ledger.cross_reward_threshold(now=10.0)
        assert snap is not None
        assert snap.explosion_number == 1
        assert snap.unique_contributor_count == 10

        # Second call while still above: returns None (no re-trigger).
        assert ledger.cross_reward_threshold(now=11.0) is None

    def test_re_arms_after_dropping_below(self) -> None:
        ledger = ChatContributionLedger(window_seconds=10.0, reward_threshold=5.0)
        for i in range(10):
            ledger.record_chat(f"user_{i}", 10, ts=float(i))
        snap1 = ledger.cross_reward_threshold(now=10.0)
        assert snap1 is not None
        # Wait long enough for all events to age out.
        assert ledger.cross_reward_threshold(now=50.0) is None
        # New surge.
        for i in range(10):
            ledger.record_chat(f"v_{i}", 10, ts=50.0 + i)
        snap2 = ledger.cross_reward_threshold(now=60.0)
        assert snap2 is not None
        assert snap2.explosion_number == 2


# ---------------------------------------------------------------------------
# Privacy — salt, hashing, no leakage
# ---------------------------------------------------------------------------


class TestPrivacy:
    def test_salt_env_var_respected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_CHAT_HASH_SALT", "deterministic-salt-1")
        h1 = hash_author("alice")
        monkeypatch.setenv("HAPAX_CHAT_HASH_SALT", "deterministic-salt-2")
        h2 = hash_author("alice")
        assert h1 != h2

    def test_same_salt_same_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_CHAT_HASH_SALT", "fixed")
        assert hash_author("alice") == hash_author("alice")

    def test_resolve_salt_env_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_CHAT_HASH_SALT", "env-salt")
        assert resolve_salt() == b"env-salt"

    def test_caplog_never_contains_names(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HAPAX_CHAT_HASH_SALT", "test-salt")
        caplog.set_level(logging.DEBUG, logger="agents.studio_compositor.chat_contribution")
        ledger = ChatContributionLedger()
        secret_name = "unique-sentinel-user-xyzzy"
        secret_message = "super-sensitive-sentinel-body-qwerty"
        ledger.record_chat(secret_name, len(secret_message), ts=0.0)
        log_text = "\n".join(r.getMessage() for r in caplog.records)
        assert secret_name not in log_text
        assert secret_message not in log_text

    @given(author_name=st.text(min_size=1, max_size=80))
    @settings(max_examples=200, deadline=None)
    def test_author_hash_never_equals_name(self, author_name: str) -> None:
        """Hypothesis: for arbitrary inputs the hash never leaks the name."""
        h = hash_author(author_name)
        assert h != author_name
        # Hash output is 16 hex chars regardless of input.
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# EmojiSpewEffect
# ---------------------------------------------------------------------------


class TestEmojiSpewEffect:
    def test_inactive_by_default(self) -> None:
        fx = EmojiSpewEffect()
        assert fx.active is False
        assert fx.frames_remaining == 0
        assert fx.emoji == []

    def test_trigger_arms(self) -> None:
        fx = EmojiSpewEffect(duration_frames=30)
        fx.trigger(explosion_number=1, contributor_count=4)
        assert fx.active
        assert fx.frames_remaining == 30
        assert fx.explosion_number == 1
        assert fx.contributor_count == 4

    def test_tick_advances_frames_and_terminates(self) -> None:
        fx = EmojiSpewEffect(duration_frames=5, spawn_per_tick=2, max_emoji=10)
        fx.trigger(explosion_number=1, contributor_count=3)
        # Advance many frames — cascade must terminate cleanly.
        for _ in range(200):
            fx.tick(canvas_w=300, canvas_h=300)
        assert fx.active is False
        assert fx.frames_remaining == 0
        assert fx.emoji == []

    def test_marker_text_format(self) -> None:
        fx = EmojiSpewEffect()
        assert fx.marker_text() is None
        fx.trigger(explosion_number=7, contributor_count=12)
        assert fx.marker_text() == "#7 FROM 12"

    def test_marker_helper_is_aggregate_only(self) -> None:
        # The marker function produces only numeric output — no slot for
        # a name even if one were offered.
        out = cascade_marker_text(3, 5)
        assert out == "#3 FROM 5"

    def test_retrigger_while_active_resets(self) -> None:
        fx = EmojiSpewEffect(duration_frames=60)
        fx.trigger(explosion_number=1, contributor_count=2)
        for _ in range(10):
            fx.tick(300, 300)
        fx.trigger(explosion_number=2, contributor_count=5)
        assert fx.frames_remaining == 60
        assert fx.explosion_number == 2
        assert fx.contributor_count == 5

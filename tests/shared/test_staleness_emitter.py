"""Tests for shared.staleness_emitter.StalenessEmitter.

36-LOC rate-limited impingement emitter. Untested before this commit.
Tests use unittest.mock to drive ``time.time`` so cooldown
transitions are deterministic without real sleeps.
"""

from __future__ import annotations

from unittest.mock import patch

from shared.impingement import ImpingementType
from shared.staleness_emitter import StalenessEmitter

# ── First-emit path ────────────────────────────────────────────────


class TestFirstEmit:
    def test_first_call_returns_impingement(self) -> None:
        emitter = StalenessEmitter()
        with patch("shared.staleness_emitter.time") as mock_time:
            mock_time.time.return_value = 1000.0
            imp = emitter.maybe_emit("ir-presence")
        assert imp is not None
        assert imp.source == "staleness.ir-presence"
        assert imp.type is ImpingementType.ABSOLUTE_THRESHOLD
        assert imp.strength == 0.4
        assert imp.content == {"metric": "ir-presence_staleness", "value": "stale"}
        assert imp.timestamp == 1000.0


# ── Cooldown gating ────────────────────────────────────────────────


class TestCooldown:
    def test_within_cooldown_returns_none(self) -> None:
        emitter = StalenessEmitter(cooldown_s=60.0)
        with patch("shared.staleness_emitter.time") as mock_time:
            mock_time.time.return_value = 1000.0
            assert emitter.maybe_emit("src") is not None
            mock_time.time.return_value = 1059.0  # 59s elapsed
            assert emitter.maybe_emit("src") is None

    def test_after_cooldown_returns_impingement(self) -> None:
        emitter = StalenessEmitter(cooldown_s=60.0)
        with patch("shared.staleness_emitter.time") as mock_time:
            mock_time.time.return_value = 1000.0
            assert emitter.maybe_emit("src") is not None
            mock_time.time.return_value = 1061.0  # 61s elapsed
            imp = emitter.maybe_emit("src")
            assert imp is not None
            assert imp.timestamp == 1061.0

    def test_per_source_cooldowns_are_independent(self) -> None:
        """Cooldown is keyed by source — emitting for src-a doesn't
        gate emissions for src-b."""
        emitter = StalenessEmitter(cooldown_s=60.0)
        with patch("shared.staleness_emitter.time") as mock_time:
            mock_time.time.return_value = 1000.0
            assert emitter.maybe_emit("src-a") is not None
            mock_time.time.return_value = 1010.0  # 10s — within cooldown for src-a
            assert emitter.maybe_emit("src-a") is None
            # src-b never seen → emits
            assert emitter.maybe_emit("src-b") is not None

    def test_custom_cooldown_zero_emits_every_call(self) -> None:
        """cooldown_s=0 with the < check means any non-negative elapsed
        time passes the gate — emissions land on every call (including
        same-instant repeats)."""
        emitter = StalenessEmitter(cooldown_s=0.0)
        with patch("shared.staleness_emitter.time") as mock_time:
            mock_time.time.return_value = 1000.0
            assert emitter.maybe_emit("src") is not None
            # Same instant: 0 < 0.0 is False → emits again (not gated)
            assert emitter.maybe_emit("src") is not None
            mock_time.time.return_value = 1000.5
            assert emitter.maybe_emit("src") is not None


# ── Source name shaping ────────────────────────────────────────────


class TestSourceShaping:
    def test_emitted_source_is_prefixed(self) -> None:
        emitter = StalenessEmitter()
        with patch("shared.staleness_emitter.time") as mock_time:
            mock_time.time.return_value = 1000.0
            imp = emitter.maybe_emit("contact-mic")
        assert imp is not None
        assert imp.source == "staleness.contact-mic"

    def test_metric_field_includes_source(self) -> None:
        emitter = StalenessEmitter()
        with patch("shared.staleness_emitter.time") as mock_time:
            mock_time.time.return_value = 1000.0
            imp = emitter.maybe_emit("yamnet")
        assert imp is not None
        assert imp.content["metric"] == "yamnet_staleness"

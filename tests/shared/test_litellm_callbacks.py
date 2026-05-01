"""Tests for shared.litellm_callbacks.RateLimitScoreCallback.

51-LOC LiteLLM callback that scores Anthropic generations for rate
limiting via Langfuse. Untested before this commit. Tests mock the
``langfuse.get_client`` import so the callback's scoring branch can
be exercised without a live Langfuse client.
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

from shared.litellm_callbacks import RateLimitScoreCallback


def _kwargs(model: str = "anthropic/claude-3-sonnet", **extra: Any) -> dict:
    return {"model": model, **extra}


def _install_fake_langfuse(client_mock: MagicMock) -> None:
    """Install a fake `langfuse.get_client` in sys.modules so the
    callback's `from langfuse import get_client` resolves to it."""
    fake = types.ModuleType("langfuse")
    fake.get_client = lambda: client_mock  # type: ignore[attr-defined]
    sys.modules["langfuse"] = fake


# ── async_log_success_event: scores rate_limited=False ─────────────


class TestSuccessEvent:
    def test_anthropic_success_scores_false(self) -> None:
        client = MagicMock()
        _install_fake_langfuse(client)
        cb = RateLimitScoreCallback()
        cb.async_log_success_event(_kwargs(model="anthropic/claude-opus"), None, None, None)
        client.score_current_trace.assert_called_once()
        kwargs = client.score_current_trace.call_args.kwargs
        assert kwargs["name"] == "rate_limited"
        assert kwargs["value"] == 0  # int(False)
        assert kwargs["data_type"] == "BOOLEAN"

    def test_claude_alias_also_scored(self) -> None:
        """Models containing 'claude' (without 'anthropic') still score."""
        client = MagicMock()
        _install_fake_langfuse(client)
        cb = RateLimitScoreCallback()
        cb.async_log_success_event(_kwargs(model="claude-haiku"), None, None, None)
        client.score_current_trace.assert_called_once()


# ── async_log_failure_event: scores rate_limited=True only on 429 ───


class TestFailureEvent:
    def test_429_exception_scores_true(self) -> None:
        client = MagicMock()
        _install_fake_langfuse(client)
        cb = RateLimitScoreCallback()
        cb.async_log_failure_event(
            _kwargs(exception=Exception("got 429 from upstream")),
            None,
            None,
            None,
        )
        client.score_current_trace.assert_called_once()
        assert client.score_current_trace.call_args.kwargs["value"] == 1

    def test_rate_limit_string_in_exception_scores_true(self) -> None:
        client = MagicMock()
        _install_fake_langfuse(client)
        cb = RateLimitScoreCallback()
        cb.async_log_failure_event(
            _kwargs(exception=Exception("rate_limit_exceeded for org x")),
            None,
            None,
            None,
        )
        client.score_current_trace.assert_called_once()
        assert client.score_current_trace.call_args.kwargs["value"] == 1

    def test_unrelated_failure_does_not_score(self) -> None:
        """Non-rate-limit failures are NOT scored — the dashboard tracks
        rate-limit pressure specifically, not all failures."""
        client = MagicMock()
        _install_fake_langfuse(client)
        cb = RateLimitScoreCallback()
        cb.async_log_failure_event(
            _kwargs(exception=Exception("connection reset by peer")),
            None,
            None,
            None,
        )
        client.score_current_trace.assert_not_called()

    def test_no_exception_returns_early(self) -> None:
        """A failure event with no exception in kwargs is a no-op."""
        client = MagicMock()
        _install_fake_langfuse(client)
        cb = RateLimitScoreCallback()
        cb.async_log_failure_event(_kwargs(), None, None, None)
        client.score_current_trace.assert_not_called()


# ── Model-name gating ──────────────────────────────────────────────


class TestModelGating:
    def test_non_anthropic_model_not_scored(self) -> None:
        """OpenAI/Gemini/etc generations are not scored — the metric is
        scoped to Anthropic rate-limit pressure."""
        client = MagicMock()
        _install_fake_langfuse(client)
        cb = RateLimitScoreCallback()
        cb.async_log_success_event(_kwargs(model="openai/gpt-4"), None, None, None)
        client.score_current_trace.assert_not_called()

    def test_empty_model_not_scored(self) -> None:
        client = MagicMock()
        _install_fake_langfuse(client)
        cb = RateLimitScoreCallback()
        cb.async_log_success_event(_kwargs(model=""), None, None, None)
        client.score_current_trace.assert_not_called()


# ── Langfuse-import failure tolerated ──────────────────────────────


class TestLangfuseFailureTolerance:
    def test_langfuse_import_error_swallowed(self) -> None:
        """When langfuse.get_client raises, the callback logs and
        continues — never propagates."""
        client = MagicMock()
        client.score_current_trace.side_effect = RuntimeError("langfuse down")
        _install_fake_langfuse(client)
        cb = RateLimitScoreCallback()
        # Should NOT raise.
        cb.async_log_success_event(_kwargs(model="claude-opus"), None, None, None)

    def test_no_langfuse_module_swallowed(self) -> None:
        """If `langfuse` isn't installed at all, the import inside _score
        raises ImportError; the callback's bare except catches it."""
        sys.modules.pop("langfuse", None)
        with patch.dict(sys.modules, {"langfuse": None}):
            cb = RateLimitScoreCallback()
            # Should NOT raise.
            cb.async_log_success_event(_kwargs(model="claude-opus"), None, None, None)

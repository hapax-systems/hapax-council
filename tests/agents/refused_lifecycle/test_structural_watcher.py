"""Tests for ``agents.refused_lifecycle.structural_watcher``.

Covers HTTP-conditional-GET probe behaviour, cadence-degrade logic, snippet
extraction, and ETag/Last-Modified/SHA fingerprint persistence on the
RefusalTask probe state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agents.refused_lifecycle.state import (
    RefusalHistoryEntry,
    RefusalTask,
)
from agents.refused_lifecycle.structural_watcher import (
    CADENCE_MONTHLY,
    CADENCE_WEEKLY,
    STABLE_THRESHOLD,
    cadence_for_task,
    extract_snippet_around_keyword,
    probe_url,
)


def _now() -> datetime:
    return datetime(2026, 4, 26, 23, 0, tzinfo=UTC)


def _structural_task(**probe_overrides) -> RefusalTask:
    probe = {
        "url": "https://example.com/policy",
        "lift_keywords": ["upload api", "submission"],
        "lift_polarity": "present",
        "last_etag": None,
        "last_lm": None,
        "last_fingerprint": None,
    }
    probe.update(probe_overrides)
    return RefusalTask(
        slug="pub-bus-bandcamp-upload-REFUSED",
        path="/tmp/x.md",
        automation_status="REFUSED",
        refusal_reason="vendor lock-in",
        evaluation_trigger=["structural"],
        evaluation_probe=probe,
    )


def _mock_response(status_code: int, text: str = "", headers: dict | None = None):
    """Build a stand-in httpx.Response with minimal fields."""
    return httpx.Response(
        status_code=status_code,
        text=text,
        headers=headers or {},
        request=httpx.Request("GET", "https://example.com/policy"),
    )


# ── probe_url branches ──────────────────────────────────────────────


class TestProbeUrl:
    @pytest.mark.asyncio
    async def test_304_returns_unchanged(self):
        task = _structural_task(last_etag='"abc"')
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_mock_response(304))):
            result = await probe_url(task)
        assert result.changed is False
        assert result.error is None

    @pytest.mark.asyncio
    async def test_5xx_returns_error(self):
        task = _structural_task()
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_mock_response(503))):
            result = await probe_url(task)
        assert result.changed is False
        assert result.error is not None
        assert "503" in result.error

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        task = _structural_task()
        with patch(
            "httpx.AsyncClient.get",
            new=AsyncMock(side_effect=httpx.TimeoutException("timeout")),
        ):
            result = await probe_url(task)
        assert result.changed is False
        assert result.error is not None
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unchanged_fingerprint_returns_unchanged(self):
        # First-pass: compute fingerprint on a known body, then re-run with
        # that fingerprint persisted; second probe must return unchanged.
        body = "stable policy text without lift keywords"
        import hashlib

        sha = hashlib.sha256(body.encode()).hexdigest()
        task = _structural_task(last_fingerprint=sha)
        with patch(
            "httpx.AsyncClient.get",
            new=AsyncMock(return_value=_mock_response(200, body)),
        ):
            result = await probe_url(task)
        assert result.changed is False

    @pytest.mark.asyncio
    async def test_content_changed_no_lift_returns_unchanged(self):
        body = "policy update — submission still prohibited"
        task = _structural_task(lift_keywords=["upload api"])
        with patch(
            "httpx.AsyncClient.get",
            new=AsyncMock(return_value=_mock_response(200, body)),
        ):
            result = await probe_url(task)
        # Content changed but lift-keyword absent — re-affirm
        assert result.changed is False

    @pytest.mark.asyncio
    async def test_lift_keyword_present_returns_changed_with_snippet(self):
        body = "Effective today: we now offer an upload api for partners."
        task = _structural_task(lift_keywords=["upload api"])
        with patch(
            "httpx.AsyncClient.get",
            new=AsyncMock(return_value=_mock_response(200, body)),
        ):
            result = await probe_url(task)
        assert result.changed is True
        assert result.evidence_url == "https://example.com/policy"
        assert result.snippet is not None
        assert "upload api" in result.snippet.lower()

    @pytest.mark.asyncio
    async def test_200_response_carries_etag_and_fingerprint(self):
        """P0-2 regression: probe must round-trip ETag/LM/SHA so the next
        probe sends conditional-GET headers instead of burning a full GET.
        """
        body = "stable policy text"
        headers = {"ETag": '"abc123"', "Last-Modified": "Mon, 01 Apr 2026 12:00:00 GMT"}
        task = _structural_task()
        with patch(
            "httpx.AsyncClient.get",
            new=AsyncMock(return_value=_mock_response(200, body, headers)),
        ):
            result = await probe_url(task)
        assert result.etag == '"abc123"'
        assert result.last_modified == "Mon, 01 Apr 2026 12:00:00 GMT"
        assert result.fingerprint is not None
        assert len(result.fingerprint) == 64  # sha256 hex

    @pytest.mark.asyncio
    async def test_304_preserves_previous_etag(self):
        # 304 carries no body; ETag/LM should still survive into the next probe
        task = _structural_task(last_etag='"prev"', last_fingerprint="prev-sha")
        with patch(
            "httpx.AsyncClient.get",
            new=AsyncMock(return_value=_mock_response(304)),
        ):
            result = await probe_url(task)
        assert result.changed is False
        assert result.etag == '"prev"'
        assert result.fingerprint == "prev-sha"

    @pytest.mark.asyncio
    async def test_conditional_get_sends_if_none_match_header(self):
        # When task.evaluation_probe.last_etag is populated, the probe must
        # send If-None-Match. Verify by capturing the headers passed to httpx.
        task = _structural_task(last_etag='"persisted"')
        captured = {}

        async def _capture(self, url, headers=None):
            captured["headers"] = headers or {}
            return _mock_response(304)

        with patch("httpx.AsyncClient.get", new=_capture):
            await probe_url(task)
        assert captured["headers"].get("If-None-Match") == '"persisted"'


# ── cadence_for_task ───────────────────────────────────────────────


class TestCadenceForTask:
    def test_weekly_when_no_history(self):
        task = _structural_task()
        assert cadence_for_task(task) == CADENCE_WEEKLY

    def test_weekly_with_few_reaffirmations(self):
        task = _structural_task()
        task.refusal_history = [
            RefusalHistoryEntry(date=_now(), transition="re-affirmed", reason="x") for _ in range(3)
        ]
        assert cadence_for_task(task) == CADENCE_WEEKLY

    def test_monthly_after_threshold_consecutive_reaffirmations(self):
        task = _structural_task()
        task.refusal_history = [
            RefusalHistoryEntry(date=_now(), transition="re-affirmed", reason="x")
            for _ in range(STABLE_THRESHOLD)
        ]
        assert cadence_for_task(task) == CADENCE_MONTHLY

    def test_resets_to_weekly_after_non_reaffirmation(self):
        task = _structural_task()
        # 12 re-affirmations interrupted by a content-change, then 3 more
        task.refusal_history = (
            [
                RefusalHistoryEntry(date=_now(), transition="re-affirmed", reason="x")
                for _ in range(STABLE_THRESHOLD)
            ]
            + [RefusalHistoryEntry(date=_now(), transition="created", reason="y")]
            + [
                RefusalHistoryEntry(date=_now(), transition="re-affirmed", reason="z")
                for _ in range(3)
            ]
        )
        # Trailing run of re-affirms is only 3 (< STABLE_THRESHOLD) → weekly
        assert cadence_for_task(task) == CADENCE_WEEKLY


# ── extract_snippet_around_keyword ──────────────────────────────────


class TestExtractSnippet:
    def test_short_text_returned_verbatim(self):
        text = "We offer an upload api now."
        snippet = extract_snippet_around_keyword(text, ["upload api"])
        assert "upload api" in snippet
        assert len(snippet) <= 500

    def test_long_text_truncated_to_500(self):
        text = "x" * 1000 + " upload api " + "y" * 1000
        snippet = extract_snippet_around_keyword(text, ["upload api"])
        assert len(snippet) <= 500
        assert "upload api" in snippet

    def test_no_keyword_match_returns_short_default(self):
        text = "policy text without any matches"
        snippet = extract_snippet_around_keyword(text, ["nope"])
        assert len(snippet) <= 500

    def test_multiple_keywords_finds_first_match(self):
        text = "first some content, then submission api appears here."
        snippet = extract_snippet_around_keyword(text, ["upload", "submission api"])
        assert "submission api" in snippet

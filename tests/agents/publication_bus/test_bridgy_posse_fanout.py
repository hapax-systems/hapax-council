"""Tests for ``agents.publication_bus.bridgy_posse_fanout``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.publication_bus.bridgy_posse_fanout import (
    BRIDGY_PUBLISH_TARGET_PREFIX,
    posse_after_weblog_publish,
)
from agents.publication_bus.bridgy_publisher import BridgyPublisher


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return response


class TestPosseFanoutDefaultTargets:
    @patch("agents.publication_bus.bridgy_publisher.requests")
    def test_fans_out_to_mastodon_and_bluesky(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(201)
        outcomes = posse_after_weblog_publish(
            entry_url="https://hapax.omg.lol/weblog/2026-05-10-test"
        )
        assert set(outcomes.keys()) == {"mastodon", "bluesky"}
        assert all(r.ok for r in outcomes.values())

    @patch("agents.publication_bus.bridgy_publisher.requests")
    def test_posts_correct_source_and_target(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(201)
        entry = "https://hapax.omg.lol/weblog/2026-05-10-test"
        posse_after_weblog_publish(entry_url=entry)
        calls = mock_requests.post.call_args_list
        assert len(calls) == 2
        targets_sent = set()
        for call in calls:
            data = call.kwargs["data"]
            assert data["source"] == entry
            targets_sent.add(data["target"])
        assert targets_sent == {
            f"{BRIDGY_PUBLISH_TARGET_PREFIX}mastodon",
            f"{BRIDGY_PUBLISH_TARGET_PREFIX}bluesky",
        }


class TestPosseFanoutCustomTargets:
    @patch("agents.publication_bus.bridgy_publisher.requests")
    def test_single_target(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(201)
        outcomes = posse_after_weblog_publish(
            entry_url="https://hapax.omg.lol/weblog/entry",
            targets=["mastodon"],
        )
        assert list(outcomes.keys()) == ["mastodon"]
        assert mock_requests.post.call_count == 1

    @patch("agents.publication_bus.bridgy_publisher.requests")
    def test_empty_targets_no_posts(self, mock_requests: MagicMock) -> None:
        outcomes = posse_after_weblog_publish(
            entry_url="https://hapax.omg.lol/weblog/entry",
            targets=[],
        )
        assert outcomes == {}
        mock_requests.post.assert_not_called()


class TestPosseFanoutPartialFailure:
    @patch("agents.publication_bus.bridgy_publisher.requests")
    def test_one_succeeds_one_fails(self, mock_requests: MagicMock) -> None:
        responses = [_mock_response(201), _mock_response(500)]
        mock_requests.post.side_effect = responses
        outcomes = posse_after_weblog_publish(
            entry_url="https://hapax.omg.lol/weblog/entry",
        )
        assert len(outcomes) == 2
        results = list(outcomes.values())
        ok_count = sum(1 for r in results if r.ok)
        error_count = sum(1 for r in results if r.error)
        assert ok_count == 1
        assert error_count == 1


class TestPosseFanoutWithExplicitPublisher:
    @patch("agents.publication_bus.bridgy_publisher.requests")
    def test_uses_provided_publisher(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(202)
        custom_pub = BridgyPublisher(timeout_s=5.0)
        outcomes = posse_after_weblog_publish(
            entry_url="https://hapax.omg.lol/weblog/entry",
            publisher=custom_pub,
        )
        assert all(r.ok for r in outcomes.values())
        for call in mock_requests.post.call_args_list:
            assert call.kwargs["timeout"] == 5.0


class TestPosseFanoutAllowlist:
    def test_bridgy_publish_targets_in_allowlist(self) -> None:
        pub = BridgyPublisher()
        assert pub.allowlist.permits(f"{BRIDGY_PUBLISH_TARGET_PREFIX}mastodon")
        assert pub.allowlist.permits(f"{BRIDGY_PUBLISH_TARGET_PREFIX}bluesky")

    def test_omg_lol_sections_still_in_allowlist(self) -> None:
        pub = BridgyPublisher()
        assert pub.allowlist.permits("https://hapax.omg.lol/weblog")
        assert pub.allowlist.permits("https://hapax.omg.lol/now")
        assert pub.allowlist.permits("https://hapax.omg.lol/statuslog")

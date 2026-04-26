"""Tests for ``agents.publication_bus.community_submitter``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.publication_bus.community_submitter import (
    DEFAULT_COMMUNITY_TAXONOMY,
    HAPAX_COMMUNITY_SLUGS,
    ZENODO_COMMUNITY_SUBMIT_PATH_TEMPLATE,
    SubmissionOutcome,
    ZenodoCommunitySubmitter,
    match_communities_for_deposit,
)


def _mock_response(status_code: int, json_data: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.text = ""
    return response


class TestCommunityTaxonomy:
    def test_canonical_communities_listed(self) -> None:
        assert "single-operator-systems" in HAPAX_COMMUNITY_SLUGS
        assert "philosophy-of-computation" in HAPAX_COMMUNITY_SLUGS
        assert "refusal-shaped-infrastructure" in HAPAX_COMMUNITY_SLUGS

    def test_taxonomy_keyed_by_topic(self) -> None:
        # Each topic maps to one or more community slugs
        assert isinstance(DEFAULT_COMMUNITY_TAXONOMY, dict)
        for topic, communities in DEFAULT_COMMUNITY_TAXONOMY.items():
            assert isinstance(topic, str)
            assert isinstance(communities, (list, tuple, set, frozenset))
            for c in communities:
                assert c in HAPAX_COMMUNITY_SLUGS, f"taxonomy maps to unknown community {c!r}"


class TestMatchCommunities:
    def test_matches_topic_to_communities(self) -> None:
        deposit_topics = ["single-operator", "axioms"]
        taxonomy = {
            "single-operator": ["single-operator-systems"],
            "axioms": ["philosophy-of-computation"],
        }
        matched = match_communities_for_deposit(deposit_topics, taxonomy)
        assert "single-operator-systems" in matched
        assert "philosophy-of-computation" in matched

    def test_returns_empty_when_no_overlap(self) -> None:
        matched = match_communities_for_deposit(
            ["unrelated-topic"], {"single-operator": ["single-operator-systems"]}
        )
        assert matched == []

    def test_dedups_overlapping_communities(self) -> None:
        # Two topics both map to the same community → only one entry
        taxonomy = {
            "single-operator": ["single-operator-systems"],
            "axioms": ["single-operator-systems"],
        }
        matched = match_communities_for_deposit(["single-operator", "axioms"], taxonomy)
        assert matched.count("single-operator-systems") == 1

    def test_uses_default_taxonomy_when_unspecified(self) -> None:
        matched = match_communities_for_deposit(["refusal-as-data"])
        # default taxonomy includes refusal-as-data → refusal-shaped-infrastructure
        assert "refusal-shaped-infrastructure" in matched


class TestSubmissionOutcome:
    def test_dataclass_carries_status(self) -> None:
        outcome = SubmissionOutcome(
            deposit_id="123",
            community="single-operator-systems",
            ok=True,
            detail="submitted",
        )
        assert outcome.deposit_id == "123"
        assert outcome.community == "single-operator-systems"
        assert outcome.ok is True


class TestSubmitterMissingCreds:
    def test_returns_refused_when_token_missing(self) -> None:
        submitter = ZenodoCommunitySubmitter(zenodo_token="")
        outcome = submitter.submit_to_community(
            deposit_id="123",
            community="single-operator-systems",
        )
        assert outcome.ok is False
        assert "credential" in outcome.detail.lower() or "token" in outcome.detail.lower()


class TestSubmitterAuto:
    @patch("agents.publication_bus.community_submitter.requests")
    def test_submit_to_community_posts_to_zenodo(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(201, json_data={"id": 123})
        submitter = ZenodoCommunitySubmitter(zenodo_token="t")
        outcome = submitter.submit_to_community(
            deposit_id="123",
            community="single-operator-systems",
        )
        assert outcome.ok is True
        url = mock_requests.post.call_args[0][0]
        assert "depositions/123" in url

    @patch("agents.publication_bus.community_submitter.requests")
    def test_2xx_returns_ok(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(202, {"queued": True})
        submitter = ZenodoCommunitySubmitter(zenodo_token="t")
        outcome = submitter.submit_to_community(
            deposit_id="123",
            community="single-operator-systems",
        )
        assert outcome.ok is True

    @patch("agents.publication_bus.community_submitter.requests")
    def test_4xx_returns_error(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(400, {"error": "bad"})
        submitter = ZenodoCommunitySubmitter(zenodo_token="t")
        outcome = submitter.submit_to_community(
            deposit_id="123",
            community="single-operator-systems",
        )
        assert outcome.ok is False

    @patch("agents.publication_bus.community_submitter.requests")
    def test_5xx_returns_error(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(503, {"error": "server"})
        submitter = ZenodoCommunitySubmitter(zenodo_token="t")
        outcome = submitter.submit_to_community(
            deposit_id="123",
            community="single-operator-systems",
        )
        assert outcome.ok is False

    @patch("agents.publication_bus.community_submitter.requests")
    def test_request_exception_returns_error(self, mock_requests: MagicMock) -> None:
        import requests as _requests_lib

        mock_requests.post.side_effect = _requests_lib.RequestException("offline")
        mock_requests.RequestException = _requests_lib.RequestException
        submitter = ZenodoCommunitySubmitter(zenodo_token="t")
        outcome = submitter.submit_to_community(
            deposit_id="123",
            community="single-operator-systems",
        )
        assert outcome.ok is False

    @patch("agents.publication_bus.community_submitter.requests")
    def test_bearer_authorization_header(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(201)
        submitter = ZenodoCommunitySubmitter(zenodo_token="my-token")
        submitter.submit_to_community(
            deposit_id="123",
            community="single-operator-systems",
        )
        kwargs = mock_requests.post.call_args.kwargs
        headers = kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer my-token"

    @patch("agents.publication_bus.community_submitter.requests")
    def test_no_auto_accept_only_submit(self, mock_requests: MagicMock) -> None:
        """Per cc-task: submit only, never auto-accept; the Zenodo
        manual gate is honored."""
        mock_requests.post.return_value = _mock_response(201)
        submitter = ZenodoCommunitySubmitter(zenodo_token="t")
        submitter.submit_to_community(
            deposit_id="123",
            community="single-operator-systems",
        )
        url = mock_requests.post.call_args[0][0]
        # The URL must NOT call the community-curate / accept endpoint
        assert "/accept" not in url
        # The path uses Zenodo's deposit-side actions (not community-side)
        assert ZENODO_COMMUNITY_SUBMIT_PATH_TEMPLATE.split("{deposit_id}")[0] in url


class TestUrlTemplate:
    def test_url_template_uses_zenodo_deposit_actions(self) -> None:
        # Submitter posts via the deposit's metadata — communities array
        # is updated via PUT to depositions/{id}; the action endpoint
        # publishes the deposit which triggers community submission.
        assert "depositions" in ZENODO_COMMUNITY_SUBMIT_PATH_TEMPLATE
        assert "{deposit_id}" in ZENODO_COMMUNITY_SUBMIT_PATH_TEMPLATE

"""Tests for ``agents.cold_contact.orcid_validator``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.cold_contact.candidate_registry import CandidateEntry
from agents.cold_contact.orcid_validator import (
    ORCID_PUBLIC_API_BASE,
    OrcidValidationOutcome,
    validate_candidate,
)


def _mock_response(status_code: int, json_data=None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.json = MagicMock(return_value={} if json_data is None else json_data)
    return response


_OK_PERSON = {
    "person": {
        "name": {
            "given-names": {"value": "Wendy"},
            "family-name": {"value": "Chun"},
        }
    }
}


class TestValidateCandidate:
    @patch("agents.cold_contact.orcid_validator.requests")
    def test_200_with_matching_name_returns_ok(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(200, _OK_PERSON)
        entry = CandidateEntry(
            name="Wendy Chun",
            orcid="0000-0001-2345-6789",
            audience_vectors=["critical-ai"],
            topic_relevance=[],
        )
        result = validate_candidate(entry)
        assert result.outcome == OrcidValidationOutcome.OK

    @patch("agents.cold_contact.orcid_validator.requests")
    def test_200_with_name_mismatch_flagged(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(200, _OK_PERSON)
        entry = CandidateEntry(
            name="Different Name",
            orcid="0000-0001-2345-6789",
            audience_vectors=["critical-ai"],
            topic_relevance=[],
        )
        result = validate_candidate(entry)
        assert result.outcome == OrcidValidationOutcome.NAME_MISMATCH
        assert result.expected_name == "Different Name"
        assert "Wendy Chun" in result.fetched_name

    @patch("agents.cold_contact.orcid_validator.requests")
    def test_404_marks_not_found(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(404, text="not found")
        entry = CandidateEntry(
            name="Ghost",
            orcid="0000-0009-9999-9999",
            audience_vectors=[],
            topic_relevance=[],
        )
        result = validate_candidate(entry)
        assert result.outcome == OrcidValidationOutcome.NOT_FOUND

    @patch("agents.cold_contact.orcid_validator.requests")
    def test_request_exception_returns_error(self, mock_requests: MagicMock) -> None:
        import requests as _requests_lib

        mock_requests.get.side_effect = _requests_lib.RequestException("network down")
        mock_requests.RequestException = _requests_lib.RequestException
        entry = CandidateEntry(
            name="x",
            orcid="0000-0001-2345-6789",
            audience_vectors=[],
            topic_relevance=[],
        )
        result = validate_candidate(entry)
        assert result.outcome == OrcidValidationOutcome.TRANSPORT_ERROR

    @patch("agents.cold_contact.orcid_validator.requests")
    def test_url_construction(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(200, _OK_PERSON)
        entry = CandidateEntry(
            name="Wendy Chun",
            orcid="0000-0001-2345-6789",
            audience_vectors=["critical-ai"],
            topic_relevance=[],
        )
        validate_candidate(entry)
        url = mock_requests.get.call_args[0][0]
        assert url.startswith(ORCID_PUBLIC_API_BASE)
        assert "0000-0001-2345-6789" in url

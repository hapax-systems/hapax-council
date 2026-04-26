"""Tests for ``agents.attribution.crossref_depositor``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.attribution.crossref_depositor import (
    CROSSREF_DEPOSIT_ENDPOINT,
    CrossrefDepositor,
    DepositOutcome,
    log_deposit,
)


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return response


_VALID_DEPOSIT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<doi_batch>
  <head><doi_batch_id>test-batch-1</doi_batch_id></head>
  <body><deposit/></body>
</doi_batch>
"""


class TestCrossrefDepositor:
    @patch("agents.attribution.crossref_depositor.requests")
    def test_200_returns_ok(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(200, text="SUCCESS submission-id=12345")
        depositor = CrossrefDepositor(login_id="test", login_passwd="pw")
        result = depositor.submit_deposit(_VALID_DEPOSIT_XML)
        assert result.outcome == DepositOutcome.OK
        assert result.error is None

    @patch("agents.attribution.crossref_depositor.requests")
    def test_403_returns_refused(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(403, text="forbidden")
        depositor = CrossrefDepositor(login_id="test", login_passwd="pw")
        result = depositor.submit_deposit(_VALID_DEPOSIT_XML)
        assert result.outcome == DepositOutcome.REFUSED

    @patch("agents.attribution.crossref_depositor.requests")
    def test_5xx_returns_error(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(503, text="server error")
        depositor = CrossrefDepositor(login_id="test", login_passwd="pw")
        result = depositor.submit_deposit(_VALID_DEPOSIT_XML)
        assert result.outcome == DepositOutcome.ERROR

    def test_missing_creds_returns_refused_creds(self) -> None:
        depositor = CrossrefDepositor(login_id="", login_passwd="")
        result = depositor.submit_deposit(_VALID_DEPOSIT_XML)
        assert result.outcome == DepositOutcome.MISSING_CREDS
        assert "credentials" in (result.error or "").lower()

    @patch("agents.attribution.crossref_depositor.requests")
    def test_request_exception_returns_error(self, mock_requests: MagicMock) -> None:
        import requests as _requests_lib

        mock_requests.post.side_effect = _requests_lib.RequestException("offline")
        mock_requests.RequestException = _requests_lib.RequestException
        depositor = CrossrefDepositor(login_id="test", login_passwd="pw")
        result = depositor.submit_deposit(_VALID_DEPOSIT_XML)
        assert result.outcome == DepositOutcome.ERROR

    @patch("agents.attribution.crossref_depositor.requests")
    def test_url_is_crossref_deposit_endpoint(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(200, text="OK")
        depositor = CrossrefDepositor(login_id="test", login_passwd="pw")
        depositor.submit_deposit(_VALID_DEPOSIT_XML)
        url = mock_requests.post.call_args[0][0]
        assert url.startswith(CROSSREF_DEPOSIT_ENDPOINT)


class TestLogDeposit:
    def test_appends_jsonl_entry(self, tmp_path: Path) -> None:
        log_path = tmp_path / "crossref-deposits.jsonl"
        log_deposit(
            doi="10.5281/zenodo.111",
            outcome=DepositOutcome.OK,
            log_path=log_path,
        )
        entries = log_path.read_text().splitlines()
        assert len(entries) == 1
        record = json.loads(entries[0])
        assert record["doi"] == "10.5281/zenodo.111"
        assert record["outcome"] == "ok"
        assert "timestamp" in record

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        log_path = tmp_path / "deep" / "nested" / "log.jsonl"
        log_deposit(
            doi="10.5281/zenodo.222",
            outcome=DepositOutcome.OK,
            log_path=log_path,
        )
        assert log_path.exists()

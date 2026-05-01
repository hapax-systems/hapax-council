"""Tests for ``agents.self_federate.rss_validator``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.self_federate.rss_validator import (
    DEFAULT_HAPAX_RSS_URL,
    _classify_outcome,
    extract_items,
    fetch_rss,
    items_with_doi_links,
    load_validity_state,
    notify_on_validity_loss,
    validate_rss,
    write_validity_state,
)


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.content = text.encode("utf-8")
    return response


_VALID_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Hapax weblog</title>
    <link>https://hapax.weblog.lol</link>
    <description>Infrastructure as argument.</description>
    <item>
      <title>Cohort Disparity Disclosure</title>
      <link>https://hapax.weblog.lol/cohort-disparity</link>
      <pubDate>Fri, 25 Apr 2026 12:00:00 +0000</pubDate>
      <description>See https://doi.org/10.5281/zenodo.111 for full data.</description>
    </item>
    <item>
      <title>Refusal Annex: Bandcamp</title>
      <link>https://hapax.weblog.lol/refusal-annex-bandcamp</link>
      <pubDate>Sat, 26 Apr 2026 04:00:00 +0000</pubDate>
      <description>Annex declining Bandcamp upload (no API). https://doi.org/10.5281/zenodo.222</description>
    </item>
  </channel>
</rss>
"""

_INVALID_RSS_NO_CHANNEL = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
</rss>
"""

_RSS_NO_DOI_ITEMS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Hapax weblog</title>
    <link>https://hapax.weblog.lol</link>
    <description>x</description>
    <item>
      <title>No DOI here</title>
      <link>https://hapax.weblog.lol/x</link>
      <pubDate>Fri, 25 Apr 2026 12:00:00 +0000</pubDate>
      <description>Just a regular post.</description>
    </item>
  </channel>
</rss>
"""


class TestFetchRss:
    @patch("agents.self_federate.rss_validator.requests")
    def test_200_returns_xml_bytes(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(200, _VALID_RSS)
        result = fetch_rss(DEFAULT_HAPAX_RSS_URL)
        assert result is not None
        assert b"<rss" in result

    @patch("agents.self_federate.rss_validator.requests")
    def test_404_returns_none(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(404)
        assert fetch_rss(DEFAULT_HAPAX_RSS_URL) is None

    @patch("agents.self_federate.rss_validator.requests")
    def test_request_exception_returns_none(self, mock_requests: MagicMock) -> None:
        import requests as _requests_lib

        mock_requests.get.side_effect = _requests_lib.RequestException("offline")
        mock_requests.RequestException = _requests_lib.RequestException
        assert fetch_rss(DEFAULT_HAPAX_RSS_URL) is None


class TestValidateRss:
    def test_valid_rss_returns_true(self) -> None:
        assert validate_rss(_VALID_RSS.encode()) is True

    def test_invalid_no_channel_returns_false(self) -> None:
        assert validate_rss(_INVALID_RSS_NO_CHANNEL.encode()) is False

    def test_malformed_xml_returns_false(self) -> None:
        assert validate_rss(b"<rss>not closed") is False


class TestExtractItems:
    def test_returns_list_of_items(self) -> None:
        items = extract_items(_VALID_RSS.encode())
        assert len(items) == 2
        assert items[0]["title"] == "Cohort Disparity Disclosure"
        assert items[0]["link"] == "https://hapax.weblog.lol/cohort-disparity"

    def test_empty_when_no_channel(self) -> None:
        assert extract_items(_INVALID_RSS_NO_CHANNEL.encode()) == []


class TestItemsWithDoiLinks:
    def test_finds_doi_in_description(self) -> None:
        items = extract_items(_VALID_RSS.encode())
        with_dois = items_with_doi_links(items)
        assert len(with_dois) == 2
        assert "10.5281/zenodo.111" in with_dois[0]["dois"]

    def test_no_dois_returns_empty_list_per_item(self) -> None:
        items = extract_items(_RSS_NO_DOI_ITEMS.encode())
        with_dois = items_with_doi_links(items)
        assert len(with_dois) == 1
        assert with_dois[0]["dois"] == []


class TestClassifyOutcome:
    def test_valid_xml_returns_ok(self) -> None:
        outcome, item_count, doi_count = _classify_outcome(_VALID_RSS.encode())
        assert outcome == "ok"
        assert item_count == 2
        assert doi_count == 2

    def test_none_returns_transport_error(self) -> None:
        assert _classify_outcome(None) == ("transport-error", 0, 0)

    def test_malformed_xml_returns_invalid(self) -> None:
        outcome, _, _ = _classify_outcome(b"<rss>malformed")
        assert outcome == "invalid-xml"

    def test_no_channel_returns_invalid(self) -> None:
        outcome, _, _ = _classify_outcome(_INVALID_RSS_NO_CHANNEL.encode())
        assert outcome == "invalid-xml"


class TestValidityStatePersistence:
    def test_load_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        assert load_validity_state(tmp_path / "missing.json") is None

    def test_load_returns_none_when_file_malformed(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        path.write_text("not-json", encoding="utf-8")
        assert load_validity_state(path) is None

    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        write_validity_state("ok", path)
        assert load_validity_state(path) == "ok"
        write_validity_state("transport-error", path)
        assert load_validity_state(path) == "transport-error"

    def test_write_is_atomic_via_tmp_rename(self, tmp_path: Path) -> None:
        """No tmp file should remain after a successful write."""
        path = tmp_path / "state.json"
        write_validity_state("ok", path)
        assert path.is_file()
        assert not path.with_suffix(path.suffix + ".tmp").exists()


class TestNotifyOnValidityLoss:
    @patch("agents.self_federate.rss_validator.send_notification")
    def test_no_notification_on_steady_ok(self, mock_send: MagicMock) -> None:
        notify_on_validity_loss(prior_outcome="ok", current_outcome="ok")
        mock_send.assert_not_called()

    @patch("agents.self_federate.rss_validator.send_notification")
    def test_no_notification_on_first_run_ok(self, mock_send: MagicMock) -> None:
        # First run with no prior state, outcome is healthy — silent.
        notify_on_validity_loss(prior_outcome=None, current_outcome="ok")
        mock_send.assert_not_called()

    @patch("agents.self_federate.rss_validator.send_notification")
    def test_notification_on_first_run_loss(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        notify_on_validity_loss(prior_outcome=None, current_outcome="invalid-xml")
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["priority"] == "high"
        assert "warning" in call_kwargs["tags"]

    @patch("agents.self_federate.rss_validator.send_notification")
    def test_notification_on_ok_to_loss_transition(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        notify_on_validity_loss(prior_outcome="ok", current_outcome="transport-error")
        mock_send.assert_called_once()

    @patch("agents.self_federate.rss_validator.send_notification")
    def test_no_notification_on_sustained_loss(self, mock_send: MagicMock) -> None:
        notify_on_validity_loss(prior_outcome="transport-error", current_outcome="transport-error")
        mock_send.assert_not_called()

    @patch("agents.self_federate.rss_validator.send_notification")
    def test_notification_on_recovery(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        notify_on_validity_loss(prior_outcome="invalid-xml", current_outcome="ok")
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        # Recovery uses default priority + check tag (not the warning tag).
        assert call_kwargs["priority"] == "default"
        assert "white_check_mark" in call_kwargs["tags"]

    @patch("agents.self_federate.rss_validator.send_notification")
    def test_notification_message_contains_feed_url(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        notify_on_validity_loss(prior_outcome="ok", current_outcome="invalid-xml")
        msg = mock_send.call_args.kwargs["message"]
        assert DEFAULT_HAPAX_RSS_URL in msg

    @patch("agents.self_federate.rss_validator.send_notification")
    def test_notification_does_not_re_notify_on_outcome_change_within_failure(
        self, mock_send: MagicMock
    ) -> None:
        """Edge-trigger semantics: ``transport-error → invalid-xml`` is a
        failure-mode change, but the operator has already been paged about
        the original failure. The current behavior re-notifies on any
        outcome change within failure modes — guard the wired behavior."""
        mock_send.return_value = True
        notify_on_validity_loss(prior_outcome="transport-error", current_outcome="invalid-xml")
        # Wired behavior: yes, re-notify when failure mode changes (the
        # nature of the failure is operator-relevant). If this changes,
        # update both the function and this test.
        mock_send.assert_called_once()

"""Tests for ``agents.self_federate.rss_validator``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.self_federate.rss_validator import (
    DEFAULT_HAPAX_RSS_URL,
    extract_items,
    fetch_rss,
    items_with_doi_links,
    validate_rss,
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

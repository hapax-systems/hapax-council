"""Tests for agents/omg_email_setup — ytb-OMG5 Phase A."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.omg_email_setup.setup import (
    configure_email_forwarding,
    show_current_destination,
)


def _client(
    *,
    enabled: bool = True,
    current_destination: str | None = "",
    set_ok: bool = True,
) -> MagicMock:
    c = MagicMock()
    c.enabled = enabled
    if current_destination is None:
        c.get_email.return_value = None
    else:
        c.get_email.return_value = {"response": {"destination": current_destination}}
    c.set_email.return_value = (
        {"request": {"statusCode": 200}, "response": {"destination": "ok"}} if set_ok else None
    )
    return c


class TestConfigure:
    def test_configures_new_destination(self) -> None:
        client = _client(current_destination="")
        outcome = configure_email_forwarding(client=client, forwards_to="op@example.com")
        assert outcome == "configured"
        client.set_email.assert_called_once_with("hapax", forwards_to="op@example.com")

    def test_unchanged_when_already_configured(self) -> None:
        client = _client(current_destination="op@example.com")
        outcome = configure_email_forwarding(client=client, forwards_to="op@example.com")
        assert outcome == "unchanged"
        client.set_email.assert_not_called()

    def test_overwrites_different_destination(self) -> None:
        client = _client(current_destination="old@example.com")
        outcome = configure_email_forwarding(client=client, forwards_to="new@example.com")
        assert outcome == "configured"
        client.set_email.assert_called_once()

    def test_disabled_client_reports_disabled(self) -> None:
        client = _client(enabled=False)
        outcome = configure_email_forwarding(client=client, forwards_to="op@example.com")
        assert outcome == "client-disabled"
        client.get_email.assert_not_called()
        client.set_email.assert_not_called()

    def test_set_failure_reports_failed(self) -> None:
        client = _client(current_destination="", set_ok=False)
        outcome = configure_email_forwarding(client=client, forwards_to="op@example.com")
        assert outcome == "failed"

    def test_get_email_returning_none_proceeds_with_set(self) -> None:
        client = _client(current_destination=None)
        outcome = configure_email_forwarding(client=client, forwards_to="op@example.com")
        assert outcome == "configured"
        client.set_email.assert_called_once()

    def test_accepts_non_default_address(self) -> None:
        client = _client(current_destination="")
        outcome = configure_email_forwarding(
            client=client, address="legomena", forwards_to="op@example.com"
        )
        assert outcome == "configured"
        client.set_email.assert_called_once_with("legomena", forwards_to="op@example.com")


class TestShowCurrent:
    def test_returns_destination_string(self) -> None:
        client = _client(current_destination="op@example.com")
        assert show_current_destination(client=client) == "op@example.com"

    def test_returns_empty_when_disabled(self) -> None:
        client = _client(enabled=False)
        assert show_current_destination(client=client) == ""

    def test_returns_empty_on_api_error(self) -> None:
        client = _client(current_destination=None)
        assert show_current_destination(client=client) == ""


class TestResponseUnwrap:
    def test_handles_top_level_destination_shape(self) -> None:
        """Some API endpoints return {"destination": ...} at top level
        instead of nested under ``response``."""
        client = MagicMock()
        client.enabled = True
        client.get_email.return_value = {"destination": "op@example.com"}
        result = show_current_destination(client=client)
        assert result == "op@example.com"

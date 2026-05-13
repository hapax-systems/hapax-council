"""Tests for omg.lol publication-bus adapters beyond weblog/statuslog."""

from __future__ import annotations

from unittest import mock

from agents.publication_bus.omg_email_publisher import OmgLolEmailPublisher
from agents.publication_bus.omg_now_publisher import OmgLolNowPublisher
from agents.publication_bus.omg_pastebin_publisher import OmgLolPastebinPublisher
from agents.publication_bus.omg_purl_publisher import OmgLolPurlPublisher
from agents.publication_bus.omg_web_publisher import OmgLolWebPublisher
from agents.publication_bus.omg_weblog_delete_publisher import OmgLolWeblogDeletePublisher
from agents.publication_bus.publisher_kit import PublisherPayload
from agents.publication_bus.publisher_kit.allowlist import load_allowlist


def test_web_publisher_calls_set_web() -> None:
    client = mock.Mock(enabled=True)
    client.set_web.return_value = {"response": {"ok": True}}
    result = OmgLolWebPublisher(client=client).publish(
        PublisherPayload(target="hapax", text="<html></html>", metadata={"publish": True})
    )
    assert result.ok is True
    client.set_web.assert_called_once_with("hapax", content="<html></html>", publish=True)


def test_now_publisher_calls_set_now() -> None:
    client = mock.Mock(enabled=True)
    client.set_now.return_value = {"response": {"ok": True}}
    result = OmgLolNowPublisher(client=client).publish(
        PublisherPayload(target="hapax", text="now", metadata={"listed": True})
    )
    assert result.ok is True
    client.set_now.assert_called_once_with("hapax", content="now", listed=True)


def test_pastebin_publisher_calls_set_paste() -> None:
    client = mock.Mock(enabled=True)
    client.set_paste.return_value = {"response": {"ok": True}}
    result = OmgLolPastebinPublisher(client=client).publish(
        PublisherPayload(
            target="hapax",
            text="paste",
            metadata={"title": "credits", "listed": True},
        )
    )
    assert result.ok is True
    client.set_paste.assert_called_once_with(
        "hapax",
        content="paste",
        title="credits",
        listed=True,
    )


def test_purl_publisher_calls_create_purl() -> None:
    client = mock.Mock(enabled=True)
    client.create_purl.return_value = {"response": {"ok": True}}
    result = OmgLolPurlPublisher(client=client).publish(
        PublisherPayload(
            target="hapax",
            text="https://example.com",
            metadata={"name": "example"},
        )
    )
    assert result.ok is True
    client.create_purl.assert_called_once_with(
        "hapax",
        name="example",
        url="https://example.com",
    )


def test_email_publisher_calls_set_email() -> None:
    client = mock.Mock(enabled=True)
    client.set_email.return_value = {"response": {"ok": True}}
    result = OmgLolEmailPublisher(client=client).publish(
        PublisherPayload(target="hapax", text="op@example.com")
    )
    assert result.ok is True
    client.set_email.assert_called_once_with("hapax", forwards_to="op@example.com")


def test_weblog_delete_publisher_is_tightly_allowlisted() -> None:
    client = mock.Mock(enabled=True)
    client.delete_entry.return_value = {"response": {"ok": True}}
    OmgLolWeblogDeletePublisher.allowlist = load_allowlist(
        OmgLolWeblogDeletePublisher.surface_name,
        ["deploy-verify-weblog-producer"],
    )

    result = OmgLolWeblogDeletePublisher(client=client, address="hapax").publish(
        PublisherPayload(
            target="deploy-verify-weblog-producer",
            text="delete deploy verification entry",
        )
    )

    assert result.ok is True
    client.delete_entry.assert_called_once_with("hapax", "deploy-verify-weblog-producer")

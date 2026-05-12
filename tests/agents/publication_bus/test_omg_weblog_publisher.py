"""Tests for ``agents.publication_bus.omg_weblog_publisher``."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.publication_bus.omg_weblog_publisher import (
    OMG_WEBLOG_SURFACE,
    OmgLolWeblogPublisher,
)
from agents.publication_bus.publisher_kit import PublisherPayload
from agents.publication_bus.publisher_kit.allowlist import load_allowlist

_SENTINEL = object()


def _make_client(enabled: bool = True, set_entry_returns=_SENTINEL) -> MagicMock:
    client = MagicMock()
    client.enabled = enabled
    if set_entry_returns is _SENTINEL:
        set_entry_returns = {"id": "entry-1"}
    client.set_entry = MagicMock(return_value=set_entry_returns)
    return client


class TestSurfaceMetadata:
    def test_surface_name_is_omg_lol_weblog(self) -> None:
        assert OmgLolWeblogPublisher.surface_name == OMG_WEBLOG_SURFACE
        assert OMG_WEBLOG_SURFACE == "omg-lol-weblog-bearer-fanout"

    def test_does_not_require_legal_name(self) -> None:
        assert OmgLolWeblogPublisher.requires_legal_name is False


class TestPublisher:
    def test_emit_calls_set_entry(self) -> None:
        client = _make_client()
        OmgLolWeblogPublisher.allowlist = load_allowlist(OMG_WEBLOG_SURFACE, ["entry-1"])
        publisher = OmgLolWeblogPublisher(client=client, address="hapax")
        result = publisher.publish(PublisherPayload(target="entry-1", text="body"))
        assert result.ok is True
        client.set_entry.assert_called_once_with("hapax", "entry-1", content="body")

    def test_set_entry_failure_returns_error(self) -> None:
        client = _make_client(set_entry_returns=None)
        OmgLolWeblogPublisher.allowlist = load_allowlist(OMG_WEBLOG_SURFACE, ["entry-1"])
        publisher = OmgLolWeblogPublisher(client=client, address="hapax")
        result = publisher.publish(PublisherPayload(target="entry-1", text="body"))
        assert result.error is True

    def test_disabled_client_returns_refused(self) -> None:
        client = _make_client(enabled=False)
        OmgLolWeblogPublisher.allowlist = load_allowlist(OMG_WEBLOG_SURFACE, ["entry-1"])
        publisher = OmgLolWeblogPublisher(client=client, address="hapax")
        result = publisher.publish(PublisherPayload(target="entry-1", text="body"))
        assert result.refused is True
        assert "client" in result.detail.lower()
        client.set_entry.assert_not_called()

    def test_allowlist_deny_short_circuits(self) -> None:
        client = _make_client()
        OmgLolWeblogPublisher.allowlist = load_allowlist(OMG_WEBLOG_SURFACE, [])
        publisher = OmgLolWeblogPublisher(client=client, address="hapax")
        result = publisher.publish(PublisherPayload(target="entry-1", text="body"))
        assert result.refused is True
        client.set_entry.assert_not_called()

    def test_invokes_with_correct_address(self) -> None:
        client = _make_client()
        OmgLolWeblogPublisher.allowlist = load_allowlist(OMG_WEBLOG_SURFACE, ["entry-1"])
        publisher = OmgLolWeblogPublisher(client=client, address="oudepode")
        publisher.publish(PublisherPayload(target="entry-1", text="body"))
        # First positional arg is the address
        assert client.set_entry.call_args.args[0] == "oudepode"

    def test_metadata_payload_rewrites_collection_location(self) -> None:
        client = _make_client(
            set_entry_returns={
                "response": {
                    "entry": {
                        "entry": "show-hn-governance-that-ships",
                        "location": "/2026/05/show-hn-governance-that-ships",
                    }
                }
            }
        )
        OmgLolWeblogPublisher.allowlist = load_allowlist(
            OMG_WEBLOG_SURFACE, ["show-hn-governance-that-ships"]
        )
        publisher = OmgLolWeblogPublisher(client=client, address="hapax")

        text = (
            "---\n"
            "Date: 2026-05-10\n"
            "Title: Show HN: Mechanical Governance for AI Coding Agents at 3,000+ PRs\n"
            "Type: post\n"
            "Location: /weblog\n"
            "Tags: ai-governance, show-hn\n"
            "Slug: show-hn-governance-that-ships\n"
            "---\n\n"
            "# Show HN: Mechanical Governance\n\n"
            "Body.\n"
        )
        result = publisher.publish(
            PublisherPayload(
                target="show-hn-governance-that-ships",
                text=text,
                metadata={"location": "/2026/05/show-hn-governance-that-ships"},
            )
        )

        assert result.ok is True
        content = client.set_entry.call_args.kwargs["content"]
        assert "Location: /2026/05/show-hn-governance-that-ships" in content
        assert "Location: /weblog" not in content
        assert "Title: Show HN: Mechanical Governance for AI Coding Agents at 3,000+ PRs" in content
        assert "# Show HN: Mechanical Governance" in content

    def test_refuses_collection_location_without_derivation_data(self) -> None:
        client = _make_client()
        OmgLolWeblogPublisher.allowlist = load_allowlist(OMG_WEBLOG_SURFACE, ["entry-1"])
        publisher = OmgLolWeblogPublisher(client=client, address="hapax")
        text = "---\nLocation: /weblog\n---\n\n# Entry\n\nBody.\n"

        result = publisher.publish(PublisherPayload(target="entry-1", text=text))

        assert result.refused is True
        assert "unsafe weblog Location" in result.detail
        client.set_entry.assert_not_called()

    def test_location_mismatch_from_omg_lol_is_error(self) -> None:
        client = _make_client(
            set_entry_returns={
                "response": {
                    "entry": {
                        "entry": "entry-1",
                        "location": "/2026/05/unexpected",
                    }
                }
            }
        )
        OmgLolWeblogPublisher.allowlist = load_allowlist(OMG_WEBLOG_SURFACE, ["entry-1"])
        publisher = OmgLolWeblogPublisher(client=client, address="hapax")
        text = (
            "---\n"
            "Date: 2026-05-12\n"
            "Slug: entry-1\n"
            "Location: /2026/05/entry-1\n"
            "---\n\n"
            "# Entry\n\n"
            "Body.\n"
        )

        result = publisher.publish(PublisherPayload(target="entry-1", text=text))

        assert result.error is True
        assert "expected '/2026/05/entry-1'" in result.detail

"""Tests for agents/omg_weblog_publisher — ytb-OMG8 Phase B."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest  # noqa: TC002

from agents.omg_weblog_publisher.publisher import (
    WeblogDraft,
    WeblogPublisher,
    derive_entry_slug,
    parse_draft,
)


class TestDeriveEntrySlug:
    def test_iso_date_only(self) -> None:
        assert derive_entry_slug("2026-04-24.md") == "2026-04-24"

    def test_iso_date_plus_title(self) -> None:
        assert derive_entry_slug("2026-04-24-programme-retro.md") == "2026-04-24-programme-retro"

    def test_iso_date_plus_underscore_title(self) -> None:
        assert derive_entry_slug("2026-04-24_programme-retro.md") == "2026-04-24-programme-retro"

    def test_arbitrary_title(self) -> None:
        assert derive_entry_slug("Programme Retro.md") == "programme-retro"

    def test_special_characters_cleaned(self) -> None:
        assert derive_entry_slug("Art & Science: Vol 1!.md") == "art-science-vol-1"

    def test_stem_only_underscores(self) -> None:
        assert derive_entry_slug("_____.md") == "untitled"


class TestParseDraft:
    def test_extracts_title_from_first_heading(self, tmp_path: Path) -> None:
        f = tmp_path / "2026-04-24-essay.md"
        f.write_text("# A Long-Form Essay\n\nBody here.\n")
        draft = parse_draft(f)
        assert draft.title == "A Long-Form Essay"
        assert draft.slug == "2026-04-24-essay"
        assert "Body here." in draft.content

    def test_falls_back_to_slug_when_no_heading(self, tmp_path: Path) -> None:
        f = tmp_path / "2026-04-24-x.md"
        f.write_text("no heading body\n")
        draft = parse_draft(f)
        assert draft.title == "2026-04-24-x"

    def test_skips_leading_empty_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "2026-04-24-x.md"
        f.write_text("\n\n# Real Title\n\nbody\n")
        draft = parse_draft(f)
        assert draft.title == "Real Title"


class TestPublisher:
    def _client(self, *, enabled: bool = True, set_ok: bool = True) -> MagicMock:
        c = MagicMock()
        c.enabled = enabled
        c.set_entry.return_value = (
            {"request": {"statusCode": 200}, "response": {"slug": "stub"}} if set_ok else None
        )
        return c

    def _draft(self) -> WeblogDraft:
        return WeblogDraft(slug="2026-04-24-test", content="# Test\n\nBody.", title="Test")

    def test_publish_calls_set_entry(self) -> None:
        client = self._client()
        publisher = WeblogPublisher(client=client)
        outcome = publisher.publish(self._draft())
        assert outcome == "published"
        client.set_entry.assert_called_once()
        call = client.set_entry.call_args
        # Positional: (address, slug); kwargs: content=...
        assert call.args[0] == "hapax"
        assert call.args[1] == "2026-04-24-test"
        assert call.kwargs["content"].startswith("# Test")

    def test_dry_run_skips_client(self) -> None:
        client = self._client()
        publisher = WeblogPublisher(client=client)
        outcome = publisher.publish(self._draft(), dry_run=True)
        assert outcome == "dry-run"
        client.set_entry.assert_not_called()

    def test_disabled_client_short_circuits(self) -> None:
        client = self._client(enabled=False)
        publisher = WeblogPublisher(client=client)
        outcome = publisher.publish(self._draft())
        assert outcome == "client-disabled"
        client.set_entry.assert_not_called()

    def test_set_entry_failure_reports_failed(self) -> None:
        client = self._client(set_ok=False)
        publisher = WeblogPublisher(client=client)
        outcome = publisher.publish(self._draft())
        assert outcome == "failed"

    def test_allowlist_deny_skips_post(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agents.omg_weblog_publisher import publisher as pub_mod

        def _deny(*args, **kwargs):
            from shared.governance.publication_allowlist import AllowlistResult

            return AllowlistResult(decision="deny", payload={}, reason="stub deny")

        monkeypatch.setattr(pub_mod, "allowlist_check", _deny)
        client = self._client()
        publisher = WeblogPublisher(client=client)
        outcome = publisher.publish(self._draft())
        assert outcome == "allowlist-denied"
        client.set_entry.assert_not_called()

    def test_accepts_non_default_address(self) -> None:
        client = self._client()
        publisher = WeblogPublisher(client=client, address="legomena")
        publisher.publish(self._draft())
        call = client.set_entry.call_args
        assert call.args[0] == "legomena"

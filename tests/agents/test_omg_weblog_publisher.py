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
        return WeblogDraft(
            slug="2026-04-24-test",
            content="# Test\n\nBody.",
            title="Test",
            approved=True,
        )

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


class TestApprovalGate:
    """Phase A → Phase B handoff: drafts marked ``approved: false`` must
    not publish, even if all other gates pass."""

    def _client(self) -> MagicMock:
        c = MagicMock()
        c.enabled = True
        c.set_entry.return_value = {"request": {"statusCode": 200}, "response": {"slug": "stub"}}
        return c

    def test_unapproved_short_circuits_before_allowlist(self) -> None:
        unapproved = WeblogDraft(
            slug="2026-04-24-test",
            content="body",
            title="Test",
            approved=False,
        )
        client = self._client()
        publisher = WeblogPublisher(client=client)
        outcome = publisher.publish(unapproved)
        assert outcome == "not-approved"
        client.set_entry.assert_not_called()

    def test_approved_passes_gate(self) -> None:
        approved = WeblogDraft(
            slug="2026-04-24-test",
            content="body",
            title="Test",
            approved=True,
        )
        client = self._client()
        publisher = WeblogPublisher(client=client)
        outcome = publisher.publish(approved)
        assert outcome == "published"

    def test_default_is_unapproved(self) -> None:
        """Drafts constructed without explicit ``approved`` carry False."""
        d = WeblogDraft(slug="x", content="y", title="z")
        assert d.approved is False


class TestParseDraftApproval:
    """parse_draft lifts the frontmatter ``approved`` flag; strips frontmatter
    from the published body."""

    def test_reads_approved_true(self, tmp_path: Path) -> None:
        f = tmp_path / "2026-04-24-essay.md"
        f.write_text(
            '---\ntitle: "Essay"\napproved: true\n---\n\n# Essay heading\n\nBody content.\n'
        )
        draft = parse_draft(f)
        assert draft.approved is True
        # Frontmatter stripped from content.
        assert draft.content.lstrip().startswith("#")
        assert "approved: true" not in draft.content

    def test_reads_approved_false(self, tmp_path: Path) -> None:
        f = tmp_path / "2026-04-24-essay.md"
        f.write_text('---\ntitle: "Essay"\napproved: false\n---\n\n# Essay\n\nBody.\n')
        draft = parse_draft(f)
        assert draft.approved is False

    def test_missing_approved_defaults_false(self, tmp_path: Path) -> None:
        f = tmp_path / "essay.md"
        f.write_text('---\ntitle: "Essay"\n---\nBody.\n')
        draft = parse_draft(f)
        assert draft.approved is False

    def test_no_frontmatter_defaults_false(self, tmp_path: Path) -> None:
        f = tmp_path / "essay.md"
        f.write_text("# Essay\n\nBody.\n")
        draft = parse_draft(f)
        assert draft.approved is False

    def test_frontmatter_title_used(self, tmp_path: Path) -> None:
        f = tmp_path / "essay.md"
        f.write_text('---\ntitle: "Frontmatter Title"\napproved: true\n---\n# Body Heading\n')
        draft = parse_draft(f)
        # Frontmatter title takes precedence over body heading.
        assert draft.title == "Frontmatter Title"


# ── Orchestrator entry-point (PUB-P2-C foundation) ───────────────────


class _FakeArtifact:
    def __init__(
        self,
        *,
        slug: str = "test",
        title: str = "",
        abstract: str = "",
        body_md: str = "",
        attribution_block: str = "",
    ) -> None:
        self.slug = slug
        self.title = title
        self.abstract = abstract
        self.body_md = body_md
        self.attribution_block = attribution_block


class TestPublishArtifact:
    def test_disabled_client_returns_no_credentials(self) -> None:
        from unittest.mock import patch

        from agents.omg_weblog_publisher.publisher import publish_artifact

        client = MagicMock()
        client.enabled = False
        with patch("shared.omg_lol_client.OmgLolClient", return_value=client):
            artifact = _FakeArtifact(title="t", body_md="b")
            assert publish_artifact(artifact) == "no_credentials"

    def test_happy_path_returns_ok(self) -> None:
        from unittest.mock import patch

        from agents.omg_weblog_publisher.publisher import publish_artifact

        client = MagicMock()
        client.enabled = True
        client.set_entry.return_value = {"ok": True}
        with patch("shared.omg_lol_client.OmgLolClient", return_value=client):
            artifact = _FakeArtifact(
                slug="hello-world",
                title="Hello World",
                attribution_block="Hapax + CC.",
                abstract="Abstract.",
                body_md="Body.",
            )
            assert publish_artifact(artifact) == "ok"
        client.set_entry.assert_called_once()
        kwargs = client.set_entry.call_args.kwargs
        args = client.set_entry.call_args.args
        assert args[1] == "hello-world"
        # Content carries omg.lol-required inline Date line + sections.
        content = kwargs["content"]
        assert content.startswith("Date: ")
        assert "# Hello World" in content
        assert "Hapax + CC." in content
        assert "Abstract." in content
        assert "Body." in content

    def test_set_entry_returns_none_yields_error(self) -> None:
        from unittest.mock import patch

        from agents.omg_weblog_publisher.publisher import publish_artifact

        client = MagicMock()
        client.enabled = True
        client.set_entry.return_value = None
        with patch("shared.omg_lol_client.OmgLolClient", return_value=client):
            artifact = _FakeArtifact(title="t", body_md="b")
            assert publish_artifact(artifact) == "error"

    def test_set_entry_raises_yields_error(self) -> None:
        from unittest.mock import patch

        from agents.omg_weblog_publisher.publisher import publish_artifact

        client = MagicMock()
        client.enabled = True
        client.set_entry.side_effect = RuntimeError("network down")
        with patch("shared.omg_lol_client.OmgLolClient", return_value=client):
            artifact = _FakeArtifact(title="t", body_md="b")
            assert publish_artifact(artifact) == "error"

    def test_empty_artifact_returns_error(self) -> None:
        from unittest.mock import patch

        from agents.omg_weblog_publisher.publisher import publish_artifact

        client = MagicMock()
        client.enabled = True
        with patch("shared.omg_lol_client.OmgLolClient", return_value=client):
            artifact = _FakeArtifact()  # all fields empty
            assert publish_artifact(artifact) == "error"

    def test_allowlist_deny_returns_denied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock as _MM
        from unittest.mock import patch

        from agents.omg_weblog_publisher.publisher import publish_artifact

        client = MagicMock()
        client.enabled = True
        deny = _MM()
        deny.decision = "deny"
        deny.reason = "test reason"

        def _check(*_args, **_kwargs):
            return deny

        monkeypatch.setattr("agents.omg_weblog_publisher.publisher.allowlist_check", _check)
        with patch("shared.omg_lol_client.OmgLolClient", return_value=client):
            artifact = _FakeArtifact(title="t", body_md="b")
            assert publish_artifact(artifact) == "denied"
        client.set_entry.assert_not_called()

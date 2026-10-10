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


def _grounding_gate() -> dict:
    return {
        "schema_version": 1,
        "public_private_mode": "public_archive",
        "gate_state": "pass",
        "claim": {
            "evidence_refs": ["weblog:draft"],
            "provenance": {"source_refs": ["weblog:source"]},
            "freshness": {"status": "not_applicable"},
            "rights_state": "operator_original",
            "privacy_state": "public_safe",
            "public_private_mode": "public_archive",
            "refusal_correction_path": {
                "refusal_reason": None,
                "correction_event_ref": None,
                "artifact_ref": None,
            },
        },
        "gate_result": {
            "may_emit_claim": True,
            "may_publish_live": False,
            "may_publish_archive": True,
            "may_monetize": False,
        },
    }


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
            grounding_gate_result=_grounding_gate(),
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
            grounding_gate_result=_grounding_gate(),
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
        grounding_gate_result: dict | None = None,
    ) -> None:
        self.slug = slug
        self.title = title
        self.abstract = abstract
        self.body_md = body_md
        self.attribution_block = attribution_block
        self.grounding_gate_result = (
            _grounding_gate() if grounding_gate_result is None else grounding_gate_result
        )


class TestPublishArtifact:
    @pytest.mark.parametrize(
        ("slug", "title", "body"),
        [
            (
                "att0011-cor0003-weblog-20261008",
                "Correction to the lab's notebook-entry attestation",
                "Zero completed attribution checks did not establish that there were no entries. "
                "The commitment's outcome is undetermined.",
            ),
            (
                "notebook-after-the-window",
                "After the window closed, the result remained undetermined",
                "The earlier attestations remain available as historical records.",
            ),
            (
                "refusal-brief",
                "A historical distribution decision",
                "The earlier refusal is a historical record, not a current promise.",
            ),
        ],
    )
    def test_compose_does_not_invent_distribution_policy(
        self, slug: str, title: str, body: str
    ) -> None:
        from datetime import datetime

        from agents.omg_weblog_publisher.publisher import _compose_artifact_content
        from shared.preprint_artifact import PreprintArtifact

        attribution = "Prepared by GPT; independent review remains pending."
        abstract = "A dated account of the evidence inspected."
        artifact = PreprintArtifact(
            slug=slug,
            title=title,
            attribution_block=attribution,
            abstract=abstract,
            body_md=f"# {title}\n\n{body}",
        )

        date, rendered = _compose_artifact_content(artifact).split("\n\n", 1)

        datetime.strptime(date, "Date: %Y-%m-%d %H:%M UTC")
        assert rendered == f"# {title}\n\n{attribution}\n\n{abstract}\n\n{body}"

    @pytest.mark.parametrize("location", ["attribution_block", "body_md"])
    def test_compose_preserves_explicit_distribution_posture(self, location: str) -> None:
        from agents.omg_weblog_publisher.publisher import _compose_artifact_content
        from shared.attribution_block import NON_ENGAGEMENT_CLAUSE_LONG
        from shared.preprint_artifact import PreprintArtifact

        # Historical refusal content remains renderable when the artifact actually carries it.
        text = f"Historical distribution statement:\n\n{NON_ENGAGEMENT_CLAUSE_LONG}"
        artifact = PreprintArtifact(
            slug="historical-note", title="Historical note", **{location: text}
        )

        _, rendered = _compose_artifact_content(artifact).split("\n\n", 1)

        assert rendered == f"# Historical note\n\n{text}"

    def test_publish_artifact_transports_admitted_copy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agents.omg_weblog_publisher.publisher import publish_artifact
        from shared.preprint_artifact import PreprintArtifact

        client = MagicMock()
        client.enabled = True
        client.set_entry.return_value = {"ok": True}
        monkeypatch.setattr("shared.omg_lol_client.OmgLolClient", lambda **_: client)
        artifact = PreprintArtifact(
            slug="correction-notice",
            title="Correction notice",
            attribution_block="Machine-assisted draft; reviewed attribution supplied by the artifact.",
            body_md="The correction preserves the original record and explains what was unsupported.",
            grounding_gate_result=_grounding_gate(),
        )

        assert publish_artifact(artifact) == "ok"

        client.set_entry.assert_called_once()
        assert client.set_entry.call_args.args == ("hapax", artifact.slug)
        _, rendered = client.set_entry.call_args.kwargs["content"].split("\n\n", 1)
        assert rendered == (
            f"# {artifact.title}\n\n{artifact.attribution_block}\n\n{artifact.body_md}"
        )

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

    def test_compose_suppresses_auto_abstract_that_duplicates_body_lead(self) -> None:
        from agents.omg_weblog_publisher.publisher import _compose_artifact_content

        title = "Hapax Velocity Report — 2026-04-25"
        lead = (
            "30 PRs, 137 commits, ~33,500 LOC churn in a single 18-hour window "
            "on 2026-04-25. Single-operator system, four concurrent Claude Code "
            "sessions, all on max-effort routing."
        )
        artifact = _FakeArtifact(
            slug="velocity-report-2026-04-25",
            title=title,
            attribution_block="Hapax + Claude Code.",
            abstract=lead[:96],
            body_md=f"# {title}\n\n## §1 Observation\n\n{lead}\n\n## §2 Comparison\n\nBody.",
        )

        content = _compose_artifact_content(artifact)

        assert content.count(lead[:96]) == 1
        assert "## §1 Observation" in content
        assert "Hapax + Claude Code." in content

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

    def test_oudepode_variant_routes_to_oudepode_address(self) -> None:
        """publish_artifact_oudepode targets the oudepode address + key."""
        from unittest.mock import patch

        from agents.omg_weblog_publisher.publisher import publish_artifact_oudepode

        client = MagicMock()
        client.enabled = True
        client.set_entry.return_value = {"ok": True}
        with patch("shared.omg_lol_client.OmgLolClient", return_value=client) as mock_cls:
            artifact = _FakeArtifact(
                slug="oudepode-disclosure",
                title="Oudepode Disclosure",
                attribution_block="Hapax + CC.",
                abstract="A.",
                body_md="B.",
            )
            assert publish_artifact_oudepode(artifact) == "ok"
        # Client constructed with oudepode credentials.
        construct_kwargs = mock_cls.call_args.kwargs
        assert construct_kwargs["address"] == "oudepode"
        assert construct_kwargs["pass_key"] == "omg-lol/oudepode-api-key"
        # set_entry called with the oudepode address (not hapax).
        set_entry_args = client.set_entry.call_args.args
        assert set_entry_args[0] == "oudepode"
        assert set_entry_args[1] == "oudepode-disclosure"

    def test_address_kwarg_propagates_to_set_entry(self) -> None:
        """Custom address kwarg overrides the default and reaches set_entry."""
        from unittest.mock import patch

        from agents.omg_weblog_publisher.publisher import publish_artifact

        client = MagicMock()
        client.enabled = True
        client.set_entry.return_value = {"ok": True}
        with patch("shared.omg_lol_client.OmgLolClient", return_value=client):
            artifact = _FakeArtifact(slug="x", title="t", body_md="b")
            assert publish_artifact(artifact, address="custom-addr") == "ok"
        assert client.set_entry.call_args.args[0] == "custom-addr"


def _entry_response(*, entry_id: str, title: str, source: str, location: str | None = None) -> dict:
    """The omg.lol weblog GET envelope, shaped as the live API returns it."""
    return {
        "request": {"status_code": 200, "success": True},
        "response": {
            "message": "Here is your weblog entry.",
            "entry": {
                "entry": entry_id,
                "location": location or f"/2026/05/{entry_id}",
                "title": title,
                "date": 1778394600,
                "type": "post",
                "status": "live",
                "source": source,
            },
        },
    }


# The two withdrawn May origins, as read on 2026-10-10. One pins its URL with a Slug line. The
# other has only a Date line, and its entry id differs from its URL slug.
PINNED_SOURCE = (
    "---\nDate: 2026-05-10 06:30:00\nSlug: may-10-origin\n---\n\n# Old title\n\nOld body."
)
UNPINNED_SOURCE = "---\nDate: 2026-05-11 23:53 UTC\n---\n\n# Entry 006 — May 10-11, 2026\n\nOld."


def _set_entry_response(location: str | None) -> dict:
    entry = {"entry": "x"} if location is None else {"entry": "x", "location": location}
    return {"response": {"entry": entry}}


class TestInPlaceEntryUpdate:
    """An artifact naming an existing entry replaces its body and keeps where it lives."""

    def _client(
        self, monkeypatch: pytest.MonkeyPatch, read, *, returned_location: str | None = None
    ) -> MagicMock:
        client = MagicMock()
        client.enabled = True
        client.get_entry.return_value = read
        client.set_entry.return_value = _set_entry_response(returned_location)
        monkeypatch.setattr("shared.omg_lol_client.OmgLolClient", lambda **_: client)
        return client

    def _artifact(self, *, entry_id: str, title: str, body: str = "New body."):
        from shared.preprint_artifact import PreprintArtifact

        return PreprintArtifact(
            slug=entry_id,
            title=title,
            body_md=body,
            weblog_entry_update=entry_id,
            grounding_gate_result=_grounding_gate(),
        )

    def test_update_keeps_the_metadata_and_replaces_only_the_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agents.omg_weblog_publisher.publisher import publish_artifact

        before = _entry_response(entry_id="may-10-origin", title="Old title", source=PINNED_SOURCE)
        client = self._client(monkeypatch, before, returned_location="/2026/05/may-10-origin")

        result = publish_artifact(self._artifact(entry_id="may-10-origin", title="New title"))

        assert result == "ok"
        client.set_entry.assert_called_once()
        assert client.set_entry.call_args.args == ("hapax", "may-10-origin")
        assert client.set_entry.call_args.kwargs["content"] == (
            "---\nDate: 2026-05-10 06:30:00\nSlug: may-10-origin\n---\n\n# New title\n\nNew body."
        )

    def test_an_unpinned_entry_gets_its_current_url_slug_not_its_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agents.omg_weblog_publisher.publisher import publish_artifact

        location = "/2026/05/entry-006-may-10-11-2026"
        before = _entry_response(
            entry_id="entry-006-may-10-11",
            title="Entry 006 — May 10-11, 2026",
            source=UNPINNED_SOURCE,
            location=location,
        )
        client = self._client(monkeypatch, before, returned_location=location)

        # With the slug pinned, a changed title can no longer move the entry.
        result = publish_artifact(
            self._artifact(entry_id="entry-006-may-10-11", title="A new title")
        )

        assert result == "ok"
        assert client.set_entry.call_args.kwargs["content"] == (
            "---\nDate: 2026-05-11 23:53 UTC\nSlug: entry-006-may-10-11-2026\n---\n\n"
            "# A new title\n\nNew body."
        )

    def test_an_unfenced_date_line_as_this_publisher_writes_is_kept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agents.omg_weblog_publisher.publisher import publish_artifact

        source = "Date: 2026-10-10 19:57 UTC\n\n# Notebook entry\n\nOld."
        before = _entry_response(
            entry_id="notebook-x",
            title="Notebook entry",
            source=source,
            location="/2026/10/notebook-x",
        )
        client = self._client(monkeypatch, before, returned_location="/2026/10/notebook-x")

        result = publish_artifact(self._artifact(entry_id="notebook-x", title="Notebook entry"))

        assert result == "ok"
        assert client.set_entry.call_args.kwargs["content"] == (
            "---\nDate: 2026-10-10 19:57 UTC\nSlug: notebook-x\n---\n\n# Notebook entry\n\nNew body."
        )

    def test_an_unreadable_entry_writes_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agents.omg_weblog_publisher.publisher import publish_artifact

        client = self._client(monkeypatch, None)

        result = publish_artifact(self._artifact(entry_id="may-10-origin", title="New title"))

        assert result == "error"
        client.set_entry.assert_not_called()

    @pytest.mark.parametrize(
        ("source", "location"),
        [
            ("# Old title\n\nNo metadata block at all.", None),
            ("---\nSlug: may-10-origin\n---\n\n# Old title\n\nNo Date line.", None),
            ("---\nDate: 2026-05-10 06:30:00\nSlug: may-10-origin\n\n# Never closes.", None),
            (PINNED_SOURCE.replace("Slug: may-10-origin", "Slug: another-slug"), None),
            (PINNED_SOURCE.replace("2026-05-10", "2026-06-10"), None),
            (PINNED_SOURCE, "/weblog"),
        ],
        ids=["no-block", "no-date", "unclosed", "slug-disagrees", "month-disagrees", "location"],
    )
    def test_metadata_that_disagrees_with_the_location_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, source: str, location: str | None
    ) -> None:
        from agents.omg_weblog_publisher.publisher import publish_artifact

        before = _entry_response(
            entry_id="may-10-origin", title="Old title", source=source, location=location
        )
        client = self._client(monkeypatch, before)

        result = publish_artifact(self._artifact(entry_id="may-10-origin", title="New title"))

        assert result == "denied"
        client.set_entry.assert_not_called()

    def test_a_returned_location_that_moved_is_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agents.omg_weblog_publisher.publisher import publish_artifact

        before = _entry_response(entry_id="may-10-origin", title="Old title", source=PINNED_SOURCE)
        client = self._client(monkeypatch, before, returned_location="/2026/10/new-title")

        result = publish_artifact(self._artifact(entry_id="may-10-origin", title="New title"))

        assert result == "error"
        client.set_entry.assert_called_once()

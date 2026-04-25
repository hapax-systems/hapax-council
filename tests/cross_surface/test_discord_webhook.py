"""Tests for ``agents.cross_surface.discord_webhook``."""

from __future__ import annotations

import json
from unittest import mock

from prometheus_client import CollectorRegistry

from agents.cross_surface.discord_webhook import (
    DISCORD_EMBED_COLOR,
    EVENT_TYPE,
    DiscordWebhookPoster,
    _broadcast_url_from_event,
    _webhook_url_from_env,
)


def _write_events(path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")


def _make_poster(
    *,
    event_path,
    cursor_path,
    webhook_url: str | None = "https://discord.test/webhook/abc",
    compose_fn=None,
    post_fn=None,
    dry_run: bool = False,
) -> tuple[DiscordWebhookPoster, mock.Mock]:
    if post_fn is None:
        post_fn = mock.Mock(return_value=True)
    if compose_fn is None:
        compose_fn = mock.Mock(return_value=("test title", "test description"))
    poster = DiscordWebhookPoster(
        webhook_url=webhook_url,
        compose_fn=compose_fn,
        post_fn=post_fn,
        event_path=event_path,
        cursor_path=cursor_path,
        registry=CollectorRegistry(),
        dry_run=dry_run,
    )
    return poster, post_fn


# ── Cursor + tail ────────────────────────────────────────────────────


class TestCursor:
    def test_missing_event_file_handles_cleanly(self, tmp_path):
        poster, _ = _make_poster(
            event_path=tmp_path / "absent.jsonl",
            cursor_path=tmp_path / "cursor.txt",
        )
        assert poster.run_once() == 0

    def test_persists_cursor(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        cursor = tmp_path / "cursor.txt"
        poster, _ = _make_poster(event_path=bus, cursor_path=cursor)
        poster.run_once()
        assert int(cursor.read_text()) == bus.stat().st_size

    def test_cursor_resume_skips_processed(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        cursor = tmp_path / "cursor.txt"
        _write_events(
            bus,
            [
                {"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"},
                {"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-B"},
            ],
        )
        poster, post_fn = _make_poster(event_path=bus, cursor_path=cursor)
        poster.run_once()
        assert post_fn.call_count == 2
        poster.run_once()  # no new events
        assert post_fn.call_count == 2


# ── Event filtering ──────────────────────────────────────────────────


class TestEventFiltering:
    def test_skips_non_broadcast_rotated(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                {"event_type": "stream_started"},
                {"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"},
            ],
        )
        poster, post_fn = _make_poster(event_path=bus, cursor_path=tmp_path / "cursor.txt")
        poster.run_once()
        assert post_fn.call_count == 1


# ── Dry-run ──────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_does_not_post(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        poster, post_fn = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            dry_run=True,
        )
        poster.run_once()
        post_fn.assert_not_called()

    def test_dry_run_advances_cursor(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        cursor = tmp_path / "cursor.txt"
        poster, _ = _make_poster(event_path=bus, cursor_path=cursor, dry_run=True)
        poster.run_once()
        assert int(cursor.read_text()) == bus.stat().st_size


# ── Allowlist ────────────────────────────────────────────────────────


class TestAllowlist:
    def test_deny_short_circuits(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        poster, post_fn = _make_poster(event_path=bus, cursor_path=tmp_path / "cursor.txt")

        from agents.cross_surface import discord_webhook as mod

        denied = mock.Mock()
        denied.decision = "deny"
        denied.reason = "test override"
        with mock.patch.object(mod, "allowlist_check", return_value=denied):
            poster.run_once()
        post_fn.assert_not_called()


# ── Payload shape ────────────────────────────────────────────────────


class TestPayload:
    def test_payload_includes_embed_with_url(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                {
                    "event_type": EVENT_TYPE,
                    "incoming_broadcast_id": "vid-A",
                    "incoming_broadcast_url": "https://www.youtube.com/watch?v=vid-A",
                }
            ],
        )
        post_fn = mock.Mock(return_value=True)
        compose_fn = mock.Mock(return_value=("the title", "the description"))
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            post_fn=post_fn,
            compose_fn=compose_fn,
        )
        poster.run_once()

        post_fn.assert_called_once()
        call_args = post_fn.call_args
        url = call_args[0][0]
        payload = call_args[0][1]
        assert url == "https://discord.test/webhook/abc"
        assert payload["embeds"][0]["title"] == "the title"
        assert payload["embeds"][0]["description"] == "the description"
        assert payload["embeds"][0]["url"] == "https://www.youtube.com/watch?v=vid-A"
        assert payload["embeds"][0]["color"] == DISCORD_EMBED_COLOR

    def test_url_synthesized_from_id_when_url_missing(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-Z"}])
        post_fn = mock.Mock(return_value=True)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            post_fn=post_fn,
        )
        poster.run_once()
        payload = post_fn.call_args[0][1]
        assert payload["embeds"][0]["url"] == "https://www.youtube.com/watch?v=vid-Z"

    def test_url_omitted_when_unknown(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE}])
        post_fn = mock.Mock(return_value=True)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            post_fn=post_fn,
        )
        poster.run_once()
        payload = post_fn.call_args[0][1]
        assert "url" not in payload["embeds"][0]


# ── Webhook URL handling ─────────────────────────────────────────────


class TestWebhookUrl:
    def test_missing_webhook_url_skips_post(self, tmp_path, caplog):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        post_fn = mock.Mock()
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            webhook_url=None,
            post_fn=post_fn,
        )
        with caplog.at_level("WARNING"):
            poster.run_once()
        post_fn.assert_not_called()
        assert any("webhook" in r.message.lower() for r in caplog.records)

    def test_post_failure_returns_error_label(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        post_fn = mock.Mock(return_value=False)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            post_fn=post_fn,
        )
        poster.run_once()
        # error counter ticked
        samples = list(poster.posts_total.collect())
        error_value = next(
            (s.value for m in samples for s in m.samples if s.labels.get("result") == "error"),
            0,
        )
        assert error_value == 1.0

    def test_post_raises_returns_error_label(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        post_fn = mock.Mock(side_effect=RuntimeError("network down"))
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            post_fn=post_fn,
        )
        poster.run_once()
        samples = list(poster.posts_total.collect())
        error_value = next(
            (s.value for m in samples for s in m.samples if s.labels.get("result") == "error"),
            0,
        )
        assert error_value == 1.0


class TestEnvUrl:
    def test_reads_env(self, monkeypatch):
        monkeypatch.setenv("HAPAX_DISCORD_WEBHOOK_URL", "https://discord.test/x")
        assert _webhook_url_from_env() == "https://discord.test/x"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("HAPAX_DISCORD_WEBHOOK_URL", "  https://discord.test/x  ")
        assert _webhook_url_from_env() == "https://discord.test/x"

    def test_returns_none_when_missing(self, monkeypatch):
        monkeypatch.delenv("HAPAX_DISCORD_WEBHOOK_URL", raising=False)
        assert _webhook_url_from_env() is None

    def test_returns_none_when_empty(self, monkeypatch):
        monkeypatch.setenv("HAPAX_DISCORD_WEBHOOK_URL", "")
        assert _webhook_url_from_env() is None


class TestUrlExtractor:
    def test_uses_explicit_url_when_present(self):
        event = {
            "incoming_broadcast_id": "vid-A",
            "incoming_broadcast_url": "https://example.com/explicit",
        }
        assert _broadcast_url_from_event(event) == "https://example.com/explicit"

    def test_synthesizes_from_id(self):
        event = {"incoming_broadcast_id": "vid-Z"}
        assert _broadcast_url_from_event(event) == "https://www.youtube.com/watch?v=vid-Z"

    def test_returns_none_when_missing_both(self):
        event = {}
        assert _broadcast_url_from_event(event) is None


# ── Orchestrator entry-point (PUB-P1-D foundation) ───────────────────


class _FakeArtifact:
    def __init__(
        self,
        *,
        slug: str = "test",
        title: str = "",
        abstract: str = "",
        attribution_block: str = "",
        doi: str | None = None,
    ) -> None:
        self.slug = slug
        self.title = title
        self.abstract = abstract
        self.attribution_block = attribution_block
        self.doi = doi


class TestPublishArtifact:
    def test_no_credentials_returns_no_credentials(self, monkeypatch):
        from agents.cross_surface.discord_webhook import publish_artifact

        monkeypatch.setenv("HAPAX_DISCORD_WEBHOOK_URL", "")
        artifact = _FakeArtifact(title="x", abstract="y")
        assert publish_artifact(artifact) == "no_credentials"

    def test_attribution_block_preferred_in_description(self, monkeypatch):
        from agents.cross_surface import discord_webhook

        monkeypatch.setenv("HAPAX_DISCORD_WEBHOOK_URL", "https://discord.test/webhook/abc")
        with mock.patch.object(discord_webhook, "_default_post", return_value=True) as post:
            artifact = _FakeArtifact(
                title="Title",
                abstract="Abstract.",
                attribution_block="Attribution Block",
            )
            assert discord_webhook.publish_artifact(artifact) == "ok"
        payload = post.call_args.args[1]
        assert payload["embeds"][0]["title"] == "Title"
        assert payload["embeds"][0]["description"] == "Attribution Block"
        assert payload["embeds"][0]["color"] == discord_webhook.DISCORD_EMBED_COLOR

    def test_abstract_fallback_when_no_attribution(self, monkeypatch):
        from agents.cross_surface import discord_webhook

        monkeypatch.setenv("HAPAX_DISCORD_WEBHOOK_URL", "https://discord.test/webhook/abc")
        with mock.patch.object(discord_webhook, "_default_post", return_value=True) as post:
            artifact = _FakeArtifact(title="T", abstract="A")
            assert discord_webhook.publish_artifact(artifact) == "ok"
        assert post.call_args.args[1]["embeds"][0]["description"] == "A"

    def test_doi_yields_embed_url(self, monkeypatch):
        from agents.cross_surface import discord_webhook

        monkeypatch.setenv("HAPAX_DISCORD_WEBHOOK_URL", "https://discord.test/webhook/abc")
        with mock.patch.object(discord_webhook, "_default_post", return_value=True) as post:
            artifact = _FakeArtifact(title="T", abstract="A", doi="10.5281/zenodo.1234")
            assert discord_webhook.publish_artifact(artifact) == "ok"
        assert post.call_args.args[1]["embeds"][0]["url"] == "https://doi.org/10.5281/zenodo.1234"

    def test_no_doi_omits_embed_url(self, monkeypatch):
        from agents.cross_surface import discord_webhook

        monkeypatch.setenv("HAPAX_DISCORD_WEBHOOK_URL", "https://discord.test/webhook/abc")
        with mock.patch.object(discord_webhook, "_default_post", return_value=True) as post:
            artifact = _FakeArtifact(title="T", abstract="A")
            assert discord_webhook.publish_artifact(artifact) == "ok"
        assert "url" not in post.call_args.args[1]["embeds"][0]

    def test_post_returns_false_yields_error(self, monkeypatch):
        from agents.cross_surface import discord_webhook

        monkeypatch.setenv("HAPAX_DISCORD_WEBHOOK_URL", "https://discord.test/webhook/abc")
        with mock.patch.object(discord_webhook, "_default_post", return_value=False):
            artifact = _FakeArtifact(title="T", abstract="A")
            assert discord_webhook.publish_artifact(artifact) == "error"

    def test_post_raises_yields_error(self, monkeypatch):
        from agents.cross_surface import discord_webhook

        monkeypatch.setenv("HAPAX_DISCORD_WEBHOOK_URL", "https://discord.test/webhook/abc")
        with mock.patch.object(
            discord_webhook,
            "_default_post",
            side_effect=RuntimeError("network down"),
        ):
            artifact = _FakeArtifact(title="T", abstract="A")
            assert discord_webhook.publish_artifact(artifact) == "error"

    def test_title_truncated_to_256(self, monkeypatch):
        from agents.cross_surface import discord_webhook

        monkeypatch.setenv("HAPAX_DISCORD_WEBHOOK_URL", "https://discord.test/webhook/abc")
        with mock.patch.object(discord_webhook, "_default_post", return_value=True) as post:
            artifact = _FakeArtifact(title="x" * 300, abstract="A")
            assert discord_webhook.publish_artifact(artifact) == "ok"
        assert len(post.call_args.args[1]["embeds"][0]["title"]) == 256

    def test_description_truncated_to_4096(self, monkeypatch):
        from agents.cross_surface import discord_webhook

        monkeypatch.setenv("HAPAX_DISCORD_WEBHOOK_URL", "https://discord.test/webhook/abc")
        with mock.patch.object(discord_webhook, "_default_post", return_value=True) as post:
            artifact = _FakeArtifact(title="T", attribution_block="x" * 5000)
            assert discord_webhook.publish_artifact(artifact) == "ok"
        assert len(post.call_args.args[1]["embeds"][0]["description"]) == 4096

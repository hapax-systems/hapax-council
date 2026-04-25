"""Tests for ``agents.cross_surface.arena_post``."""

from __future__ import annotations

import json
from unittest import mock

from prometheus_client import CollectorRegistry

from agents.cross_surface.arena_post import (
    ARENA_BLOCK_TEXT_LIMIT,
    EVENT_TYPE,
    ArenaPoster,
    _credentials_from_env,
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
    token: str | None = "test-token",
    channel_slug: str | None = "hapax-visual-surface",
    compose_fn=None,
    client_factory=None,
    dry_run: bool = False,
) -> tuple[ArenaPoster, mock.Mock]:
    if client_factory is None:
        client = mock.Mock()
        client.add_block.return_value = None
        client_factory = mock.Mock(return_value=client)
    if compose_fn is None:
        compose_fn = mock.Mock(return_value=("default test block", None))
    poster = ArenaPoster(
        token=token,
        channel_slug=channel_slug,
        compose_fn=compose_fn,
        client_factory=client_factory,
        event_path=event_path,
        cursor_path=cursor_path,
        registry=CollectorRegistry(),
        dry_run=dry_run,
    )
    return poster, client_factory


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
        client = mock.Mock()
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )
        poster.run_once()
        assert client.add_block.call_count == 1


# ── Dry run ──────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_does_not_send(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        client = mock.Mock()
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
            dry_run=True,
        )
        poster.run_once()
        assert client.add_block.call_count == 0


# ── Live send ────────────────────────────────────────────────────────


class TestSendBlock:
    def test_text_only_block_uses_content(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        client = mock.Mock()
        factory = mock.Mock(return_value=client)
        compose_fn = mock.Mock(return_value=("Reverie pass 7 — RD step 0.18", None))
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
            compose_fn=compose_fn,
        )
        poster.run_once()
        client.add_block.assert_called_once_with(
            "hapax-visual-surface",
            content="Reverie pass 7 — RD step 0.18",
            source=None,
        )

    def test_link_block_uses_source(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        client = mock.Mock()
        factory = mock.Mock(return_value=client)
        compose_fn = mock.Mock(
            return_value=("livestream chronicle moment", "https://hapax.omg.lol/clips/x")
        )
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
            compose_fn=compose_fn,
        )
        poster.run_once()
        client.add_block.assert_called_once_with(
            "hapax-visual-surface",
            content="livestream chronicle moment",
            source="https://hapax.omg.lol/clips/x",
        )

    def test_no_credentials_skips_send(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        factory = mock.Mock()
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            token=None,
            channel_slug=None,
            client_factory=factory,
        )
        poster.run_once()
        factory.assert_not_called()

    def test_content_truncated_to_limit(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        client = mock.Mock()
        factory = mock.Mock(return_value=client)
        oversized = "x" * (ARENA_BLOCK_TEXT_LIMIT + 100)
        compose_fn = mock.Mock(return_value=(oversized, None))
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
            compose_fn=compose_fn,
        )
        poster.run_once()
        sent_content = client.add_block.call_args.kwargs["content"]
        assert len(sent_content) == ARENA_BLOCK_TEXT_LIMIT


# ── Credentials helper ──────────────────────────────────────────────


class TestCredentials:
    def test_reads_env(self, monkeypatch):
        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "abc")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "ch")
        assert _credentials_from_env() == ("abc", "ch")

    def test_empty_env_yields_none(self, monkeypatch):
        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "")
        assert _credentials_from_env() == (None, None)


# ── Orchestrator entry-point (PUB-P1-C foundation) ───────────────────


class _FakeArtifact:
    """Minimal duck-type for ``publish_artifact`` tests.

    Mirrors the surface ``PreprintArtifact`` exposes today: ``slug``,
    ``title``, ``abstract``, ``attribution_block``, ``doi``,
    ``embed_image_url``. Pydantic isn't pulled in here so the test
    isn't coupled to model evolution.
    """

    def __init__(
        self,
        *,
        slug: str = "test",
        title: str = "",
        abstract: str = "",
        attribution_block: str = "",
        doi: str | None = None,
        embed_image_url: str | None = None,
    ) -> None:
        self.slug = slug
        self.title = title
        self.abstract = abstract
        self.attribution_block = attribution_block
        self.doi = doi
        self.embed_image_url = embed_image_url


class TestPublishArtifact:
    def test_no_credentials_returns_no_credentials(self, monkeypatch):
        from agents.cross_surface.arena_post import publish_artifact

        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "")
        artifact = _FakeArtifact(title="x", abstract="y")
        assert publish_artifact(artifact) == "no_credentials"

    def test_only_token_set_returns_no_credentials(self, monkeypatch):
        from agents.cross_surface.arena_post import publish_artifact

        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "")
        artifact = _FakeArtifact(title="x", abstract="y")
        assert publish_artifact(artifact) == "no_credentials"

    def test_attribution_block_preferred(self, monkeypatch):
        from agents.cross_surface import arena_post

        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "ch")
        client = mock.Mock()
        client.add_block.return_value = None
        with mock.patch.object(arena_post, "_default_client_factory", return_value=client):
            artifact = _FakeArtifact(
                title="Title",
                abstract="Abstract.",
                attribution_block="Attribution Block",
            )
            assert arena_post.publish_artifact(artifact) == "ok"
        kwargs = client.add_block.call_args.kwargs
        args = client.add_block.call_args.args
        assert args == ("ch",)
        assert kwargs["content"] == "Attribution Block"
        assert kwargs["source"] is None

    def test_title_abstract_fallback(self, monkeypatch):
        from agents.cross_surface import arena_post

        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "ch")
        client = mock.Mock()
        client.add_block.return_value = None
        with mock.patch.object(arena_post, "_default_client_factory", return_value=client):
            artifact = _FakeArtifact(title="Title", abstract="Abstract.")
            assert arena_post.publish_artifact(artifact) == "ok"
        assert client.add_block.call_args.kwargs["content"] == "Title — Abstract."

    def test_doi_yields_source_url(self, monkeypatch):
        from agents.cross_surface import arena_post

        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "ch")
        client = mock.Mock()
        client.add_block.return_value = None
        with mock.patch.object(arena_post, "_default_client_factory", return_value=client):
            artifact = _FakeArtifact(title="T", abstract="A", doi="10.5281/zenodo.1234")
            assert arena_post.publish_artifact(artifact) == "ok"
        assert client.add_block.call_args.kwargs["source"] == "https://doi.org/10.5281/zenodo.1234"

    def test_embed_image_used_when_no_doi(self, monkeypatch):
        from agents.cross_surface import arena_post

        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "ch")
        client = mock.Mock()
        client.add_block.return_value = None
        with mock.patch.object(arena_post, "_default_client_factory", return_value=client):
            artifact = _FakeArtifact(
                title="T",
                abstract="A",
                embed_image_url="https://cdn.example/img.png",
            )
            assert arena_post.publish_artifact(artifact) == "ok"
        assert client.add_block.call_args.kwargs["source"] == "https://cdn.example/img.png"

    def test_content_truncated_to_limit(self, monkeypatch):
        from agents.cross_surface import arena_post

        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "ch")
        client = mock.Mock()
        client.add_block.return_value = None
        with mock.patch.object(arena_post, "_default_client_factory", return_value=client):
            artifact = _FakeArtifact(attribution_block="x" * (ARENA_BLOCK_TEXT_LIMIT + 50))
            assert arena_post.publish_artifact(artifact) == "ok"
        assert len(client.add_block.call_args.kwargs["content"]) == ARENA_BLOCK_TEXT_LIMIT

    def test_factory_failure_yields_auth_error(self, monkeypatch):
        from agents.cross_surface import arena_post

        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "ch")
        with mock.patch.object(
            arena_post,
            "_default_client_factory",
            side_effect=RuntimeError("boom"),
        ):
            artifact = _FakeArtifact(title="t", abstract="a")
            assert arena_post.publish_artifact(artifact) == "auth_error"

    def test_add_block_failure_yields_error(self, monkeypatch):
        from agents.cross_surface import arena_post

        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "ch")
        client = mock.Mock()
        client.add_block.side_effect = RuntimeError("api down")
        with mock.patch.object(arena_post, "_default_client_factory", return_value=client):
            artifact = _FakeArtifact(title="t", abstract="a")
            assert arena_post.publish_artifact(artifact) == "error"

    def test_empty_artifact_returns_error_only_when_content_empty(self, monkeypatch):
        from agents.cross_surface import arena_post

        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "ch")
        client = mock.Mock()
        client.add_block.return_value = None
        with mock.patch.object(arena_post, "_default_client_factory", return_value=client):
            # Bare artifact still gets a placeholder, so this is "ok".
            artifact = _FakeArtifact()
            assert arena_post.publish_artifact(artifact) == "ok"
        assert client.add_block.call_args.kwargs["content"] == "hapax — publication artifact"

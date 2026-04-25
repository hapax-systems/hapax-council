"""Tests for ``agents.cross_surface.mastodon_post``."""

from __future__ import annotations

import json
from unittest import mock

from prometheus_client import CollectorRegistry

from agents.cross_surface.mastodon_post import (
    EVENT_TYPE,
    MASTODON_TEXT_LIMIT,
    MastodonPoster,
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
    instance_url: str | None = "https://mastodon.test",
    access_token: str | None = "tok-1234",
    compose_fn=None,
    client_factory=None,
    text_limit: int = MASTODON_TEXT_LIMIT,
    dry_run: bool = False,
) -> tuple[MastodonPoster, mock.Mock]:
    if client_factory is None:
        client = mock.Mock()
        client.status_post.return_value = mock.Mock(id="1234")
        client_factory = mock.Mock(return_value=client)
    if compose_fn is None:
        compose_fn = mock.Mock(return_value="default test toot")
    poster = MastodonPoster(
        instance_url=instance_url,
        access_token=access_token,
        compose_fn=compose_fn,
        client_factory=client_factory,
        event_path=event_path,
        cursor_path=cursor_path,
        registry=CollectorRegistry(),
        text_limit=text_limit,
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
        client.status_post.return_value = mock.Mock(id="1")
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )
        poster.run_once()
        assert client.status_post.call_count == 1


# ── Dry-run ──────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_does_not_call_factory(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        factory = mock.Mock()
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
            dry_run=True,
        )
        poster.run_once()
        factory.assert_not_called()


# ── Allowlist ────────────────────────────────────────────────────────


class TestAllowlist:
    def test_deny_short_circuits(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        client = mock.Mock()
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )

        from agents.cross_surface import mastodon_post as mod

        denied = mock.Mock()
        denied.decision = "deny"
        denied.reason = "test override"
        with mock.patch.object(mod, "allowlist_check", return_value=denied):
            poster.run_once()
        client.status_post.assert_not_called()


# ── Text length cap ──────────────────────────────────────────────────


class TestTextLength:
    def test_text_truncated_to_default_500(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        client = mock.Mock()
        factory = mock.Mock(return_value=client)
        compose_fn = mock.Mock(return_value="x" * 1000)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
            compose_fn=compose_fn,
        )
        poster.run_once()
        sent = client.status_post.call_args.args[0]
        assert len(sent) == MASTODON_TEXT_LIMIT

    def test_text_limit_override(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        client = mock.Mock()
        factory = mock.Mock(return_value=client)
        compose_fn = mock.Mock(return_value="x" * 1000)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
            compose_fn=compose_fn,
            text_limit=200,
        )
        poster.run_once()
        sent = client.status_post.call_args.args[0]
        assert len(sent) == 200


# ── Credentials ──────────────────────────────────────────────────────


class TestCredentials:
    def test_missing_instance_skips_send(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        factory = mock.Mock()
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            instance_url=None,
            client_factory=factory,
        )
        poster.run_once()
        factory.assert_not_called()

    def test_missing_token_skips_send(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        factory = mock.Mock()
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            access_token=None,
            client_factory=factory,
        )
        poster.run_once()
        factory.assert_not_called()

    def test_init_failure_returns_auth_error(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        factory = mock.Mock(side_effect=RuntimeError("invalid creds"))
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )
        poster.run_once()
        samples = list(poster.posts_total.collect())
        auth_error = next(
            (s.value for m in samples for s in m.samples if s.labels.get("result") == "auth_error"),
            0,
        )
        assert auth_error == 1.0

    def test_status_post_raises_returns_error(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        client = mock.Mock()
        client.status_post.side_effect = RuntimeError("api down")
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )
        poster.run_once()
        samples = list(poster.posts_total.collect())
        error = next(
            (s.value for m in samples for s in m.samples if s.labels.get("result") == "error"),
            0,
        )
        assert error == 1.0

    def test_factory_receives_instance_and_token(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        client = mock.Mock()
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
            instance_url="https://custom.instance",
            access_token="custom-tok",
        )
        poster.run_once()
        factory.assert_called_once_with("https://custom.instance", "custom-tok")


class TestEnvCredentials:
    def test_reads_both(self, monkeypatch):
        monkeypatch.setenv("HAPAX_MASTODON_INSTANCE_URL", "https://mastodon.social")
        monkeypatch.setenv("HAPAX_MASTODON_ACCESS_TOKEN", "tok-XYZ")
        assert _credentials_from_env() == ("https://mastodon.social", "tok-XYZ")

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("HAPAX_MASTODON_INSTANCE_URL", "  https://x.test  ")
        monkeypatch.setenv("HAPAX_MASTODON_ACCESS_TOKEN", "  tok  ")
        assert _credentials_from_env() == ("https://x.test", "tok")

    def test_missing_returns_none(self, monkeypatch):
        monkeypatch.delenv("HAPAX_MASTODON_INSTANCE_URL", raising=False)
        monkeypatch.delenv("HAPAX_MASTODON_ACCESS_TOKEN", raising=False)
        assert _credentials_from_env() == (None, None)


# ── Orchestrator entry-point ────────────────────────────────────────


class TestPublishArtifact:
    def test_no_credentials_short_circuits(self, monkeypatch):
        from agents.cross_surface.mastodon_post import publish_artifact
        from shared.preprint_artifact import PreprintArtifact

        monkeypatch.delenv("HAPAX_MASTODON_INSTANCE_URL", raising=False)
        monkeypatch.delenv("HAPAX_MASTODON_ACCESS_TOKEN", raising=False)
        artifact = PreprintArtifact(slug="x", title="T", abstract="A")
        assert publish_artifact(artifact) == "no_credentials"

    def test_compose_uses_attribution_when_present(self):
        from agents.cross_surface.mastodon_post import _compose_artifact_text
        from shared.preprint_artifact import PreprintArtifact

        artifact = PreprintArtifact(
            slug="x",
            title="Title",
            abstract="Abstract.",
            attribution_block="Hapax + Claude Code + Oudepode (unsettled).",
        )
        assert _compose_artifact_text(artifact) == "Hapax + Claude Code + Oudepode (unsettled)."

    def test_compose_falls_back_to_title_abstract(self):
        from agents.cross_surface.mastodon_post import _compose_artifact_text
        from shared.preprint_artifact import PreprintArtifact

        artifact = PreprintArtifact(slug="x", title="Title", abstract="Abstract.")
        assert _compose_artifact_text(artifact) == "Title — Abstract."

    def test_compose_truncates_to_limit(self):
        from agents.cross_surface.mastodon_post import (
            MASTODON_TEXT_LIMIT,
            _compose_artifact_text,
        )
        from shared.preprint_artifact import PreprintArtifact

        artifact = PreprintArtifact(slug="x", title="T", abstract="x" * 800)
        assert len(_compose_artifact_text(artifact)) == MASTODON_TEXT_LIMIT

    def test_publish_artifact_ok_path(self, monkeypatch):
        from agents.cross_surface import mastodon_post
        from shared.preprint_artifact import PreprintArtifact

        monkeypatch.setenv("HAPAX_MASTODON_INSTANCE_URL", "https://x.test")
        monkeypatch.setenv("HAPAX_MASTODON_ACCESS_TOKEN", "tok")

        fake_client = mock.Mock()
        fake_client.status_post.return_value = mock.Mock(id="42")
        monkeypatch.setattr(mastodon_post, "_default_client_factory", lambda i, t: fake_client)

        artifact = PreprintArtifact(slug="x", title="T", abstract="A")
        assert mastodon_post.publish_artifact(artifact) == "ok"
        fake_client.status_post.assert_called_once()

    def test_publish_artifact_auth_error(self, monkeypatch):
        from agents.cross_surface import mastodon_post
        from shared.preprint_artifact import PreprintArtifact

        monkeypatch.setenv("HAPAX_MASTODON_INSTANCE_URL", "https://x.test")
        monkeypatch.setenv("HAPAX_MASTODON_ACCESS_TOKEN", "tok")

        def _raise(i, t):
            raise RuntimeError("login failed")

        monkeypatch.setattr(mastodon_post, "_default_client_factory", _raise)

        artifact = PreprintArtifact(slug="x", title="T", abstract="A")
        assert mastodon_post.publish_artifact(artifact) == "auth_error"

    def test_publish_artifact_send_error(self, monkeypatch):
        from agents.cross_surface import mastodon_post
        from shared.preprint_artifact import PreprintArtifact

        monkeypatch.setenv("HAPAX_MASTODON_INSTANCE_URL", "https://x.test")
        monkeypatch.setenv("HAPAX_MASTODON_ACCESS_TOKEN", "tok")

        fake_client = mock.Mock()
        fake_client.status_post.side_effect = RuntimeError("send failed")
        monkeypatch.setattr(mastodon_post, "_default_client_factory", lambda i, t: fake_client)

        artifact = PreprintArtifact(slug="x", title="T", abstract="A")
        assert mastodon_post.publish_artifact(artifact) == "error"

"""Tests for ``agents.cross_surface.bluesky_post``."""

from __future__ import annotations

import json
from unittest import mock

from prometheus_client import CollectorRegistry

from agents.cross_surface.bluesky_post import (
    BLUESKY_TEXT_LIMIT,
    EVENT_TYPE,
    BlueskyPoster,
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
    handle: str | None = "hapax.bsky.social",
    app_password: str | None = "test-pw-1234",
    compose_fn=None,
    client_factory=None,
    dry_run: bool = False,
) -> tuple[BlueskyPoster, mock.Mock]:
    if client_factory is None:
        client = mock.Mock()
        client.send_post.return_value = mock.Mock(uri="at://example/post/1")
        client_factory = mock.Mock(return_value=client)
    if compose_fn is None:
        compose_fn = mock.Mock(return_value="default test post")
    poster = BlueskyPoster(
        handle=handle,
        app_password=app_password,
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
        client.send_post.return_value = mock.Mock(uri="at://post/1")
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )
        poster.run_once()
        assert client.send_post.call_count == 1


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
        client = mock.Mock()
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )

        from agents.cross_surface import bluesky_post as mod

        denied = mock.Mock()
        denied.decision = "deny"
        denied.reason = "test override"
        with mock.patch.object(mod, "allowlist_check", return_value=denied):
            poster.run_once()
        client.send_post.assert_not_called()


# ── Text length cap ──────────────────────────────────────────────────


class TestTextLength:
    def test_text_truncated_to_300_chars(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        client = mock.Mock()
        factory = mock.Mock(return_value=client)
        long_text = "x" * 500
        compose_fn = mock.Mock(return_value=long_text)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
            compose_fn=compose_fn,
        )
        poster.run_once()
        sent = client.send_post.call_args.kwargs["text"]
        assert len(sent) == BLUESKY_TEXT_LIMIT


# ── Credentials ──────────────────────────────────────────────────────


class TestCredentials:
    def test_missing_handle_skips_send(self, tmp_path, caplog):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        factory = mock.Mock()
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            handle=None,
            client_factory=factory,
        )
        with caplog.at_level("WARNING"):
            poster.run_once()
        factory.assert_not_called()

    def test_missing_password_skips_send(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        factory = mock.Mock()
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            app_password=None,
            client_factory=factory,
        )
        poster.run_once()
        factory.assert_not_called()

    def test_login_failure_returns_auth_error(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        factory = mock.Mock(side_effect=RuntimeError("invalid creds"))
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )
        poster.run_once()
        # auth_error counter should tick.
        samples = list(poster.posts_total.collect())
        auth_error = next(
            (s.value for m in samples for s in m.samples if s.labels.get("result") == "auth_error"),
            0,
        )
        assert auth_error == 1.0

    def test_send_post_raises_returns_error(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        client = mock.Mock()
        client.send_post.side_effect = RuntimeError("api down")
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

    def test_client_factory_receives_handle_and_password(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        client = mock.Mock()
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
            handle="custom.handle",
            app_password="custom-pw",
        )
        poster.run_once()
        factory.assert_called_once_with("custom.handle", "custom-pw")


class TestEnvCredentials:
    def test_reads_both(self, monkeypatch):
        monkeypatch.setenv("HAPAX_BLUESKY_HANDLE", "h.bsky.social")
        monkeypatch.setenv("HAPAX_BLUESKY_APP_PASSWORD", "abcd-1234")
        assert _credentials_from_env() == ("h.bsky.social", "abcd-1234")

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("HAPAX_BLUESKY_HANDLE", "  h.bsky.social  ")
        monkeypatch.setenv("HAPAX_BLUESKY_APP_PASSWORD", "  abcd-1234  ")
        assert _credentials_from_env() == ("h.bsky.social", "abcd-1234")

    def test_missing_handle_returns_none(self, monkeypatch):
        monkeypatch.delenv("HAPAX_BLUESKY_HANDLE", raising=False)
        monkeypatch.setenv("HAPAX_BLUESKY_APP_PASSWORD", "abcd-1234")
        assert _credentials_from_env() == (None, "abcd-1234")

    def test_missing_both_returns_none(self, monkeypatch):
        monkeypatch.delenv("HAPAX_BLUESKY_HANDLE", raising=False)
        monkeypatch.delenv("HAPAX_BLUESKY_APP_PASSWORD", raising=False)
        assert _credentials_from_env() == (None, None)


# ── Orchestrator entry-point ────────────────────────────────────────


class TestPublishArtifact:
    def test_no_credentials_short_circuits(self, monkeypatch):
        from agents.cross_surface.bluesky_post import publish_artifact
        from shared.preprint_artifact import PreprintArtifact

        monkeypatch.delenv("HAPAX_BLUESKY_HANDLE", raising=False)
        monkeypatch.delenv("HAPAX_BLUESKY_APP_PASSWORD", raising=False)
        artifact = PreprintArtifact(slug="x", title="T", abstract="A")
        assert publish_artifact(artifact) == "no_credentials"

    def test_compose_uses_attribution_when_present(self, monkeypatch):
        from agents.cross_surface.bluesky_post import _compose_artifact_text
        from shared.preprint_artifact import PreprintArtifact

        artifact = PreprintArtifact(
            slug="x",
            title="Title",
            abstract="Abstract.",
            attribution_block="Hapax + Claude Code + Oudepode (unsettled).",
        )
        assert _compose_artifact_text(artifact) == "Hapax + Claude Code + Oudepode (unsettled)."

    def test_compose_falls_back_to_title_abstract(self):
        from agents.cross_surface.bluesky_post import _compose_artifact_text
        from shared.preprint_artifact import PreprintArtifact

        artifact = PreprintArtifact(slug="x", title="Title", abstract="Abstract.")
        assert _compose_artifact_text(artifact) == "Title — Abstract."

    def test_compose_truncates_to_limit(self):
        from agents.cross_surface.bluesky_post import (
            BLUESKY_TEXT_LIMIT,
            _compose_artifact_text,
        )
        from shared.preprint_artifact import PreprintArtifact

        artifact = PreprintArtifact(
            slug="x",
            title="T",
            abstract="x" * 500,
        )
        assert len(_compose_artifact_text(artifact)) == BLUESKY_TEXT_LIMIT

    def test_publish_artifact_ok_path(self, monkeypatch):
        from agents.cross_surface import bluesky_post
        from shared.preprint_artifact import PreprintArtifact

        monkeypatch.setenv("HAPAX_BLUESKY_HANDLE", "h.bsky.social")
        monkeypatch.setenv("HAPAX_BLUESKY_APP_PASSWORD", "abcd-1234")

        fake_client = mock.Mock()
        fake_client.send_post.return_value = mock.Mock(uri="at://post/1")
        monkeypatch.setattr(bluesky_post, "_default_client_factory", lambda h, p: fake_client)

        artifact = PreprintArtifact(slug="x", title="T", abstract="A")
        assert bluesky_post.publish_artifact(artifact) == "ok"
        fake_client.send_post.assert_called_once()

    def test_publish_artifact_auth_error(self, monkeypatch):
        from agents.cross_surface import bluesky_post
        from shared.preprint_artifact import PreprintArtifact

        monkeypatch.setenv("HAPAX_BLUESKY_HANDLE", "h.bsky.social")
        monkeypatch.setenv("HAPAX_BLUESKY_APP_PASSWORD", "abcd-1234")

        def _raise(h, p):
            raise RuntimeError("login failed")

        monkeypatch.setattr(bluesky_post, "_default_client_factory", _raise)

        artifact = PreprintArtifact(slug="x", title="T", abstract="A")
        assert bluesky_post.publish_artifact(artifact) == "auth_error"

    def test_publish_artifact_send_error(self, monkeypatch):
        from agents.cross_surface import bluesky_post
        from shared.preprint_artifact import PreprintArtifact

        monkeypatch.setenv("HAPAX_BLUESKY_HANDLE", "h.bsky.social")
        monkeypatch.setenv("HAPAX_BLUESKY_APP_PASSWORD", "abcd-1234")

        fake_client = mock.Mock()
        fake_client.send_post.side_effect = RuntimeError("send failed")
        monkeypatch.setattr(bluesky_post, "_default_client_factory", lambda h, p: fake_client)

        artifact = PreprintArtifact(slug="x", title="T", abstract="A")
        assert bluesky_post.publish_artifact(artifact) == "error"

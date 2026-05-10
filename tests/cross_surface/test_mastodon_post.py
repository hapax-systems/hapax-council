"""Tests for ``agents.cross_surface.mastodon_post``."""

from __future__ import annotations

import json
from unittest import mock

from prometheus_client import CollectorRegistry

from agents.cross_surface.mastodon_post import (
    ALLOWED_PUBLIC_EVENT_TYPES,
    MASTODON_TEXT_LIMIT,
    MastodonPoster,
    _credentials_from_env,
)
from shared.research_vehicle_public_event import (
    PublicEventChapterRef,
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
)


def _public_event(**overrides) -> ResearchVehiclePublicEvent:
    payload = {
        "schema_version": 1,
        "event_id": "rvpe:broadcast_boundary:20260430:mastodon",
        "event_type": "broadcast.boundary",
        "occurred_at": "2026-04-30T12:00:00Z",
        "broadcast_id": "broadcast-123",
        "programme_id": None,
        "condition_id": None,
        "source": PublicEventSource(
            producer="tests",
            substrate_id="youtube_metadata",
            task_anchor="mastodon-public-event-adapter",
            evidence_ref="tests#event",
            freshness_ref="tests.age_s",
        ),
        "salience": 0.72,
        "state_kind": "live_state",
        "rights_class": "operator_original",
        "privacy_class": "public_safe",
        "provenance": PublicEventProvenance(
            token="public-event-token",
            generated_at="2026-04-30T12:00:01Z",
            producer="tests",
            evidence_refs=["tests.evidence"],
            rights_basis="operator generated test event",
            citation_refs=["tests.citation"],
        ),
        "public_url": "https://www.youtube.com/watch?v=broadcast-123",
        "frame_ref": None,
        "chapter_ref": PublicEventChapterRef(
            kind="chapter",
            label="Boundary",
            timecode="00:00",
            source_event_id="rvpe:broadcast_boundary:20260430:mastodon",
        ),
        "attribution_refs": ["tests.attribution"],
        "surface_policy": PublicEventSurfacePolicy(
            allowed_surfaces=["mastodon", "archive", "health"],
            denied_surfaces=["bluesky"],
            claim_live=True,
            claim_archive=True,
            claim_monetizable=False,
            requires_egress_public_claim=True,
            requires_audio_safe=True,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key="broadcast.boundary:live_state",
            redaction_policy="operator_referent",
            fallback_action="hold",
            dry_run_reason=None,
        ),
    }
    payload.update(overrides)
    return ResearchVehiclePublicEvent(**payload)


def _surface_policy(**overrides) -> PublicEventSurfacePolicy:
    payload = {
        "allowed_surfaces": ["mastodon", "archive", "health"],
        "denied_surfaces": ["bluesky"],
        "claim_live": True,
        "claim_archive": True,
        "claim_monetizable": False,
        "requires_egress_public_claim": True,
        "requires_audio_safe": True,
        "requires_provenance": True,
        "requires_human_review": False,
        "rate_limit_key": "broadcast.boundary:live_state",
        "redaction_policy": "operator_referent",
        "fallback_action": "hold",
        "dry_run_reason": None,
    }
    payload.update(overrides)
    return PublicEventSurfacePolicy(**payload)


def _write_events(path, events: list[ResearchVehiclePublicEvent | dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            if isinstance(event, ResearchVehiclePublicEvent):
                fh.write(event.to_json_line())
            else:
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
        idempotency_path=cursor_path.with_name("posted-event-ids.json"),
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
        _write_events(bus, [_public_event()])
        cursor = tmp_path / "cursor.txt"
        poster, _ = _make_poster(event_path=bus, cursor_path=cursor)
        poster.run_once()
        assert int(cursor.read_text()) == bus.stat().st_size

    def test_file_shrink_resets_cursor_and_processes_new_event(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        cursor = tmp_path / "cursor.txt"
        _write_events(bus, [_public_event(event_id="rvpe:broadcast_boundary:long-file")])
        poster, factory = _make_poster(event_path=bus, cursor_path=cursor)
        poster.run_once()

        client = factory.return_value
        client.status_post.reset_mock()
        _write_events(bus, [_public_event(event_id="rvpe:broadcast_boundary:short")])
        cursor.write_text(str(bus.stat().st_size + 100), encoding="utf-8")

        assert poster.run_once() == 1
        assert int(cursor.read_text(encoding="utf-8")) == bus.stat().st_size
        client.status_post.assert_called_once()

    def test_processed_event_id_prevents_repost_after_cursor_loss(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        cursor = tmp_path / "cursor.txt"
        event = _public_event(event_id="rvpe:broadcast_boundary:stable-id")
        _write_events(bus, [event])
        poster, factory = _make_poster(event_path=bus, cursor_path=cursor)
        assert poster.run_once() == 1

        cursor.write_text("0", encoding="utf-8")
        assert poster.run_once() == 0
        factory.return_value.status_post.assert_called_once()


# ── Event filtering ──────────────────────────────────────────────────


class TestEventFiltering:
    def test_allowed_public_event_types_match_contract(self):
        assert {
            "broadcast.boundary",
            "chronicle.high_salience",
            "omg.weblog",
            "shorts.upload",
        } == ALLOWED_PUBLIC_EVENT_TYPES

    def test_skips_unsupported_public_event_type(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    event_id="rvpe:aesthetic_frame:ignored",
                    event_type="aesthetic.frame_capture",
                    state_kind="aesthetic_frame",
                ),
                _public_event(event_id="rvpe:broadcast_boundary:posted"),
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

    def test_legacy_broadcast_rotated_record_is_not_consumed(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": "broadcast_rotated", "incoming_broadcast_id": "vid-A"}])
        cursor = tmp_path / "cursor.txt"
        client = mock.Mock()
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=cursor,
            client_factory=factory,
        )

        assert poster.run_once() == 0
        assert int(cursor.read_text(encoding="utf-8")) == bus.stat().st_size
        client.status_post.assert_not_called()

    def test_rejects_event_without_mastodon_surface_policy(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    surface_policy=_surface_policy(
                        allowed_surfaces=["archive"],
                        denied_surfaces=["mastodon"],
                    )
                )
            ],
        )
        client = mock.Mock()
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )
        assert poster.run_once() == 1
        client.status_post.assert_not_called()

    def test_chronicle_event_projects_grounding_for_allowlist(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    event_id="rvpe:chronicle_high_salience:mastodon",
                    event_type="chronicle.high_salience",
                    state_kind="research_observation",
                    chapter_ref=PublicEventChapterRef(
                        kind="chapter",
                        label="high-salience observation",
                        timecode="00:42",
                        source_event_id="rvpe:chronicle_high_salience:mastodon",
                    ),
                )
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

        assert poster.run_once() == 1
        client.status_post.assert_called_once()

    def test_shorts_upload_event_projects_grounding_for_allowlist(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    event_id="rvpe:shorts_upload:mastodon",
                    event_type="shorts.upload",
                    state_kind="short_form",
                    public_url="https://www.youtube.com/shorts/short-123",
                    chapter_ref=None,
                    surface_policy=_surface_policy(
                        rate_limit_key="shorts.upload:short_form",
                    ),
                )
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

        assert poster.run_once() == 1
        client.status_post.assert_called_once()

    def test_weblog_event_projects_grounding_for_allowlist(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    event_id="rvpe:omg_weblog:mastodon",
                    event_type="omg.weblog",
                    state_kind="public_post",
                    public_url="https://hapax.weblog.lol/visibility-engine",
                    chapter_ref=PublicEventChapterRef(
                        kind="chapter",
                        label="Visibility Engine Online",
                        timecode="00:00",
                        source_event_id="rvpe:omg_weblog:mastodon",
                    ),
                    surface_policy=_surface_policy(
                        claim_live=False,
                        claim_archive=True,
                        requires_egress_public_claim=False,
                        requires_audio_safe=False,
                        rate_limit_key="omg.weblog:public_post",
                    ),
                )
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

        assert poster.run_once() == 1
        client.status_post.assert_called_once()


# ── Dry-run ──────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_does_not_call_factory(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [_public_event()])
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
        _write_events(bus, [_public_event()])
        cursor = tmp_path / "cursor.txt"
        poster, _ = _make_poster(event_path=bus, cursor_path=cursor, dry_run=True)
        poster.run_once()
        assert int(cursor.read_text()) == bus.stat().st_size


# ── Allowlist ────────────────────────────────────────────────────────


class TestAllowlist:
    def test_deny_short_circuits(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [_public_event()])
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
        _write_events(bus, [_public_event()])
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
        _write_events(bus, [_public_event()])
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
        _write_events(bus, [_public_event()])
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
        _write_events(bus, [_public_event()])
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
        _write_events(bus, [_public_event()])
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
        _write_events(bus, [_public_event()])
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

    def test_existing_posts_total_metric_name_is_preserved(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [_public_event()])
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            dry_run=True,
        )
        poster.run_once()

        samples = [s for metric in poster.posts_total.collect() for s in metric.samples]
        assert any(
            s.name == "hapax_broadcast_mastodon_posts_total"
            and s.labels.get("result") == "dry_run"
            and s.value == 1.0
            for s in samples
        )

    def test_factory_receives_instance_and_token(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [_public_event()])
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
        from shared.attribution_block import NON_ENGAGEMENT_CLAUSE_SHORT
        from shared.preprint_artifact import PreprintArtifact

        artifact = PreprintArtifact(
            slug="x",
            title="Title",
            abstract="Abstract.",
            attribution_block="Hapax + Claude Code + Oudepode (unsettled).",
        )
        text = _compose_artifact_text(artifact)
        assert text.startswith("Hapax + Claude Code + Oudepode (unsettled).")
        assert NON_ENGAGEMENT_CLAUSE_SHORT in text

    def test_compose_skips_clause_for_self_referential_refusal_brief(self):
        from agents.cross_surface.mastodon_post import _compose_artifact_text
        from shared.attribution_block import NON_ENGAGEMENT_CLAUSE_SHORT
        from shared.preprint_artifact import PreprintArtifact

        artifact = PreprintArtifact(
            slug="refusal-brief",
            title="Refusal Brief",
            abstract="Self-referential.",
            attribution_block="Hapax + Claude Code.",
        )
        text = _compose_artifact_text(artifact)
        assert NON_ENGAGEMENT_CLAUSE_SHORT not in text

    def test_compose_falls_back_to_title_abstract(self):
        from agents.cross_surface.mastodon_post import _compose_artifact_text
        from shared.attribution_block import NON_ENGAGEMENT_CLAUSE_SHORT
        from shared.preprint_artifact import PreprintArtifact

        artifact = PreprintArtifact(slug="x", title="Title", abstract="Abstract.")
        text = _compose_artifact_text(artifact)
        assert text.startswith("Title — Abstract.")
        assert NON_ENGAGEMENT_CLAUSE_SHORT in text

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

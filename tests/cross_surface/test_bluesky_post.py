"""Tests for ``agents.cross_surface.bluesky_post``."""

from __future__ import annotations

import json
from unittest import mock

from prometheus_client import CollectorRegistry

from agents.cross_surface.bluesky_post import (
    ALLOWED_PUBLIC_EVENT_TYPES,
    BLUESKY_TEXT_LIMIT,
    BlueskyPoster,
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
        "event_id": "rvpe:broadcast_boundary:20260430:bsky",
        "event_type": "broadcast.boundary",
        "occurred_at": "2026-04-30T12:00:00Z",
        "broadcast_id": "broadcast-123",
        "programme_id": None,
        "condition_id": None,
        "source": PublicEventSource(
            producer="tests",
            substrate_id="youtube_metadata",
            task_anchor="bluesky-public-event-adapter",
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
            source_event_id="rvpe:broadcast_boundary:20260430:bsky",
        ),
        "attribution_refs": ["tests.attribution"],
        "surface_policy": PublicEventSurfacePolicy(
            allowed_surfaces=["bluesky", "archive", "health"],
            denied_surfaces=["mastodon"],
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
        "allowed_surfaces": ["bluesky", "archive", "health"],
        "denied_surfaces": ["mastodon"],
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
        idempotency_path=cursor_path.with_name("posted-event-ids.json"),
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
        client.send_post.reset_mock()
        _write_events(bus, [_public_event(event_id="rvpe:broadcast_boundary:short")])
        cursor.write_text(str(bus.stat().st_size + 100), encoding="utf-8")

        assert poster.run_once() == 1
        assert int(cursor.read_text(encoding="utf-8")) == bus.stat().st_size
        client.send_post.assert_called_once()

    def test_processed_event_id_prevents_repost_after_cursor_loss(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        cursor = tmp_path / "cursor.txt"
        event = _public_event(event_id="rvpe:broadcast_boundary:stable-id")
        _write_events(bus, [event])
        poster, factory = _make_poster(event_path=bus, cursor_path=cursor)
        assert poster.run_once() == 1

        cursor.write_text("0", encoding="utf-8")
        assert poster.run_once() == 0
        factory.return_value.send_post.assert_called_once()

    def test_persists_post_uri_receipt_for_public_proof(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        cursor = tmp_path / "cursor.txt"
        event = _public_event(event_id="rvpe:broadcast_boundary:proof")
        _write_events(bus, [event])

        client = mock.Mock()
        client.send_post.return_value = mock.Mock(
            uri="at://did:plc:example/app.bsky.feed.post/3proof"
        )
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=cursor,
            client_factory=mock.Mock(return_value=client),
            compose_fn=mock.Mock(return_value="proof post"),
            handle="hapax.bsky.social",
        )

        assert poster.run_once() == 1
        state = json.loads(cursor.with_name("posted-event-ids.json").read_text())
        assert state["schema_version"] == 2
        assert "rvpe:broadcast_boundary:proof" in state["event_ids"]
        assert state["posts"] == [
            {
                "event_id": "rvpe:broadcast_boundary:proof",
                "event_public_url": "https://www.youtube.com/watch?v=broadcast-123",
                "public_url": "https://bsky.app/profile/hapax.bsky.social/post/3proof",
                "recorded_at": state["posts"][0]["recorded_at"],
                "result": "ok",
                "text": "proof post",
                "uri": "at://did:plc:example/app.bsky.feed.post/3proof",
            }
        ]


# ── Event filtering ──────────────────────────────────────────────────


class TestEventFiltering:
    def test_allowed_public_event_types_match_contract(self):
        assert {
            "broadcast.boundary",
            "chronicle.high_salience",
            "governance.enforcement",
            "omg.weblog",
            "shorts.upload",
            "velocity.digest",
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
        client.send_post.return_value = mock.Mock(uri="at://post/1")
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )
        poster.run_once()
        assert client.send_post.call_count == 1

    def test_rejects_event_without_bluesky_surface_policy(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    surface_policy=_surface_policy(
                        allowed_surfaces=["archive"],
                        denied_surfaces=["bluesky"],
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
        client.send_post.assert_not_called()

    def test_chronicle_event_projects_grounding_for_allowlist(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    event_id="rvpe:chronicle_high_salience:bsky",
                    event_type="chronicle.high_salience",
                    state_kind="research_observation",
                    chapter_ref=PublicEventChapterRef(
                        kind="chapter",
                        label="high-salience observation",
                        timecode="00:42",
                        source_event_id="rvpe:chronicle_high_salience:bsky",
                    ),
                )
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

        assert poster.run_once() == 1
        client.send_post.assert_called_once()

    def test_shorts_upload_event_projects_grounding_for_allowlist(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    event_id="rvpe:shorts_upload:bsky",
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
        client.send_post.return_value = mock.Mock(uri="at://post/1")
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )

        assert poster.run_once() == 1
        client.send_post.assert_called_once()

    def test_weblog_event_projects_grounding_for_allowlist(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    event_id="rvpe:omg_weblog:bsky",
                    event_type="omg.weblog",
                    state_kind="public_post",
                    public_url="https://hapax.weblog.lol/visibility-engine",
                    chapter_ref=PublicEventChapterRef(
                        kind="chapter",
                        label="Visibility Engine Online",
                        timecode="00:00",
                        source_event_id="rvpe:omg_weblog:bsky",
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
        client.send_post.return_value = mock.Mock(uri="at://post/1")
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )

        assert poster.run_once() == 1
        client.send_post.assert_called_once()

    def test_default_compose_weblog_uses_public_url_directly(self):
        from agents.cross_surface import bluesky_post as mod

        event = _public_event(
            event_id="rvpe:omg_weblog:bsky",
            event_type="omg.weblog",
            state_kind="public_post",
            public_url="https://hapax.weblog.lol/2026/05/show-hn-governance-that-ships",
            chapter_ref=PublicEventChapterRef(
                kind="chapter",
                label="Show HN: Mechanical Governance for AI Coding Agents at 3,000+ PRs",
                timecode="00:00",
                source_event_id="rvpe:omg_weblog:bsky",
            ),
            surface_policy=_surface_policy(
                claim_live=False,
                claim_archive=True,
                requires_egress_public_claim=False,
                requires_audio_safe=False,
                rate_limit_key="omg.weblog:public_post",
            ),
        )

        with mock.patch("agents.metadata_composer.composer.compose_metadata") as compose:
            text = mod._default_compose(event)

        compose.assert_not_called()
        assert "Show HN: Mechanical Governance" in text
        assert "https://hapax.weblog.lol/2026/05/show-hn-governance-that-ships" in text
        assert "metadata-public-claim-gate" not in text

    def test_non_broadcast_events_post_without_live_egress_claim(self, tmp_path):
        for event_type, state_kind in (
            ("velocity.digest", "research_observation"),
            ("governance.enforcement", "governance_state"),
        ):
            bus = tmp_path / f"{event_type.replace('.', '_')}.jsonl"
            _write_events(
                bus,
                [
                    _public_event(
                        event_id=f"rvpe:{event_type.replace('.', '_')}:bsky",
                        event_type=event_type,
                        state_kind=state_kind,
                        broadcast_id=None,
                        public_url=None,
                        chapter_ref=None,
                        surface_policy=_surface_policy(
                            claim_live=False,
                            claim_archive=True,
                            requires_egress_public_claim=True,
                            requires_audio_safe=True,
                            rate_limit_key=f"{event_type}:{state_kind}",
                        ),
                    )
                ],
            )
            client = mock.Mock()
            client.send_post.return_value = mock.Mock(uri="at://post/1")
            factory = mock.Mock(return_value=client)
            poster, _ = _make_poster(
                event_path=bus,
                cursor_path=tmp_path / f"{event_type.replace('.', '_')}.cursor",
                client_factory=factory,
            )

            assert poster.run_once() == 1
            client.send_post.assert_called_once()


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
        _write_events(bus, [_public_event()])
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
        _write_events(bus, [_public_event()])
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
        _write_events(bus, [_public_event()])
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
        _write_events(bus, [_public_event()])
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
        _write_events(bus, [_public_event()])
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
        _write_events(bus, [_public_event()])
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
        from shared.attribution_block import NON_ENGAGEMENT_CLAUSE_SHORT
        from shared.preprint_artifact import PreprintArtifact

        # Non-self-referential artifact gets the Refusal Brief clause appended
        # when it fits inside BLUESKY_TEXT_LIMIT.
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
        from agents.cross_surface.bluesky_post import _compose_artifact_text
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
        from agents.cross_surface.bluesky_post import _compose_artifact_text
        from shared.attribution_block import NON_ENGAGEMENT_CLAUSE_SHORT
        from shared.preprint_artifact import PreprintArtifact

        artifact = PreprintArtifact(slug="x", title="Title", abstract="Abstract.")
        text = _compose_artifact_text(artifact)
        assert text.startswith("Title — Abstract.")
        assert NON_ENGAGEMENT_CLAUSE_SHORT in text

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

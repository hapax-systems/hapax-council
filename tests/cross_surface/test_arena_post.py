"""Tests for ``agents.cross_surface.arena_post``."""

from __future__ import annotations

import json
from unittest import mock

from prometheus_client import CollectorRegistry

from agents.cross_surface.arena_post import (
    ALLOWED_PUBLIC_EVENT_TYPES,
    ARENA_BLOCK_TEXT_LIMIT,
    ArenaPoster,
    _credentials_from_env,
)
from shared.research_vehicle_public_event import (
    PublicEventChapterRef,
    PublicEventFrameRef,
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
)


def _public_event(**overrides) -> ResearchVehiclePublicEvent:
    payload = {
        "schema_version": 1,
        "event_id": "rvpe:arena_block_candidate:20260430:arena",
        "event_type": "arena_block.candidate",
        "occurred_at": "2026-04-30T12:00:00Z",
        "broadcast_id": "broadcast-123",
        "programme_id": None,
        "condition_id": None,
        "source": PublicEventSource(
            producer="tests",
            substrate_id="aesthetic_library",
            task_anchor="arena-public-event-unit-and-block-shape",
            evidence_ref="tests#event",
            freshness_ref="tests.age_s",
        ),
        "salience": 0.72,
        "state_kind": "public_post",
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
        "public_url": "https://hapax.weblog.lol/2026/04/30/livestream-frame",
        "frame_ref": None,
        "chapter_ref": PublicEventChapterRef(
            kind="chapter",
            label="Reverie pass 7 — RD step 0.18",
            timecode="00:00",
            source_event_id="rvpe:arena_block_candidate:20260430:arena",
        ),
        "attribution_refs": ["tests.attribution"],
        "surface_policy": PublicEventSurfacePolicy(
            allowed_surfaces=["arena", "archive", "health"],
            denied_surfaces=[],
            claim_live=True,
            claim_archive=True,
            claim_monetizable=False,
            requires_egress_public_claim=True,
            requires_audio_safe=True,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key="arena_block.candidate:public_post",
            redaction_policy="operator_referent",
            fallback_action="hold",
            dry_run_reason=None,
        ),
    }
    payload.update(overrides)
    return ResearchVehiclePublicEvent(**payload)


def _surface_policy(**overrides) -> PublicEventSurfacePolicy:
    payload = {
        "allowed_surfaces": ["arena", "archive", "health"],
        "denied_surfaces": [],
        "claim_live": True,
        "claim_archive": True,
        "claim_monetizable": False,
        "requires_egress_public_claim": True,
        "requires_audio_safe": True,
        "requires_provenance": True,
        "requires_human_review": False,
        "rate_limit_key": "arena_block.candidate:public_post",
        "redaction_policy": "operator_referent",
        "fallback_action": "hold",
        "dry_run_reason": None,
    }
    payload.update(overrides)
    return PublicEventSurfacePolicy(**payload)


def _frame_ref(**overrides) -> PublicEventFrameRef:
    payload = {
        "kind": "frame",
        "uri": "https://hapax.cdn/frames/livestream-2026-04-30.jpg",
        "captured_at": "2026-04-30T12:00:00Z",
        "source_event_id": "rvpe:aesthetic_frame_capture:20260430",
    }
    payload.update(overrides)
    return PublicEventFrameRef(**payload)


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
        _write_events(bus, [_public_event(event_id="rvpe:arena:long-file")])
        poster, factory = _make_poster(event_path=bus, cursor_path=cursor)
        poster.run_once()

        client = factory.return_value
        client.add_block.reset_mock()
        _write_events(bus, [_public_event(event_id="rvpe:arena:short")])
        cursor.write_text(str(bus.stat().st_size + 100), encoding="utf-8")

        assert poster.run_once() == 1
        assert int(cursor.read_text(encoding="utf-8")) == bus.stat().st_size
        client.add_block.assert_called_once()

    def test_processed_event_id_prevents_repost_after_cursor_loss(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        cursor = tmp_path / "cursor.txt"
        event = _public_event(event_id="rvpe:arena:stable-id")
        _write_events(bus, [event])
        poster, factory = _make_poster(event_path=bus, cursor_path=cursor)
        assert poster.run_once() == 1

        cursor.write_text("0", encoding="utf-8")
        assert poster.run_once() == 0
        factory.return_value.add_block.assert_called_once()


# ── Event filtering ──────────────────────────────────────────────────


class TestEventFiltering:
    def test_allowed_public_event_types_match_contract(self):
        assert {
            "arena_block.candidate",
            "aesthetic.frame_capture",
            "chronicle.high_salience",
            "omg.weblog",
            "publication.artifact",
        } == ALLOWED_PUBLIC_EVENT_TYPES

    def test_skips_unsupported_public_event_type(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    event_id="rvpe:shorts_upload:ignored",
                    event_type="shorts.upload",
                    state_kind="short_form",
                ),
                _public_event(event_id="rvpe:arena_block_candidate:posted"),
            ],
        )
        client = mock.Mock()
        client.add_block.return_value = None
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )
        poster.run_once()
        assert client.add_block.call_count == 1

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
        client.add_block.assert_not_called()

    def test_rejects_event_without_arena_surface_policy(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    surface_policy=_surface_policy(
                        allowed_surfaces=["archive"],
                        denied_surfaces=["arena"],
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
        client.add_block.assert_not_called()

    def test_aesthetic_frame_capture_event_passes_grounding(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    event_id="rvpe:aesthetic_frame_capture:arena",
                    event_type="aesthetic.frame_capture",
                    state_kind="aesthetic_frame",
                    frame_ref=_frame_ref(),
                    public_url=None,
                )
            ],
        )
        client = mock.Mock()
        client.add_block.return_value = None
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )

        assert poster.run_once() == 1
        client.add_block.assert_called_once()

    def test_chronicle_high_salience_event_passes_grounding(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    event_id="rvpe:chronicle_high_salience:arena",
                    event_type="chronicle.high_salience",
                    state_kind="research_observation",
                    chapter_ref=PublicEventChapterRef(
                        kind="chapter",
                        label="high-salience observation",
                        timecode="00:42",
                        source_event_id="rvpe:chronicle_high_salience:arena",
                    ),
                )
            ],
        )
        client = mock.Mock()
        client.add_block.return_value = None
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )

        assert poster.run_once() == 1
        client.add_block.assert_called_once()

    def test_publication_artifact_event_passes_grounding(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    event_id="rvpe:publication_artifact:arena",
                    event_type="publication.artifact",
                    state_kind="archive_artifact",
                    public_url="https://doi.org/10.5281/zenodo.example",
                    chapter_ref=None,
                    surface_policy=_surface_policy(
                        rate_limit_key="publication.artifact:archive_artifact",
                    ),
                )
            ],
        )
        client = mock.Mock()
        client.add_block.return_value = None
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )

        assert poster.run_once() == 1
        client.add_block.assert_called_once()

    def test_weblog_event_passes_grounding(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    event_id="rvpe:omg_weblog:arena",
                    event_type="omg.weblog",
                    state_kind="public_post",
                    public_url="https://hapax.weblog.lol/visibility-engine",
                    chapter_ref=PublicEventChapterRef(
                        kind="chapter",
                        label="Visibility Engine Online",
                        timecode="00:00",
                        source_event_id="rvpe:omg_weblog:arena",
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
        client.add_block.return_value = None
        factory = mock.Mock(return_value=client)
        poster, _ = _make_poster(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client_factory=factory,
        )

        assert poster.run_once() == 1
        client.add_block.assert_called_once()


# ── Block source URL by event type ───────────────────────────────────


class TestBlockSourceUrl:
    def test_aesthetic_frame_capture_prefers_frame_ref_uri(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    event_id="rvpe:aesthetic_frame_capture:source",
                    event_type="aesthetic.frame_capture",
                    state_kind="aesthetic_frame",
                    public_url="https://hapax.weblog.lol/post",
                    frame_ref=_frame_ref(uri="https://hapax.cdn/frame.jpg"),
                )
            ],
        )
        client = mock.Mock()
        client.add_block.return_value = None
        factory = mock.Mock(return_value=client)
        # Use default composer (no compose_fn) so source URL selection runs.
        poster = ArenaPoster(
            token="test-token",
            channel_slug="hapax-visual-surface",
            client_factory=factory,
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            idempotency_path=tmp_path / "ids.json",
            registry=CollectorRegistry(),
        )
        with mock.patch("agents.metadata_composer.composer.compose_metadata") as compose:
            compose.return_value = mock.Mock(arena_block="frame body", bluesky_post=None)
            poster.run_once()
        assert client.add_block.call_args.kwargs["source"] == "https://hapax.cdn/frame.jpg"

    def test_chronicle_uses_public_url(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                _public_event(
                    event_id="rvpe:chronicle_high_salience:source",
                    event_type="chronicle.high_salience",
                    state_kind="research_observation",
                    public_url="https://hapax.weblog.lol/observation",
                    frame_ref=_frame_ref(),
                )
            ],
        )
        client = mock.Mock()
        client.add_block.return_value = None
        factory = mock.Mock(return_value=client)
        poster = ArenaPoster(
            token="test-token",
            channel_slug="hapax-visual-surface",
            client_factory=factory,
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            idempotency_path=tmp_path / "ids.json",
            registry=CollectorRegistry(),
        )
        with mock.patch("agents.metadata_composer.composer.compose_metadata") as compose:
            compose.return_value = mock.Mock(arena_block="chronicle body", bluesky_post=None)
            poster.run_once()
        assert client.add_block.call_args.kwargs["source"] == "https://hapax.weblog.lol/observation"


# ── Dry run ──────────────────────────────────────────────────────────


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


# ── Live send ────────────────────────────────────────────────────────


class TestSendBlock:
    def test_text_only_block_uses_content(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        # Event has public_url (fanout requires one reference), but the
        # composer chooses to emit the block as text-only by returning source=None.
        _write_events(bus, [_public_event()])
        client = mock.Mock()
        client.add_block.return_value = None
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
        _write_events(bus, [_public_event()])
        client = mock.Mock()
        client.add_block.return_value = None
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
        _write_events(bus, [_public_event()])
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
        _write_events(bus, [_public_event()])
        client = mock.Mock()
        client.add_block.return_value = None
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

        from agents.cross_surface import arena_post as mod

        denied = mock.Mock()
        denied.decision = "deny"
        denied.reason = "test override"
        with mock.patch.object(mod, "allowlist_check", return_value=denied):
            poster.run_once()
        client.add_block.assert_not_called()


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
        from shared.attribution_block import NON_ENGAGEMENT_CLAUSE_LONG

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
        # Attribution body present + Refusal Brief LONG clause appended.
        assert kwargs["content"].startswith("Attribution Block")
        assert NON_ENGAGEMENT_CLAUSE_LONG in kwargs["content"]
        assert kwargs["source"] is None

    def test_title_abstract_fallback(self, monkeypatch):
        from agents.cross_surface import arena_post
        from shared.attribution_block import NON_ENGAGEMENT_CLAUSE_LONG

        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "ch")
        client = mock.Mock()
        client.add_block.return_value = None
        with mock.patch.object(arena_post, "_default_client_factory", return_value=client):
            artifact = _FakeArtifact(title="Title", abstract="Abstract.")
            assert arena_post.publish_artifact(artifact) == "ok"
        content = client.add_block.call_args.kwargs["content"]
        assert content.startswith("Title — Abstract.")
        assert NON_ENGAGEMENT_CLAUSE_LONG in content

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
        # Bare placeholder + appended Refusal Brief LONG clause.
        content = client.add_block.call_args.kwargs["content"]
        assert content.startswith("hapax — publication artifact")

    def test_refusal_brief_self_referential_skips_clause(self, monkeypatch):
        from agents.cross_surface import arena_post
        from shared.attribution_block import (
            NON_ENGAGEMENT_CLAUSE_LONG,
            NON_ENGAGEMENT_CLAUSE_SHORT,
        )

        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "ch")
        client = mock.Mock()
        client.add_block.return_value = None
        with mock.patch.object(arena_post, "_default_client_factory", return_value=client):
            artifact = _FakeArtifact(
                slug="refusal-brief",
                title="Refusal Brief",
                attribution_block="Hapax + Claude Code.",
            )
            assert arena_post.publish_artifact(artifact) == "ok"
        content = client.add_block.call_args.kwargs["content"]
        assert NON_ENGAGEMENT_CLAUSE_LONG not in content
        assert NON_ENGAGEMENT_CLAUSE_SHORT not in content

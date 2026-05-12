"""End-to-end integration test for the Phase 1 publish bus.

Validates that an approved ``PreprintArtifact`` dropped at
``$HAPAX_STATE/publish/inbox/{slug}.json`` fans out via the orchestrator's
SURFACE_REGISTRY, hits each per-surface ``publish_artifact()``
entry-point, and lands per-surface results at
``$HAPAX_STATE/publish/log/{slug}.{surface}.json``.

Distinct from ``tests/publish_orchestrator/test_orchestrator.py`` which
unit-tests the orchestrator with mock surface registries. This test
exercises the **real** SURFACE_REGISTRY (post-#1416 wiring) against
mocked transport layers — verifying the import paths, entry-point
signatures, and result-string vocabulary all line up.

If a publisher's ``publish_artifact`` is renamed, removed, or its
return-string vocabulary drifts, this test fails loudly.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from unittest import mock

from prometheus_client import CollectorRegistry

from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY, Orchestrator
from shared.preprint_artifact import PreprintArtifact
from shared.publication_hardening.review import ReviewReport


def _drop_approved_artifact(
    state_root,
    *,
    slug: str,
    surfaces: list[str],
) -> None:
    artifact = PreprintArtifact(
        slug=slug,
        title=f"E2E test artifact {slug}",
        abstract="Validates publish-bus end-to-end fan-out.",
        body_md="Body content; not consumed by Phase 1 text-only surfaces.",
        attribution_block=(
            "Hapax + Claude Code (substrate). Oudepode (operator, "
            "unsettled contribution as feature)."
        ),
        surfaces_targeted=surfaces,
    )
    artifact.mark_approved(by_referent="Oudepode")
    inbox_path = artifact.inbox_path(state_root=state_root)
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    inbox_path.write_text(artifact.model_dump_json(indent=2))


def _read_log(state_root, slug: str, surface: str) -> dict:
    log_path = state_root / "publish" / "log" / f"{slug}.{surface}.json"
    assert log_path.exists(), f"missing log at {log_path}"
    return json.loads(log_path.read_text())


class _ApprovingReviewPass:
    def review_text(
        self,
        text: str,
        *,
        author_model: str | None = None,
        lint_report: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ReviewReport:
        del text, lint_report, metadata
        return ReviewReport(
            reviewer_model="test-reviewer",
            author_model=author_model,
            overall_confidence=0.99,
        )


# ── Phase 1 publishers: real SURFACE_REGISTRY, mocked transports ────


class TestPhase1PublishBusEndToEnd:
    """Validates inbox → fanout → log lifecycle for all 4 cross-surface
    publishers + osf-preprint, against the live SURFACE_REGISTRY."""

    def test_all_phase_1_surfaces_registered(self):
        """Pin: SURFACE_REGISTRY has every Phase 1+2 entry.

        ``discord-webhook`` was retired 2026-05-01 per cc-task
        ``discord-public-event-activation-or-retire`` (constitutional refusal,
        ``leverage-REFUSED-discord-community``). It is now REFUSED tier in the
        canonical registry and intentionally absent from the orchestrator
        dispatch registry.
        """
        for surface in (
            "bluesky-post",
            "mastodon-post",
            "arena-post",
            "osf-preprint",
        ):
            assert surface in SURFACE_REGISTRY, f"{surface} missing from SURFACE_REGISTRY"
        assert "discord-webhook" not in SURFACE_REGISTRY, (
            "discord-webhook is REFUSED; runtime dispatch must not reach it"
        )

    def test_e2e_no_credentials_path(self, tmp_path, monkeypatch):
        """Without env credentials, every Phase 1 surface returns
        ``no_credentials``. Artifact moves to ``failed/`` because
        ``no_credentials`` is terminal but not a publication.
        """
        for env_var in (
            "HAPAX_BLUESKY_HANDLE",
            "HAPAX_BLUESKY_APP_PASSWORD",
            "HAPAX_MASTODON_INSTANCE_URL",
            "HAPAX_MASTODON_ACCESS_TOKEN",
            "HAPAX_ARENA_TOKEN",
            "HAPAX_ARENA_CHANNEL_SLUG",
        ):
            monkeypatch.delenv(env_var, raising=False)

        _drop_approved_artifact(
            tmp_path,
            slug="e2e-no-creds",
            surfaces=[
                "bluesky-post",
                "mastodon-post",
                "arena-post",
            ],
        )
        orch = Orchestrator(
            state_root=tmp_path,
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=_ApprovingReviewPass(),
            registry=CollectorRegistry(),
        )

        handled = orch.run_once()
        assert handled == 1

        # All 3 active surfaces report no_credentials (terminal failure).
        # discord-webhook was retired 2026-05-01 (REFUSED tier).
        for surface in ("bluesky-post", "mastodon-post", "arena-post"):
            record = _read_log(tmp_path, "e2e-no-creds", surface)
            assert record["result"] == "no_credentials", f"surface={surface} got {record['result']}"

        assert not (tmp_path / "publish" / "published" / "e2e-no-creds.json").exists()
        assert (tmp_path / "publish" / "failed" / "e2e-no-creds.json").exists()
        assert not (tmp_path / "publish" / "inbox" / "e2e-no-creds.json").exists()

    def test_e2e_bsky_ok_with_mocked_transport(self, tmp_path, monkeypatch):
        """With creds + mocked atproto, bsky returns ``ok`` and
        artifact moves to published/."""
        monkeypatch.setenv("HAPAX_BLUESKY_HANDLE", "test.bsky.social")
        monkeypatch.setenv("HAPAX_BLUESKY_APP_PASSWORD", "abcd-efgh-ijkl-mnop")

        _drop_approved_artifact(tmp_path, slug="e2e-bsky-ok", surfaces=["bluesky-post"])

        orch = Orchestrator(
            state_root=tmp_path,
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=_ApprovingReviewPass(),
            registry=CollectorRegistry(),
        )

        from agents.cross_surface import bluesky_post

        client_mock = mock.Mock()
        client_mock.send_post = mock.Mock(return_value=None)
        with mock.patch.object(bluesky_post, "_default_client_factory", return_value=client_mock):
            handled = orch.run_once()

        assert handled == 1
        assert _read_log(tmp_path, "e2e-bsky-ok", "bluesky-post")["result"] == "ok"
        assert (tmp_path / "publish" / "published" / "e2e-bsky-ok.json").exists()

        # The publisher was called with the artifact's attribution_block as the
        # body, since attribution_block takes precedence over title/abstract.
        called_text = client_mock.send_post.call_args.kwargs["text"]
        assert "Hapax + Claude Code" in called_text
        assert "unsettled contribution as feature" in called_text

    def test_e2e_discord_typed_artifact_lands_surface_unwired(self, tmp_path, monkeypatch):
        """discord-webhook was retired 2026-05-01 (cc-task
        ``discord-public-event-activation-or-retire``). An artifact targeting
        ``discord-webhook`` now falls through to ``surface_unwired`` because
        REFUSED-tier surfaces are intentionally absent from the orchestrator
        dispatch registry. This is the correct fail-mode for a refused surface
        — no spurious ``no_credentials`` outcome that would imply Discord is
        merely waiting for a webhook URL.
        """
        monkeypatch.delenv("HAPAX_DISCORD_WEBHOOK_URL", raising=False)

        _drop_approved_artifact(tmp_path, slug="e2e-discord-refused", surfaces=["discord-webhook"])

        orch = Orchestrator(
            state_root=tmp_path,
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=_ApprovingReviewPass(),
            registry=CollectorRegistry(),
        )

        handled = orch.run_once()
        assert handled == 1
        record = _read_log(tmp_path, "e2e-discord-refused", "discord-webhook")
        assert record["result"] == "surface_unwired", (
            f"REFUSED surface dispatch must yield surface_unwired, got {record['result']}"
        )

    def test_e2e_arena_ok_with_mocked_transport(self, tmp_path, monkeypatch):
        """With token + slug set + mocked Arena adapter, arena returns ``ok``."""
        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "test-token")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "hapax-test-channel")

        _drop_approved_artifact(tmp_path, slug="e2e-arena-ok", surfaces=["arena-post"])

        orch = Orchestrator(
            state_root=tmp_path,
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=_ApprovingReviewPass(),
            registry=CollectorRegistry(),
        )

        from agents.cross_surface import arena_post

        adapter_mock = mock.Mock()
        adapter_mock.add_block = mock.Mock(return_value=None)
        with mock.patch.object(arena_post, "_default_client_factory", return_value=adapter_mock):
            handled = orch.run_once()

        assert handled == 1
        assert _read_log(tmp_path, "e2e-arena-ok", "arena-post")["result"] == "ok"

        # Arena receives the channel slug as positional + content as kwarg.
        adapter_mock.add_block.assert_called_once()
        args, kwargs = adapter_mock.add_block.call_args
        assert args == ("hapax-test-channel",)
        assert "Hapax + Claude Code" in kwargs["content"]

    def test_e2e_multi_surface_partial_credentials(self, tmp_path, monkeypatch):
        """One surface has creds (bsky), three don't. Each reports
        independently; artifact moves to failed/ because only all-ok
        artifacts count as published."""
        monkeypatch.setenv("HAPAX_BLUESKY_HANDLE", "test.bsky.social")
        monkeypatch.setenv("HAPAX_BLUESKY_APP_PASSWORD", "abcd-efgh-ijkl-mnop")
        for env_var in (
            "HAPAX_MASTODON_INSTANCE_URL",
            "HAPAX_MASTODON_ACCESS_TOKEN",
            "HAPAX_ARENA_TOKEN",
            "HAPAX_ARENA_CHANNEL_SLUG",
        ):
            monkeypatch.delenv(env_var, raising=False)

        _drop_approved_artifact(
            tmp_path,
            slug="e2e-partial",
            surfaces=[
                "bluesky-post",
                "mastodon-post",
                "arena-post",
            ],
        )

        orch = Orchestrator(
            state_root=tmp_path,
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=_ApprovingReviewPass(),
            registry=CollectorRegistry(),
        )

        from agents.cross_surface import bluesky_post

        client_mock = mock.Mock()
        client_mock.send_post = mock.Mock(return_value=None)
        with mock.patch.object(bluesky_post, "_default_client_factory", return_value=client_mock):
            handled = orch.run_once()

        assert handled == 1
        assert _read_log(tmp_path, "e2e-partial", "bluesky-post")["result"] == "ok"
        assert _read_log(tmp_path, "e2e-partial", "mastodon-post")["result"] == "no_credentials"
        assert _read_log(tmp_path, "e2e-partial", "arena-post")["result"] == "no_credentials"
        assert not (tmp_path / "publish" / "published" / "e2e-partial.json").exists()
        assert (tmp_path / "publish" / "failed" / "e2e-partial.json").exists()

    def test_e2e_unwired_surface_logs_surface_unwired(self, tmp_path):
        """A typo in surfaces_targeted (not in SURFACE_REGISTRY) lands as
        ``surface_unwired`` in the log, doesn't crash the run."""
        _drop_approved_artifact(
            tmp_path,
            slug="e2e-typo",
            surfaces=["bluesky-pst"],  # typo: should be bluesky-post
        )

        orch = Orchestrator(
            state_root=tmp_path,
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=_ApprovingReviewPass(),
            registry=CollectorRegistry(),
        )
        handled = orch.run_once()

        assert handled == 1
        record = _read_log(tmp_path, "e2e-typo", "bluesky-pst")
        assert record["result"] == "surface_unwired"
        assert not (tmp_path / "publish" / "published" / "e2e-typo.json").exists()
        assert (tmp_path / "publish" / "failed" / "e2e-typo.json").exists()

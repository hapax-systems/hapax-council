"""Tests for ``agents.publish_orchestrator.orchestrator.Orchestrator``."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from unittest import mock

from prometheus_client import CollectorRegistry

from agents.publish_orchestrator.orchestrator import Orchestrator
from shared.preprint_artifact import PreprintArtifact
from shared.publication_hardening.review import ReviewReport


def _drop_artifact(
    state_root: Path,
    *,
    slug: str,
    surfaces: list[str],
    body_md: str = "Body.",
    source_path: Path | None = None,
    author_model: str | None = None,
) -> Path:
    """Write an approved PreprintArtifact JSON to inbox/."""
    artifact = PreprintArtifact(
        slug=slug,
        title=f"Test artifact {slug}",
        abstract="Brief.",
        body_md=body_md,
        surfaces_targeted=surfaces,
        source_path=str(source_path) if source_path is not None else None,
        author_model=author_model,
    )
    artifact.mark_approved(by_referent="Oudepode")
    inbox_path = artifact.inbox_path(state_root=state_root)
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    inbox_path.write_text(artifact.model_dump_json(indent=2))
    return inbox_path


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


class _HoldingReviewPass:
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
            overall_confidence=0.2,
            flagged_issues=("tone too promotional",),
        )


def _make_orchestrator(state_root: Path, *, surface_registry: dict[str, str]) -> Orchestrator:
    return Orchestrator(
        state_root=state_root,
        surface_registry=surface_registry,
        public_event_path=state_root / "public-events.jsonl",
        review_pass=_ApprovingReviewPass(),
        registry=CollectorRegistry(),
    )


# ── Empty inbox ─────────────────────────────────────────────────────


class TestEmptyInbox:
    def test_missing_inbox_dir(self, tmp_path):
        orch = _make_orchestrator(tmp_path, surface_registry={})
        assert orch.run_once() == 0

    def test_empty_inbox(self, tmp_path):
        (tmp_path / "publish/inbox").mkdir(parents=True)
        orch = _make_orchestrator(tmp_path, surface_registry={})
        assert orch.run_once() == 0


# ── Single artifact, single surface ─────────────────────────────────


class TestSingleSurface:
    def test_unwired_surface(self, tmp_path):
        _drop_artifact(tmp_path, slug="x", surfaces=["unknown-surface"])
        orch = _make_orchestrator(tmp_path, surface_registry={})
        orch.run_once()

        log_path = tmp_path / "publish/log/x.unknown-surface.json"
        assert log_path.exists()
        record = json.loads(log_path.read_text())
        assert record["result"] == "surface_unwired"
        assert not (tmp_path / "publish/published/x.json").exists()
        assert (tmp_path / "publish/failed/x.json").exists()

    def test_ok_dispatch(self, tmp_path, monkeypatch):
        # Create a fake module with a publish_artifact entry-point
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="x", surfaces=["fake"])
        orch = _make_orchestrator(
            tmp_path, surface_registry={"fake": "fake_publisher:publish_artifact"}
        )
        orch.run_once()

        # Result logged
        log_path = tmp_path / "publish/log/x.fake.json"
        assert log_path.exists()
        assert json.loads(log_path.read_text())["result"] == "ok"

        # Artifact moved to published/
        assert not (tmp_path / "publish/inbox/x.json").exists()
        assert (tmp_path / "publish/published/x.json").exists()

        events = [
            json.loads(line) for line in (tmp_path / "public-events.jsonl").read_text().splitlines()
        ]
        assert [event["event_type"] for event in events] == [
            "publication.artifact",
            "publication.artifact",
            "publication.artifact",
        ]
        assert {event["source"]["substrate_id"] for event in events} == {"publication_artifact"}
        surface_event = next(event for event in events if event["event_id"].endswith(":fake:ok"))
        assert surface_event["surface_policy"]["dry_run_reason"] == ("surface_policy_denied:fake")
        assert "Body." not in json.dumps(surface_event)

    def test_cross_provider_review_hold_suppresses_surface_dispatch(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        source = tmp_path / "draft.md"
        source.write_text("---\ntitle: Held\n---\n\nBody\n", encoding="utf-8")
        _drop_artifact(
            tmp_path,
            slug="held-for-review",
            surfaces=["fake"],
            source_path=source,
            author_model="codex",
        )
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=_HoldingReviewPass(),
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        fake_module.publish_artifact.assert_not_called()

        assert not (tmp_path / "publish/inbox/held-for-review.json").exists()
        assert not (tmp_path / "publish/published/held-for-review.json").exists()
        assert not (tmp_path / "publish/failed/held-for-review.json").exists()

        draft = json.loads((tmp_path / "publish/draft/held-for-review.json").read_text())
        assert draft["approval"] == "withheld"
        assert draft["publication_review"]["overall_confidence"] == 0.2
        assert draft["publication_review"]["author_model"] == "codex"

        frontmatter = source.read_text(encoding="utf-8").split("---", 2)[1]
        assert "publication_review:" in frontmatter
        assert "overall_confidence: 0.2" in frontmatter

        review_log = json.loads(
            (tmp_path / "publish/log/held-for-review.cross-provider-review.json").read_text()
        )
        assert review_log["result"] == "operator_hold"
        assert review_log["flagged_issues"] == ["tone too promotional"]

    def test_publisher_raises_logs_error(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(side_effect=RuntimeError("send failure"))
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="y", surfaces=["fake"])
        orch = _make_orchestrator(
            tmp_path, surface_registry={"fake": "fake_publisher:publish_artifact"}
        )
        orch.run_once()

        log_path = tmp_path / "publish/log/y.fake.json"
        assert json.loads(log_path.read_text())["result"] == "error"
        assert not (tmp_path / "publish/published/y.json").exists()
        assert (tmp_path / "publish/failed/y.json").exists()

    def test_no_credentials_moves_to_failed_not_published(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="no_credentials")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="creds", surfaces=["fake"])
        orch = _make_orchestrator(
            tmp_path, surface_registry={"fake": "fake_publisher:publish_artifact"}
        )
        orch.run_once()

        assert json.loads((tmp_path / "publish/log/creds.fake.json").read_text())["result"] == (
            "no_credentials"
        )
        assert not (tmp_path / "publish/published/creds.json").exists()
        assert not (tmp_path / "publish/inbox/creds.json").exists()
        assert (tmp_path / "publish/failed/creds.json").exists()

    def test_deferred_re_runs(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        # First call returns deferred; second call returns ok
        fake_module.publish_artifact = mock.Mock(side_effect=["deferred", "ok"])
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="z", surfaces=["fake"])
        orch = _make_orchestrator(
            tmp_path, surface_registry={"fake": "fake_publisher:publish_artifact"}
        )

        # Tick 1: deferred — artifact stays in inbox
        orch.run_once()
        assert (tmp_path / "publish/inbox/z.json").exists()
        assert not (tmp_path / "publish/published/z.json").exists()

        # Tick 2: ok — artifact moves to published
        orch.run_once()
        assert not (tmp_path / "publish/inbox/z.json").exists()
        assert (tmp_path / "publish/published/z.json").exists()

        events = [
            json.loads(line) for line in (tmp_path / "public-events.jsonl").read_text().splitlines()
        ]
        event_ids = [event["event_id"] for event in events]
        assert any(event_id.endswith(":fake:deferred") for event_id in event_ids)
        assert any(event_id.endswith(":fake:ok") for event_id in event_ids)
        assert len(event_ids) == len(set(event_ids))

    def test_changed_artifact_republishes_same_slug(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        orch = _make_orchestrator(
            tmp_path, surface_registry={"fake": "fake_publisher:publish_artifact"}
        )

        _drop_artifact(tmp_path, slug="repeat", surfaces=["fake"], body_md="first")
        orch.run_once()
        first_log = json.loads((tmp_path / "publish/log/repeat.fake.json").read_text())

        _drop_artifact(tmp_path, slug="repeat", surfaces=["fake"], body_md="second")
        orch.run_once()
        second_log = json.loads((tmp_path / "publish/log/repeat.fake.json").read_text())
        published = json.loads((tmp_path / "publish/published/repeat.json").read_text())

        assert fake_module.publish_artifact.call_count == 2
        assert first_log["artifact_fingerprint"] != second_log["artifact_fingerprint"]
        assert published["body_md"] == "second"


# ── Multi-surface fan-out ───────────────────────────────────────────


class TestMultiSurface:
    def test_all_surfaces_terminal_publishes(self, tmp_path, monkeypatch):
        bsky = mock.Mock()
        bsky.publish_artifact = mock.Mock(return_value="ok")
        masto = mock.Mock()
        masto.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_bsky", bsky)
        monkeypatch.setitem(__import__("sys").modules, "fake_masto", masto)

        _drop_artifact(tmp_path, slug="multi", surfaces=["bsky", "masto"])
        orch = _make_orchestrator(
            tmp_path,
            surface_registry={
                "bsky": "fake_bsky:publish_artifact",
                "masto": "fake_masto:publish_artifact",
            },
        )
        orch.run_once()

        assert (tmp_path / "publish/published/multi.json").exists()
        assert json.loads((tmp_path / "publish/log/multi.bsky.json").read_text())["result"] == "ok"
        assert json.loads((tmp_path / "publish/log/multi.masto.json").read_text())["result"] == "ok"

    def test_one_deferred_holds_artifact(self, tmp_path, monkeypatch):
        bsky = mock.Mock()
        bsky.publish_artifact = mock.Mock(return_value="ok")
        masto = mock.Mock()
        masto.publish_artifact = mock.Mock(return_value="deferred")
        monkeypatch.setitem(__import__("sys").modules, "fake_bsky", bsky)
        monkeypatch.setitem(__import__("sys").modules, "fake_masto", masto)

        _drop_artifact(tmp_path, slug="held", surfaces=["bsky", "masto"])
        orch = _make_orchestrator(
            tmp_path,
            surface_registry={
                "bsky": "fake_bsky:publish_artifact",
                "masto": "fake_masto:publish_artifact",
            },
        )
        orch.run_once()

        # bsky is terminal, masto is deferred — artifact stays in inbox
        assert (tmp_path / "publish/inbox/held.json").exists()
        assert not (tmp_path / "publish/published/held.json").exists()
        assert not (tmp_path / "publish/failed/held.json").exists()

    def test_partial_success_moves_to_failed_not_published(self, tmp_path, monkeypatch):
        bsky = mock.Mock()
        bsky.publish_artifact = mock.Mock(return_value="ok")
        masto = mock.Mock()
        masto.publish_artifact = mock.Mock(return_value="auth_error")
        monkeypatch.setitem(__import__("sys").modules, "fake_bsky", bsky)
        monkeypatch.setitem(__import__("sys").modules, "fake_masto", masto)

        _drop_artifact(tmp_path, slug="partial", surfaces=["bsky", "masto"])
        orch = _make_orchestrator(
            tmp_path,
            surface_registry={
                "bsky": "fake_bsky:publish_artifact",
                "masto": "fake_masto:publish_artifact",
            },
        )
        orch.run_once()

        assert json.loads((tmp_path / "publish/log/partial.bsky.json").read_text())["result"] == (
            "ok"
        )
        assert (
            json.loads((tmp_path / "publish/log/partial.masto.json").read_text())["result"]
            == "auth_error"
        )
        assert not (tmp_path / "publish/published/partial.json").exists()
        assert (tmp_path / "publish/failed/partial.json").exists()


# ── Counter labels ──────────────────────────────────────────────────


class TestCounter:
    def test_counter_labels_per_surface(self, tmp_path, monkeypatch):
        fake = mock.Mock()
        fake.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_pub", fake)

        _drop_artifact(tmp_path, slug="count", surfaces=["fake"])
        orch = _make_orchestrator(tmp_path, surface_registry={"fake": "fake_pub:publish_artifact"})
        orch.run_once()

        sample = orch.dispatches_total.labels(surface="fake", result="ok")._value.get()
        assert sample == 1.0

    def test_counter_unwired_surface(self, tmp_path):
        _drop_artifact(tmp_path, slug="u", surfaces=["nope"])
        orch = _make_orchestrator(tmp_path, surface_registry={})
        orch.run_once()

        sample = orch.dispatches_total.labels(surface="nope", result="surface_unwired")._value.get()
        assert sample == 1.0


# ── SURFACE_REGISTRY entries (regression pin) ───────────────────────


class TestSurfaceRegistry:
    """Pin module-level SURFACE_REGISTRY wiring per ticket.

    Each entry must point at a real ``module:attr`` path. We pin the
    string here rather than importing so a renamed symbol fails the
    test loudly. Live import-resolution is exercised by
    ``Orchestrator._import_publisher`` indirectly across the rest of
    the suite.
    """

    def test_bluesky_post_wired(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "bluesky-post" in SURFACE_REGISTRY
        assert SURFACE_REGISTRY["bluesky-post"] == (
            "agents.cross_surface.bluesky_post:publish_artifact"
        )

    def test_mastodon_post_wired(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "mastodon-post" in SURFACE_REGISTRY
        assert SURFACE_REGISTRY["mastodon-post"] == (
            "agents.cross_surface.mastodon_post:publish_artifact"
        )

    def test_bluesky_entry_resolves(self):
        """Importing the registered entry-point must not raise."""
        import importlib

        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        module_path, attr = SURFACE_REGISTRY["bluesky-post"].split(":")
        mod = importlib.import_module(module_path)
        fn = getattr(mod, attr)
        assert callable(fn)

    def test_mastodon_entry_resolves(self):
        import importlib

        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        module_path, attr = SURFACE_REGISTRY["mastodon-post"].split(":")
        mod = importlib.import_module(module_path)
        fn = getattr(mod, attr)
        assert callable(fn)

    def test_arena_post_wired(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "arena-post" in SURFACE_REGISTRY
        assert SURFACE_REGISTRY["arena-post"] == (
            "agents.cross_surface.arena_post:publish_artifact"
        )

    def test_arena_entry_resolves(self):
        import importlib

        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        module_path, attr = SURFACE_REGISTRY["arena-post"].split(":")
        mod = importlib.import_module(module_path)
        fn = getattr(mod, attr)
        assert callable(fn)

    def test_discord_webhook_refused_not_in_dispatch(self):
        """discord-webhook was retired 2026-05-01 per cc-task
        ``discord-public-event-activation-or-retire``. Constitutional refusal
        per ``leverage-REFUSED-discord-community`` (single-operator axiom +
        full-automation envelope). The surface still exists in the canonical
        registry as REFUSED tier so refusal_brief / dashboard can enumerate it,
        but the runtime dispatch registry (FULL_AUTO + CONDITIONAL_ENGAGE only)
        must not include it.
        """
        from agents.publication_bus.surface_registry import (
            SURFACE_REGISTRY as CANONICAL,
        )
        from agents.publication_bus.surface_registry import (
            AutomationStatus,
        )
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert CANONICAL["discord-webhook"].automation_status == AutomationStatus.REFUSED, (
            "discord-webhook must be REFUSED tier in canonical surface_registry"
        )
        assert "discord-webhook" not in SURFACE_REGISTRY, (
            "discord-webhook must not appear in the orchestrator dispatch "
            "registry (REFUSED surfaces are quarantined from runtime fanout)"
        )

    def test_zenodo_doi_wired(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "zenodo-doi" in SURFACE_REGISTRY
        assert SURFACE_REGISTRY["zenodo-doi"] == ("agents.zenodo_publisher:publish_artifact")

    def test_zenodo_entry_resolves(self):
        import importlib

        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        module_path, attr = SURFACE_REGISTRY["zenodo-doi"].split(":")
        mod = importlib.import_module(module_path)
        fn = getattr(mod, attr)
        assert callable(fn)

    def test_omg_weblog_wired(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "omg-weblog" in SURFACE_REGISTRY
        assert SURFACE_REGISTRY["omg-weblog"] == ("agents.omg_weblog_publisher:publish_artifact")

    def test_omg_weblog_entry_resolves(self):
        import importlib

        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        module_path, attr = SURFACE_REGISTRY["omg-weblog"].split(":")
        mod = importlib.import_module(module_path)
        fn = getattr(mod, attr)
        assert callable(fn)

    def test_alphaxiv_comments_not_runtime_wired(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "alphaxiv-comments" not in SURFACE_REGISTRY

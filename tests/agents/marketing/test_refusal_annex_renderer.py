"""Tests for ``agents.marketing.refusal_annex_renderer``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agents.marketing.refusal_annex_renderer import (
    REFUSAL_ANNEX_SLUGS,
    RefusalAnnexEntry,
    discover_annex_entries,
    render_annex,
    render_index,
)


def _write_log(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


class TestRenderAnnex:
    def test_emits_title_and_slug(self) -> None:
        text = render_annex(
            slug="declined-bandcamp",
            title="Refusal: Bandcamp",
            events=[],
        )
        assert "declined-bandcamp" in text
        assert "Refusal: Bandcamp" in text
        # Markdown heading
        assert text.startswith("# ")

    def test_includes_each_event_timestamp_and_reason(self) -> None:
        events = [
            RefusalAnnexEntry(
                timestamp=datetime(2026, 4, 25, 12, tzinfo=UTC),
                axiom="full_auto_or_nothing",
                surface="publication-bus:bandcamp-upload",
                reason="surface declined per Refusal Brief",
            ),
            RefusalAnnexEntry(
                timestamp=datetime(2026, 4, 26, 13, tzinfo=UTC),
                axiom="full_auto_or_nothing",
                surface="publication-bus:bandcamp-upload",
                reason="manual upload required — not automatable",
            ),
        ]
        text = render_annex(slug="declined-bandcamp", title="x", events=events)
        assert "2026-04-25" in text
        assert "2026-04-26" in text
        assert "surface declined per Refusal Brief" in text
        assert "manual upload required" in text

    def test_empty_events_renders_no_log_section(self) -> None:
        text = render_annex(slug="declined-x", title="x", events=[])
        # Body still emits frontmatter + heading + clause; no events section
        assert "## Log" not in text or text.split("## Log")[1].strip() == ""

    def test_includes_non_engagement_clause(self) -> None:
        text = render_annex(slug="declined-x", title="x", events=[])
        assert (
            "non-engagement" in text.lower()
            or "no operator outreach" in text.lower()
            or "infrastructure-as-argument" in text.lower()
        )


class TestRenderIndex:
    def test_lists_each_annex_slug(self) -> None:
        text = render_index(["declined-alphaxiv", "declined-bandcamp"])
        assert "declined-alphaxiv" in text
        assert "declined-bandcamp" in text

    def test_includes_series_heading(self) -> None:
        text = render_index([])
        assert text.startswith("# ")
        assert "refusal" in text.lower() or "annex" in text.lower()


class TestDiscoverAnnexEntries:
    def test_groups_log_entries_by_surface(self, tmp_path: Path) -> None:
        log_path = tmp_path / "log.jsonl"
        _write_log(
            log_path,
            [
                {
                    "timestamp": "2026-04-25T10:00:00+00:00",
                    "axiom": "single_user",
                    "surface": "publication-bus:bandcamp-upload",
                    "reason": "manual upload only",
                    "public": False,
                    "refusal_brief_link": None,
                },
                {
                    "timestamp": "2026-04-25T11:00:00+00:00",
                    "axiom": "single_user",
                    "surface": "publication-bus:bandcamp-upload",
                    "reason": "manual upload only",
                    "public": False,
                    "refusal_brief_link": None,
                },
                {
                    "timestamp": "2026-04-25T12:00:00+00:00",
                    "axiom": "interpersonal_transparency",
                    "surface": "leverage:discord-community",
                    "reason": "no community presence",
                    "public": False,
                    "refusal_brief_link": None,
                },
            ],
        )
        entries = discover_annex_entries(log_path=log_path)
        # Two distinct surfaces → two annex slug groups
        slugs = {entry["slug"] for entry in entries}
        assert any("bandcamp" in s for s in slugs)
        assert any("discord" in s for s in slugs)

    def test_missing_log_returns_empty(self, tmp_path: Path) -> None:
        result = discover_annex_entries(log_path=tmp_path / "missing.jsonl")
        assert result == []

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        log_path = tmp_path / "log.jsonl"
        log_path.write_text(
            "not-json\n"
            + json.dumps(
                {
                    "timestamp": "2026-04-25T10:00:00+00:00",
                    "axiom": "single_user",
                    "surface": "publication-bus:bandcamp-upload",
                    "reason": "x",
                    "public": False,
                    "refusal_brief_link": None,
                }
            )
            + "\n"
        )
        entries = discover_annex_entries(log_path=log_path)
        assert len(entries) >= 1


class TestSeedSlugs:
    def test_includes_eight_seed_annexes(self) -> None:
        # cc-task lists 8 initial annexes — verify seeds match
        assert len(REFUSAL_ANNEX_SLUGS) >= 8
        assert "declined-bandcamp" in REFUSAL_ANNEX_SLUGS
        assert "declined-alphaxiv" in REFUSAL_ANNEX_SLUGS


class TestPublishAllAnnexesDispatchesThroughPublisher:
    def test_routes_through_v5_publisher_chain(self, tmp_path: Path) -> None:
        """Phase 2b: publish_all_annexes must go through RefusalAnnexPublisher
        so the V5 pub-bus counter (and allowlist, legal-name guard) applies."""
        from agents.marketing.refusal_annex_renderer import publish_all_annexes
        from agents.publication_bus.publisher_kit.base import Publisher

        log_path = tmp_path / "log.jsonl"
        _write_log(
            log_path,
            [
                {
                    "timestamp": "2026-04-25T10:00:00+00:00",
                    "axiom": "single_user",
                    "surface": "publication-bus:bandcamp-upload",
                    "reason": "manual upload only",
                    "public": False,
                    "refusal_brief_link": None,
                },
            ],
        )

        # Capture pub-bus counter state before publish
        counter = Publisher._get_counter()
        if counter is not None:
            before = counter.labels(surface="marketing-refusal-annex", result="ok")._value.get()
        else:
            before = 0

        output_dir = tmp_path / "publications"
        written = publish_all_annexes(log_path=log_path, output_dir=output_dir)

        # File written
        assert "declined-bandcamp" in written
        assert (output_dir / "refusal-annex-declined-bandcamp.md").exists()

        # V5 pub-bus counter incremented
        if counter is not None:
            after = counter.labels(surface="marketing-refusal-annex", result="ok")._value.get()
            assert after == before + 1


class TestEnqueueAnnexForFanout:
    """Phase 3: orchestrator fanout — enqueue PreprintArtifact for cross-surface dispatch.

    The orchestrator globs ``~/hapax-state/publish/inbox/`` for approved artifacts and
    dispatches each via ``SURFACE_REGISTRY``. A successful annex publish must drop a
    matching ``PreprintArtifact.json`` so committed Zenodo (DOI mint) and omg.lol weblog
    surfaces receive the annex without operator action. Bridgy remains dry-run/blocked
    until source URL sequencing is committed.
    """

    def test_writes_approved_preprint_artifact_to_inbox(self, tmp_path: Path) -> None:
        from agents.marketing.refusal_annex_renderer import enqueue_annex_for_fanout
        from shared.preprint_artifact import ApprovalState, PreprintArtifact

        path = enqueue_annex_for_fanout(
            slug="declined-bandcamp",
            title="Refusal: Bandcamp",
            body="# Refusal Annex\n\nBody content.",
            state_root=tmp_path,
        )
        assert path.exists()
        assert path.parent == tmp_path / "publish" / "inbox"
        # Artifact is approved (orchestrator only globs approved-state inbox)
        artifact = PreprintArtifact.model_validate_json(path.read_text())
        assert artifact.approval == ApprovalState.APPROVED
        assert artifact.approved_at is not None
        assert artifact.approved_by_referent == "Oudepode"

    def test_default_surfaces_target_only_committed_zenodo_omg(self, tmp_path: Path) -> None:
        from agents.marketing.refusal_annex_renderer import (
            BRIDGY_FANOUT_SURFACE,
            DEFAULT_FANOUT_SURFACES,
            enqueue_annex_for_fanout,
        )
        from shared.preprint_artifact import PreprintArtifact

        path = enqueue_annex_for_fanout(
            slug="declined-bandcamp", title="x", body="x", state_root=tmp_path
        )
        artifact = PreprintArtifact.model_validate_json(path.read_text())
        assert "zenodo-refusal-deposit" in artifact.surfaces_targeted
        assert "omg-weblog" in artifact.surfaces_targeted
        assert BRIDGY_FANOUT_SURFACE not in artifact.surfaces_targeted
        assert set(artifact.surfaces_targeted) == set(DEFAULT_FANOUT_SURFACES)

    def test_bridgy_fanout_target_is_rejected_until_committed(self, tmp_path: Path) -> None:
        from agents.marketing.refusal_annex_renderer import (
            BRIDGY_FANOUT_BLOCKER,
            BRIDGY_FANOUT_SURFACE,
            enqueue_annex_for_fanout,
        )

        try:
            enqueue_annex_for_fanout(
                slug="declined-bandcamp",
                title="x",
                body="x",
                surfaces=["omg-weblog", BRIDGY_FANOUT_SURFACE],
                state_root=tmp_path,
            )
        except ValueError as exc:
            assert BRIDGY_FANOUT_BLOCKER in str(exc)
        else:  # pragma: no cover - defensive assertion
            raise AssertionError("Bridgy refusal-annex fanout must fail closed")

    def test_explicit_surfaces_override_default(self, tmp_path: Path) -> None:
        from agents.marketing.refusal_annex_renderer import enqueue_annex_for_fanout
        from shared.preprint_artifact import PreprintArtifact

        path = enqueue_annex_for_fanout(
            slug="declined-x",
            title="x",
            body="x",
            surfaces=["zenodo-refusal-deposit"],
            state_root=tmp_path,
        )
        artifact = PreprintArtifact.model_validate_json(path.read_text())
        assert artifact.surfaces_targeted == ["zenodo-refusal-deposit"]

    def test_artifact_slug_prefixed_to_avoid_collision(self, tmp_path: Path) -> None:
        from agents.marketing.refusal_annex_renderer import enqueue_annex_for_fanout
        from shared.preprint_artifact import PreprintArtifact

        path = enqueue_annex_for_fanout(
            slug="declined-bandcamp", title="x", body="x", state_root=tmp_path
        )
        # Inbox filename includes refusal-annex- prefix so a future preprint
        # named "declined-bandcamp" can't overwrite the annex artifact.
        assert path.name == "refusal-annex-declined-bandcamp.json"
        artifact = PreprintArtifact.model_validate_json(path.read_text())
        assert artifact.slug == "refusal-annex-declined-bandcamp"

    def test_body_becomes_body_md_and_truncated_abstract(self, tmp_path: Path) -> None:
        from agents.marketing.refusal_annex_renderer import enqueue_annex_for_fanout
        from shared.preprint_artifact import PreprintArtifact

        body = "# Big Annex\n\n" + ("x" * 8192)  # > 4096 abstract limit
        path = enqueue_annex_for_fanout(
            slug="declined-x", title="x", body=body, state_root=tmp_path
        )
        artifact = PreprintArtifact.model_validate_json(path.read_text())
        # Full body preserved in body_md
        assert artifact.body_md == body
        # Abstract truncated to model's max_length (4096)
        assert len(artifact.abstract) <= 4096


class TestPublishAllAnnexesEnqueueFanout:
    """``publish_all_annexes(enqueue_for_fanout=True)`` enqueues each annex
    for orchestrator dispatch in addition to writing local files."""

    def test_enqueue_for_fanout_drops_inbox_artifact_per_published_annex(
        self, tmp_path: Path
    ) -> None:
        from agents.marketing.refusal_annex_renderer import publish_all_annexes

        log_path = tmp_path / "log.jsonl"
        _write_log(
            log_path,
            [
                {
                    "timestamp": "2026-04-25T10:00:00+00:00",
                    "axiom": "single_user",
                    "surface": "publication-bus:bandcamp-upload",
                    "reason": "manual upload only",
                    "public": False,
                    "refusal_brief_link": None,
                },
            ],
        )
        output_dir = tmp_path / "publications"
        state_root = tmp_path / "state"

        publish_all_annexes(
            log_path=log_path,
            output_dir=output_dir,
            enqueue_for_fanout=True,
            fanout_state_root=state_root,
        )

        inbox = state_root / "publish" / "inbox"
        assert inbox.exists()
        # Exactly one artifact per published annex
        artifact_files = sorted(inbox.glob("*.json"))
        assert len(artifact_files) == 1
        assert artifact_files[0].name == "refusal-annex-declined-bandcamp.json"

    def test_default_does_not_enqueue_for_fanout(self, tmp_path: Path) -> None:
        """Backward-compat: existing callers without enqueue_for_fanout=True
        get no inbox artifact (Phase 1+2 behavior preserved)."""
        from agents.marketing.refusal_annex_renderer import publish_all_annexes

        log_path = tmp_path / "log.jsonl"
        _write_log(
            log_path,
            [
                {
                    "timestamp": "2026-04-25T10:00:00+00:00",
                    "axiom": "single_user",
                    "surface": "publication-bus:bandcamp-upload",
                    "reason": "manual upload only",
                    "public": False,
                    "refusal_brief_link": None,
                },
            ],
        )
        output_dir = tmp_path / "publications"
        state_root = tmp_path / "state"

        publish_all_annexes(
            log_path=log_path,
            output_dir=output_dir,
            fanout_state_root=state_root,
        )
        inbox = state_root / "publish" / "inbox"
        assert not inbox.exists() or list(inbox.glob("*.json")) == []

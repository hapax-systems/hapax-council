"""Tests for ``agents.publication_bus.publisher_kit.refused``."""

from __future__ import annotations

from agents.publication_bus.publisher_kit import (
    REFUSED_PUBLISHER_CLASSES,
    PublisherPayload,
    RefusedPublisher,
)
from agents.publication_bus.publisher_kit.refused import (
    AlphaXivCommentsRefusedPublisher,
    BandcampRefusedPublisher,
    CrossrefEventDataRefusedPublisher,
    DiscogsRefusedPublisher,
    RymRefusedPublisher,
)
from agents.publication_bus.surface_registry import SURFACE_REGISTRY, AutomationStatus


class TestRefusedPublisherBase:
    def test_subclass_gets_empty_allowlist_automatically(self) -> None:
        """RefusedPublisher.__init_subclass__ wires the empty
        AllowlistGate; subclasses don't need to declare it."""
        pub = BandcampRefusedPublisher()
        assert pub.allowlist.surface_name == "bandcamp-upload"
        assert pub.allowlist.permitted == frozenset()

    def test_publish_always_returns_refused(self) -> None:
        """Empty allowlist refuses every target before _emit runs."""
        pub = BandcampRefusedPublisher()
        result = pub.publish(PublisherPayload(target="any-target", text="any-text"))
        assert result.refused
        assert not result.ok

    def test_refusal_reason_in_class(self) -> None:
        """Each refused-publisher class declares its rationale."""
        assert BandcampRefusedPublisher.refusal_reason
        assert "no documented public upload API" in BandcampRefusedPublisher.refusal_reason


class TestRegisteredRefusedClasses:
    def test_refused_classes_registered(self) -> None:
        """The keystone task acceptance criterion #6 enumerated 4 REFUSED-class
        publishers (bandcamp / discogs / rym / crossref-event-data); cc-task
        `cold-contact-alphaxiv-comments` adds the 5th (alphaxiv-comments);
        cc-task `discord-public-event-activation-or-retire` (2026-05-01
        retirement) adds the 6th (discord-webhook); the Wise design spike's
        `direct-debit-active-reception-refusal-brief` follow-up adds the
        7th (wise-direct-debit-active-reception); cc-task
        `leverage-REFUSED-twitter-linkedin-substack-accounts` (PR #1560,
        first-class-graph promotion 2026-05-03) adds the 8th-10th
        (twitter-x-account / linkedin-account / substack-account); cc-task
        `reddit-refusal-brief` (2026-05-03) adds the 11th (reddit-account);
        cc-tasks `leverage-REFUSED-github-discussions-enabled` (PR #1567)
        and `leverage-REFUSED-wikipedia-auto-edit` (PR #1570),
        first-class-graph promotion 2026-05-03, add the 12th-13th
        (github-discussions / wikipedia-auto-edit).
        """
        assert len(REFUSED_PUBLISHER_CLASSES) == 13

    def test_all_refused_classes_subclass_refused_publisher(self) -> None:
        for cls in REFUSED_PUBLISHER_CLASSES:
            assert issubclass(cls, RefusedPublisher)

    def test_all_refused_classes_exported_from_publisher_kit(self) -> None:
        """The package-level API should expose every registered refused publisher.

        Review #2396's junior packet failed because the actual PR diff was
        invisible to that lane; senior verification showed the social-media
        refused publishers had landed in ``refused.py`` but the package-level
        import surface had not been kept in sync.
        """
        import agents.publication_bus.publisher_kit as publisher_kit

        for cls in REFUSED_PUBLISHER_CLASSES:
            assert getattr(publisher_kit, cls.__name__) is cls
            assert cls.__name__ in publisher_kit.__all__

    def test_all_refused_surfaces_in_registry(self) -> None:
        """Every registered RefusedPublisher's surface_name appears in
        SURFACE_REGISTRY with automation_status REFUSED."""
        for cls in REFUSED_PUBLISHER_CLASSES:
            assert cls.surface_name in SURFACE_REGISTRY, (
                f"{cls.__name__} surface_name {cls.surface_name!r} not in registry"
            )
            spec = SURFACE_REGISTRY[cls.surface_name]
            assert spec.automation_status == AutomationStatus.REFUSED, (
                f"{cls.surface_name!r} should be REFUSED in registry"
            )

    def test_each_class_carries_refusal_reason(self) -> None:
        for cls in REFUSED_PUBLISHER_CLASSES:
            assert cls.refusal_reason
            assert len(cls.refusal_reason) > 50  # non-trivial rationale


class TestSpecificRefusedClasses:
    def test_bandcamp_surface_name(self) -> None:
        assert BandcampRefusedPublisher.surface_name == "bandcamp-upload"

    def test_discogs_surface_name(self) -> None:
        assert DiscogsRefusedPublisher.surface_name == "discogs-submission"

    def test_rym_surface_name(self) -> None:
        assert RymRefusedPublisher.surface_name == "rym-submission"

    def test_crossref_surface_name(self) -> None:
        assert CrossrefEventDataRefusedPublisher.surface_name == "crossref-event-data"

    def test_alphaxiv_surface_name(self) -> None:
        assert AlphaXivCommentsRefusedPublisher.surface_name == "alphaxiv-comments"

    def test_alphaxiv_refusal_reason_cites_tos(self) -> None:
        # Per cc-task: alphaXiv community guidelines prohibit LLM-generated comments
        reason = AlphaXivCommentsRefusedPublisher.refusal_reason
        assert reason
        assert "LLM" in reason or "guidelines" in reason or "community" in reason

    def test_each_publishes_returns_refused(self) -> None:
        """Smoke: each registered class returns refused on publish()."""
        for cls in REFUSED_PUBLISHER_CLASSES:
            pub = cls()
            result = pub.publish(PublisherPayload(target="t", text="x"))
            assert result.refused, f"{cls.__name__}.publish() should always refuse"

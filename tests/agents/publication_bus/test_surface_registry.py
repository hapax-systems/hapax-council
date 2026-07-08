"""Tests for ``agents.publication_bus.surface_registry``."""

from __future__ import annotations

from agents.publication_bus.surface_registry import (
    SURFACE_REGISTRY,
    AutomationStatus,
    SurfaceSpec,
    auto_surfaces,
    dispatch_registry,
    is_engageable,
    refused_surfaces,
)
from shared.ndcvb_api_harness import NDCVB_PRODUCT_SURFACE_ID


class TestSurfaceRegistry:
    def test_registry_has_zenodo_entries(self) -> None:
        """V5 weave §2.1 wk1 d4 — Zenodo deposit + RelatedIdentifier
        graph are FULL_AUTO surfaces."""
        assert "zenodo-deposit" in SURFACE_REGISTRY
        assert "zenodo-related-identifier-graph" in SURFACE_REGISTRY
        assert SURFACE_REGISTRY["zenodo-deposit"].automation_status == AutomationStatus.FULL_AUTO

    def test_registry_has_refused_entries_with_links(self) -> None:
        """REFUSED surfaces must carry a Refusal Brief refusal_link."""
        for name, spec in SURFACE_REGISTRY.items():
            if spec.automation_status == AutomationStatus.REFUSED:
                assert spec.refusal_link is not None, (
                    f"REFUSED surface {name!r} missing refusal_link"
                )

    def test_registry_has_conditional_engage_entries(self) -> None:
        """V5 weave Phase 3 Playwright surfaces are CONDITIONAL_ENGAGE."""
        assert "philarchive-deposit" in SURFACE_REGISTRY
        spec = SURFACE_REGISTRY["philarchive-deposit"]
        assert spec.automation_status == AutomationStatus.CONDITIONAL_ENGAGE

    def test_orcid_carries_scope_note(self) -> None:
        """ORCID auto-update is concept-DOI-granularity only; the scope
        note documents this constraint at the registry layer."""
        spec = SURFACE_REGISTRY["orcid-auto-update"]
        assert spec.scope_note is not None
        assert "concept-DOI" in spec.scope_note

    def test_omg_lol_pay_is_not_registered(self) -> None:
        """omg.lol has no Pay product, so the publication bus must not
        expose an omg.lol Pay surface or publisher activation path."""
        assert "omg-lol-pay-receiver" not in SURFACE_REGISTRY

    def test_ndcvb_phase0_api_harness_is_not_a_publication_surface(self) -> None:
        """Phase-0 NDCVB packaging is schema-only, not an engageable public offer."""
        assert NDCVB_PRODUCT_SURFACE_ID not in SURFACE_REGISTRY
        assert not is_engageable(NDCVB_PRODUCT_SURFACE_ID)
        assert NDCVB_PRODUCT_SURFACE_ID not in dispatch_registry()

    def test_public_fanout_scope_notes_pin_publication_bus_claim_ceiling(self) -> None:
        expected_phrases = {
            "bluesky-post": ("publication bus", "reviewed artifacts"),
            "arena-post": ("publication bus", "reviewed artifacts"),
            "mastodon-post": ("publication bus", "reviewed artifacts"),
            "omg-weblog": ("claim ceilings", "config/omg-lol.yaml"),
            "omg-lol-weblog-bearer-fanout": ("no direct public egress authority",),
            "omg-lol-statuslog": ("publication bus", "reviewed artifacts"),
            "omg-lol-web": ("publication bus", "claim ceilings"),
            "omg-lol-now": ("publication bus", "claim ceilings"),
            "omg-lol-pastebin": ("publication bus", "reviewed artifacts"),
            "omg-lol-purl": ("publication bus", "reviewed artifacts"),
        }

        for surface, phrases in expected_phrases.items():
            note = (SURFACE_REGISTRY[surface].scope_note or "").lower()
            for phrase in phrases:
                assert phrase in note, f"{surface} scope_note missing {phrase!r}"


class TestAutomationStatusEnum:
    def test_three_tiers(self) -> None:
        names = {s.name for s in AutomationStatus}
        assert names == {"FULL_AUTO", "CONDITIONAL_ENGAGE", "REFUSED"}


class TestSurfaceSpecDataclass:
    def test_minimal_construction(self) -> None:
        spec = SurfaceSpec(automation_status=AutomationStatus.FULL_AUTO)
        assert spec.automation_status == AutomationStatus.FULL_AUTO
        assert spec.api is None
        assert spec.dispatch_entry is None
        assert spec.activation_path is None
        assert spec.refusal_link is None
        assert spec.scope_note is None
        assert spec.readback_adapter is None
        assert spec.freshness_slo_s is None
        assert spec.durable_target_required is False
        assert spec.content_hash_strategy is None
        assert spec.surface_owner == "publication_bus"
        assert spec.correction_policy is None
        assert spec.blocks_release_when_stale is False

    def test_full_construction(self) -> None:
        spec = SurfaceSpec(
            automation_status=AutomationStatus.REFUSED,
            api="REST",
            activation_path="some-daemon",
            refusal_link="docs/refusal-briefs/x.md",
            scope_note="some scope",
            readback_adapter="agents.publication_readback.example:readback",
            freshness_slo_s=900,
            durable_target_required=True,
            content_hash_strategy="canonical_html_sha256",
            surface_owner="publication_bus",
            correction_policy="hold_then_mint_correction_task",
            blocks_release_when_stale=True,
        )
        assert spec.api == "REST"
        assert spec.activation_path == "some-daemon"
        assert spec.refusal_link == "docs/refusal-briefs/x.md"
        assert spec.readback_adapter == "agents.publication_readback.example:readback"
        assert spec.freshness_slo_s == 900
        assert spec.durable_target_required is True
        assert spec.content_hash_strategy == "canonical_html_sha256"
        assert spec.correction_policy == "hold_then_mint_correction_task"
        assert spec.blocks_release_when_stale is True


class TestDispatchRegistry:
    def test_dispatch_registry_comes_from_surface_registry(self) -> None:
        dispatch = dispatch_registry()
        assert dispatch["bluesky-post"] == "agents.cross_surface.bluesky_post:publish_artifact"
        assert dispatch["zenodo-doi"] == "agents.zenodo_publisher:publish_artifact"

    def test_refused_surfaces_are_not_dispatchable(self) -> None:
        assert "alphaxiv-comments" not in dispatch_registry()


class TestIsEngageable:
    def test_full_auto_is_engageable(self) -> None:
        assert is_engageable("zenodo-deposit")
        assert is_engageable("bluesky-atproto-multi-identity")

    def test_conditional_engage_is_engageable(self) -> None:
        assert is_engageable("philarchive-deposit")
        assert is_engageable("crossref-doi-deposit")

    def test_refused_is_not_engageable(self) -> None:
        assert not is_engageable("bandcamp-upload")
        assert not is_engageable("discogs-submission")

    def test_unknown_surface_is_not_engageable(self) -> None:
        assert not is_engageable("nonexistent-surface")


class TestRefusedSurfaces:
    def test_returns_sorted_list(self) -> None:
        surfaces = refused_surfaces()
        assert surfaces == sorted(surfaces)

    def test_contains_known_refused(self) -> None:
        surfaces = refused_surfaces()
        assert "bandcamp-upload" in surfaces
        assert "discogs-submission" in surfaces
        assert "rym-submission" in surfaces

    def test_excludes_full_auto(self) -> None:
        surfaces = refused_surfaces()
        assert "zenodo-deposit" not in surfaces


class TestAutoSurfaces:
    def test_returns_sorted_list(self) -> None:
        surfaces = auto_surfaces()
        assert surfaces == sorted(surfaces)

    def test_contains_full_auto_only(self) -> None:
        surfaces = auto_surfaces()
        for name in surfaces:
            assert SURFACE_REGISTRY[name].automation_status == AutomationStatus.FULL_AUTO

    def test_excludes_refused_and_conditional(self) -> None:
        surfaces = auto_surfaces()
        assert "bandcamp-upload" not in surfaces
        assert "philarchive-deposit" not in surfaces

    def test_every_full_auto_surface_has_dispatch_or_activation_path(self) -> None:
        for name in auto_surfaces():
            spec = SURFACE_REGISTRY[name]
            assert spec.dispatch_entry or spec.activation_path, (
                f"{name} must declare dispatch_entry or activation_path"
            )

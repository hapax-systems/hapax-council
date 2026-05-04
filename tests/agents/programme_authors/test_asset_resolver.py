"""Tests for agents.programme_authors.asset_resolver.

Each per-role resolver is exercised against a mocked ``get_qdrant`` +
``embed`` pair so the tests don't reach a live Qdrant instance. Vault
lookups are exercised against a temp-dir vault layout. The
``resolve_react`` path is tested with both a mocked successful resolve
and the import-failure / exception fail-open paths.

The resolvers fail open by design — Qdrant outages, missing vault
notes, or content-resolver failures must produce empty asset bundles,
never exceptions, so the planner loop keeps running. Tests pin that
contract for each resolver.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from agents.programme_authors.asset_resolver import (
    DEFAULT_TIER_LIST_CANDIDATES,
    DEFAULT_TOP_10_CANDIDATES,
    IcebergAssets,
    InterviewAssets,
    LectureAssets,
    RantAssets,
    ReactAssets,
    TierListAssets,
    Top10Assets,
    resolve_assets,
    resolve_iceberg,
    resolve_interview,
    resolve_lecture,
    resolve_rant,
    resolve_react,
    resolve_tier_list,
    resolve_top_10,
)


def _qdrant_points(items: list[tuple[str, str, float]]):
    """Return a SimpleNamespace shaped like a qdrant query result."""
    points = [
        SimpleNamespace(
            payload={"text": text, "source": source},
            score=score,
        )
        for text, source, score in items
    ]
    return SimpleNamespace(points=points)


@pytest.fixture()
def fake_qdrant():
    """Patch shared.config.get_qdrant + embed for resolver tests."""

    def _factory(by_collection: dict[str, list[tuple[str, str, float]]]):
        client = mock.Mock()

        def _query_points(collection: str, *, query, limit: int):
            data = by_collection.get(collection, [])
            return _qdrant_points(data[:limit])

        client.query_points = mock.Mock(side_effect=_query_points)
        return client

    return _factory


@pytest.fixture()
def patch_qdrant(monkeypatch, fake_qdrant):
    """Convenience: patch get_qdrant + embed in shared.config."""

    def _patch(by_collection: dict[str, list[tuple[str, str, float]]]):
        client = fake_qdrant(by_collection)
        monkeypatch.setattr("shared.config.get_qdrant", lambda: client)
        monkeypatch.setattr("shared.config.embed", lambda text, prefix=None: [0.0] * 384)
        return client

    return _patch


# --- TierListAssets ---------------------------------------------------------


class TestResolveTierList:
    def test_returns_candidates_with_sources(self, patch_qdrant):
        patch_qdrant(
            {
                "documents": [
                    ("Album A is a doom metal masterpiece", "vault://music/a.md", 0.9),
                    ("Album B is post-rock", "vault://music/b.md", 0.85),
                ]
            }
        )
        assets = resolve_tier_list("doom albums", limit=5)

        assert isinstance(assets, TierListAssets)
        assert assets.topic == "doom albums"
        assert len(assets.candidates) == 2
        assert "doom metal" in assets.candidates[0]
        assert assets.candidate_sources[0].startswith("vault://")

    def test_empty_qdrant_returns_empty_assets(self, patch_qdrant):
        patch_qdrant({"documents": []})
        assets = resolve_tier_list("nonsense topic")
        assert assets.is_empty
        assert assets.candidates == ()

    def test_qdrant_failure_fails_open(self, monkeypatch):
        """Qdrant import or call failure ⇒ empty assets, no exception."""
        monkeypatch.setattr(
            "shared.config.get_qdrant",
            lambda: (_ for _ in ()).throw(RuntimeError("qdrant down")),
        )
        monkeypatch.setattr("shared.config.embed", lambda text, prefix=None: [0.0] * 384)
        assets = resolve_tier_list("anything")
        assert assets.is_empty

    def test_default_limit_matches_constant(self, patch_qdrant):
        client = patch_qdrant({"documents": []})
        resolve_tier_list("topic")
        # The fake's last call's limit kwarg is the default.
        assert client.query_points.call_args.kwargs["limit"] == DEFAULT_TIER_LIST_CANDIDATES


# --- Top10Assets ------------------------------------------------------------


class TestResolveTop10:
    def test_default_caps_at_10(self, patch_qdrant):
        client = patch_qdrant({"documents": []})
        resolve_top_10("anything")
        assert client.query_points.call_args.kwargs["limit"] == DEFAULT_TOP_10_CANDIDATES

    def test_returns_ranked_candidates(self, patch_qdrant):
        # Scores order is preserved (Qdrant returns highest-first; resolver
        # accepts that ordering as the ranking).
        patch_qdrant(
            {"documents": [(f"Item {i}", f"src://{i}", 1.0 - i * 0.05) for i in range(15)]}
        )
        assets = resolve_top_10("topic")
        assert isinstance(assets, Top10Assets)
        assert len(assets.ranked_candidates) == 10
        assert assets.ranked_candidates[0] == "Item 0"  # highest score
        assert assets.ranked_candidates[-1] == "Item 9"


# --- RantAssets -------------------------------------------------------------


class TestResolveRant:
    def test_pulls_positions_and_corrections(self, patch_qdrant):
        patch_qdrant(
            {
                "profile-facts": [
                    ("Operator dislikes vendor lock-in", "profile/positions.md", 0.9),
                ],
                "operator-corrections": [
                    ("Don't conflate X with Y", "corr-a", 0.8),
                ],
            }
        )
        assets = resolve_rant("vendor lock-in")
        assert isinstance(assets, RantAssets)
        assert "Operator dislikes" in assets.operator_positions[0]
        assert "Don't conflate" in assets.prior_corrections[0]
        assert not assets.is_empty

    def test_empty_when_both_collections_silent(self, patch_qdrant):
        patch_qdrant({"profile-facts": [], "operator-corrections": []})
        assets = resolve_rant("topic operator has not weighed in on")
        assert assets.is_empty


# --- ReactAssets ------------------------------------------------------------


class TestResolveReact:
    def test_empty_uri_is_resolution_failed(self):
        assets = resolve_react("   ")
        assert isinstance(assets, ReactAssets)
        assert assets.resolution_failed
        assert assets.is_empty

    def test_missing_client_module_fails_open(self):
        # No agents.content_resolver_client in tree — resolve_react
        # should silently fall through to resolution_failed.
        # (If the module is added later, this test still passes when
        # the module's resolve() raises on a malformed URI.)
        assets = resolve_react("https://example.invalid/clip")
        assert isinstance(assets, ReactAssets)
        assert assets.source_uri == "https://example.invalid/clip"
        assert assets.resolution_failed

    def test_successful_resolve_populates_fields(self):
        fake_module = SimpleNamespace(
            resolve=lambda uri: SimpleNamespace(
                title="A Talk on Caching",
                excerpt="Brief abstract here.",
                chapter_markers=("0:00 intro", "5:30 prefix caching"),
            )
        )
        with mock.patch.dict(
            sys.modules, {"agents.content_resolver_client": fake_module}, clear=False
        ):
            assets = resolve_react("https://example.com/talk")

        assert assets.resolved_title == "A Talk on Caching"
        assert assets.resolved_excerpt == "Brief abstract here."
        assert "intro" in assets.chapter_markers[0]
        assert assets.resolution_failed is False

    def test_dict_response_is_supported(self):
        fake_module = SimpleNamespace(
            resolve=lambda uri: {
                "title": "Dict-shaped resolver",
                "excerpt": "ok",
                "chapter_markers": ("a",),
            }
        )
        with mock.patch.dict(
            sys.modules, {"agents.content_resolver_client": fake_module}, clear=False
        ):
            assets = resolve_react("ref://x")
        assert assets.resolved_title == "Dict-shaped resolver"
        assert assets.chapter_markers == ("a",)


# --- IcebergAssets ----------------------------------------------------------


class TestResolveIceberg:
    def test_layers_truncate_to_requested_count(self, patch_qdrant, monkeypatch, tmp_path: Path):
        patch_qdrant({"documents": [("Surface fact", "rag", 0.8)]})
        # No vault available ⇒ deeper layers empty.
        monkeypatch.setattr(
            "agents.programme_authors.asset_resolver.VAULT_AREAS", tmp_path / "areas"
        )
        monkeypatch.setattr(
            "agents.programme_authors.asset_resolver.VAULT_PROJECTS",
            tmp_path / "projects",
        )
        monkeypatch.setattr(
            "agents.programme_authors.asset_resolver.VAULT_RESOURCES",
            tmp_path / "resources",
        )
        assets = resolve_iceberg("topic", layers=2)
        assert isinstance(assets, IcebergAssets)
        assert len(assets.layers) == 2
        assert assets.layers[0]  # surface populated
        assert assets.layers[1] == ()  # vault empty

    def test_vault_layer_uses_relative_paths(self, patch_qdrant, monkeypatch, tmp_path: Path):
        patch_qdrant({"documents": []})
        vault_root = tmp_path / "vault"
        areas = vault_root / "30-areas"
        areas.mkdir(parents=True)
        (areas / "topic-deep.md").write_text("explicit topic content here", encoding="utf-8")

        monkeypatch.setattr("agents.programme_authors.asset_resolver.VAULT_ROOT", vault_root)
        monkeypatch.setattr("agents.programme_authors.asset_resolver.VAULT_AREAS", areas)
        monkeypatch.setattr(
            "agents.programme_authors.asset_resolver.VAULT_PROJECTS",
            vault_root / "20-projects",
        )
        monkeypatch.setattr(
            "agents.programme_authors.asset_resolver.VAULT_RESOURCES",
            vault_root / "50-resources",
        )

        assets = resolve_iceberg("topic", layers=4)
        # Layer 1 surface is empty (no qdrant hits), layer 2 (areas) hits.
        assert assets.layers[1] == ("30-areas/topic-deep.md",)


# --- InterviewAssets --------------------------------------------------------


class TestResolveInterview:
    def test_combines_documents_and_profile_hits(self, patch_qdrant):
        patch_qdrant(
            {
                "documents": [("Subject biographical context", "rag", 0.8)],
                "profile-facts": [("Operator's prior take on subject", "profile", 0.85)],
            }
        )
        assets = resolve_interview("Subject Name")
        assert isinstance(assets, InterviewAssets)
        assert any("biographical" in hit for hit in assets.prep_hits)
        assert any("prior take" in hit for hit in assets.prep_hits)
        assert assets.prior_interaction_refs == ()

    def test_empty_collections_yields_empty_assets(self, patch_qdrant):
        patch_qdrant({"documents": [], "profile-facts": []})
        assets = resolve_interview("Unknown Subject")
        assert assets.is_empty


# --- LectureAssets ----------------------------------------------------------


class TestResolveLecture:
    def test_vault_notes_preferred_over_rag(self, patch_qdrant, monkeypatch, tmp_path: Path):
        patch_qdrant({"documents": [("RAG fallback hit", "rag", 0.7)]})
        vault_root = tmp_path / "vault"
        areas = vault_root / "30-areas"
        projects = vault_root / "20-projects"
        areas.mkdir(parents=True)
        projects.mkdir(parents=True)
        (areas / "lecture-topic.md").write_text("topic detail", encoding="utf-8")

        monkeypatch.setattr("agents.programme_authors.asset_resolver.VAULT_ROOT", vault_root)
        monkeypatch.setattr("agents.programme_authors.asset_resolver.VAULT_AREAS", areas)
        monkeypatch.setattr("agents.programme_authors.asset_resolver.VAULT_PROJECTS", projects)

        assets = resolve_lecture("topic")
        assert isinstance(assets, LectureAssets)
        assert assets.outline_notes == ("30-areas/lecture-topic.md",)
        # When vault has hits, rag_fallbacks stays empty.
        assert assets.rag_fallbacks == ()

    def test_rag_fallback_when_vault_silent(self, patch_qdrant, monkeypatch, tmp_path: Path):
        patch_qdrant({"documents": [("RAG hit", "rag", 0.7)]})
        monkeypatch.setattr(
            "agents.programme_authors.asset_resolver.VAULT_AREAS", tmp_path / "areas"
        )
        monkeypatch.setattr(
            "agents.programme_authors.asset_resolver.VAULT_PROJECTS",
            tmp_path / "projects",
        )
        assets = resolve_lecture("nonexistent topic")
        assert assets.outline_notes == ()
        assert "RAG hit" in assets.rag_fallbacks


# --- resolve_assets dispatch ------------------------------------------------


class TestResolveAssetsDispatch:
    @pytest.fixture(autouse=True)
    def _patch_resolvers(self, monkeypatch, patch_qdrant):
        # Empty resolvers across the board so dispatch tests assert
        # only the routing decision, not the underlying I/O.
        patch_qdrant({"documents": [], "profile-facts": [], "operator-corrections": []})
        monkeypatch.setattr(
            "agents.programme_authors.asset_resolver.VAULT_AREAS",
            Path("/nonexistent/areas"),
        )
        monkeypatch.setattr(
            "agents.programme_authors.asset_resolver.VAULT_PROJECTS",
            Path("/nonexistent/projects"),
        )
        monkeypatch.setattr(
            "agents.programme_authors.asset_resolver.VAULT_RESOURCES",
            Path("/nonexistent/resources"),
        )

    @pytest.mark.parametrize(
        "role,expected_type",
        [
            ("tier_list", TierListAssets),
            ("top_10", Top10Assets),
            ("rant", RantAssets),
            ("react", ReactAssets),
            ("iceberg", IcebergAssets),
            ("interview", InterviewAssets),
            ("lecture", LectureAssets),
        ],
    )
    def test_each_segmented_role_dispatches_correctly(self, role: str, expected_type):
        result = resolve_assets(role, topic="t", source_uri="ref://x", subject="s")
        assert isinstance(result, expected_type)

    def test_operator_context_role_returns_none(self):
        # work_block etc. are operator-context roles — they don't have a
        # declared topic to acquire assets for; resolution returns None.
        assert resolve_assets("work_block", topic="anything") is None
        assert resolve_assets("listening", topic="anything") is None

    def test_enum_role_value_works(self):
        # Real consumers pass `programme.role` (StrEnum); accept either
        # the StrEnum or the bare string.
        role = SimpleNamespace(value="rant")
        result = resolve_assets(role, topic="t")
        assert isinstance(result, RantAssets)


# --- Smoke: every role builds without crashing ------------------------------


class TestSmokeAllSevenRoles:
    """Final acceptance: each segmented-content role builds an asset
    bundle from a topic seed, even with no Qdrant + no vault."""

    @pytest.fixture(autouse=True)
    def _empty_environment(self, monkeypatch):
        monkeypatch.setattr(
            "shared.config.get_qdrant",
            lambda: (_ for _ in ()).throw(RuntimeError("offline")),
        )
        monkeypatch.setattr("shared.config.embed", lambda text, prefix=None: [0.0] * 384)
        monkeypatch.setattr(
            "agents.programme_authors.asset_resolver.VAULT_AREAS",
            Path("/nonexistent/areas"),
        )
        monkeypatch.setattr(
            "agents.programme_authors.asset_resolver.VAULT_PROJECTS",
            Path("/nonexistent/projects"),
        )
        monkeypatch.setattr(
            "agents.programme_authors.asset_resolver.VAULT_RESOURCES",
            Path("/nonexistent/resources"),
        )

    @pytest.mark.parametrize(
        "role",
        ["tier_list", "top_10", "rant", "react", "iceberg", "interview", "lecture"],
    )
    def test_role_returns_assets_or_none(self, role: str):
        assets = resolve_assets(role, topic="EXL3 quants", source_uri="ref://x")
        assert assets is not None
        # is_empty is permitted (no env), but the type must be correct.
        assert hasattr(assets, "is_empty")

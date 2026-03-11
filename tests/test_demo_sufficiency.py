"""Tests for the knowledge sufficiency gate."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agents.demo_models import AudienceDossier
from agents.demo_pipeline.sufficiency import (
    SufficiencyResult,
    check_sufficiency,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profiles_dir(tmp_path: Path) -> Path:
    """Create a profiles dir with all expected files present."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()

    # component-registry.yaml
    (profiles / "component-registry.yaml").write_text("components: []")

    # health-history.jsonl — fresh
    hist = profiles / "health-history.jsonl"
    hist.write_text('{"status": "ok"}\n')

    # briefing.md — fresh
    (profiles / "briefing.md").write_text("# Daily Briefing\nAll systems nominal.")

    # operator-digest.json
    (profiles / "operator-digest.json").write_text('{"name": "Operator"}')

    return profiles


def _mock_operator_with_axioms():
    return {"axioms": {"single_user": "100"}, "name": "Operator"}


def _mock_operator_no_axioms():
    return {"name": "Operator"}


def _mock_qdrant_collection(point_count: int, arch_rag_available: bool = True):
    client = MagicMock()
    info = MagicMock()
    info.points_count = point_count
    client.get_collection.return_value = info
    # Mock query_points for architecture_rag check
    qp_result = MagicMock()
    if arch_rag_available:
        point = MagicMock()
        point.payload = {"source": "/documents/rag-sources/hapaxromana/CLAUDE.md", "text": "arch"}
        qp_result.points = [point]
    else:
        qp_result.points = []
    client.query_points.return_value = qp_result
    # Mock count for doc_freshness check
    count_result = MagicMock()
    count_result.count = point_count
    client.count.return_value = count_result
    return client


def _wife_dossier() -> dict[str, AudienceDossier]:
    return {
        "my partner": AudienceDossier(
            key="my partner",
            archetype="family",
            name="Sarah",
            context="Has some experience with the system. Her goal is to understand what I built. No concerns or resistance. She is my spouse with no decision authority. Casual context at home.",
            calibration={},
        )
    }


def _run_with_all_passing(
    tmp_path: Path,
    audience_text: str = "show my partner",
    archetype: str = "family",
    dossiers: dict[str, AudienceDossier] | None = None,
    health_report: object | None = None,
    point_count: int = 500,
    operator_fn=_mock_operator_with_axioms,
) -> SufficiencyResult:
    """Run check_sufficiency with all system checks passing by default."""
    profiles = _make_profiles_dir(tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("x" * 2000)

    if dossiers is None:
        dossiers = _wife_dossier()

    if health_report is None:
        health_report = SimpleNamespace(healthy_count=75, total_checks=75, failed_count=0)

    qdrant = _mock_qdrant_collection(point_count)

    with (
        patch("agents.demo_pipeline.sufficiency._HAPAXROMANA_CLAUDE_MD", claude_md),
        patch("agents.demo_pipeline.sufficiency.PROFILES_DIR", profiles),
        patch("agents.demo_pipeline.sufficiency.get_qdrant", return_value=qdrant),
        patch("agents.demo_pipeline.sufficiency.get_operator", operator_fn),
        patch("agents.demo_pipeline.sufficiency.load_audiences", return_value=dossiers),
        patch("shared.config.embed", return_value=[0.1] * 768),
    ):
        return check_sufficiency(
            scope="full",
            archetype=archetype,
            audience_text=audience_text,
            health_report=health_report,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConfidenceLevels:
    def test_high_confidence(self, tmp_path: Path):
        """9/9 system + dossier → 'high'."""
        result = _run_with_all_passing(tmp_path)
        assert result.confidence == "high"
        assert sum(1 for c in result.system_checks if c.available) == 9
        assert result.audience_dossier is not None

    def test_adequate_no_dossier(self, tmp_path: Path):
        """7/7 system, no dossier → 'adequate'."""
        result = _run_with_all_passing(
            tmp_path,
            audience_text="random person",
            dossiers={},
        )
        assert result.confidence == "adequate"
        assert result.audience_dossier is None

    def test_low_missing_sources(self, tmp_path: Path):
        """5/7 system → 'low' with enrichment actions."""
        profiles = _make_profiles_dir(tmp_path)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("x" * 2000)

        # Remove briefing and profile_digest → 5/7
        (profiles / "briefing.md").unlink()
        (profiles / "operator-digest.json").unlink()

        health_report = SimpleNamespace(healthy_count=75, total_checks=75, failed_count=0)
        qdrant = _mock_qdrant_collection(500)

        with (
            patch("agents.demo_pipeline.sufficiency._HAPAXROMANA_CLAUDE_MD", claude_md),
            patch("agents.demo_pipeline.sufficiency.PROFILES_DIR", profiles),
            patch("agents.demo_pipeline.sufficiency.get_qdrant", return_value=qdrant),
            patch("agents.demo_pipeline.sufficiency.get_operator", _mock_operator_with_axioms),
            patch("agents.demo_pipeline.sufficiency.load_audiences", return_value={}),
            patch("shared.config.embed", return_value=[0.1] * 768),
        ):
            result = check_sufficiency(
                scope="full",
                archetype="family",
                audience_text="someone",
                health_report=health_report,
            )

        assert result.confidence == "low"
        assert len(result.enrichment_actions) > 0

    def test_blocked_few_sources(self, tmp_path: Path):
        """3/8 system → 'blocked'."""
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        # Only component-registry present → checks: component_registry passes
        (profiles / "component-registry.yaml").write_text("components: []")

        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("x" * 2000)  # architecture_docs passes

        # health_report provided → health_data passes
        # That's 3 passing. operator fails, profile_facts fails, briefing fails, digest fails,
        # architecture_rag fails (no points returned).
        health_report = SimpleNamespace(healthy_count=75, total_checks=75, failed_count=0)

        qdrant = _mock_qdrant_collection(
            10, arch_rag_available=False
        )  # < 100 → profile_facts fails

        with (
            patch("agents.demo_pipeline.sufficiency._HAPAXROMANA_CLAUDE_MD", claude_md),
            patch("agents.demo_pipeline.sufficiency.PROFILES_DIR", profiles),
            patch("agents.demo_pipeline.sufficiency.get_qdrant", return_value=qdrant),
            patch("agents.demo_pipeline.sufficiency.get_operator", _mock_operator_no_axioms),
            patch("agents.demo_pipeline.sufficiency.load_audiences", return_value={}),
            patch("shared.config.embed", return_value=[0.1] * 768),
        ):
            result = check_sufficiency(
                scope="full",
                archetype="family",
                audience_text="someone",
                health_report=health_report,
            )

        assert result.confidence == "blocked"
        passing = sum(1 for c in result.system_checks if c.available)
        assert passing < 4


class TestEnrichmentActions:
    def test_enrichment_actions_match_gaps(self, tmp_path: Path):
        """Missing briefing → 'briefing_stats' in enrichment actions."""
        profiles = _make_profiles_dir(tmp_path)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("x" * 2000)

        # Remove briefing only
        (profiles / "briefing.md").unlink()

        health_report = SimpleNamespace(healthy_count=75, total_checks=75, failed_count=0)
        qdrant = _mock_qdrant_collection(500)

        with (
            patch("agents.demo_pipeline.sufficiency._HAPAXROMANA_CLAUDE_MD", claude_md),
            patch("agents.demo_pipeline.sufficiency.PROFILES_DIR", profiles),
            patch("agents.demo_pipeline.sufficiency.get_qdrant", return_value=qdrant),
            patch("agents.demo_pipeline.sufficiency.get_operator", _mock_operator_with_axioms),
            patch("agents.demo_pipeline.sufficiency.load_audiences", return_value={}),
            patch("shared.config.embed", return_value=[0.1] * 768),
        ):
            result = check_sufficiency(
                scope="full",
                archetype="family",
                audience_text="someone",
                health_report=health_report,
            )

        assert "briefing_stats" in result.enrichment_actions


class TestAudienceDossier:
    def test_dossier_found(self, tmp_path: Path):
        """'my partner' in audience text → dossier returned."""
        result = _run_with_all_passing(
            tmp_path,
            audience_text="show my partner the system",
        )
        assert result.audience_dossier is not None
        assert result.audience_dossier.name == "Sarah"

    def test_dossier_not_found(self, tmp_path: Path):
        """'random person' → None."""
        result = _run_with_all_passing(
            tmp_path,
            audience_text="random person",
            dossiers=_wife_dossier(),
        )
        assert result.audience_dossier is None


class TestHealthReportReuse:
    def test_reuses_health_report(self, tmp_path: Path):
        """When health_report param is provided, no file check needed."""
        profiles = _make_profiles_dir(tmp_path)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("x" * 2000)

        # Remove health-history.jsonl — should still pass because health_report is provided
        hist = profiles / "health-history.jsonl"
        if hist.exists():
            hist.unlink()

        health_report = SimpleNamespace(healthy_count=75, total_checks=75, failed_count=0)
        qdrant = _mock_qdrant_collection(500)

        with (
            patch("agents.demo_pipeline.sufficiency._HAPAXROMANA_CLAUDE_MD", claude_md),
            patch("agents.demo_pipeline.sufficiency.PROFILES_DIR", profiles),
            patch("agents.demo_pipeline.sufficiency.get_qdrant", return_value=qdrant),
            patch("agents.demo_pipeline.sufficiency.get_operator", _mock_operator_with_axioms),
            patch("agents.demo_pipeline.sufficiency.load_audiences", return_value={}),
            patch("shared.config.embed", return_value=[0.1] * 768),
        ):
            result = check_sufficiency(
                scope="full",
                archetype="family",
                audience_text="someone",
                health_report=health_report,
            )

        health_check = next(c for c in result.system_checks if c.name == "health_data")
        assert health_check.available is True
        assert "readiness gate" in health_check.detail


class TestQdrantFailure:
    def test_qdrant_unreachable(self, tmp_path: Path):
        """Graceful failure when Qdrant is unreachable."""
        profiles = _make_profiles_dir(tmp_path)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("x" * 2000)

        health_report = SimpleNamespace(healthy_count=75, total_checks=75, failed_count=0)

        def _qdrant_error():
            client = MagicMock()
            client.get_collection.side_effect = ConnectionError("Qdrant unreachable")
            return client

        with (
            patch("agents.demo_pipeline.sufficiency._HAPAXROMANA_CLAUDE_MD", claude_md),
            patch("agents.demo_pipeline.sufficiency.PROFILES_DIR", profiles),
            patch("agents.demo_pipeline.sufficiency.get_qdrant", return_value=_qdrant_error()),
            patch("agents.demo_pipeline.sufficiency.get_operator", _mock_operator_with_axioms),
            patch("agents.demo_pipeline.sufficiency.load_audiences", return_value={}),
            patch("shared.config.embed", return_value=[0.1] * 768),
        ):
            result = check_sufficiency(
                scope="full",
                archetype="family",
                audience_text="someone",
                health_report=health_report,
            )

        facts_check = next(c for c in result.system_checks if c.name == "profile_facts")
        assert facts_check.available is False
        assert "unreachable" in facts_check.detail

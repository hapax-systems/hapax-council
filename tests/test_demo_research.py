"""Tests for agents.demo_pipeline.research — subject matter research stage."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from agents.demo_models import AudienceDossier
from agents.demo_pipeline.research import (
    _SECTION_HEADERS,
    AUDIENCE_SOURCES,
    _format_audience_dossier,
    _gather_architecture_rag,
    _gather_audit_findings,
    _gather_briefing_stats,
    _gather_component_registry,
    _gather_component_registry_rich,
    _gather_design_plans,
    _gather_domain_literature,
    _gather_operator_philosophy,
    _gather_profile_facts_rich,
    _gather_scout_summary,
    _gather_system_docs,
    gather_research,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


def _make_health_report(
    status: str = "healthy",
    total: int = 10,
    healthy: int = 10,
    failed: int = 0,
    degraded: int = 0,
):
    """Build a mock HealthReport."""
    mock = MagicMock()
    mock.overall_status.value = status
    mock.total_checks = total
    mock.healthy_count = healthy
    mock.failed_count = failed
    mock.degraded_count = degraded
    mock.duration_ms = 42
    mock.groups = []
    mock.summary = "All good"
    return mock


def _make_manifest(n_containers: int = 3, n_timers: int = 2):
    """Build a mock InfrastructureManifest."""
    mock = MagicMock()
    containers = []
    for i in range(n_containers):
        c = MagicMock()
        c.service = f"svc-{i}"
        c.state = "running"
        c.health = "healthy"
        c.ports = [f"127.0.0.1:{4000 + i}"]
        containers.append(c)
    mock.containers = containers

    timers = []
    for i in range(n_timers):
        t = MagicMock()
        t.name = f"timer-{i}.timer"
        t.active = "active"
        t.enabled = "enabled"
        timers.append(t)
    mock.systemd_timers = timers

    mock.gpu = None
    mock.listening_ports = ["127.0.0.1:4000"]
    return mock


@pytest.fixture
def component_registry_yaml(tmp_path: Path) -> Path:
    """Write a minimal component-registry.yaml to a temp dir."""
    data = {
        "components": {
            "vector-database": {
                "role": "Vector storage for RAG",
                "current": "Qdrant (Docker)",
            },
            "llm-gateway": {
                "role": "Unified API gateway",
                "current": "LiteLLM (Docker)",
            },
        }
    }
    p = tmp_path / "component-registry.yaml"
    p.write_text(yaml.dump(data))
    return p


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gather_research_family():
    """Family audience should call component_registry, health_summary, profile_facts_rich, briefing_stats, operator_philosophy."""
    called_sources: list[str] = []

    async def mock_run_checks(groups=None):
        called_sources.append("health_summary")
        return _make_health_report()

    with (
        patch(
            "agents.demo_pipeline.research._gather_component_registry",
            side_effect=lambda: called_sources.append("component_registry") or "components here",
        ),
        patch(
            "agents.health_monitor.run_checks",
            side_effect=mock_run_checks,
        ),
        patch(
            "agents.demo_pipeline.research._gather_profile_facts_rich",
            side_effect=lambda scope, audience="": (
                called_sources.append("profile_facts_rich") or "facts here"
            ),
        ),
        patch(
            "agents.demo_pipeline.research._gather_briefing_stats",
            side_effect=lambda: called_sources.append("briefing_stats") or "stats here",
        ),
        patch(
            "agents.demo_pipeline.research._gather_operator_philosophy",
            side_effect=lambda: called_sources.append("operator_philosophy") or "philosophy here",
        ),
        patch(
            "agents.demo_pipeline.research._gather_domain_literature",
            side_effect=lambda scope: (
                called_sources.append("domain_literature") or "literature here"
            ),
        ),
    ):
        await gather_research(scope="my system", audience="family")

    assert "component_registry" in called_sources
    assert "health_summary" in called_sources
    assert "profile_facts_rich" in called_sources
    assert "briefing_stats" in called_sources
    assert "operator_philosophy" in called_sources
    assert "domain_literature" in called_sources
    # Should NOT have called these
    assert "langfuse_metrics" not in called_sources
    assert "web_research" not in called_sources
    assert "introspect" not in called_sources


@pytest.mark.asyncio
async def test_gather_research_leadership():
    """Leadership audience should include web_research, langfuse_metrics, and new sources."""
    called_sources: list[str] = []

    async def mock_run_checks(groups=None):
        called_sources.append("health_summary")
        return _make_health_report()

    async def mock_introspect(partial=False):
        called_sources.append("introspect")
        return "infra data"

    with (
        patch(
            "agents.demo_pipeline.research._gather_component_registry_rich",
            side_effect=lambda: called_sources.append("component_registry_rich") or "components",
        ),
        patch(
            "agents.health_monitor.run_checks",
            side_effect=mock_run_checks,
        ),
        patch(
            "agents.demo_pipeline.research._gather_introspect",
            side_effect=mock_introspect,
        ),
        patch(
            "agents.demo_pipeline.research._gather_langfuse_metrics",
            side_effect=lambda: called_sources.append("langfuse_metrics") or "metrics",
        ),
        patch(
            "agents.demo_pipeline.research._gather_system_docs",
            side_effect=lambda summary=False: called_sources.append("system_docs") or "docs",
        ),
        patch(
            "agents.demo_pipeline.research._gather_profile_facts_rich",
            side_effect=lambda scope, audience="": (
                called_sources.append("profile_facts_rich") or "facts"
            ),
        ),
        patch(
            "agents.demo_pipeline.research._gather_operator_philosophy",
            side_effect=lambda: called_sources.append("operator_philosophy") or "philosophy",
        ),
        patch(
            "agents.demo_pipeline.research._gather_briefing_stats",
            side_effect=lambda: called_sources.append("briefing_stats") or "stats",
        ),
        patch(
            "agents.demo_pipeline.research._gather_web_research",
            side_effect=lambda scope, audience: called_sources.append("web_research") or "web",
        ),
        patch(
            "agents.demo_pipeline.research._gather_architecture_rag",
            side_effect=lambda scope: called_sources.append("architecture_rag") or "arch rag",
        ),
        patch(
            "agents.demo_pipeline.research._gather_design_plans",
            side_effect=lambda scope: called_sources.append("design_plans") or "plans",
        ),
        patch(
            "agents.demo_pipeline.research._gather_domain_literature",
            side_effect=lambda scope: called_sources.append("domain_literature") or "literature",
        ),
        patch(
            "agents.demo_pipeline.research._gather_audit_findings",
            side_effect=lambda: called_sources.append("audit_findings") or "audit",
        ),
    ):
        await gather_research(scope="agent architecture", audience="leadership")

    assert "langfuse_metrics" in called_sources
    assert "web_research" in called_sources
    assert "introspect" in called_sources
    assert "system_docs" in called_sources
    assert "profile_facts_rich" in called_sources
    assert "operator_philosophy" in called_sources
    assert "briefing_stats" in called_sources
    assert "architecture_rag" in called_sources
    assert "design_plans" in called_sources
    assert "domain_literature" in called_sources
    assert "audit_findings" in called_sources


@pytest.mark.asyncio
async def test_gather_research_source_failure_graceful():
    """If one source raises, the rest should still produce output."""

    async def mock_run_checks(groups=None):
        raise ConnectionError("health service down")

    with (
        patch(
            "agents.demo_pipeline.research._gather_component_registry",
            return_value="components ok",
        ),
        patch(
            "agents.health_monitor.run_checks",
            side_effect=mock_run_checks,
        ),
        patch(
            "agents.demo_pipeline.research._gather_profile_facts_rich",
            return_value="profile ok",
        ),
        patch(
            "agents.demo_pipeline.research._gather_briefing_stats",
            return_value="stats ok",
        ),
        patch(
            "agents.demo_pipeline.research._gather_operator_philosophy",
            return_value="philosophy ok",
        ),
        patch(
            "agents.demo_pipeline.research._gather_domain_literature",
            return_value="literature ok",
        ),
    ):
        result = await gather_research(scope="test", audience="family")

    # Should still have component and profile sections despite health failure
    assert "## System Components" in result
    assert "components ok" in result
    assert "## Operator Profile (Detailed)" in result
    assert "profile ok" in result


def test_gather_component_registry(component_registry_yaml: Path):
    """Verify component registry formats names and descriptions."""
    # _gather_component_registry imports PROFILES_DIR inside the function body
    with patch("shared.config.PROFILES_DIR", component_registry_yaml.parent):
        result = _gather_component_registry()

    assert "vector-database" in result
    assert "llm-gateway" in result
    assert "Vector storage for RAG" in result
    assert "Qdrant (Docker)" in result


def test_audience_filtering():
    """Verify AUDIENCE_SOURCES keys match known archetypes from demo-personas.yaml."""
    known_archetypes = {"family", "technical-peer", "leadership", "team-member"}
    assert set(AUDIENCE_SOURCES.keys()) == known_archetypes


@pytest.mark.asyncio
async def test_context_document_has_sections():
    """Verify output document has ## section headers."""

    async def mock_run_checks(groups=None):
        return _make_health_report()

    with (
        patch(
            "agents.demo_pipeline.research._gather_component_registry",
            return_value="- **test**: Test component (current: v1)",
        ),
        patch(
            "agents.health_monitor.run_checks",
            side_effect=mock_run_checks,
        ),
        patch(
            "agents.demo_pipeline.research._gather_profile_facts_rich",
            return_value="- Test fact",
        ),
        patch(
            "agents.demo_pipeline.research._gather_briefing_stats",
            return_value="stats",
        ),
        patch(
            "agents.demo_pipeline.research._gather_operator_philosophy",
            return_value="philosophy",
        ),
        patch(
            "agents.demo_pipeline.research._gather_domain_literature",
            return_value="literature",
        ),
    ):
        result = await gather_research(scope="test", audience="family")

    # Should have section headers
    assert "## System Components" in result
    assert "## Current Health" in result
    assert "## Operator Profile (Detailed)" in result


@pytest.mark.asyncio
async def test_gather_research_unknown_audience_falls_back_to_family():
    """Unknown audience key should fall back to family sources."""

    async def mock_run_checks(groups=None):
        return _make_health_report()

    with (
        patch(
            "agents.demo_pipeline.research._gather_component_registry",
            return_value="components",
        ),
        patch(
            "agents.health_monitor.run_checks",
            side_effect=mock_run_checks,
        ),
        patch(
            "agents.demo_pipeline.research._gather_profile_facts_rich",
            return_value="facts",
        ),
        patch(
            "agents.demo_pipeline.research._gather_briefing_stats",
            return_value="stats",
        ),
        patch(
            "agents.demo_pipeline.research._gather_operator_philosophy",
            return_value="philosophy",
        ),
        patch(
            "agents.demo_pipeline.research._gather_domain_literature",
            return_value="literature",
        ),
    ):
        result = await gather_research(scope="test", audience="unknown-audience")

    # Should still produce output (family fallback)
    assert result


@pytest.mark.asyncio
async def test_on_progress_callback():
    """Verify on_progress is called for each source."""
    progress_messages: list[str] = []

    async def mock_run_checks(groups=None):
        return _make_health_report()

    with (
        patch(
            "agents.demo_pipeline.research._gather_component_registry",
            return_value="components",
        ),
        patch(
            "agents.health_monitor.run_checks",
            side_effect=mock_run_checks,
        ),
        patch(
            "agents.demo_pipeline.research._gather_profile_facts_rich",
            return_value="facts",
        ),
        patch(
            "agents.demo_pipeline.research._gather_briefing_stats",
            return_value="stats",
        ),
        patch(
            "agents.demo_pipeline.research._gather_operator_philosophy",
            return_value="philosophy",
        ),
        patch(
            "agents.demo_pipeline.research._gather_domain_literature",
            return_value="literature",
        ),
    ):
        await gather_research(
            scope="test",
            audience="family",
            on_progress=progress_messages.append,
        )

    # Should have progress messages for each family source + completion
    assert any("component_registry" in m for m in progress_messages)
    assert any("health_summary" in m for m in progress_messages)
    assert any("profile_facts_rich" in m for m in progress_messages)
    # Completion message includes source count (some may fail in test env)
    assert any("Research" in m and "sources" in m for m in progress_messages)


def test_system_docs_summary_truncates(tmp_path: Path):
    """Verify system docs summary mode truncates to 2000 chars."""
    long_content = "x" * 5000
    doc_path = tmp_path / "CLAUDE.md"
    doc_path.write_text(long_content)

    with patch(
        "agents.demo_pipeline.research._HAPAXROMANA_CLAUDE_MD",
        doc_path,
    ):
        result = _gather_system_docs(summary=True)

    assert len(result) == 2000


def test_system_docs_full_returns_all(tmp_path: Path):
    """Verify system docs full mode returns complete content."""
    content = "Full system documentation here.\n" * 100
    doc_path = tmp_path / "CLAUDE.md"
    doc_path.write_text(content)

    with patch(
        "agents.demo_pipeline.research._HAPAXROMANA_CLAUDE_MD",
        doc_path,
    ):
        result = _gather_system_docs(summary=False)

    assert result == content


# ── New source function tests ──────────────────────────────────────────────


def test_gather_component_registry_rich(tmp_path: Path):
    """Rich registry includes constraints and eval_notes."""
    data = {
        "components": {
            "vector-database": {
                "role": "Vector storage for RAG",
                "current": "Qdrant (Docker)",
                "constraints": "Must support 768d vectors",
                "eval_notes": "Evaluated Weaviate, chose Qdrant for simplicity",
            },
            "llm-gateway": {
                "role": "Unified API gateway",
                "current": "LiteLLM (Docker)",
            },
        }
    }
    p = tmp_path / "component-registry.yaml"
    p.write_text(yaml.dump(data))

    with patch("shared.config.PROFILES_DIR", tmp_path):
        result = _gather_component_registry_rich()

    assert "### vector-database" in result
    assert "**Constraints**: Must support 768d vectors" in result
    assert "**Eval notes**: Evaluated Weaviate" in result
    assert "### llm-gateway" in result
    # llm-gateway has no constraints/eval_notes — those lines should be absent
    assert result.count("**Constraints**") == 1


def test_gather_briefing_stats(tmp_path: Path):
    """Reads briefing.md and returns formatted stats."""
    briefing_content = "# Daily Briefing\n\nHealth: all green\nTraces: 1,234"
    (tmp_path / "briefing.md").write_text(briefing_content)

    with patch("shared.config.PROFILES_DIR", tmp_path):
        result = _gather_briefing_stats()

    assert "Daily Briefing" in result
    assert "Health: all green" in result


def test_gather_briefing_stats_missing_file(tmp_path: Path):
    """Returns empty string when briefing.md is missing."""
    with patch("shared.config.PROFILES_DIR", tmp_path):
        result = _gather_briefing_stats()

    assert result == ""


def test_gather_operator_philosophy():
    """Formats axioms and goals from operator.json."""
    mock_data = {
        "axioms": {
            "single_user": True,
            "executive_function": True,
        },
        "goals": {
            "primary": [
                {"name": "Autonomous ops", "description": "System runs itself"},
            ],
            "secondary": [
                {"name": "Music production", "description": "DAWless workflow"},
            ],
        },
        "patterns": {
            "decision_making": ["Evaluate before adopting", "Prefer simplicity"],
        },
    }

    with patch("shared.operator.get_operator", return_value=mock_data):
        result = _gather_operator_philosophy()

    assert "### Axioms" in result
    assert "**single_user**" in result
    assert "### Goals" in result
    assert "Autonomous ops" in result
    assert "Music production" in result
    assert "### Key Patterns" in result
    assert "Evaluate before adopting" in result


def test_gather_scout_summary(tmp_path: Path):
    """Reads and formats scout-report.json via shared read_scout_report()."""
    scout_data = {
        "generated_at": "2026-03-12T10:00:00",
        "components_scanned": 6,
        "recommendations": [
            {
                "tier": "evaluate",
                "component": "Qdrant",
                "summary": "Best fit for current scale",
            },
            {
                "tier": "evaluate",
                "component": "LiteLLM",
                "summary": "No viable alternative",
            },
        ],
    }
    (tmp_path / "scout-report.json").write_text(json.dumps(scout_data))

    with patch("shared.config.PROFILES_DIR", tmp_path):
        result = _gather_scout_summary()

    assert "Qdrant" in result
    assert "Best fit for current scale" in result
    assert "LiteLLM" in result


def test_gather_profile_facts_rich_deduplicates():
    """Three Qdrant queries with deduped results by (dimension, key)."""

    # Build mock points — some share (dimension, key) across queries
    def make_point(dim: str, key: str, fact: str):
        p = MagicMock()
        p.payload = {"dimension": dim, "key": key, "fact": fact}
        return p

    call_count = 0

    def mock_embed(text):
        return [0.1] * 768

    def mock_query_points(collection_name, query, limit):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.points = [
                make_point("tech", "stack", "Uses Qdrant for vectors"),
                make_point("tech", "llm", "Routes through LiteLLM"),
            ]
        elif call_count == 2:
            result.points = [
                make_point("tech", "stack", "Uses Qdrant for vectors"),  # duplicate
                make_point("philosophy", "axiom", "Single user system"),
            ]
        else:
            result.points = [
                make_point("background", "role", "Software developer"),
                make_point("tech", "llm", "Routes through LiteLLM"),  # duplicate
            ]
        return result

    mock_client = MagicMock()
    mock_client.query_points = mock_query_points

    with (
        patch("shared.config.embed", side_effect=mock_embed),
        patch("shared.config.get_qdrant", return_value=mock_client),
    ):
        result = _gather_profile_facts_rich("agent architecture")

    # Should have 4 unique facts, not 6
    lines = [l for l in result.strip().split("\n") if l.startswith("- ")]
    assert len(lines) == 4
    assert "Uses Qdrant for vectors" in result
    assert "Single user system" in result
    assert "Software developer" in result


@pytest.mark.asyncio
async def test_gather_research_with_enrichment_actions():
    """Extra sources from enrichment_actions are added to the source list."""
    called_sources: list[str] = []

    async def mock_run_checks(groups=None):
        called_sources.append("health_summary")
        return _make_health_report()

    with (
        patch(
            "agents.demo_pipeline.research._gather_component_registry",
            side_effect=lambda: called_sources.append("component_registry") or "components",
        ),
        patch(
            "agents.health_monitor.run_checks",
            side_effect=mock_run_checks,
        ),
        patch(
            "agents.demo_pipeline.research._gather_profile_facts_rich",
            side_effect=lambda scope, audience="": (
                called_sources.append("profile_facts_rich") or "facts"
            ),
        ),
        patch(
            "agents.demo_pipeline.research._gather_briefing_stats",
            side_effect=lambda: called_sources.append("briefing_stats") or "stats",
        ),
        patch(
            "agents.demo_pipeline.research._gather_operator_philosophy",
            side_effect=lambda: called_sources.append("operator_philosophy") or "philosophy",
        ),
        patch(
            "agents.demo_pipeline.research._gather_domain_literature",
            side_effect=lambda scope: called_sources.append("domain_literature") or "literature",
        ),
        patch(
            "agents.demo_pipeline.research._gather_scout_summary",
            side_effect=lambda: called_sources.append("scout_summary") or "scout",
        ),
    ):
        result = await gather_research(
            scope="test",
            audience="family",
            enrichment_actions=["scout_summary"],
        )

    # scout_summary is not in family defaults but was added via enrichment
    assert "scout_summary" in called_sources
    assert "## External Fitness (Scout)" in result


@pytest.mark.asyncio
async def test_gather_research_with_dossier():
    """Dossier section appears in output when audience_dossier provided."""

    async def mock_run_checks(groups=None):
        return _make_health_report()

    dossier = AudienceDossier(
        key="my partner",
        archetype="family",
        name="Sarah",
        context="Non-technical, curious about the project",
        calibration={"emphasize": ["impact", "autonomy"], "skip": ["code"]},
    )

    with (
        patch(
            "agents.demo_pipeline.research._gather_component_registry",
            return_value="components",
        ),
        patch(
            "agents.health_monitor.run_checks",
            side_effect=mock_run_checks,
        ),
        patch(
            "agents.demo_pipeline.research._gather_profile_facts_rich",
            return_value="facts",
        ),
        patch(
            "agents.demo_pipeline.research._gather_briefing_stats",
            return_value="stats",
        ),
        patch(
            "agents.demo_pipeline.research._gather_operator_philosophy",
            return_value="philosophy",
        ),
        patch(
            "agents.demo_pipeline.research._gather_domain_literature",
            return_value="literature",
        ),
    ):
        result = await gather_research(
            scope="test",
            audience="family",
            audience_dossier=dossier,
        )

    assert "## Audience Profile" in result
    assert "**Name**: Sarah" in result
    assert "Non-technical" in result
    assert "impact, autonomy" in result


def test_format_audience_dossier():
    """Correct formatting of audience dossier."""
    dossier = AudienceDossier(
        key="my boss",
        archetype="leadership",
        name="Alex",
        context="VP of Engineering, cares about ROI",
        calibration={
            "emphasize": ["cost savings", "reliability"],
            "skip": ["implementation details"],
        },
    )

    result = _format_audience_dossier(dossier)

    assert "**Name**: Alex" in result
    assert "**Context**: VP of Engineering, cares about ROI" in result
    assert "**Emphasize**: cost savings, reliability" in result
    assert "**Skip**: implementation details" in result


@pytest.mark.asyncio
async def test_research_quality_signal_on_failures():
    """Failed sources should be reported via on_progress."""
    progress_messages: list[str] = []

    with (
        patch(
            "agents.demo_pipeline.research._gather_component_registry",
            return_value="components",
        ),
        patch(
            "agents.health_monitor.run_checks",
            side_effect=ConnectionError("down"),
        ),
        patch(
            "agents.demo_pipeline.research._gather_profile_facts_rich",
            side_effect=Exception("Qdrant unreachable"),
        ),
        patch(
            "agents.demo_pipeline.research._gather_briefing_stats",
            return_value="",  # empty = counted as failed
        ),
        patch(
            "agents.demo_pipeline.research._gather_operator_philosophy",
            return_value="philosophy",
        ),
        patch(
            "agents.demo_pipeline.research._gather_domain_literature",
            return_value="literature",
        ),
    ):
        await gather_research(
            scope="test",
            audience="family",
            on_progress=progress_messages.append,
        )

    # Should report failed sources
    summary = [m for m in progress_messages if "Missing:" in m]
    assert len(summary) == 1
    assert "health_summary" in summary[0]
    assert "profile_facts_rich" in summary[0]
    assert "briefing_stats" in summary[0]
    # Should report partial success count
    assert "2/" in summary[0] or "sources" in summary[0]


def test_backward_compat_audience_sources():
    """Old source names (profile_facts, component_registry) still work in dispatch."""
    # Verify the old _gather_profile_facts function still exists and is importable
    from agents.demo_pipeline.research import _gather_profile_facts

    assert callable(_gather_profile_facts)

    # Verify old source names still have section headers
    assert "profile_facts" in _SECTION_HEADERS
    assert "component_registry" in _SECTION_HEADERS


# ── New research source tests ─────────────────────────────────────────────


def test_gather_architecture_rag_filters_by_source():
    """Verify architecture RAG uses source field with MatchText filter."""

    def make_point(pid, source, text):
        p = MagicMock()
        p.id = pid
        p.payload = {"source": source, "text": text}
        return p

    call_count = 0

    def mock_query_points(collection_name, query, query_filter, limit):
        nonlocal call_count
        call_count += 1
        # Verify correct collection and filter
        assert collection_name == "documents"
        assert query_filter is not None
        # First query returns results, rest empty
        result = MagicMock()
        if call_count == 1:
            result.points = [
                make_point(
                    "p1",
                    "/home/user/documents/rag-sources/hapaxromana/CLAUDE.md",
                    "Architecture overview",
                ),
                make_point(
                    "p2",
                    "/home/user/documents/rag-sources/hapaxromana/agent-architecture.md",
                    "Agent tiers",
                ),
            ]
        else:
            result.points = [
                make_point(
                    "p1",
                    "/home/user/documents/rag-sources/hapaxromana/CLAUDE.md",
                    "Architecture overview",
                ),  # dupe
            ]
        return result

    mock_client = MagicMock()
    mock_client.query_points = mock_query_points

    with (
        patch("shared.config.embed", return_value=[0.1] * 768),
        patch("shared.config.get_qdrant", return_value=mock_client),
    ):
        result = _gather_architecture_rag("agent architecture")

    assert "Architecture overview" in result
    assert "Agent tiers" in result
    # Should have been called 3 times (3 queries)
    assert call_count == 3
    # Should include filename labels
    assert "[CLAUDE.md]" in result
    assert "[agent-architecture.md]" in result


def test_gather_architecture_rag_graceful_on_failure():
    """Returns empty string when Qdrant is unreachable."""
    with (
        patch("shared.config.embed", side_effect=ConnectionError("down")),
        patch("shared.config.get_qdrant", side_effect=ConnectionError("down")),
    ):
        result = _gather_architecture_rag("test")
    assert result == ""


def test_gather_design_plans_matches_scope(tmp_path: Path):
    """Verify scope-based matching and sorting of plan files."""
    plans_dir = tmp_path / "docs" / "plans"
    plans_dir.mkdir(parents=True)

    # Create test plans
    (plans_dir / "2026-03-04-demo-generator-design.md").write_text(
        "# Demo Generator Design\nDesign details here."
    )
    (plans_dir / "2026-03-04-corporate-boundary-design.md").write_text(
        "# Corporate Boundary\nBoundary details."
    )
    (plans_dir / "2026-03-01-old-plan.md").write_text("# Old Plan\nOld stuff.")

    with patch("agents.demo_pipeline.research.HAPAXROMANA_DIR", tmp_path):
        result = _gather_design_plans("demo generator design")

    assert "Demo Generator Design" in result
    # More relevant plan should appear
    assert "demo-generator-design.md" in result


def test_gather_design_plans_missing_dir(tmp_path: Path):
    """Returns empty when plans directory doesn't exist."""
    with patch("agents.demo_pipeline.research.HAPAXROMANA_DIR", tmp_path):
        result = _gather_design_plans("test")
    assert result == ""


def test_gather_domain_literature_loads_corpus(tmp_path: Path):
    """Verify domain literature loads and filters by scope."""
    corpus_dir = tmp_path / "domain_corpus"
    corpus_dir.mkdir()

    (corpus_dir / "executive-function-accommodation.md").write_text(
        "---\ntopic: executive-function\nkeywords: [ADHD, executive function]\nrelevance: [system-rationale]\nlast_reviewed: 2026-03-05\n---\n# Executive Function\nContent about EF."
    )
    (corpus_dir / "cognitive-load-theory.md").write_text(
        "---\ntopic: cognitive-load\nkeywords: [sweller, intrinsic load]\nrelevance: [interface-design]\nlast_reviewed: 2026-03-05\n---\n# Cognitive Load\nContent about CLT."
    )
    (corpus_dir / "llm-interaction-design.md").write_text(
        "---\ntopic: llm-interaction\nkeywords: [human-AI, agentic UX]\nrelevance: [agent-design]\nlast_reviewed: 2026-03-05\n---\n# LLM Interaction\nContent about interaction."
    )

    # Patch Path(__file__).parent to point to tmp_path
    with patch("agents.demo_pipeline.research.Path") as mock_path_cls:
        # Need __file__.parent to return tmp_path
        mock_file = MagicMock()
        mock_file.parent = tmp_path
        mock_path_cls.__call__ = Path  # Keep regular Path() working
        mock_path_cls.return_value = mock_file
        # This won't work cleanly — let's use a different approach
        pass

    # Better approach: patch the corpus dir path directly
    import agents.demo_pipeline.research as research_mod

    try:
        # Temporarily redirect __file__ parent
        with patch.object(research_mod, "__file__", str(tmp_path / "research.py")):
            result = _gather_domain_literature("executive function ADHD")
    finally:
        pass

    # Foundational files should always be included
    assert "Executive Function" in result
    assert "Cognitive Load" in result
    # Frontmatter should be stripped
    assert "---" not in result or "topic:" not in result


def test_gather_domain_literature_missing_dir():
    """Returns empty when corpus directory doesn't exist."""
    import agents.demo_pipeline.research as research_mod

    with patch.object(research_mod, "__file__", "/nonexistent/path/research.py"):
        result = _gather_domain_literature("test")
    assert result == ""


@pytest.mark.asyncio
async def test_gather_live_system_state_graceful():
    """Returns empty string when introspect and Qdrant both fail."""
    with (
        patch("agents.introspect.generate_manifest", side_effect=ConnectionError("down")),
        patch("shared.config.get_qdrant", side_effect=ConnectionError("down")),
    ):
        from agents.demo_pipeline.research import _gather_live_system_state

        result = await _gather_live_system_state()
    # Should not raise, returns empty or partial
    assert isinstance(result, str)


def test_gather_audit_findings(tmp_path: Path):
    """Reads holistic audit file."""
    audit_dir = tmp_path / "docs" / "audit" / "v2"
    audit_dir.mkdir(parents=True)
    (audit_dir / "10-holistic.md").write_text(
        "# Holistic Audit\n\nKey finding: system is well-integrated."
    )

    with patch("agents.demo_pipeline.research.HAPAXROMANA_DIR", tmp_path):
        result = _gather_audit_findings()

    assert "Holistic Audit" in result
    assert "well-integrated" in result


def test_gather_audit_findings_missing(tmp_path: Path):
    """Returns empty when audit file doesn't exist."""
    with patch("agents.demo_pipeline.research.HAPAXROMANA_DIR", tmp_path):
        result = _gather_audit_findings()
    assert result == ""


def test_audience_sources_include_new_sources():
    """Verify new sources are in the correct audience lists."""
    # technical-peer should have all new sources
    tp = AUDIENCE_SOURCES["technical-peer"]
    assert "architecture_rag" in tp
    assert "design_plans" in tp
    assert "live_system_state" in tp
    assert "domain_literature" in tp
    assert "audit_findings" in tp

    # leadership should have architecture + domain + audit but not live_system_state
    lead = AUDIENCE_SOURCES["leadership"]
    assert "architecture_rag" in lead
    assert "design_plans" in lead
    assert "domain_literature" in lead
    assert "audit_findings" in lead
    assert "live_system_state" not in lead

    # family should have domain_literature
    fam = AUDIENCE_SOURCES["family"]
    assert "domain_literature" in fam
    assert "architecture_rag" not in fam

    # team-member should have domain_literature
    tm = AUDIENCE_SOURCES["team-member"]
    assert "domain_literature" in tm


def test_section_headers_complete():
    """Every source key in AUDIENCE_SOURCES values has a section header."""
    all_sources: set[str] = set()
    for sources in AUDIENCE_SOURCES.values():
        all_sources.update(sources)

    for source in all_sources:
        assert source in _SECTION_HEADERS, f"Missing section header for '{source}'"


# ── Workflow Corpus Registry ───────────────────────────────────────────────


class TestWorkflowCorpus:
    """Tests for profiles/workflow-registry.yaml canonical workflow definitions."""

    REGISTRY_PATH = Path(__file__).resolve().parent.parent / "profiles" / "workflow-registry.yaml"

    def test_load_workflow_registry(self):
        """Load YAML and verify each workflow has label, trigger, steps (>=2), components."""
        assert self.REGISTRY_PATH.exists(), f"Missing {self.REGISTRY_PATH}"
        data = yaml.safe_load(self.REGISTRY_PATH.read_text())

        assert "workflows" in data
        workflows = data["workflows"]
        assert len(workflows) >= 1, "Registry must contain at least one workflow"

        for wf_id, wf in workflows.items():
            assert "label" in wf, f"{wf_id} missing 'label'"
            assert "trigger" in wf, f"{wf_id} missing 'trigger'"
            assert "steps" in wf, f"{wf_id} missing 'steps'"
            assert "components" in wf, f"{wf_id} missing 'components'"
            assert isinstance(wf["steps"], list), f"{wf_id} steps must be a list"
            assert len(wf["steps"]) >= 2, f"{wf_id} must have >= 2 steps, got {len(wf['steps'])}"
            assert isinstance(wf["components"], list), f"{wf_id} components must be a list"
            assert len(wf["components"]) >= 1, f"{wf_id} must have >= 1 component"

    def test_load_workflow_registry_all_steps_are_strings(self):
        """Verify all step entries are strings."""
        data = yaml.safe_load(self.REGISTRY_PATH.read_text())

        for wf_id, wf in data["workflows"].items():
            for i, step in enumerate(wf["steps"]):
                assert isinstance(step, str), (
                    f"{wf_id} step[{i}] is {type(step).__name__}, expected str"
                )

    def test_load_workflow_registry_all_components_are_strings(self):
        """Verify all component entries are strings."""
        data = yaml.safe_load(self.REGISTRY_PATH.read_text())

        for wf_id, wf in data["workflows"].items():
            for i, comp in enumerate(wf["components"]):
                assert isinstance(comp, str), (
                    f"{wf_id} component[{i}] is {type(comp).__name__}, expected str"
                )


# ── Workflow Injection into Research ───────────────────────────────────────


class TestWorkflowInResearch:
    """Tests for _gather_workflow_patterns injecting workflow corpus into research context."""

    def test_gather_workflow_patterns_returns_content(self):
        """_gather_workflow_patterns returns formatted workflow descriptions."""
        from agents.demo_pipeline.research import _gather_workflow_patterns

        result = _gather_workflow_patterns("full system")
        assert "Morning Briefing" in result
        # Check formatted output has numbered steps
        assert "1." in result

    def test_gather_workflow_patterns_filters_by_scope(self):
        """Scope keyword narrows which workflows are returned."""
        from agents.demo_pipeline.research import _gather_workflow_patterns

        result = _gather_workflow_patterns("health monitoring")
        assert "Health Monitoring" in result

    def test_gather_workflow_patterns_missing_file(self):
        """Returns empty string if registry file is missing."""
        import agents.demo_pipeline.research as mod
        from agents.demo_pipeline.research import _gather_workflow_patterns

        original = mod.WORKFLOW_REGISTRY_PATH
        mod.WORKFLOW_REGISTRY_PATH = Path("/nonexistent/path.yaml")
        try:
            result = _gather_workflow_patterns("full system")
            assert result == ""
        finally:
            mod.WORKFLOW_REGISTRY_PATH = original

    def test_workflow_patterns_in_all_audiences(self):
        """workflow_patterns source is present in every audience's source list."""
        for audience, sources in AUDIENCE_SOURCES.items():
            assert "workflow_patterns" in sources, (
                f"workflow_patterns missing from {audience} audience sources"
            )

    def test_workflow_patterns_has_section_header(self):
        """workflow_patterns has a section header in _SECTION_HEADERS."""
        assert "workflow_patterns" in _SECTION_HEADERS
        assert "Workflow" in _SECTION_HEADERS["workflow_patterns"]

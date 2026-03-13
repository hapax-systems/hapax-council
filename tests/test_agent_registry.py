"""Tests for shared/agent_registry.py — agent manifest loading and queries."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from shared.agent_registry import (
    AgentCategory,
    AutonomyTier,
    ScheduleType,
    get_registry,
    load_manifests,
)

MANIFESTS_DIR = Path(__file__).resolve().parent.parent / "agents" / "manifests"


# ── Manifest loading ─────────────────────────────────────────────────────────


class TestManifestLoading:
    def test_loads_all_manifests(self):
        agents = load_manifests()
        assert len(agents) >= 26, f"Expected >=26 manifests, got {len(agents)}"

    def test_all_have_required_fields(self):
        agents = load_manifests()
        for agent_id, m in agents.items():
            assert m.id == agent_id
            assert m.name, f"{agent_id} missing name"
            assert m.purpose, f"{agent_id} missing purpose"
            assert m.category in AgentCategory
            assert m.schedule.type in ScheduleType

    def test_ids_match_filenames(self):
        for path in sorted(MANIFESTS_DIR.glob("*.yaml")):
            agents = load_manifests()
            stem = path.stem
            assert stem in agents, f"Manifest {path.name} id '{stem}' not in loaded agents"

    def test_no_duplicate_ids(self):
        import yaml

        ids = []
        for path in sorted(MANIFESTS_DIR.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            ids.append(data["id"])
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {[x for x in ids if ids.count(x) > 1]}"


# ── Schema validation ────────────────────────────────────────────────────────


class TestSchemaValidation:
    def test_valid_categories(self):
        agents = load_manifests()
        valid = {c.value for c in AgentCategory}
        for agent_id, m in agents.items():
            assert m.category.value in valid, f"{agent_id} has invalid category {m.category}"

    def test_valid_autonomy_tiers(self):
        agents = load_manifests()
        for agent_id, m in agents.items():
            assert m.autonomy in AutonomyTier, f"{agent_id} has invalid autonomy {m.autonomy}"

    def test_service_tiers_in_range(self):
        agents = load_manifests()
        for agent_id, m in agents.items():
            assert 0 <= m.service_tier <= 3, (
                f"{agent_id} service_tier {m.service_tier} out of range"
            )

    def test_axiom_bindings_reference_known_axioms(self):
        known_axioms = {
            "single_user",
            "executive_function",
            "corporate_boundary",
            "interpersonal_transparency",
            "management_governance",
        }
        agents = load_manifests()
        for agent_id, m in agents.items():
            for binding in m.axiom_bindings:
                assert binding.axiom_id in known_axioms, (
                    f"{agent_id} binds to unknown axiom {binding.axiom_id}"
                )

    def test_schedule_timers_have_units(self):
        agents = load_manifests()
        for agent_id, m in agents.items():
            if m.schedule.type == ScheduleType.TIMER:
                assert m.schedule.systemd_unit, f"{agent_id} has timer schedule but no systemd_unit"


# ── Registry queries ─────────────────────────────────────────────────────────


class TestRegistryQueries:
    @pytest.fixture()
    def registry(self):
        return get_registry()

    def test_get_agent(self, registry):
        hm = registry.get_agent("health_monitor")
        assert hm is not None
        assert hm.name == "Health Monitor"

    def test_get_nonexistent(self, registry):
        assert registry.get_agent("nonexistent_agent") is None

    def test_list_agents_sorted(self, registry):
        agents = registry.list_agents()
        ids = [a.id for a in agents]
        assert ids == sorted(ids)

    def test_agents_by_category(self, registry):
        sync_agents = registry.agents_by_category(AgentCategory.SYNC)
        assert (
            len(sync_agents) >= 6
        )  # gdrive, gcalendar, gmail, youtube, chrome, obsidian, claude_code
        for a in sync_agents:
            assert a.category == AgentCategory.SYNC

    def test_agents_for_capability(self, registry):
        rag = registry.agents_for_capability("rag_retrieval")
        ids = {a.id for a in rag}
        assert "research" in ids

    def test_agents_by_autonomy(self, registry):
        advisory = registry.agents_by_autonomy(AutonomyTier.ADVISORY)
        assert len(advisory) >= 1
        for a in advisory:
            assert a.autonomy == AutonomyTier.ADVISORY

    def test_agents_by_service_tier(self, registry):
        critical = registry.agents_by_service_tier(0)
        assert any(a.id == "health_monitor" for a in critical)

    def test_dependents_of(self, registry):
        deps = registry.dependents_of("ingest")
        dep_ids = {a.id for a in deps}
        assert "knowledge_maint" in dep_ids

    def test_raci_for_task(self, registry):
        raci = registry.raci_for_task("daily_briefing")
        assert "briefing" in raci.get("responsible", [])

    def test_agents_bound_to_axiom(self, registry):
        ef_agents = registry.agents_bound_to_axiom("executive_function")
        assert len(ef_agents) >= 5  # many agents bind to executive_function


# ── Inline manifest parsing ──────────────────────────────────────────────────


class TestInlineParsing:
    def test_minimal_manifest(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            id: test_agent
            name: Test Agent
            category: observability
            purpose: A test agent for unit testing.
            schedule:
              type: on-demand
        """)
        (tmp_path / "test_agent.yaml").write_text(yaml_content)
        agents = load_manifests(tmp_path)
        assert "test_agent" in agents
        m = agents["test_agent"]
        assert m.name == "Test Agent"
        assert m.category == AgentCategory.OBSERVABILITY
        assert m.autonomy == AutonomyTier.FULL  # default
        assert m.service_tier == 2  # default

    def test_invalid_yaml_skipped(self, tmp_path):
        (tmp_path / "bad.yaml").write_text("id: [invalid\n")
        agents = load_manifests(tmp_path)
        assert len(agents) == 0

    def test_missing_required_field_skipped(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            id: incomplete
            name: Incomplete Agent
        """)
        (tmp_path / "incomplete.yaml").write_text(yaml_content)
        agents = load_manifests(tmp_path)
        assert len(agents) == 0

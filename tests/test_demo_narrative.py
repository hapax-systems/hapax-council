"""Tests for narrative framework selection and planning constraints."""
from agents.demo_pipeline.narrative import (
    load_style_guide, select_framework, get_duration_constraints,
    format_planning_context, FRAMEWORKS, AUDIENCE_FRAMEWORK,
)


class TestSelectFramework:
    def test_family_gets_guided_tour(self):
        fw = select_framework("family")
        assert fw["name"] == "Guided Tour"

    def test_leadership_gets_psb(self):
        fw = select_framework("leadership")
        assert fw["name"] == "Problem → Solution → Benefit"

    def test_peers_get_design_rationale(self):
        fw = select_framework("technical-peer")
        assert fw["name"] == "Design Rationale"

    def test_team_gets_operational_cadence(self):
        fw = select_framework("team-member")
        assert fw["name"] == "Operational Cadence"

    def test_unknown_defaults_to_design_rationale(self):
        fw = select_framework("stranger")
        assert fw["name"] == "Design Rationale"

class TestDurationConstraints:
    def test_3_minute_demo(self):
        c = get_duration_constraints(180)
        assert c["scenes"] == (3, 5)
        assert c["depth"] == "concise but complete narration"

    def test_10_minute_demo(self):
        c = get_duration_constraints(600)
        assert c["scenes"] == (10, 14)

    def test_15_minute_demo(self):
        c = get_duration_constraints(900)
        assert c["scenes"] == (12, 16)

    def test_20_minute_demo(self):
        c = get_duration_constraints(1200)
        assert c["scenes"] == (14, 18)

    def test_beyond_max_uses_longest(self):
        c = get_duration_constraints(3600)
        assert c["scenes"] == (14, 18)

class TestLoadStyleGuide:
    def test_loads_from_default_path(self):
        guide = load_style_guide()
        assert "voice" in guide
        assert "avoid" in guide
        assert "embrace" in guide

    def test_missing_file_returns_empty(self, tmp_path):
        guide = load_style_guide(tmp_path / "nonexistent.yaml")
        assert guide == {}

class TestFormatPlanningContext:
    def test_contains_all_sections(self):
        guide = load_style_guide()
        fw = select_framework("leadership")
        dc = get_duration_constraints(600)
        text = format_planning_context(guide, fw, dc, 600)
        assert "Presenter Style Guide" in text
        assert "Narrative Framework" in text
        assert "Duration Constraints" in text
        assert "10 minutes" in text

    def test_includes_avoid_list(self):
        guide = load_style_guide()
        fw = select_framework("family")
        dc = get_duration_constraints(180)
        text = format_planning_context(guide, fw, dc, 180)
        assert "AVOID" in text

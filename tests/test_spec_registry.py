"""Tests for the spec registry loader."""

from __future__ import annotations

from shared.spec_registry import get_spec, load_specs, load_systems, spec_summary


class TestSpecRegistry:
    def test_loads_systems(self):
        systems = load_systems()
        assert len(systems) >= 9  # original 9 + consent + latency

    def test_loads_specs(self):
        specs = load_specs()
        assert len(specs) >= 40  # substantial registry

    def test_filter_by_tier(self):
        v0 = load_specs(tier="V0")
        assert all(s.tier == "V0" for s in v0)
        assert len(v0) >= 5  # perception, stimmung, infra, embedding, consent

    def test_filter_by_system(self):
        stimmung = load_specs(system_id="stimmung")
        assert all(s.system_id == "stimmung" for s in stimmung)
        assert len(stimmung) >= 5

    def test_get_spec_by_id(self):
        spec = get_spec("cn-governor-veto-001")
        assert spec is not None
        assert spec.tier == "V0"
        assert "interpersonal_transparency" in spec.text

    def test_get_spec_missing(self):
        assert get_spec("nonexistent-spec") is None

    def test_summary(self):
        summary = spec_summary()
        assert summary["systems"] >= 9
        assert summary["total_specs"] >= 40
        assert "V0" in summary["by_tier"]
        assert "V1" in summary["by_tier"]

    def test_consent_system_exists(self):
        systems = load_systems()
        consent = [s for s in systems if s.id == "consent"]
        assert len(consent) == 1
        assert len(consent[0].specs) >= 4

    def test_latency_system_exists(self):
        systems = load_systems()
        latency = [s for s in systems if s.id == "latency"]
        assert len(latency) == 1
        assert len(latency[0].specs) >= 3

    def test_rule_count_updated(self):
        spec = get_spec("re-rule-count-001")
        assert spec is not None
        assert "14 rules" in spec.text
        assert "phone-health-summary" in "\n".join(spec.properties)

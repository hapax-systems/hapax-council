"""Tests for carrier fact intake — parsing, validation, and registry integration.

Tests the bridge from filesystem events (carrier-flagged files) to the
CarrierRegistry, implementing DD-26.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from shared.governance.carrier import CarrierRegistry
from shared.governance.carrier_intake import intake_carrier_fact, parse_carrier_fact
from shared.governance.consent_label import ConsentLabel


def _write_carrier_file(
    tmpdir: Path,
    name: str = "test.md",
    source_domain: str = "health_monitor",
    carrier_value: str = "resting HR elevated",
    carrier: bool = True,
    extra_frontmatter: str = "",
) -> Path:
    """Write a carrier-flagged markdown file for testing."""
    path = tmpdir / name
    fm_lines = []
    if carrier:
        fm_lines.append("carrier: true")
    if source_domain:
        fm_lines.append(f"source_domain: {source_domain}")
    if carrier_value:
        fm_lines.append(f'carrier_value: "{carrier_value}"')
    if extra_frontmatter:
        fm_lines.append(extra_frontmatter)
    fm = "\n".join(fm_lines)
    path.write_text(f"---\n{fm}\n---\nBody text here.\n")
    return path


class TestParseCarrierFact(unittest.TestCase):
    """parse_carrier_fact extracts CarrierFact from frontmatter."""

    def test_valid_carrier_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_carrier_file(Path(tmpdir))
            fact = parse_carrier_fact(path, now=100.0)
            assert fact is not None
            assert fact.source_domain == "health_monitor"
            assert fact.labeled.value == "resting HR elevated"
            assert fact.observation_count == 1
            assert fact.first_seen == 100.0

    def test_missing_carrier_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_carrier_file(Path(tmpdir), carrier=False)
            fact = parse_carrier_fact(path)
            assert fact is None

    def test_missing_source_domain(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_carrier_file(Path(tmpdir), source_domain="")
            fact = parse_carrier_fact(path)
            assert fact is None

    def test_missing_carrier_value_uses_body(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.md"
            path.write_text(
                "---\ncarrier: true\nsource_domain: drift\n---\nThe body is the value.\n"
            )
            fact = parse_carrier_fact(path)
            assert fact is not None
            assert fact.labeled.value == "The body is the value."

    def test_consent_label_extracted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            extra = 'consent_label:\n  policies:\n    - owner: "alice"\n      readers: ["bob"]'
            path = _write_carrier_file(Path(tmpdir), extra_frontmatter=extra)
            fact = parse_carrier_fact(path)
            assert fact is not None
            expected = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
            assert fact.consent_label == expected

    def test_provenance_extracted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            extra = 'provenance: ["contract-1", "contract-2"]'
            path = _write_carrier_file(Path(tmpdir), extra_frontmatter=extra)
            fact = parse_carrier_fact(path)
            assert fact is not None
            assert fact.provenance == frozenset({"contract-1", "contract-2"})

    def test_no_consent_label_defaults_to_bottom(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_carrier_file(Path(tmpdir))
            fact = parse_carrier_fact(path)
            assert fact is not None
            assert fact.consent_label == ConsentLabel.bottom()


class TestIntakeCarrierFact(unittest.TestCase):
    """intake_carrier_fact validates and registers carrier facts."""

    def _make_registry(self, principal: str = "operator", capacity: int = 3) -> CarrierRegistry:
        reg = CarrierRegistry()
        reg.register(principal, capacity)
        return reg

    def test_valid_intake(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_carrier_file(Path(tmpdir))
            reg = self._make_registry()
            result = intake_carrier_fact(path, "operator", reg, now=1.0)
            assert result.accepted
            assert result.source_domain == "health_monitor"
            assert len(reg.facts("operator")) == 1

    def test_invalid_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_carrier_file(Path(tmpdir), carrier=False)
            reg = self._make_registry()
            result = intake_carrier_fact(path, "operator", reg)
            assert not result.accepted
            assert result.rejection_reason == "invalid carrier file"

    def test_consent_flow_violation_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # File has a restrictive label (alice+bob)
            extra = 'consent_label:\n  policies:\n    - owner: "alice"\n      readers: ["bob"]'
            path = _write_carrier_file(Path(tmpdir), extra_frontmatter=extra)
            reg = self._make_registry()
            # Require bottom (public) — alice-restricted cannot flow to public
            required = ConsentLabel.bottom()
            result = intake_carrier_fact(path, "operator", reg, required_label=required)
            assert not result.accepted
            assert result.rejection_reason == "consent label flow violation"

    def test_consent_flow_allowed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            extra = 'consent_label:\n  policies:\n    - owner: "alice"\n      readers: ["bob"]'
            path = _write_carrier_file(Path(tmpdir), extra_frontmatter=extra)
            reg = self._make_registry()
            required = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
            result = intake_carrier_fact(path, "operator", reg, required_label=required)
            assert result.accepted

    def test_unregistered_principal_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_carrier_file(Path(tmpdir))
            reg = CarrierRegistry()  # No principals registered
            result = intake_carrier_fact(path, "unknown", reg)
            assert not result.accepted
            assert "not registered" in result.rejection_reason

    def test_capacity_enforcement(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = self._make_registry(capacity=1)
            # First fact — accepted
            p1 = _write_carrier_file(Path(tmpdir), name="f1.md", source_domain="d1")
            r1 = intake_carrier_fact(p1, "operator", reg, now=1.0)
            assert r1.accepted

            # Second fact (different domain, low observation) — rejected (capacity 1, no displacement)
            p2 = _write_carrier_file(Path(tmpdir), name="f2.md", source_domain="d2")
            r2 = intake_carrier_fact(p2, "operator", reg, now=2.0)
            assert not r2.accepted
            assert r2.displacement is not None
            assert "insufficient frequency" in r2.displacement.reason

    def test_duplicate_updates_observation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = self._make_registry()
            path = _write_carrier_file(Path(tmpdir))
            intake_carrier_fact(path, "operator", reg, now=1.0)
            intake_carrier_fact(path, "operator", reg, now=2.0)
            facts = reg.facts("operator")
            assert len(facts) == 1
            assert facts[0].observation_count == 2

    def test_displacement_result_included(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = self._make_registry()
            path = _write_carrier_file(Path(tmpdir))
            result = intake_carrier_fact(path, "operator", reg, now=1.0)
            assert result.displacement is not None
            assert result.displacement.inserted
            assert result.displacement.reason == "slot available"


class TestCarrierIntakeReactiveRule(unittest.TestCase):
    """Test the reactive rule filter and produce functions.

    Uses importlib to import reactive_rules directly, bypassing
    cockpit.engine.__init__ which requires watchdog (optional dep).
    """

    @classmethod
    def _import_rules(cls) -> Any:
        import importlib

        return importlib.import_module("cockpit.engine.reactive_rules")

    def _make_event(self, frontmatter: dict | None = None) -> Any:
        from datetime import datetime

        from cockpit.engine.models import ChangeEvent

        return ChangeEvent(
            path=Path("/data/test.md"),
            event_type="created",
            doc_type=None,
            frontmatter=frontmatter,
            timestamp=datetime.now(),
        )

    def test_filter_matches_carrier_frontmatter(self):
        rules = self._import_rules()
        event = self._make_event({"carrier": True, "source_domain": "test"})
        assert rules._carrier_intake_filter(event)

    def test_filter_rejects_non_carrier(self):
        rules = self._import_rules()
        event = self._make_event({"type": "profile-fact"})
        assert not rules._carrier_intake_filter(event)

    def test_filter_rejects_none_frontmatter(self):
        rules = self._import_rules()
        event = self._make_event(None)
        assert not rules._carrier_intake_filter(event)

    def test_produce_extracts_principal(self):
        rules = self._import_rules()
        event = self._make_event({"carrier": True, "carrier_principal": "agent-scout"})
        actions = rules._carrier_intake_produce(event)
        assert len(actions) == 1
        assert actions[0].args["principal_id"] == "agent-scout"

    def test_produce_defaults_to_operator(self):
        rules = self._import_rules()
        event = self._make_event({"carrier": True})
        actions = rules._carrier_intake_produce(event)
        assert actions[0].args["principal_id"] == "operator"


class TestCarrierIntakeHypothesis(unittest.TestCase):
    """Property-based tests for carrier intake."""

    @given(
        domain=st.text(min_size=1, max_size=10, alphabet="abcdefghij"),
        value=st.text(
            min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))
        ),
    )
    def test_parsed_fact_preserves_domain_and_value(self, domain: str, value: str):
        """parse_carrier_fact preserves source_domain and carrier_value."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_carrier_file(Path(tmpdir), source_domain=domain, carrier_value=value)
            fact = parse_carrier_fact(path, now=1.0)
            assert fact is not None
            assert fact.source_domain == domain
            assert fact.labeled.value == value

    @given(
        domain=st.text(min_size=1, max_size=10, alphabet="abcdefghij"),
        value=st.text(
            min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))
        ),
    )
    def test_intake_accepted_iff_registry_has_capacity(self, domain: str, value: str):
        """Valid carrier fact is accepted when registry has capacity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_carrier_file(Path(tmpdir), source_domain=domain, carrier_value=value)
            reg = CarrierRegistry()
            reg.register("op", 5)
            result = intake_carrier_fact(path, "op", reg, now=1.0)
            assert result.accepted
            assert len(reg.facts("op")) == 1


if __name__ == "__main__":
    unittest.main()

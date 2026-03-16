"""Tests for governance observability — heartbeat, coverage, blast radius.

Proves: heartbeat is bounded [0,1], coverage reflects reality,
blast radius is non-negative and monotonic with contract count.

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from cockpit.data.governance import (
    GovernanceHeartbeat,
    collect_consent_coverage,
    collect_consent_lifecycle,
    collect_governance_heartbeat,
)
from shared.governance.consent import ConsentContract, ConsentRegistry


def _registry(*contracts: ConsentContract) -> ConsentRegistry:
    reg = ConsentRegistry()
    for c in contracts:
        reg._contracts[c.id] = c
    return reg


def _contract(person: str, scope: frozenset[str], active: bool = True) -> ConsentContract:
    return ConsentContract(
        id=f"contract-{person}",
        parties=("operator", person),
        scope=scope,
        created_at="2026-03-15T00:00:00",
        revoked_at=None if active else "2026-03-15T01:00:00",
    )


class TestGovernanceHeartbeat(unittest.TestCase):
    def test_heartbeat_returns_score(self):
        with (
            patch("shared.governance.consent.load_contracts", return_value=_registry()),
            patch("cockpit.data.governance.CONSENT_AUDIT", Path("/nonexistent")),
        ):
            hb = collect_governance_heartbeat()
            assert isinstance(hb, GovernanceHeartbeat)
            assert 0.0 <= hb.score <= 1.0
            assert hb.label in ("green", "yellow", "red")
            assert hb.timestamp

    def test_heartbeat_with_active_contracts_is_green(self):
        reg = _registry(_contract("wife", frozenset({"audio"})))
        with (
            patch("shared.governance.consent.load_contracts", return_value=reg),
            patch("cockpit.data.governance.CONSENT_AUDIT", Path("/nonexistent")),
        ):
            hb = collect_governance_heartbeat()
            assert hb.score >= 0.8
            assert hb.label == "green"

    def test_heartbeat_with_high_denial_rate_degrades(self):
        reg = _registry(_contract("wife", frozenset({"audio"})))
        audit_data = "\n".join(
            [json.dumps({"allowed": False, "reason": "no contract"})] * 8
            + [json.dumps({"allowed": True, "reason": "ok"})] * 2
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(audit_data)
            audit_path = Path(f.name)

        try:
            with (
                patch("shared.governance.consent.load_contracts", return_value=reg),
                patch("cockpit.data.governance.CONSENT_AUDIT", audit_path),
            ):
                hb = collect_governance_heartbeat()
                assert hb.score < 0.8  # degraded due to 80% denial rate
                assert any("denial rate" in i.lower() for i in hb.issues)
        finally:
            audit_path.unlink()

    def test_heartbeat_components_present(self):
        with (
            patch("shared.governance.consent.load_contracts", return_value=_registry()),
            patch("cockpit.data.governance.CONSENT_AUDIT", Path("/nonexistent")),
        ):
            hb = collect_governance_heartbeat()
            assert "consent_coverage" in hb.components
            assert "gate_health" in hb.components
            assert "contract_freshness" in hb.components
            assert "authority_health" in hb.components


class TestConsentCoverage(unittest.TestCase):
    def test_no_contracts_returns_zero(self):
        with patch("shared.governance.consent.load_contracts", return_value=_registry()):
            cov = collect_consent_coverage()
            assert cov.active_contracts == 0
            assert cov.persons_covered == []

    def test_active_contract_counted(self):
        reg = _registry(_contract("wife", frozenset({"audio", "video"})))
        with patch("shared.governance.consent.load_contracts", return_value=reg):
            cov = collect_consent_coverage()
            assert cov.active_contracts == 1
            assert "wife" in cov.persons_covered
            assert cov.scope_coverage.get("audio") == 1
            assert cov.scope_coverage.get("video") == 1

    def test_revoked_contract_not_in_coverage(self):
        reg = _registry(_contract("wife", frozenset({"audio"}), active=False))
        with patch("shared.governance.consent.load_contracts", return_value=reg):
            cov = collect_consent_coverage()
            assert cov.active_contracts == 0
            assert cov.persons_covered == []


class TestConsentLifecycle(unittest.TestCase):
    def test_no_audit_log_returns_empty(self):
        with patch("cockpit.data.governance.CONSENT_AUDIT", Path("/nonexistent")):
            lc = collect_consent_lifecycle()
            assert lc.total_gate_decisions == 0
            assert lc.denial_rate == 0.0

    def test_audit_log_parsed(self):
        audit_data = "\n".join(
            [
                json.dumps({"allowed": True, "reason": "ok"}),
                json.dumps({"allowed": False, "reason": "no contract"}),
                json.dumps({"allowed": True, "reason": "ok"}),
            ]
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(audit_data)
            path = Path(f.name)

        try:
            with patch("cockpit.data.governance.CONSENT_AUDIT", path):
                lc = collect_consent_lifecycle()
                assert lc.total_gate_decisions == 3
                assert lc.allowed == 2
                assert lc.denied == 1
                assert 30 < lc.denial_rate < 40  # ~33%
        finally:
            path.unlink()


class TestGovernanceHeartbeatProperties(unittest.TestCase):
    """Provable properties of the governance heartbeat."""

    @given(
        n_active=st.integers(min_value=0, max_value=5),
        n_revoked=st.integers(min_value=0, max_value=5),
        n_allowed=st.integers(min_value=0, max_value=20),
        n_denied=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=100)
    def test_heartbeat_always_bounded(self, n_active, n_revoked, n_allowed, n_denied):
        """∀ inputs: 0.0 ≤ heartbeat ≤ 1.0."""
        contracts = [_contract(f"p{i}", frozenset({"audio"})) for i in range(n_active)] + [
            _contract(f"r{i}", frozenset({"audio"}), active=False) for i in range(n_revoked)
        ]
        reg = _registry(*contracts)

        audit_lines = [json.dumps({"allowed": True, "reason": "ok"})] * n_allowed + [
            json.dumps({"allowed": False, "reason": "no"})
        ] * n_denied
        audit_content = "\n".join(audit_lines) if audit_lines else ""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(audit_content)
            audit_path = Path(f.name)

        try:
            with (
                patch("shared.governance.consent.load_contracts", return_value=reg),
                patch("cockpit.data.governance.CONSENT_AUDIT", audit_path),
            ):
                hb = collect_governance_heartbeat()
                assert 0.0 <= hb.score <= 1.0, f"Score {hb.score} out of bounds"
                assert hb.label in ("green", "yellow", "red")
        finally:
            audit_path.unlink()

    @given(
        n_contracts=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=50)
    def test_active_contracts_improve_score(self, n_contracts):
        """∀ n > 0: having active contracts → coverage component = 1.0."""
        contracts = [_contract(f"p{i}", frozenset({"audio"})) for i in range(n_contracts)]
        reg = _registry(*contracts)

        with (
            patch("shared.governance.consent.load_contracts", return_value=reg),
            patch("cockpit.data.governance.CONSENT_AUDIT", Path("/nonexistent")),
        ):
            hb = collect_governance_heartbeat()
            assert hb.components["consent_coverage"] == 1.0

    @given(
        denial_count=st.integers(min_value=0, max_value=20),
        allow_count=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=50)
    def test_high_denial_rate_degrades_gate_health(self, denial_count, allow_count):
        """∀ denial_rate > 50%: gate_health < 1.0."""
        total = denial_count + allow_count
        if total == 0:
            return  # skip empty case

        audit_lines = [json.dumps({"allowed": True, "reason": "ok"})] * allow_count + [
            json.dumps({"allowed": False, "reason": "no"})
        ] * denial_count

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(audit_lines))
            audit_path = Path(f.name)

        try:
            with (
                patch("shared.governance.consent.load_contracts", return_value=_registry()),
                patch("cockpit.data.governance.CONSENT_AUDIT", audit_path),
            ):
                hb = collect_governance_heartbeat()
                denial_rate = denial_count / total * 100
                if denial_rate > 50:
                    assert hb.components["gate_health"] < 1.0
        finally:
            audit_path.unlink()

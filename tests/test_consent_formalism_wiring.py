"""Tests for consent formalism wiring — integration of formal layers.

Verifies that Says monad, provenance semirings, temporal bounds,
GateToken, and contextvars are properly wired into the existing
consent infrastructure.
"""

from __future__ import annotations

import asyncio

import pytest

from shared.governance.consent import ConsentContract, ConsentRegistry
from shared.governance.consent_context import consent_scope, current_principal, current_registry
from shared.governance.consent_gate import ConsentGatedWriter
from shared.governance.consent_label import ConsentLabel
from shared.governance.gate_token import require_token
from shared.governance.governor import GovernorWrapper, consent_output_policy
from shared.governance.labeled import Labeled
from shared.governance.principal import Principal, PrincipalKind
from shared.governance.provenance import ProvenanceExpr
from shared.governance.revocation import check_provenance
from shared.governance.says import Says
from shared.governance.temporal import ConsentInterval, TemporalConsent

# ── Helpers ──────────────────────────────────────────────────────────────────


def _operator() -> Principal:
    return Principal(id="operator", kind=PrincipalKind.SOVEREIGN)


def _agent(name: str = "agent-sync") -> Principal:
    return Principal(
        id=name,
        kind=PrincipalKind.BOUND,
        delegated_by="operator",
        authority=frozenset({"read", "write"}),
    )


def _contract(cid: str, person: str, scope: frozenset[str], active: bool = True) -> ConsentContract:
    return ConsentContract(
        id=cid,
        parties=("operator", person),
        scope=scope,
        revoked_at=None if active else "2026-01-01",
    )


def _registry_with(*contracts: ConsentContract) -> ConsentRegistry:
    reg = ConsentRegistry()
    for c in contracts:
        reg._contracts[c.id] = c
    return reg


def _gate(registry: ConsentRegistry) -> ConsentGatedWriter:
    gov = GovernorWrapper("test-gate")
    gov.add_output_policy(consent_output_policy(ConsentLabel.bottom()))
    return ConsentGatedWriter(_registry=registry, _governor=gov, _gate_id="test-gate")


# ── GateToken wiring ────────────────────────────────────────────────────────


class TestGateTokenWiring:
    def test_check_mints_token_on_allow(self):
        reg = _registry_with(_contract("c1", "alice", frozenset({"behavioral"})))
        gate = _gate(reg)
        data = Labeled(value="test", label=ConsentLabel.bottom())
        decision = gate.check(data, data_category="behavioral", person_ids=("alice",))
        assert decision.allowed is True
        assert decision.token is not None
        assert decision.token.is_allow is True
        assert decision.token.gate_id == "test-gate"

    def test_check_mints_token_on_deny(self):
        reg = _registry_with()
        gate = _gate(reg)
        data = Labeled(value="test", label=ConsentLabel.bottom())
        decision = gate.check(data, data_category="behavioral", person_ids=("alice",))
        assert decision.allowed is False
        assert decision.token is not None
        assert decision.token.is_deny is True

    def test_token_unique_per_decision(self):
        reg = _registry_with(_contract("c1", "alice", frozenset({"behavioral"})))
        gate = _gate(reg)
        data = Labeled(value="test", label=ConsentLabel.bottom())
        d1 = gate.check(data, data_category="behavioral", person_ids=("alice",))
        d2 = gate.check(data, data_category="behavioral", person_ids=("alice",))
        assert d1.token is not None and d2.token is not None
        assert d1.token.nonce != d2.token.nonce

    def test_require_token_structural_enforcement(self):
        reg = _registry_with(_contract("c1", "alice", frozenset({"behavioral"})))
        gate = _gate(reg)
        data = Labeled(value="test", label=ConsentLabel.bottom())
        decision = gate.check(data, data_category="behavioral", person_ids=("alice",))
        assert decision.token is not None
        require_token(decision.token)

    def test_require_token_rejects_deny(self):
        reg = _registry_with()
        gate = _gate(reg)
        data = Labeled(value="test", label=ConsentLabel.bottom())
        decision = gate.check(data, data_category="behavioral", person_ids=("alice",))
        assert decision.token is not None
        with pytest.raises(ValueError, match="Gate token denied"):
            require_token(decision.token)


# ── ProvenanceExpr wiring ────────────────────────────────────────────────────


class TestProvenanceExprWiring:
    def test_labeled_with_expr(self):
        expr = ProvenanceExpr.leaf("c1").tensor(ProvenanceExpr.leaf("c2"))
        data = Labeled(value="test", label=ConsentLabel.bottom()).with_expr(expr)
        assert data.provenance_expr is not None
        assert data.provenance == frozenset({"c1", "c2"})

    def test_effective_expr_from_flat(self):
        data = Labeled(
            value="test", label=ConsentLabel.bottom(), provenance=frozenset({"c1", "c2"})
        )
        expr = data.effective_expr()
        assert expr.contract_ids() == frozenset({"c1", "c2"})

    def test_effective_expr_prefers_structured(self):
        expr = ProvenanceExpr.leaf("c1").plus(ProvenanceExpr.leaf("c2"))
        data = Labeled(
            value="test",
            label=ConsentLabel.bottom(),
            provenance=frozenset({"c1", "c2"}),
            provenance_expr=expr,
        )
        assert data.evaluate_provenance(frozenset({"c1"})) is True

    def test_evaluate_provenance_tensor(self):
        expr = ProvenanceExpr.leaf("c1").tensor(ProvenanceExpr.leaf("c2"))
        data = Labeled(value="test", label=ConsentLabel.bottom()).with_expr(expr)
        assert data.evaluate_provenance(frozenset({"c1", "c2"})) is True
        assert data.evaluate_provenance(frozenset({"c1"})) is False

    def test_evaluate_provenance_plus(self):
        expr = ProvenanceExpr.leaf("c1").plus(ProvenanceExpr.leaf("c2"))
        data = Labeled(value="test", label=ConsentLabel.bottom()).with_expr(expr)
        assert data.evaluate_provenance(frozenset({"c1"})) is True
        assert data.evaluate_provenance(frozenset({"c2"})) is True
        assert data.evaluate_provenance(frozenset()) is False

    def test_check_provenance_uses_semiring(self):
        expr = ProvenanceExpr.leaf("c1").plus(ProvenanceExpr.leaf("c2"))
        data = Labeled(value="test", label=ConsentLabel.bottom()).with_expr(expr)
        assert check_provenance(data, frozenset({"c1"})) is True

    def test_check_provenance_backwards_compat(self):
        data = Labeled(
            value="test", label=ConsentLabel.bottom(), provenance=frozenset({"c1", "c2"})
        )
        assert check_provenance(data, frozenset({"c1", "c2"})) is True
        assert check_provenance(data, frozenset({"c1"})) is False

    def test_join_with_expr(self):
        data1 = Labeled(value="a", label=ConsentLabel.bottom(), provenance=frozenset({"c1"}))
        data2 = Labeled(value="b", label=ConsentLabel.bottom(), provenance=frozenset({"c2"}))
        _, joined_expr = data1.join_with_expr(data2)
        assert joined_expr.evaluate(frozenset({"c1", "c2"})) is True
        assert joined_expr.evaluate(frozenset({"c1"})) is False

    def test_map_preserves_expr(self):
        expr = ProvenanceExpr.leaf("c1")
        data = Labeled(value=5, label=ConsentLabel.bottom()).with_expr(expr)
        mapped = data.map(lambda x: x * 2)
        assert mapped.value == 10
        assert mapped.provenance_expr is not None


# ── Says → Labeled → Gate flow ───────────────────────────────────────────────


class TestSaysToGateFlow:
    def test_full_flow(self):
        """Says → to_labeled → gate.check → GateToken."""
        op = _operator()
        reg = _registry_with(_contract("c1", "alice", frozenset({"behavioral"})))
        gate = _gate(reg)
        assertion = Says(principal=op, value="alice's work pattern")
        labeled = assertion.to_labeled(ConsentLabel.bottom(), frozenset({"c1"}))
        decision = gate.check(labeled, data_category="behavioral", person_ids=("alice",))
        assert decision.allowed is True
        assert decision.token is not None
        require_token(decision.token)

    def test_bound_agent_flow(self):
        agent = _agent("profiler")
        reg = _registry_with(_contract("c1", "alice", frozenset({"behavioral"})))
        gate = _gate(reg)
        assertion = Says(principal=agent, value="observed coding pattern")
        labeled = assertion.to_labeled(ConsentLabel.bottom(), frozenset({"c1"}))
        decision = gate.check(labeled, data_category="behavioral", person_ids=("alice",))
        assert decision.allowed is True
        assert decision.token is not None


# ── Temporal + Gate ──────────────────────────────────────────────────────────


class TestTemporalGateIntegration:
    def test_temporal_validity_before_gate(self):
        import time

        tc = TemporalConsent(
            contract_id="c1",
            interval=ConsentInterval.fixed(3600, start=time.time()),
            person_id="alice",
        )
        assert tc.valid_at() is True
        reg = _registry_with(_contract("c1", "alice", frozenset({"behavioral"})))
        gate = _gate(reg)
        data = Labeled(value="test", label=ConsentLabel.bottom(), provenance=frozenset({"c1"}))
        decision = gate.check(data, data_category="behavioral", person_ids=("alice",))
        assert decision.allowed is True

    def test_expired_consent_blocks(self):
        import time

        tc = TemporalConsent(
            contract_id="c1",
            interval=ConsentInterval(start=time.time() - 200, end=time.time() - 100),
        )
        assert tc.valid_at() is False


# ── contextvars + Gate ───────────────────────────────────────────────────────


class TestContextVarsGateIntegration:
    def test_gate_with_context_scope(self):
        reg = _registry_with(_contract("c1", "alice", frozenset({"behavioral"})))
        op = _operator()
        with consent_scope(reg, op):
            assert current_registry() is reg
            assert current_principal().id == "operator"
            gate = _gate(current_registry())
            data = Labeled(value="test", label=ConsentLabel.bottom())
            decision = gate.check(data, data_category="behavioral", person_ids=("alice",))
            assert decision.allowed is True

    @pytest.mark.asyncio
    async def test_async_consent_scope(self):
        reg = _registry_with(_contract("c1", "alice", frozenset({"behavioral"})))
        op = _operator()

        async def agent_work():
            return (current_registry() is reg, current_principal().id)

        with consent_scope(reg, op):
            task = asyncio.create_task(agent_work())
            result = await task
            assert result == (True, "operator")

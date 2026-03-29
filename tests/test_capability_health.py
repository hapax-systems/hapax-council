"""Tests for circuit breaker, CapabilityHealthVeto, and compliance veto."""

from __future__ import annotations

import re
import time
from unittest.mock import MagicMock

from agents.hapax_daimonion.governance import VetoChain
from shared.capabilities.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)
from shared.capabilities.health_veto import capability_health_veto, compliance_veto
from shared.capabilities.protocols import HealthStatus
from shared.capabilities.registry import CapabilityRegistry

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _healthy_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.name = "healthy"
    adapter.available.return_value = True
    adapter.health.return_value = HealthStatus(healthy=True, message="ok")
    return adapter


def _unhealthy_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.name = "unhealthy"
    adapter.available.return_value = False
    adapter.health.return_value = HealthStatus(healthy=False, message="down")
    return adapter


# ------------------------------------------------------------------
# CircuitBreaker
# ------------------------------------------------------------------


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker(_healthy_adapter())
        assert cb.state == CircuitState.CLOSED

    def test_healthy_stays_closed(self):
        cb = CircuitBreaker(_healthy_adapter())
        assert cb.health().healthy is True
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        adapter = _unhealthy_adapter()
        cb = CircuitBreaker(adapter, config=CircuitBreakerConfig(failure_threshold=2))
        cb.health()
        assert cb.state == CircuitState.CLOSED
        cb.health()
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_returns_unhealthy(self):
        adapter = _unhealthy_adapter()
        cb = CircuitBreaker(adapter, config=CircuitBreakerConfig(failure_threshold=1))
        cb.health()
        assert cb.state == CircuitState.OPEN
        status = cb.health()
        assert status.healthy is False
        assert "Circuit open" in status.message

    def test_open_circuit_available_returns_false(self):
        adapter = _unhealthy_adapter()
        cb = CircuitBreaker(adapter, config=CircuitBreakerConfig(failure_threshold=1))
        cb.available()
        assert cb.state == CircuitState.OPEN
        assert cb.available() is False

    def test_transitions_to_half_open(self):
        adapter = _unhealthy_adapter()
        cb = CircuitBreaker(
            adapter,
            config=CircuitBreakerConfig(failure_threshold=1, reset_timeout_s=0.01),
        )
        cb.health()  # → open
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self):
        adapter = MagicMock()
        adapter.name = "flaky"
        adapter.available.return_value = False
        adapter.health.return_value = HealthStatus(healthy=False, message="down")

        cb = CircuitBreaker(
            adapter,
            config=CircuitBreakerConfig(failure_threshold=1, reset_timeout_s=0.01),
        )
        cb.health()  # → open
        time.sleep(0.02)
        # Now half-open; make adapter healthy
        adapter.health.return_value = HealthStatus(healthy=True, message="ok")
        status = cb.health()
        assert status.healthy is True
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        adapter = _unhealthy_adapter()
        cb = CircuitBreaker(
            adapter,
            config=CircuitBreakerConfig(failure_threshold=1, reset_timeout_s=0.01),
        )
        cb.health()  # → open
        time.sleep(0.02)
        # Half-open; adapter still unhealthy
        cb.health()
        assert cb.state == CircuitState.OPEN

    def test_exception_counts_as_failure(self):
        adapter = MagicMock()
        adapter.name = "exploding"
        adapter.available.side_effect = RuntimeError("boom")
        adapter.health.side_effect = RuntimeError("boom")
        cb = CircuitBreaker(adapter, config=CircuitBreakerConfig(failure_threshold=1))
        assert cb.available() is False
        assert cb.state == CircuitState.OPEN

    def test_name_property(self):
        adapter = _healthy_adapter()
        cb = CircuitBreaker(adapter)
        assert cb.name == "healthy"


# ------------------------------------------------------------------
# CapabilityHealthVeto
# ------------------------------------------------------------------


class TestCapabilityHealthVeto:
    def test_healthy_allows(self):
        registry = CapabilityRegistry()
        registry.register("embedding", _healthy_adapter())
        veto = capability_health_veto("embedding", registry)
        chain: VetoChain[str] = VetoChain([veto])
        assert chain.evaluate("any context").allowed is True

    def test_unhealthy_denies(self):
        registry = CapabilityRegistry()
        registry.register("embedding", _unhealthy_adapter())
        veto = capability_health_veto("embedding", registry)
        chain: VetoChain[str] = VetoChain([veto])
        result = chain.evaluate("any context")
        assert result.allowed is False
        assert "capability_health:embedding" in result.denied_by

    def test_unregistered_denies(self):
        registry = CapabilityRegistry()
        veto = capability_health_veto("nonexistent", registry)
        chain: VetoChain[str] = VetoChain([veto])
        assert chain.evaluate("x").allowed is False

    def test_axiom_propagated(self):
        registry = CapabilityRegistry()
        registry.register("embedding", _unhealthy_adapter())
        veto = capability_health_veto("embedding", registry, axiom="executive_function")
        chain: VetoChain[str] = VetoChain([veto])
        result = chain.evaluate("x")
        assert "executive_function" in result.axiom_ids


# ------------------------------------------------------------------
# ComplianceVeto (check_fast as VetoChain predicate)
# ------------------------------------------------------------------


class TestComplianceVeto:
    def test_compliant_allows(self):
        from shared.axiom_enforcement import ComplianceRule

        rules = [
            ComplianceRule(
                axiom_id="single_user",
                implication_id="su-auth-001",
                tier="T0",
                pattern=re.compile(re.escape("su-auth-001"), re.IGNORECASE),
                description="No auth",
            )
        ]
        veto = compliance_veto(rules)
        chain: VetoChain[str] = VetoChain([veto])
        assert chain.evaluate("adding a new agent feature").allowed is True

    def test_violation_denies(self):
        from shared.axiom_enforcement import ComplianceRule

        rules = [
            ComplianceRule(
                axiom_id="single_user",
                implication_id="su-auth-001",
                tier="T0",
                pattern=re.compile(re.escape("su-auth-001"), re.IGNORECASE),
                description="No auth",
            )
        ]
        veto = compliance_veto(rules)
        chain: VetoChain[str] = VetoChain([veto])
        result = chain.evaluate("situation involving su-auth-001 implication")
        assert result.allowed is False

"""Tests for shared.service_graph."""

from shared.service_graph import (
    get_dependencies,
    get_dependents,
    impact_analysis,
    remediation_order,
)


def test_get_dependents():
    dependents = get_dependents("postgres")
    assert "litellm" in dependents
    assert "langfuse" in dependents
    assert "n8n" in dependents


def test_get_dependencies():
    deps = get_dependencies("litellm")
    assert "postgres" in deps
    assert "ollama" in deps


def test_remediation_order_deps_first():
    order = remediation_order(["litellm", "postgres", "ollama"])
    # postgres and ollama should come before litellm
    assert order.index("postgres") < order.index("litellm")
    assert order.index("ollama") < order.index("litellm")


def test_remediation_order_unknown_service():
    order = remediation_order(["unknown-svc", "postgres"])
    assert "postgres" in order
    assert "unknown-svc" in order
    # unknown at end
    assert order.index("postgres") < order.index("unknown-svc")


def test_impact_analysis():
    impact = impact_analysis("postgres")
    assert "litellm" in impact["direct"]
    assert "langfuse" in impact["direct"]
    # open-webui depends on litellm which depends on postgres
    assert "open-webui" in impact["transitive"]

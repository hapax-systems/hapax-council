"""Tests for METADATA.yaml generator."""

from __future__ import annotations

from scripts.llm_metadata_gen import generate_metadata_for_module


def test_generate_metadata_from_drift_detector():
    result = generate_metadata_for_module("agents.drift_detector")
    assert result["module"] == "drift_detector"
    assert len(result["purpose"]) > 10
    assert result["version"] == 1
    assert "runtime" in result["dependencies"]
    assert isinstance(result["dependencies"]["internal"], list)
    assert result["token_budget"]["self"] > 0


def test_generate_metadata_has_execution_entry():
    result = generate_metadata_for_module("agents.drift_detector")
    assert "entry" in result["execution"]
    assert "agents.drift_detector" in result["execution"]["entry"]

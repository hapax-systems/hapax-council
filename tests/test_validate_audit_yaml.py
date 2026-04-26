"""Tests for scripts/validate-audit-yaml.py.

P-1 of the absence-class-bug-prevention-and-remediation epic.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "validate-audit-yaml.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_audit_yaml", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {SCRIPT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load_module()


@pytest.fixture
def tier2_payload():
    return {
        "pr_number": 1234,
        "tier": 2,
        "authored_by": "beta",
        "audited_by": "alpha",
        "tests_run": True,
        "lint_passed": True,
        "data_flow_traced": True,
        "production_path_verified": True,
        "peer_module_glob_match": True,
        "new_function_call_sites": ["agents/foo.py:42"],
    }


def test_tier2_complete_payload_is_valid(mod, tier2_payload) -> None:
    errors = mod._validate(tier2_payload, tier=2)
    assert errors == []


def test_tier2_missing_substrate_field_invalidates(mod, tier2_payload) -> None:
    del tier2_payload["data_flow_traced"]
    errors = mod._validate(tier2_payload, tier=2)
    assert any("data_flow_traced" in e for e in errors)


def test_tier2_empty_call_sites_list_is_valid(mod, tier2_payload) -> None:
    """Empty new_function_call_sites means "no new public callable" — valid."""
    tier2_payload["new_function_call_sites"] = []
    errors = mod._validate(tier2_payload, tier=2)
    assert errors == []


def test_tier2_substrate_false_without_note_invalidates(mod, tier2_payload) -> None:
    """If a substrate-truth field is False, a note is required."""
    tier2_payload["data_flow_traced"] = False
    errors = mod._validate(tier2_payload, tier=2)
    assert any("data_flow_traced_note" in e for e in errors)


def test_tier2_substrate_false_with_note_is_valid(mod, tier2_payload) -> None:
    tier2_payload["data_flow_traced"] = False
    tier2_payload["data_flow_traced_note"] = "deferred — wiring lands in #1657"
    errors = mod._validate(tier2_payload, tier=2)
    assert errors == []


def test_tier1_does_not_require_substrate_fields(mod) -> None:
    tier1_payload = {
        "pr_number": 999,
        "tier": 1,
        "tests_run": True,
        "lint_passed": True,
    }
    errors = mod._validate(tier1_payload, tier=1)
    assert errors == []


def test_tier0_skips_field_checks(mod) -> None:
    tier0_payload = {"pr_number": 42, "tier": 0}
    errors = mod._validate(tier0_payload, tier=0)
    assert errors == []


def test_tier_mismatch_invalidates(mod, tier2_payload) -> None:
    """If file declares tier-N but caller passes tier-M, surface the conflict."""
    tier2_payload["tier"] = 1
    errors = mod._validate(tier2_payload, tier=2)
    assert any("tier mismatch" in e for e in errors)


def test_pr_number_required(mod) -> None:
    errors = mod._validate({"tier": 0}, tier=0)
    assert any("pr_number" in e for e in errors)


def test_p7_self_audit_is_rejected(mod, tier2_payload) -> None:
    """P-7: a session cannot audit its own merges."""
    tier2_payload["authored_by"] = "beta"
    tier2_payload["audited_by"] = "beta"
    errors = mod._validate(tier2_payload, tier=2)
    assert any("authored_by == audited_by" in e for e in errors)


def test_p7_missing_authored_by_invalidates(mod, tier2_payload) -> None:
    del tier2_payload["authored_by"]
    errors = mod._validate(tier2_payload, tier=2)
    assert any("authored_by missing" in e for e in errors)


def test_p7_missing_audited_by_invalidates(mod, tier2_payload) -> None:
    del tier2_payload["audited_by"]
    errors = mod._validate(tier2_payload, tier=2)
    assert any("audited_by missing" in e for e in errors)


def test_p7_does_not_apply_to_tier_0_or_1(mod) -> None:
    """tier-0/1 PRs don't require the cross-session attestation."""
    tier1_payload = {
        "pr_number": 999,
        "tier": 1,
        "tests_run": True,
        "lint_passed": True,
        # no authored_by / audited_by
    }
    errors = mod._validate(tier1_payload, tier=1)
    assert errors == []

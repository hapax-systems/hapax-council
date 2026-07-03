"""Tests for the vocab-drift audit (derivation-substrate MOVE 1, slice 1a — REPORT mode)."""

from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_audit() -> ModuleType:
    src = REPO_ROOT / "scripts" / "hapax-vocab-drift-audit"
    loader = importlib.machinery.SourceFileLoader("vocab_drift_audit_under_test", str(src))
    spec = importlib.util.spec_from_loader("vocab_drift_audit_under_test", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_vocabulary_is_derived_from_the_enum_not_hardcoded() -> None:
    import sys

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from shared.platform_capability_registry import Platform

    mod = _load_audit()
    vocabs = mod.registered_vocabularies()
    assert "Platform" in vocabs
    # DERIVED from the live enum (migration-agnostic) — not a hardcoded copy, else the audit would be
    # the very boutique it hunts.
    assert vocabs["Platform"] == frozenset(str(m.value) for m in Platform)
    assert {"claude", "codex", "vibe"} <= vocabs["Platform"]


def test_detects_team_registry_platform_redeclaration_and_its_drift_token() -> None:
    mod = _load_audit()
    vocabs = mod.registered_vocabularies()
    findings = mod.audit_tree(REPO_ROOT / "shared", vocabs)
    tr = [
        f for f in findings if f["path"].endswith("team_registry.py") and f["vocab"] == "Platform"
    ]
    assert tr, (
        "team_registry.py re-declares the Platform vocabulary as a bare Literal — must be detected"
    )
    # the divergent member(s) are the drift the antigrav crash rode: claude-code != the SSOT's claude
    assert any("claude-code" in f["divergent"] for f in tr)


def test_ssot_module_is_exempt_from_its_own_declaration() -> None:
    mod = _load_audit()
    vocabs = mod.registered_vocabularies()
    findings = mod.audit_tree(REPO_ROOT / "shared", vocabs)
    assert not any(f["path"].endswith("platform_capability_registry.py") for f in findings), (
        "the SSOT's own enum declaration is authoritative, not drift"
    )


def test_string_member_extraction_shapes() -> None:
    mod = _load_audit()
    lit = ast.parse('x = Literal["agy", "codex", "vibe"]').body[0].value
    fs = ast.parse('y = frozenset({"agy", "claude"})').body[0].value
    plain = (
        ast.parse('z = ("agy", "codex")').body[0].value
    )  # bare tuple: intentionally NOT matched in 1a
    assert mod._string_members(lit) == frozenset({"agy", "codex", "vibe"})
    assert mod._string_members(fs) == frozenset({"agy", "claude"})
    assert mod._string_members(plain) == frozenset()


def test_report_mode_audit_over_shared_runs_clean() -> None:
    """The audit itself must not crash on any shared module (report mode is a pure read)."""
    mod = _load_audit()
    vocabs = mod.registered_vocabularies()
    findings = mod.audit_tree(REPO_ROOT / "shared", vocabs)
    assert isinstance(findings, list)
    # every finding is well-formed
    for f in findings:
        assert set(f) >= {"path", "line", "vocab", "members", "divergent"}
        assert f["vocab"] in vocabs

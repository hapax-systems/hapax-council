"""Tests for the fail-open / degraded-default audit (derivation-substrate MOVE 6, slice 1)."""

from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_audit() -> ModuleType:
    src = REPO_ROOT / "scripts" / "hapax-fail-open-audit"
    loader = importlib.machinery.SourceFileLoader("fail_open_audit_under_test", str(src))
    spec = importlib.util.spec_from_loader("fail_open_audit_under_test", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_detects_pressure_gate_working_mode_fail_open() -> None:
    """read_working_mode() catches OSError and returns the permissive 'research' — a fail-open."""
    mod = _load_audit()
    findings = mod.audit_tree(REPO_ROOT / "shared")
    wm = [
        f
        for f in findings
        if f["path"].endswith("sdlc_pressure_gate.py") and f["func"] == "read_working_mode"
    ]
    assert wm, "read_working_mode's except->return should be detected"
    assert any("research" in f["returns"] for f in wm)
    assert all(f["severity"] == "governance-fail-open" for f in wm)


def test_detects_pressure_gate_zero_pressure_fail_open() -> None:
    """A pressure read that catches and returns 0.0 admits everything — the scariest fail-open."""
    mod = _load_audit()
    findings = mod.audit_tree(REPO_ROOT / "shared")
    zero = [
        f for f in findings if f["path"].endswith("sdlc_pressure_gate.py") and f["returns"] == "0.0"
    ]
    assert zero, "the pressure read's except->return 0.0 should be detected"
    assert all(f["severity"] == "governance-fail-open" for f in zero)


def test_governance_modules_are_flagged_highest_severity() -> None:
    mod = _load_audit()
    findings = mod.audit_tree(REPO_ROOT / "shared")
    gov = [f for f in findings if f["severity"] == "governance-fail-open"]
    assert gov, "at least the pressure gate should surface governance fail-opens"
    assert all(Path(f["path"]).name in mod._GOVERNANCE_BASENAMES for f in gov)


def test_constant_return_detection_shapes() -> None:
    mod = _load_audit()

    def handler(src: str) -> ast.ExceptHandler:
        tree = ast.parse(src)
        return tree.body[0].handlers[0]  # type: ignore[attr-defined]

    assert mod._constant_returns(handler('try:\n a()\nexcept OSError:\n return "x"')) == [
        (4, "'x'")
    ]
    assert mod._constant_returns(handler("try:\n a()\nexcept OSError:\n return 0.0")) == [
        (4, "0.0")
    ]
    assert mod._constant_returns(handler("try:\n a()\nexcept OSError:\n return")) == [(4, "None")]
    assert mod._constant_returns(handler("try:\n a()\nexcept OSError:\n return {}")) == [(4, "{}")]
    # a computed (non-constant) return is NOT a hand-picked default — must be ignored
    assert mod._constant_returns(handler("try:\n a()\nexcept OSError:\n return foo(1)")) == []


def test_report_mode_audit_over_shared_runs_clean() -> None:
    mod = _load_audit()
    findings = mod.audit_tree(REPO_ROOT / "shared")
    assert isinstance(findings, list)
    for f in findings:
        assert set(f) >= {"path", "line", "func", "excepts", "returns", "severity"}
        assert f["severity"] in ("governance-fail-open", "degraded-default")

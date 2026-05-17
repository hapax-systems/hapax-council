"""Tests for the Says monad bridge in sdlc_axiom_judge."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "agentgov" / "src"))

from agentgov import Principal, PrincipalKind, ProvenanceExpr, Says
from sdlc_axiom_judge import SemanticVerdict, _call_judge, _wrap_says


def test_wrap_says_preserves_verdicts() -> None:
    verdicts = [
        SemanticVerdict(axiom_id="single_user", compliant=True, reasoning="OK"),
        SemanticVerdict(axiom_id="executive_function", compliant=False, reasoning="Fail"),
    ]
    result = _wrap_says(verdicts, "test-model")
    assert len(result) == 2
    assert result[0].axiom_id == "single_user"
    assert result[1].compliant is False


def test_says_unit_wraps_principal() -> None:
    principal = Principal(
        id="model:test",
        kind=PrincipalKind.BOUND,
        delegated_by="operator",
        authority=frozenset({"axiom_judge"}),
    )
    verdicts = [SemanticVerdict(axiom_id="test", compliant=True)]
    said = Says.unit(principal, verdicts)
    assert said.asserter_id == "model:test"
    assert said.value == verdicts


def test_provenance_expr_leaf_for_model() -> None:
    prov = ProvenanceExpr.leaf("judge:claude-haiku-4-5-20251001")
    assert prov.evaluate(frozenset({"judge:claude-haiku-4-5-20251001"})) is True
    assert prov.evaluate(frozenset({"other"})) is False


def test_call_judge_dry_run_sets_provenance_model() -> None:
    with patch.dict("os.environ", {"SDLC_JUDGE_MODEL": "test-model-1"}):
        verdicts = _call_judge("system prompt", "diff content", dry_run=True)
        assert len(verdicts) == 1
        assert verdicts[0].provenance_model == "test-model-1"


def test_semantic_verdict_provenance_field() -> None:
    v = SemanticVerdict(
        axiom_id="corporate_boundary",
        compliant=True,
        reasoning="No work data found",
        provenance_model="claude-haiku-4-5-20251001",
    )
    assert v.provenance_model == "claude-haiku-4-5-20251001"

"""CI-reproducible pin for the eval-calibration acceptor logic.

scripts/calibrate-eval.py demonstrates "the eval is a validated acceptor" by
calling the LIVE council, which a reviewer cannot re-run in CI. This test mocks
the council so the load-bearing classification — good->ACCEPT, bad->REJECT,
degraded->DEGRADED, and the rank-AUC — is verified deterministically alongside
the live harness (claude-1, PR #4133).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "calibrate-eval.py"
_spec = importlib.util.spec_from_file_location("calibrate_eval", SCRIPT)
assert _spec and _spec.loader
cal = importlib.util.module_from_spec(_spec)
# Register before exec so @dataclass introspection can resolve cls.__module__.
sys.modules["calibrate_eval"] = cal
_spec.loader.exec_module(cal)


def _fixture(label: str = "good") -> object:
    return cal.Fixture(fixture_id="fx", label=label, rationale="r", script="a script")


def _verdict(scores: dict[str, int], status: str = "CONVERGED", members: int = 6):
    from agents.deliberative_council.models import ConvergenceStatus, CouncilVerdict

    return CouncilVerdict(
        scores=scores,
        confidence_bands={},
        convergence_status=ConvergenceStatus[status],
        disagreement_log=[],
        research_findings=[],
        evidence_matrix=None,
        receipt={"council_health": {"members_valid": members, "families_valid": 5}},
    )


def test_classification_accept_reject_degraded() -> None:
    good = cal.EvalResult(
        fixture=_fixture(), convergence_status="converged", mean_score=5.0, scores={"a": 5, "b": 5}
    )
    assert good.classification == "ACCEPT"

    bad = cal.EvalResult(
        fixture=_fixture("bad"),
        convergence_status="converged",
        mean_score=1.0,
        scores={"a": 1, "b": 1},
    )
    assert bad.classification == "REJECT"

    refused = cal.EvalResult(fixture=_fixture(), convergence_status="refused", scores={})
    assert refused.classification == "DEGRADED"

    errored = cal.EvalResult(fixture=_fixture(), error="boom")
    assert errored.classification == "DEGRADED"

    boundary = cal.EvalResult(
        fixture=_fixture(), convergence_status="converged", mean_score=3.0, scores={"a": 3}
    )
    assert boundary.classification == "ACCEPT"  # mean>=3.0 is the accept threshold


def test_auc_perfect_tie_and_empty() -> None:
    assert cal._auc([5.0, 5.0], [1.0, 1.0]) == 1.0  # perfect separation
    assert cal._auc([3.0], [3.0]) == 0.5  # a tie scores at chance
    assert cal._auc([], [1.0]) is None  # undefined without both classes


async def test_eval_one_maps_high_verdict_to_accept() -> None:
    fake = _verdict({"opening_pressure": 5, "payoff_resolution": 5})

    async def _fake_deliberate(inp, mode, rubric, config):  # noqa: ANN001
        return fake

    with patch("agents.deliberative_council.engine.deliberate", side_effect=_fake_deliberate):
        result = await cal._eval_one(_fixture("good"))
    assert result.error is None
    assert result.mean_score == 5.0
    assert result.members_valid == 6
    assert result.classification == "ACCEPT"


async def test_eval_one_maps_low_verdict_to_reject() -> None:
    fake = _verdict({"opening_pressure": 1, "payoff_resolution": 1})

    async def _fake_deliberate(inp, mode, rubric, config):  # noqa: ANN001
        return fake

    with patch("agents.deliberative_council.engine.deliberate", side_effect=_fake_deliberate):
        result = await cal._eval_one(_fixture("bad"))
    assert result.mean_score == 1.0
    assert result.classification == "REJECT"


async def test_eval_one_records_error_as_degraded() -> None:
    async def _boom(inp, mode, rubric, config):  # noqa: ANN001
        raise RuntimeError("council down")

    with patch("agents.deliberative_council.engine.deliberate", side_effect=_boom):
        result = await cal._eval_one(_fixture("good"))
    assert result.error is not None
    assert result.classification == "DEGRADED"

"""Onboarding disposition ledgers (F2 residual after classify #4505)."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.agentic_trust_boundary import AGENTIC_TRUST_EVIDENCE_SURFACE_ID
from shared.capability_onboarding_classify import classify_onboarding_surface
from shared.capability_onboarding_ledger import (
    append_classify_result,
    classify_and_ledger,
    read_ledger,
    stream_path,
)


def test_explore_lands_in_explore_stream(tmp_path: Path) -> None:
    result = classify_onboarding_surface(
        surface_id="new.slice",
        modal_class="permitted",
        measurement_sufficiency="partial",
    )
    path, row = append_classify_result(result, root=tmp_path, source_ref="test:explore")
    assert path == stream_path("EXPLORE", root=tmp_path)
    assert path.exists()
    assert row["disposition"] == "EXPLORE"
    assert row["success"] is True
    assert row["may_fulfill_demand"] is False
    rows = list(read_ledger("EXPLORE", root=tmp_path))
    assert len(rows) == 1
    assert rows[0]["row_id"] == row["row_id"]


def test_agentic_trust_never_ledgers_as_admit_supply(tmp_path: Path) -> None:
    out = classify_and_ledger(
        root=tmp_path,
        surface_id=AGENTIC_TRUST_EVIDENCE_SURFACE_ID,
        modal_class="permitted",
        measurement_sufficiency="complete",
        equal_definition_complete=True,
        demand_eligible_candidate=True,
        source_ref="test:boundary",
    )
    assert out["classify"]["disposition"] == "evidence_only"
    assert out["row"]["disposition"] == "evidence_only"
    assert list(read_ledger("admit_supply", root=tmp_path)) == []
    assert len(list(read_ledger("evidence_only", root=tmp_path))) == 1


def test_refuse_admit_supply_row_without_fulfill_flag(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="may_fulfill_demand"):
        append_classify_result(
            {
                "disposition": "admit_supply",
                "may_fulfill_demand": False,
                "reasons": [],
            },
            root=tmp_path,
        )


def test_admit_supply_when_complete(tmp_path: Path) -> None:
    out = classify_and_ledger(
        root=tmp_path,
        surface_id="codex.headless.full",
        modal_class="permitted",
        measurement_sufficiency="complete",
        equal_definition_complete=True,
        demand_eligible_candidate=True,
    )
    assert out["row"]["disposition"] == "admit_supply"
    assert out["row"]["may_fulfill_demand"] is True
    assert len(list(read_ledger("admit_supply", root=tmp_path))) == 1


def test_hold_stream(tmp_path: Path) -> None:
    out = classify_and_ledger(
        root=tmp_path,
        modal_class="unevaluable",
        measurement_sufficiency="complete",
    )
    assert out["row"]["disposition"] == "HOLD"
    assert stream_path("HOLD", root=tmp_path).exists()

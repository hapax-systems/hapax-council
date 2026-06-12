"""Tests for the shared grounding ledger retention behavior."""

from __future__ import annotations

import json
from pathlib import Path

from shared.grounding_ledger import GroundingLedger, GroundingState


def _ledger_line(claim_id: str, state: str) -> str:
    return json.dumps(
        {
            "claim_id": claim_id,
            "claim_text": f"{claim_id} text",
            "state": state,
        }
    )


def test_grounding_ledger_rewrites_bounded_latest_state(tmp_path: Path) -> None:
    path = tmp_path / "grounding-ledger.jsonl"
    ledger = GroundingLedger(path, max_entries=2)

    for idx in range(3):
        ledger.record_verdict(
            f"claim-{idx}",
            f"claim text {idx}",
            GroundingState.CCTV_COMPLETE,
        )

    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    reloaded = GroundingLedger(path, max_entries=2)
    assert [entry.claim_id for entry in reloaded.all_entries()] == ["claim-1", "claim-2"]


def test_grounding_ledger_replays_retained_generations(tmp_path: Path) -> None:
    path = tmp_path / "grounding-ledger.jsonl"
    path.with_name(f"{path.name}.1").write_text(
        _ledger_line("rotated", GroundingState.CCTV_COMPLETE.value) + "\n",
        encoding="utf-8",
    )
    path.write_text(
        _ledger_line("active", GroundingState.PERSONALLY_GROUNDED.value) + "\n",
        encoding="utf-8",
    )

    ledger = GroundingLedger(path)

    assert ledger.get("rotated") is not None
    assert ledger.get("rotated").state == GroundingState.CCTV_COMPLETE
    assert ledger.get("active") is not None
    assert ledger.get("active").state == GroundingState.PERSONALLY_GROUNDED

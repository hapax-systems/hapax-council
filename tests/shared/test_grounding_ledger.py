"""Tests for the shared grounding ledger retention behavior."""

from __future__ import annotations

from pathlib import Path

from shared.grounding_ledger import GroundingLedger, GroundingState


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

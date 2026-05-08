"""Tests for the cross-runtime orchestration ledger.

CASE-SDLC-REFORM-001 / SLICE-003C-CROSS-RUNTIME
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.orchestration_ledger import (
    DISPATCH_ORDER_KEYS,
    DispatchReceipt,
    DuplicateSessionError,
    ProtectedSessionError,
    WorkClaim,
    WorkstreamMode,
    active_claims,
    check_duplicate_session,
    check_protected_session,
    dispatch_history,
    make_dispatch_id,
    record_claim,
    record_dispatch,
    select_dispatch_priority,
)


class TestDispatchReceipt:
    def test_record_and_read(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "shared.orchestration_ledger.DISPATCH_LEDGER", tmp_path / "dispatch.jsonl"
        )
        receipt = DispatchReceipt(
            dispatch_id="DISPATCH-alpha-20260508T140000Z",
            timestamp="2026-05-08T14:00:00Z",
            dispatcher="alpha",
            target_lane="beta",
            target_platform="claude",
            task_id="ari-123",
            reason="ARI pass 2 work",
        )
        record_dispatch(receipt)
        history = dispatch_history(lane="beta")
        assert len(history) == 1
        assert history[0].target_lane == "beta"
        assert history[0].task_id == "ari-123"

    def test_dispatch_history_limit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "shared.orchestration_ledger.DISPATCH_LEDGER", tmp_path / "dispatch.jsonl"
        )
        for i in range(10):
            record_dispatch(
                DispatchReceipt(
                    dispatch_id=f"D-{i}",
                    timestamp="2026-05-08T14:00:00Z",
                    dispatcher="alpha",
                    target_lane="beta",
                    target_platform="claude",
                )
            )
        history = dispatch_history(lane="beta", limit=3)
        assert len(history) == 3
        assert history[-1].dispatch_id == "D-9"

    def test_empty_history(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shared.orchestration_ledger.DISPATCH_LEDGER", tmp_path / "ghost.jsonl")
        assert dispatch_history() == []


class TestWorkClaim:
    def test_record_and_filter(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shared.orchestration_ledger.CLAIM_LEDGER", tmp_path / "claims.jsonl")
        record_claim(
            WorkClaim(
                lane_id="beta",
                timestamp="2026-05-08T14:00:00Z",
                task_id="task-1",
                claim_type="active",
            )
        )
        record_claim(
            WorkClaim(
                lane_id="gamma",
                timestamp="2026-05-08T14:00:00Z",
                task_id="task-2",
                claim_type="active",
            )
        )
        record_claim(
            WorkClaim(
                lane_id="beta",
                timestamp="2026-05-08T15:00:00Z",
                task_id="task-1",
                claim_type="completed",
            )
        )
        beta_active = active_claims(lane="beta")
        assert len(beta_active) == 1
        assert beta_active[0].task_id == "task-1"
        all_active = active_claims()
        assert len(all_active) == 2


class TestDuplicateSessionCheck:
    def test_no_duplicate_on_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shared.orchestration_ledger.DISPATCH_LEDGER", tmp_path / "d.jsonl")
        check_duplicate_session("beta", "claude")

    def test_duplicate_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shared.orchestration_ledger.DISPATCH_LEDGER", tmp_path / "d.jsonl")
        record_dispatch(
            DispatchReceipt(
                dispatch_id="D-1",
                timestamp="2026-05-08T14:00:00Z",
                dispatcher="alpha",
                target_lane="beta",
                target_platform="claude",
                outcome="dispatched",
            )
        )
        with pytest.raises(DuplicateSessionError, match="beta.*claude"):
            check_duplicate_session("beta", "claude")

    def test_different_platform_ok(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shared.orchestration_ledger.DISPATCH_LEDGER", tmp_path / "d.jsonl")
        record_dispatch(
            DispatchReceipt(
                dispatch_id="D-1",
                timestamp="2026-05-08T14:00:00Z",
                dispatcher="alpha",
                target_lane="beta",
                target_platform="claude",
                outcome="dispatched",
            )
        )
        check_duplicate_session("beta", "codex")


class TestProtectedSessionCheck:
    def test_not_protected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pfile = tmp_path / "protection.md"
        pfile.write_text("# Protected Sessions\n\n- `alpha` protected (reason: critical)\n")
        monkeypatch.setattr("shared.orchestration_ledger.PROTECTION_FILE", pfile)
        check_protected_session("beta")

    def test_protected_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pfile = tmp_path / "protection.md"
        pfile.write_text("# Protected Sessions\n\n- `beta` protected (reason: testing)\n")
        monkeypatch.setattr("shared.orchestration_ledger.PROTECTION_FILE", pfile)
        with pytest.raises(ProtectedSessionError, match="beta.*protected"):
            check_protected_session("beta")

    def test_no_protection_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shared.orchestration_ledger.PROTECTION_FILE", tmp_path / "ghost.md")
        check_protected_session("beta")


class TestDispatchPriority:
    def test_bucket_ordering(self) -> None:
        candidates = [
            {"priority_bucket": "eligible_offered", "wsjf": 9.0, "task_id": "t3"},
            {"priority_bucket": "hard_gate", "wsjf": 5.0, "task_id": "t1"},
            {"priority_bucket": "claimed_work", "wsjf": 7.0, "task_id": "t2"},
        ]
        result = select_dispatch_priority(candidates)
        assert [c["task_id"] for c in result] == ["t1", "t2", "t3"]

    def test_wsjf_within_bucket(self) -> None:
        candidates = [
            {"priority_bucket": "eligible_offered", "wsjf": 5.0, "task_id": "low"},
            {"priority_bucket": "eligible_offered", "wsjf": 9.0, "task_id": "high"},
        ]
        result = select_dispatch_priority(candidates)
        assert result[0]["task_id"] == "high"

    def test_empty_candidates(self) -> None:
        assert select_dispatch_priority([]) == []


class TestWorkstreamMode:
    def test_enum_values(self) -> None:
        assert WorkstreamMode.SINGLE_LANE.value == "single_lane"
        assert WorkstreamMode.SHARED_COORDINATED.value == "shared_coordinated"
        assert WorkstreamMode.PARALLEL_SEPARATE.value == "parallel_separate"


class TestMakeDispatchId:
    def test_format(self) -> None:
        did = make_dispatch_id("beta")
        assert did.startswith("DISPATCH-beta-")
        assert len(did) > len("DISPATCH-beta-")


class TestDispatchOrderKeys:
    def test_order(self) -> None:
        assert DISPATCH_ORDER_KEYS == [
            "hard_gate",
            "claimed_work",
            "stale_hygiene",
            "accepted_authority_case",
            "eligible_offered",
        ]

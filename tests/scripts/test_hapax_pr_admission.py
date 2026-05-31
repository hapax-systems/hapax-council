"""Smoke tests for hapax-pr-admission governor CLI.

Spec acceptance criteria covered (P0 phase):
- status command runs without crashing
- freeze writes control file with snapshot
- normal command refuses to clear when stability not met
- normal command clears with --force
- is_admission_allowed library function works
"""

from __future__ import annotations

import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO / "scripts" / "hapax-pr-admission"


def _throttle(
    *,
    frozen: bool = False,
    state: str = "calm",
    reason: str = "merge failure_rate 0% over 0 runs",
    failure_rate: float = 0.0,
    samples: int = 0,
    open_pr_count: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        frozen=frozen,
        state=state,
        reason=reason,
        failure_rate=failure_rate,
        samples=samples,
        open_pr_count=open_pr_count,
    )


@pytest.fixture
def gov_module(monkeypatch, tmp_path):
    """Load the script as a module with a temp control file path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Script has no .py extension — provide explicit SourceFileLoader.
    loader = SourceFileLoader("hapax_pr_admission", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("hapax_pr_admission", loader)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Override CONTROL_PATH to live under tmp_path
    mod.CONTROL_PATH = tmp_path / ".cache" / "hapax" / "pr-admission-governor.yaml"
    return mod


class TestLoadState:
    def test_default_state_when_missing(self, gov_module):
        state = gov_module.load_state()
        assert state["mode"] == "normal"
        assert state["set_by"] == "default"
        assert state["allowed_existing_branches"] == []
        assert state["exit_below_count"] == 6

    def test_round_trip(self, gov_module):
        state = gov_module.load_state()
        state["mode"] = "frozen"
        state["set_by"] = "alpha"
        state["reason"] = "test reason"
        state["allowed_existing_branches"] = ["alpha/foo", "beta/bar"]
        gov_module.save_state(state)

        loaded = gov_module.load_state()
        assert loaded["mode"] == "frozen"
        assert loaded["set_by"] == "alpha"
        assert loaded["reason"] == "test reason"
        assert loaded["allowed_existing_branches"] == ["alpha/foo", "beta/bar"]


class TestStatusCommand:
    def test_status_prints_merge_queue_summary(self, gov_module, capsys, tmp_path):
        summary_path = tmp_path / "merge-queue-summary.json"
        gov_module.MERGE_QUEUE_SUMMARY_PATH = summary_path
        summary_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "event": "merge_queue_summary",
                    "observed_at": "2026-05-18T22:05:00Z",
                    "records_considered": 2,
                    "latest_run_id": 26062256385,
                    "latest_pr_number": 3450,
                    "latest_run_outcome": "success",
                    "latest_bottleneck": {
                        "kind": "branch_protection_check_mapping",
                        "reason": "successful synthetic merge-group run did not merge or close the PR",
                        "evidence": {"run_id": 26062256385, "pr_number": 3450},
                    },
                    "bottleneck_counts": {"branch_protection_check_mapping": 1},
                    "current_queue_hold_reasons": [
                        {
                            "pr_number": 3450,
                            "kind": "queue_admission",
                            "reason": "clean PR has no auto-merge request",
                            "source": "autoMergeRequest",
                            "run_id": None,
                            "details": {},
                        }
                    ],
                    "repeated_successful_synthetic_prs": [],
                    "stale_synthetic_run_ids": [],
                    "slowest_recent_job": None,
                }
            ),
            encoding="utf-8",
        )

        with (
            patch.object(gov_module, "query_open_prs", return_value=[]),
            patch.object(gov_module, "current_throttle_decision", return_value=_throttle()),
        ):
            ns = type("NS", (), {})()
            rc = gov_module.cmd_status(ns)

        assert rc == 0
        out = capsys.readouterr().out
        assert "Merge queue lineage:" in out
        assert "run=26062256385 pr=3450 outcome=success" in out
        assert "branch_protection_check_mapping" in out
        assert "clean PR has no auto-merge request" in out


class TestClassifyPR:
    def test_failed(self, gov_module):
        pr = {"statusCheckRollup": [{"conclusion": "FAILURE"}], "mergeStateStatus": ""}
        assert gov_module.classify_pr(pr) == "failed"

    def test_pending(self, gov_module):
        pr = {"statusCheckRollup": [{"status": "IN_PROGRESS"}], "mergeStateStatus": ""}
        assert gov_module.classify_pr(pr) == "pending"

    def test_behind(self, gov_module):
        pr = {"statusCheckRollup": [{"conclusion": "SUCCESS"}], "mergeStateStatus": "BEHIND"}
        assert gov_module.classify_pr(pr) == "behind"

    def test_blocked(self, gov_module):
        pr = {"statusCheckRollup": [{"conclusion": "SUCCESS"}], "mergeStateStatus": "BLOCKED"}
        assert gov_module.classify_pr(pr) == "blocked"

    def test_green(self, gov_module):
        pr = {"statusCheckRollup": [{"conclusion": "SUCCESS"}], "mergeStateStatus": "CLEAN"}
        assert gov_module.classify_pr(pr) == "green"


class TestAdmissionLibrary:
    def test_normal_mode_allows_anything(self, gov_module):
        # Default (no file) is normal
        allowed, reason = gov_module.is_admission_allowed("alpha/anything-new")
        assert allowed is True
        assert "normal" in reason

    def test_frozen_blocks_new_branch(self, gov_module):
        state = gov_module.load_state()
        state["mode"] = "frozen"
        state["allowed_existing_branches"] = ["alpha/snapshot-branch"]
        gov_module.save_state(state)

        allowed, reason = gov_module.is_admission_allowed("alpha/never-snapshotted")
        assert allowed is False
        assert "frozen" in reason

    def test_frozen_allows_snapshot_branch(self, gov_module):
        state = gov_module.load_state()
        state["mode"] = "frozen"
        state["allowed_existing_branches"] = ["alpha/snapshot-branch"]
        gov_module.save_state(state)

        allowed, reason = gov_module.is_admission_allowed("alpha/snapshot-branch")
        assert allowed is True
        assert "snapshot" in reason


class TestNormalCommand:
    def test_refuses_to_clear_when_failure_rate_freeze_active(self, gov_module, capsys):
        state = gov_module.load_state()
        state["mode"] = "frozen"
        state["stable_ticks_observed"] = 0
        gov_module.save_state(state)

        with (
            patch.object(
                gov_module, "query_open_prs", return_value=[{"number": i} for i in range(4)]
            ),
            patch.object(
                gov_module,
                "current_throttle_decision",
                return_value=_throttle(
                    frozen=True,
                    state="rate_freeze",
                    reason="merge failure_rate 75% >= 50% over 4 runs",
                    failure_rate=0.75,
                    samples=4,
                    open_pr_count=4,
                ),
            ),
        ):
            ns = type("NS", (), {"reason": "test", "force": False})()
            rc = gov_module.cmd_normal(ns)

        assert rc == 1  # refused
        loaded = gov_module.load_state()
        assert loaded["mode"] == "frozen"
        assert loaded["stable_ticks_observed"] == 0

    def test_clears_when_failure_rate_throttle_is_calm(self, gov_module):
        state = gov_module.load_state()
        state["mode"] = "frozen"
        state["stable_ticks_observed"] = 1
        gov_module.save_state(state)

        with (
            patch.object(
                gov_module, "query_open_prs", return_value=[{"number": i} for i in range(20)]
            ),
            patch.object(
                gov_module,
                "current_throttle_decision",
                return_value=_throttle(
                    frozen=False,
                    state="busy",
                    reason="20 open PRs advisory; merge queue serializes",
                    open_pr_count=20,
                ),
            ),
        ):
            ns = type("NS", (), {"reason": "test", "force": False})()
            rc = gov_module.cmd_normal(ns)

        assert rc == 0  # cleared
        loaded = gov_module.load_state()
        assert loaded["mode"] == "normal"
        assert loaded["stable_ticks_observed"] == 0  # reset on clear

    def test_force_clears_regardless(self, gov_module):
        state = gov_module.load_state()
        state["mode"] = "frozen"
        state["stable_ticks_observed"] = 0
        gov_module.save_state(state)

        with patch.object(
            gov_module, "query_open_prs", return_value=[{"number": i} for i in range(20)]
        ):
            ns = type("NS", (), {"reason": "operator override", "force": True})()
            rc = gov_module.cmd_normal(ns)

        assert rc == 0
        loaded = gov_module.load_state()
        assert loaded["mode"] == "normal"


class TestAutoCmd:
    def test_auto_freezes_when_failure_rate_threshold_crossed(self, gov_module):
        with (
            patch.object(
                gov_module,
                "query_open_prs",
                return_value=[{"number": i, "headRefName": f"branch-{i}"} for i in range(3)],
            ),
            patch.object(
                gov_module,
                "current_throttle_decision",
                return_value=_throttle(
                    frozen=True,
                    state="rate_freeze",
                    reason="merge failure_rate 100% >= 50% over 4 runs",
                    failure_rate=1.0,
                    samples=4,
                    open_pr_count=3,
                ),
            ),
        ):
            ns = type("NS", (), {})()
            rc = gov_module.cmd_auto(ns)
        assert rc == 0
        loaded = gov_module.load_state()
        assert loaded["mode"] == "frozen"
        assert loaded["set_by"] == "auto"
        assert "auto-freeze" in loaded["reason"]
        assert len(loaded["allowed_existing_branches"]) == 3

    def test_auto_no_op_when_below_threshold_in_normal(self, gov_module):
        with (
            patch.object(
                gov_module,
                "query_open_prs",
                return_value=[{"number": i, "headRefName": f"b{i}"} for i in range(5)],
            ),
            patch.object(gov_module, "current_throttle_decision", return_value=_throttle()),
        ):
            ns = type("NS", (), {})()
            rc = gov_module.cmd_auto(ns)
        assert rc == 0
        loaded = gov_module.load_state()
        assert loaded["mode"] == "normal"

    def test_auto_clears_when_failure_rate_throttle_is_calm(self, gov_module):
        state = gov_module.load_state()
        state["mode"] = "frozen"
        state["stable_ticks_observed"] = 1
        gov_module.save_state(state)

        with (
            patch.object(
                gov_module,
                "query_open_prs",
                return_value=[{"number": i, "headRefName": f"b{i}"} for i in range(12)],
            ),
            patch.object(
                gov_module,
                "current_throttle_decision",
                return_value=_throttle(
                    frozen=False,
                    state="busy",
                    reason="12 open PRs advisory; merge queue serializes",
                    open_pr_count=12,
                ),
            ),
        ):
            ns = type("NS", (), {})()
            rc = gov_module.cmd_auto(ns)

        assert rc == 0
        loaded = gov_module.load_state()
        assert loaded["mode"] == "normal"
        assert loaded["set_by"] == "auto"
        assert "auto-clear" in loaded["reason"]

    def test_auto_keeps_freeze_when_failure_rate_throttle_is_frozen(self, gov_module):
        state = gov_module.load_state()
        state["mode"] = "frozen"
        state["stable_ticks_observed"] = 0
        gov_module.save_state(state)

        with (
            patch.object(
                gov_module,
                "query_open_prs",
                return_value=[{"number": i, "headRefName": f"b{i}"} for i in range(4)],
            ),
            patch.object(
                gov_module,
                "current_throttle_decision",
                return_value=_throttle(
                    frozen=True,
                    state="rate_freeze",
                    reason="merge failure_rate 75% >= 50% over 4 runs",
                    failure_rate=0.75,
                    samples=4,
                    open_pr_count=4,
                ),
            ),
        ):
            ns = type("NS", (), {})()
            rc = gov_module.cmd_auto(ns)

        assert rc == 0
        loaded = gov_module.load_state()
        assert loaded["mode"] == "frozen"
        assert loaded["stable_ticks_observed"] == 0

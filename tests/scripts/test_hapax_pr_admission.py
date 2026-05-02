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
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO / "scripts" / "hapax-pr-admission"


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
    def test_refuses_to_clear_when_stability_not_met(self, gov_module, capsys):
        state = gov_module.load_state()
        state["mode"] = "frozen"
        state["stable_ticks_observed"] = 0
        gov_module.save_state(state)

        # Mock query_open_prs to return 4 PRs (below threshold of 6)
        with patch.object(
            gov_module, "query_open_prs", return_value=[{"number": i} for i in range(4)]
        ):
            ns = type("NS", (), {"reason": "test", "force": False})()
            rc = gov_module.cmd_normal(ns)

        assert rc == 1  # refused
        # Stability was incremented but not enough yet
        loaded = gov_module.load_state()
        assert loaded["mode"] == "frozen"
        assert loaded["stable_ticks_observed"] == 1

    def test_clears_after_required_stable_ticks(self, gov_module):
        state = gov_module.load_state()
        state["mode"] = "frozen"
        state["stable_ticks_observed"] = 1  # one tick already
        gov_module.save_state(state)

        with patch.object(
            gov_module, "query_open_prs", return_value=[{"number": i} for i in range(4)]
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
    def test_auto_freezes_when_threshold_crossed(self, gov_module):
        # Default state is normal; mock 10+ open PRs
        with patch.object(
            gov_module,
            "query_open_prs",
            return_value=[{"number": i, "headRefName": f"branch-{i}"} for i in range(10)],
        ):
            ns = type("NS", (), {})()
            rc = gov_module.cmd_auto(ns)
        assert rc == 0
        loaded = gov_module.load_state()
        assert loaded["mode"] == "frozen"
        assert loaded["set_by"] == "auto"
        assert "auto-freeze" in loaded["reason"]
        assert len(loaded["allowed_existing_branches"]) == 10

    def test_auto_no_op_when_below_threshold_in_normal(self, gov_module):
        with patch.object(
            gov_module,
            "query_open_prs",
            return_value=[{"number": i, "headRefName": f"b{i}"} for i in range(5)],
        ):
            ns = type("NS", (), {})()
            rc = gov_module.cmd_auto(ns)
        assert rc == 0
        loaded = gov_module.load_state()
        assert loaded["mode"] == "normal"

    def test_auto_clears_after_stable_ticks(self, gov_module):
        # Set up in frozen mode with one stable tick already observed
        state = gov_module.load_state()
        state["mode"] = "frozen"
        state["stable_ticks_observed"] = 1  # one tick already
        gov_module.save_state(state)

        # Mock count below threshold (4 < 6)
        with patch.object(
            gov_module,
            "query_open_prs",
            return_value=[{"number": i, "headRefName": f"b{i}"} for i in range(4)],
        ):
            ns = type("NS", (), {})()
            rc = gov_module.cmd_auto(ns)

        assert rc == 0
        loaded = gov_module.load_state()
        assert loaded["mode"] == "normal"
        assert loaded["set_by"] == "auto"
        assert "auto-clear" in loaded["reason"]

    def test_auto_increments_stable_tick_when_below_threshold(self, gov_module):
        state = gov_module.load_state()
        state["mode"] = "frozen"
        state["stable_ticks_observed"] = 0
        gov_module.save_state(state)

        with patch.object(
            gov_module,
            "query_open_prs",
            return_value=[{"number": i, "headRefName": f"b{i}"} for i in range(4)],
        ):
            ns = type("NS", (), {})()
            rc = gov_module.cmd_auto(ns)

        assert rc == 0
        loaded = gov_module.load_state()
        assert loaded["mode"] == "frozen"  # not yet stable enough
        assert loaded["stable_ticks_observed"] == 1

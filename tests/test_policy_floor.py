"""Tests for the daemon-independent embedded enforcement floor (Phase 3a).

The floor is the safety-critical fallback the bash shim runs when the kernel is
down (NEW-CATCH-2): it MUST fail-closed on every irreversible-harm class and MUST
NEVER raise. Coordination reform Phase 3a.
"""

import json

import pytest

from shared.policy_decision import FailMode, Verdict
from shared.policy_floor import evaluate_floor, main


class TestIrreversibleHarmFailsClosed:
    @pytest.mark.parametrize(
        "tool_name,command,file_path",
        [
            ("Bash", "gh pr merge 3761", ""),
            ("mcp__github__merge_pull_request", "", ""),
            ("Bash", "gh api repos/o/r/pulls/3761/merge -X PUT", ""),
        ],
    )
    def test_merge_blocks(self, tool_name, command, file_path):
        d = evaluate_floor(tool_name, command=command, file_path=file_path)
        assert d.blocked and d.fail_mode is FailMode.FAIL_CLOSED
        assert d.gate == "floor:merge"

    @pytest.mark.parametrize(
        "tool_name,command",
        [
            ("Bash", "git push origin main"),
            ("Bash", "gh pr create --base main"),
            ("mcp__github__create_pull_request", ""),
            ("mcp__github__push_files", ""),
        ],
    )
    def test_release_blocks(self, tool_name, command):
        d = evaluate_floor(tool_name, command=command)
        assert d.blocked and d.fail_mode is FailMode.FAIL_CLOSED
        assert d.gate == "floor:release"

    @pytest.mark.parametrize(
        "file_path",
        ["axioms/registry.yaml", "shared/governance/consent.py", "/abs/repo/axioms/x.py"],
    )
    def test_axiom_path_blocks(self, file_path):
        d = evaluate_floor("Edit", file_path=file_path)
        assert d.blocked and d.fail_mode is FailMode.FAIL_CLOSED
        assert d.gate == "floor:axiom"

    def test_axiom_via_bash_blocks(self):
        d = evaluate_floor("Bash", command="sed -i s/a/b/ axioms/registry.yaml")
        # sed is not merge/release; the axiom path token trips the axiom floor.
        assert d.blocked and d.gate == "floor:axiom"

    def test_egress_path_blocks(self):
        d = evaluate_floor("Write", file_path="config/publication-hardening/known-entities.yaml")
        assert d.blocked and d.gate == "floor:egress"

    def test_egress_command_blocks(self):
        d = evaluate_floor("Bash", command="hapax-publish --surface mastodon")
        assert d.blocked and d.gate == "floor:egress"


class TestReversibleFailsOpenWithLedger:
    @pytest.mark.parametrize(
        "tool_name,command,file_path",
        [
            ("Edit", "", "/tmp/x"),
            ("Edit", "", "shared/config.py"),
            ("Bash", "pytest tests/ -q", ""),
            ("Bash", "git commit -m wip", ""),
            ("Write", "", "agents/foo.py"),
        ],
    )
    def test_reversible_allows_with_ledger(self, tool_name, command, file_path):
        d = evaluate_floor(tool_name, command=command, file_path=file_path)
        assert d.allowed and d.fail_mode is FailMode.FAIL_OPEN_WITH_LEDGER
        assert d.gate == "floor:reversible"


class TestRobustness:
    @pytest.mark.parametrize(
        "command",
        ["", "   ", "git push 'unterminated", "\x00\x01", "gh", "&&&", "a" * 5000],
    )
    def test_never_raises_on_hostile_input(self, command):
        d = evaluate_floor("Bash", command=command)
        assert d.verdict in (Verdict.ALLOW, Verdict.BLOCK)

    def test_decision_carries_version_stamp(self):
        d = evaluate_floor("Edit", file_path="/tmp/x")
        assert d.policy_version  # non-empty version stamp for bisection

    def test_merge_takes_precedence_over_reversible(self):
        # A command that contains both a merge head and other tokens still blocks.
        d = evaluate_floor("Bash", command="gh pr merge 3761 --squash")
        assert d.blocked


class TestCliEntrypoint:
    """The shim's daemon-independent interface: JSON out + exit 0 (allow) / 2 (block)."""

    def test_cli_reversible_exits_0(self, capsys):
        rc = main(["Edit", "--file", "/tmp/x"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert out["verdict"] == "allow"
        assert out["fail_mode"] == "fail_open_with_ledger"

    def test_cli_merge_exits_2(self, capsys):
        rc = main(["Bash", "--command", "gh pr merge 1"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 2
        assert out["verdict"] == "block"
        assert out["gate"] == "floor:merge"
        assert out["policy_version"]

    def test_cli_axiom_edit_exits_2(self, capsys):
        rc = main(["Edit", "--file", "axioms/registry.yaml"])
        json.loads(capsys.readouterr().out)
        assert rc == 2

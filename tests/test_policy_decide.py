"""Tests for the pure policy-decide function + shadow-diff harness (Phase 3b).

Coordination reform Phase 3b (master design section 4.1). ``policy_decide`` is
the net-new pure decision function that lifts the cc-task-gate's high-frequency
decisions — claim / status / stage / scope / authority — into one typed
``Decision`` (Phase 3a). When the kernel is down it delegates to the embedded
``policy_floor`` so the irreversible-harm floor stays the single source of truth.

The shadow-diff harness computes the legacy bash-gate verdict alongside the new
``policy_decide`` verdict and records any divergence to a ledger WITHOUT raising —
the evidence that justifies the eventual cutover. NO live enforcement changes in
this slice: the bash gate remains authoritative.
"""

import json
import os

import pytest

from shared.policy_decide import (
    TaskState,
    ToolCall,
    legacy_bash_scope_block,
    main,
    policy_decide,
    record_divergence,
    run_shadow,
    shadow_compare,
)
from shared.policy_decision import FailMode, Verdict

# --- Fixtures: a fully-authorized task (the common allow path) ----------------


def _authorized_task(**overrides) -> TaskState:
    base = dict(
        task_id="reform-phase3b-policy-decide-shadow-20260530",
        assigned_to="theta",
        status="in_progress",
        authority_case="CASE-FORMAL-GOVERNANCE-001",
        parent_spec="~/Documents/Personal/30-areas/hapax/coordination-reform-master-design-2026-05-30.md",
        stage="S6_IMPLEMENTATION",
        implementation_authorized=True,
        source_mutation_authorized=True,
        docs_mutation_authorized=True,
        runtime_mutation_authorized=False,
        mutation_scope_refs=("shared/policy_decide.py", "tests/"),
    )
    base.update(overrides)
    return TaskState(**base)


def _edit(path: str) -> ToolCall:
    return ToolCall(tool_name="Edit", file_path=path)


def _bash(cmd: str) -> ToolCall:
    return ToolCall(tool_name="Bash", command=cmd)


# --- policy_decide: the common ALLOW path (parity) ----------------------------


class TestAllowPath:
    def test_in_scope_source_edit_on_authorized_task_allows(self):
        d = policy_decide(_edit("shared/policy_decide.py"), _authorized_task(), "theta")
        assert d.allowed
        assert d.gate == "authorized"

    def test_in_scope_dir_prefix_allows(self):
        d = policy_decide(_edit("tests/test_policy_decide.py"), _authorized_task(), "theta")
        assert d.allowed

    def test_ready_family_status_can_still_mutate(self):
        # The un-stranding (FM-5/G2): the ~88 `ready` tasks must remain mutable.
        d = policy_decide(
            _edit("shared/policy_decide.py"), _authorized_task(status="ready"), "theta"
        )
        assert d.allowed

    def test_non_mutating_tool_always_allows(self):
        d = policy_decide(ToolCall(tool_name="Read", file_path="anything"), None, None)
        assert d.allowed
        assert d.gate == "non-mutating"

    def test_read_only_bash_allows_without_claim(self):
        d = policy_decide(_bash("git status -sb"), None, "theta")
        assert d.allowed
        assert d.gate == "non-mutating"

    def test_cognition_path_write_always_allows(self):
        # A blocked lane can always write its memory — even with no task/role.
        path = os.path.expanduser("~/.claude/projects/x/memory/note.md")
        d = policy_decide(ToolCall(tool_name="Write", file_path=path), None, None)
        assert d.allowed
        assert d.gate == "cognition"


# --- policy_decide: claim / identity / assignment blocks ----------------------


class TestClaimAndIdentity:
    def test_no_role_blocks_identity(self):
        d = policy_decide(_edit("shared/policy_decide.py"), _authorized_task(), None)
        assert d.blocked
        assert d.gate == "identity"

    def test_no_claimed_task_blocks(self):
        d = policy_decide(_edit("shared/policy_decide.py"), None, "theta")
        assert d.blocked
        assert d.gate == "claim"

    def test_assignment_mismatch_blocks(self):
        d = policy_decide(
            _edit("shared/policy_decide.py"), _authorized_task(assigned_to="alpha"), "theta"
        )
        assert d.blocked
        assert d.gate == "assignment"
        assert d.current_value == "alpha"


# --- policy_decide: status gate ----------------------------------------------


class TestStatusGate:
    @pytest.mark.parametrize("status", ["done", "withdrawn", "superseded", "refused"])
    def test_terminal_status_blocks(self, status):
        d = policy_decide(
            _edit("shared/policy_decide.py"), _authorized_task(status=status), "theta"
        )
        assert d.blocked
        assert d.gate == "status:terminal"

    def test_blocked_status_blocks(self):
        d = policy_decide(
            _edit("shared/policy_decide.py"), _authorized_task(status="blocked"), "theta"
        )
        assert d.blocked
        assert d.gate == "status:blocked"

    @pytest.mark.parametrize("status", ["offered", ""])
    def test_unclaimed_status_blocks(self, status):
        d = policy_decide(
            _edit("shared/policy_decide.py"), _authorized_task(status=status), "theta"
        )
        assert d.blocked
        assert d.gate == "status:unclaimed"

    def test_unknown_status_blocks(self):
        d = policy_decide(
            _edit("shared/policy_decide.py"), _authorized_task(status="banana"), "theta"
        )
        assert d.blocked
        assert d.gate == "status:unknown"


# --- policy_decide: authority gate -------------------------------------------


class TestAuthorityGate:
    @pytest.mark.parametrize("value", [None, "", "null", "~"])
    def test_missing_authority_case_blocks(self, value):
        d = policy_decide(
            _edit("shared/policy_decide.py"), _authorized_task(authority_case=value), "theta"
        )
        assert d.blocked
        assert d.gate == "authority:case"

    @pytest.mark.parametrize("value", [None, "", "null"])
    def test_missing_parent_spec_blocks(self, value):
        d = policy_decide(
            _edit("shared/policy_decide.py"), _authorized_task(parent_spec=value), "theta"
        )
        assert d.blocked
        assert d.gate == "authority:parent_spec"

    def test_source_edit_without_source_auth_blocks(self):
        d = policy_decide(
            _edit("shared/policy_decide.py"),
            _authorized_task(source_mutation_authorized=False),
            "theta",
        )
        assert d.blocked
        assert d.gate == "authority:source"

    def test_implementation_not_authorized_blocks(self):
        d = policy_decide(
            _edit("shared/policy_decide.py"),
            _authorized_task(implementation_authorized=False),
            "theta",
        )
        assert d.blocked
        assert d.gate == "authority:implementation"

    def test_runtime_bash_without_runtime_auth_blocks(self):
        d = policy_decide(
            _bash("systemctl --user restart hapax-logos"),
            _authorized_task(runtime_mutation_authorized=False),
            "theta",
        )
        assert d.blocked
        assert d.gate == "authority:runtime"

    def test_runtime_bash_with_runtime_auth_allows(self):
        d = policy_decide(
            _bash("systemctl --user restart hapax-logos"),
            _authorized_task(runtime_mutation_authorized=True),
            "theta",
        )
        assert d.allowed


# --- policy_decide: stage gate (+ FR-STAGE-S6-TRAP derive) --------------------


class TestStageGate:
    def test_pre_s6_stage_blocks_source(self):
        d = policy_decide(
            _edit("shared/policy_decide.py"), _authorized_task(stage="S3_DESIGN"), "theta"
        )
        assert d.blocked
        assert d.gate == "stage"

    def test_blank_stage_with_full_authority_derives_s6_and_allows(self):
        # FR-STAGE-S6-TRAP: a blank stage on an otherwise fully-authorized task is
        # a template gap, not a stage deficiency — derive S6 rather than brick.
        d = policy_decide(_edit("shared/policy_decide.py"), _authorized_task(stage=None), "theta")
        assert d.allowed


# --- policy_decide: docs surface ---------------------------------------------


class TestDocsSurface:
    def test_docs_edit_skips_stage_when_docs_authorized(self):
        # Docs edits may precede S6 implementation when docs mutation is authorized
        # (the gate still scope-checks the path, so the docs path is in scope here).
        d = policy_decide(
            ToolCall(tool_name="Edit", file_path="docs/notes.md"),
            _authorized_task(
                stage="S3_DESIGN",
                source_mutation_authorized=False,
                mutation_scope_refs=("docs/",),
            ),
            "theta",
        )
        assert d.allowed

    def test_docs_edit_without_docs_or_source_auth_blocks(self):
        d = policy_decide(
            ToolCall(tool_name="Edit", file_path="docs/notes.md"),
            _authorized_task(docs_mutation_authorized=False, source_mutation_authorized=False),
            "theta",
        )
        assert d.blocked
        assert d.gate == "authority:docs"


# --- policy_decide: scope gate -----------------------------------------------


class TestScopeGate:
    def test_out_of_scope_edit_blocks(self):
        d = policy_decide(_edit("agents/other.py"), _authorized_task(), "theta")
        assert d.blocked
        assert d.gate == "scope:denied"

    def test_missing_scope_refs_blocks(self):
        d = policy_decide(
            _edit("shared/policy_decide.py"),
            _authorized_task(mutation_scope_refs=()),
            "theta",
        )
        assert d.blocked
        assert d.gate == "scope:missing"


# --- policy_decide: kernel-down floor delegation ------------------------------


class TestKernelDownDelegatesToFloor:
    def test_kernel_down_merge_blocks_via_floor(self):
        d = policy_decide(_bash("gh pr merge 3762"), _authorized_task(), "theta", kernel_up=False)
        assert d.blocked
        assert d.gate == "floor:merge"
        assert d.fail_mode is FailMode.FAIL_CLOSED

    def test_kernel_down_reversible_allows_fail_open(self):
        d = policy_decide(
            _edit("shared/policy_decide.py"), _authorized_task(), "theta", kernel_up=False
        )
        assert d.allowed
        assert d.gate == "floor:reversible"
        assert d.fail_mode is FailMode.FAIL_OPEN_WITH_LEDGER

    def test_kernel_down_axiom_edit_blocks_via_floor(self):
        d = policy_decide(
            ToolCall(tool_name="Edit", file_path="axioms/registry.yaml"),
            None,
            None,
            kernel_up=False,
        )
        assert d.blocked
        assert d.gate == "floor:axiom"


# --- legacy classifier (the FM-16 locus, ported verbatim) ---------------------


class TestLegacyBashScopeBlock:
    @pytest.mark.parametrize(
        "command",
        [
            "git checkout -b theta/reform-phase3b origin/main",
            "git switch -c feature",
            "sed -i s/a/b/ shared/config.py",
            "cp a b",
            "mkdir -p /run/user/1000/x",
        ],
    )
    def test_legacy_blocks_these(self, command):
        assert legacy_bash_scope_block(command) is True

    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m 'wip'",
            "git push origin HEAD",
            "git add -A",
            "pytest tests/ -q",
            "printf x > /tmp/y",
        ],
    )
    def test_legacy_allows_these(self, command):
        assert legacy_bash_scope_block(command) is False

    def test_legacy_ignores_mutation_token_inside_quoted_message(self):
        # `git commit -m "remove the rm and mv helpers"` must not trip on rm/mv.
        assert legacy_bash_scope_block('git commit -m "remove the rm and mv helpers"') is False


# --- the FM-16 fix: the new classifier does NOT scope-block a branch op -------


class TestNewClassifierFixesFM16:
    def test_branch_creation_is_not_a_source_mutation(self):
        # The case-in-chief: `git checkout -b <branch>` creates a ref, writes no
        # source. The legacy substring gate blocks it; policy_decide allows it.
        cmd = "git checkout -b theta/reform-phase3b origin/main"
        assert legacy_bash_scope_block(cmd) is True
        d = policy_decide(_bash(cmd), _authorized_task(), "theta")
        assert d.allowed


# --- shadow-diff harness ------------------------------------------------------


class TestShadowCompare:
    def test_records_divergence_when_legacy_blocks_but_new_allows(self):
        cmd = "git checkout -b theta/reform-phase3b origin/main"
        rec = shadow_compare(_bash(cmd), _authorized_task(), "theta", legacy_blocked=True)
        assert rec.diverged is True
        assert rec.new_decision.allowed
        assert rec.legacy_blocked is True

    def test_no_divergence_when_both_allow(self):
        rec = shadow_compare(
            _edit("shared/policy_decide.py"),
            _authorized_task(),
            "theta",
            legacy_blocked=False,
        )
        assert rec.diverged is False

    def test_no_divergence_when_both_block(self):
        rec = shadow_compare(
            _edit("agents/other.py"), _authorized_task(), "theta", legacy_blocked=True
        )
        assert rec.diverged is False
        assert rec.new_decision.blocked

    def test_never_raises_on_hostile_input(self):
        rec = shadow_compare(
            ToolCall(tool_name="Bash", command="\x00&&&'unterminated"),
            None,
            None,
            legacy_blocked=False,
        )
        assert rec.diverged in (True, False)


class TestRecordDivergence:
    def test_appends_jsonl_record(self, tmp_path):
        ledger = tmp_path / "shadow.jsonl"
        cmd = "git checkout -b feature origin/main"
        rec = shadow_compare(_bash(cmd), _authorized_task(), "theta", legacy_blocked=True)
        record_divergence(rec, ledger_path=ledger)
        lines = ledger.read_text().strip().splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["diverged"] is True
        assert row["tool_name"] == "Bash"
        assert row["legacy_blocked"] is True
        assert row["new_verdict"] == "allow"
        assert row["policy_version"]
        # The divergence is traceable to the task it occurred under (cutover evidence).
        assert row["task_id"] == _authorized_task().task_id

    def test_never_raises_on_unwritable_path(self):
        rec = shadow_compare(
            _edit("shared/policy_decide.py"), _authorized_task(), "theta", legacy_blocked=False
        )
        # A directory that cannot exist must not raise — the harness is advisory.
        record_divergence(rec, ledger_path="/this/does/not/exist/shadow.jsonl")


class TestRunShadow:
    def test_logs_only_on_divergence(self, tmp_path):
        ledger = tmp_path / "shadow.jsonl"
        # divergent → logged
        run_shadow(
            _bash("git checkout -b f origin/main"),
            _authorized_task(),
            "theta",
            legacy_blocked=True,
            ledger_path=ledger,
        )
        # agreeing → not logged
        run_shadow(
            _edit("shared/policy_decide.py"),
            _authorized_task(),
            "theta",
            legacy_blocked=False,
            ledger_path=ledger,
        )
        lines = ledger.read_text().strip().splitlines()
        assert len(lines) == 1

    def test_returns_record(self, tmp_path):
        rec = run_shadow(
            _edit("shared/policy_decide.py"),
            _authorized_task(),
            "theta",
            legacy_blocked=False,
            ledger_path=tmp_path / "s.jsonl",
        )
        assert rec.new_decision.allowed


# --- robustness ---------------------------------------------------------------


class TestRobustness:
    @pytest.mark.parametrize(
        "command", ["", "   ", "git push 'unterminated", "\x00\x01", "&&&", "a" * 5000]
    )
    def test_policy_decide_never_raises_on_hostile_bash(self, command):
        d = policy_decide(_bash(command), _authorized_task(), "theta")
        assert d.verdict in (Verdict.ALLOW, Verdict.BLOCK)

    def test_decision_carries_version_stamp(self):
        d = policy_decide(_edit("shared/policy_decide.py"), _authorized_task(), "theta")
        assert d.policy_version


# --- the shadow CLI (advisory; never enforces) --------------------------------


class TestShadowCli:
    def test_cli_is_advisory_and_always_exits_zero(self, capsys, tmp_path):
        # ADVISORY ONLY: the CLI prints the comparison and never enforces (exit 0),
        # even when policy_decide blocks. The bash gate stays authoritative.
        rc = main(
            [
                "Edit",
                "--file",
                "axioms/registry.yaml",
                "--ledger",
                str(tmp_path / "s.jsonl"),
            ]
        )
        out = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert out["new_verdict"] in ("allow", "block")
        assert "diverged" in out

    def test_cli_auto_computes_legacy_and_logs_divergence_with_task(self, capsys, tmp_path):
        ledger = tmp_path / "s.jsonl"
        task_json = json.dumps(
            {
                "task_id": "T-1",
                "assigned_to": "theta",
                "status": "in_progress",
                "authority_case": "C",
                "parent_spec": "P",
                "stage": "S6",
                "implementation_authorized": True,
                "source_mutation_authorized": True,
                "mutation_scope_refs": ["shared/policy_decide.py"],
            }
        )
        rc = main(
            [
                "Bash",
                "--command",
                "git checkout -b f origin/main",
                "--role",
                "theta",
                "--task-json",
                task_json,
                "--ledger",
                str(ledger),
            ]
        )
        assert rc == 0
        capsys.readouterr()
        row = json.loads(ledger.read_text().strip())
        # Legacy (substring) blocks the branch op; the new classifier allows it.
        assert row["diverged"] is True
        assert row["legacy_blocked"] is True
        assert row["new_verdict"] == "allow"
        assert row["task_id"] == "T-1"

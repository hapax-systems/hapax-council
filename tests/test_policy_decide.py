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
from hypothesis import given
from hypothesis import strategies as st

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


# --- the scope-normalization fix: absolute worktree paths resolve repo-relative --
#
# REGRESSION (reform-improve-policy-decide-scope-fix): `_scope_result` string-
# compared an ABSOLUTE worktree `file_path` against REPO-RELATIVE scope refs, so
# `startswith` never matched -> 220+ false `scope:denied` TIGHTENINGS that made the
# 3b-cutover gate (asymmetric_ok = tightening==0) structurally unreachable. The
# replay diffs decisions logged from MANY worktrees in ONE process with no recorded
# cwd, so the fix reduces BOTH sides to repo-relative form independent of Path.cwd()
# (it cannot mirror the live gate's cwd-anchored resolve — replay's cwd is not the
# decision's worktree).

#: A worktree-root prefix carrying a `projects/` anchor, built via expanduser so no
#: home-path literal lives in source (portable across CI / operator machines).
_WT = os.path.join(os.path.expanduser("~"), "projects")


class TestScopeAbsoluteWorktreePaths:
    def test_absolute_path_same_worktree_in_scope_allows(self):
        d = policy_decide(
            _edit(f"{_WT}/hapax-council--zeta/shared/policy_decide.py"),
            _authorized_task(mutation_scope_refs=("shared/policy_decide.py", "tests/")),
            "theta",
        )
        assert d.allowed, d.gate

    def test_absolute_path_different_worktree_in_scope_allows(self):
        # The replay runs in ONE worktree but the logged path is from ANOTHER
        # (epsilon). A cwd-anchored resolve would mis-resolve; repo-relative does not.
        d = policy_decide(
            _edit(f"{_WT}/hapax-council--epsilon/tests/test_vault_ownership.py"),
            _authorized_task(mutation_scope_refs=("tests/",)),
            "theta",
        )
        assert d.allowed, d.gate

    def test_absolute_path_sister_repo_in_scope_allows(self):
        # hapax-coord is a different repo entirely; the projects/<worktree>/ anchor
        # is repo-agnostic, so its relative refs resolve too.
        d = policy_decide(
            _edit(f"{_WT}/hapax-coord/shared/coord_event_log.py"),
            _authorized_task(mutation_scope_refs=("shared/coord_event_log.py",)),
            "theta",
        )
        assert d.allowed, d.gate

    def test_absolute_path_out_of_scope_still_denies(self):
        d = policy_decide(
            _edit(f"{_WT}/hapax-council--zeta/agents/other.py"),
            _authorized_task(mutation_scope_refs=("shared/policy_decide.py", "tests/")),
            "theta",
        )
        assert d.blocked
        assert d.gate == "scope:denied"

    def test_absolute_exact_file_ref_not_prefix_confused(self):
        # An exact-file ref must not allow a sibling that merely shares the prefix.
        d = policy_decide(
            _edit(f"{_WT}/hapax-council--zeta/shared/policy_decide_extra.py"),
            _authorized_task(mutation_scope_refs=("shared/policy_decide.py",)),
            "theta",
        )
        assert d.blocked
        assert d.gate == "scope:denied"

    @pytest.mark.parametrize("ref", ["tests/", "tests"])
    def test_trailing_slash_and_bare_dir_refs_equivalent(self, ref):
        d = policy_decide(
            _edit(f"{_WT}/hapax-council--beta/tests/scripts/test_x.py"),
            _authorized_task(mutation_scope_refs=(ref,)),
            "theta",
        )
        assert d.allowed, f"ref={ref!r} gate={d.gate}"

    def test_dot_slash_prefix_normalizes_on_both_sides(self):
        d = policy_decide(
            _edit("./shared/policy_decide.py"),
            _authorized_task(mutation_scope_refs=("./shared/policy_decide.py",)),
            "theta",
        )
        assert d.allowed, d.gate

    def test_inner_projects_segment_does_not_mis_anchor(self):
        # A repo that legitimately has a 'projects' dir of its own must anchor on the
        # workspace 'projects' (first occurrence), not the inner one.
        d = policy_decide(
            _edit(f"{_WT}/hapax-council--zeta/shared/projects/registry.py"),
            _authorized_task(mutation_scope_refs=("shared/projects/",)),
            "theta",
        )
        assert d.allowed, d.gate


class TestScopeAbsoluteRelativeParity:
    """The absolute worktree form must yield the SAME verdict as the repo-relative
    form — which is exactly what the live legacy gate returned (cwd == the worktree),
    so this is the shadow-parity contract the replay relies on."""

    @pytest.mark.parametrize(
        "rel_target,refs,expect_allow",
        [
            ("shared/policy_decide.py", ("shared/policy_decide.py",), True),
            ("tests/test_policy_decide.py", ("tests/",), True),
            ("scripts/policy-decide-shadow-eval", ("scripts/policy-decide-shadow-eval",), True),
            ("agents/x.py", ("shared/policy_decide.py", "tests/"), False),
        ],
    )
    def test_absolute_worktree_form_agrees_with_relative_form(self, rel_target, refs, expect_allow):
        task = _authorized_task(mutation_scope_refs=refs)
        rel = policy_decide(_edit(rel_target), task, "theta")
        for wt in ("hapax-council", "hapax-council--zeta", "hapax-council--epsilon"):
            ab = policy_decide(_edit(f"{_WT}/{wt}/{rel_target}"), task, "theta")
            assert ab.allowed == rel.allowed == expect_allow, f"{wt} {rel_target} gate={ab.gate}"


_SEGMENT = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=8)


class TestScopePropertyInvariant:
    @given(
        prefix=st.sampled_from(
            ["hapax-council", "hapax-council--zeta", "hapax-council--epsilon", "hapax-coord"]
        ),
        scope_dir=st.sampled_from(["tests", "shared", "scripts", "agents"]),
        trailing=st.booleans(),
        sub=st.lists(_SEGMENT, min_size=1, max_size=4),
    )
    def test_path_inside_scope_dir_always_allows_regardless_of_prefix(
        self, prefix, scope_dir, trailing, sub
    ):
        ref = scope_dir + ("/" if trailing else "")
        target = f"{_WT}/{prefix}/{scope_dir}/" + "/".join(sub) + ".py"
        d = policy_decide(_edit(target), _authorized_task(mutation_scope_refs=(ref,)), "theta")
        assert d.allowed, f"prefix={prefix} ref={ref!r} target={target} gate={d.gate}"

    @given(
        prefix=st.sampled_from(["hapax-council", "hapax-council--zeta", "hapax-coord"]),
        sub=st.lists(_SEGMENT, min_size=1, max_size=3),
    )
    def test_path_outside_all_scope_dirs_denies(self, prefix, sub):
        # 'agents/...' is never in this scope -> always denied, regardless of prefix.
        target = f"{_WT}/{prefix}/agents/" + "/".join(sub) + ".py"
        d = policy_decide(
            _edit(target), _authorized_task(mutation_scope_refs=("shared/", "tests/")), "theta"
        )
        assert d.blocked and d.gate == "scope:denied"


# --- residual TIGHTENING triage: the scope:command quote-strip parity fix ------
#
# After the _repo_relative fix above, replaying the REAL gate decision log left
# exactly ONE residual tightening: a `python3 -c "...open('/tmp/x','w')..."`
# verification heredoc. The legacy gate strips quoted spans BEFORE its shell-
# source-scope test (cc-task-gate.sh:791), so the `open(` living only inside the
# quoted -c payload does not count and the gate ALLOWS. policy_decide substring-
# matched `open(` on the RAW command and BLOCKED at scope:command — a regression,
# NOT a justified hardening (the reform design requires policy_decide to be a
# strict relaxation of the legacy gate). The fix mirrors the legacy strip at the
# scope:command site; these tests pin both the parity AND the fail-closed case
# where the marker is OUTSIDE any quoted span (a heredoc body) and must still block.


class TestScopeCommandQuoteStripParity:
    def test_open_inside_quoted_dash_c_payload_is_not_a_source_mutation(self):
        # THE residual tightening: open() lives only inside the double-quoted -c arg.
        cmd = "python3 -c \"import sys; open('/tmp/verify.lisp','w').write(sys.stdin.read())\""
        assert legacy_bash_scope_block(cmd) is False  # legacy strips the quoted span
        d = policy_decide(_bash(cmd), _authorized_task(), "theta")
        assert d.allowed, d.gate

    def test_quoted_open_with_stdin_heredoc_matches_live_residual_shape(self):
        # The exact shape from the live ledger: quoted -c open() + a stdin heredoc.
        cmd = (
            "python3 -c \"open('/tmp/x.lisp','w').write(sys.stdin.read())\" <<'LISPEOF'\n"
            '(format t "hi")\n'
            "LISPEOF"
        )
        assert legacy_bash_scope_block(cmd) is False
        d = policy_decide(_bash(cmd), _authorized_task(), "theta")
        assert d.allowed, d.gate

    def test_shadow_compare_reports_no_divergence_on_quoted_open(self):
        # The parity contract the replay relies on: same verdict as the legacy port,
        # so this class of command produces ZERO divergence rows (no false tightening).
        cmd = "python3 -c \"open('/tmp/x','w').write('y')\""
        rec = shadow_compare(
            _bash(cmd),
            _authorized_task(),
            "theta",
            legacy_blocked=legacy_bash_scope_block(cmd),
        )
        assert rec.diverged is False
        assert rec.new_decision.allowed

    def test_open_in_unquoted_heredoc_body_still_blocks_fail_closed(self):
        # Fail-closed preserved: when open() is NOT inside a quoted span (here a
        # heredoc body fed to a bare python3) the source-scope block still fires —
        # the quote-strip narrows ONLY the false positive, never the real writer.
        cmd = "python3 <<'PYEOF'\nopen('out.txt','w').write('x')\nPYEOF"
        d = policy_decide(_bash(cmd), _authorized_task(), "theta")
        assert d.blocked
        assert d.gate == "scope:command"

    def test_sed_inplace_without_edit_path_still_blocks(self):
        # Token-based source writers are unaffected by the strip: `sed -i` with no
        # Edit-tool path stays a scope:command block, in parity with the legacy gate.
        cmd = "sed -i 's/a/b/' shared/policy_decide.py"
        assert legacy_bash_scope_block(cmd) is True
        d = policy_decide(_bash(cmd), _authorized_task(), "theta")
        assert d.blocked
        assert d.gate == "scope:command"

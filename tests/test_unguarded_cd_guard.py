"""Tests for the unguarded-cd guard analyzer (PR #4091 fix round).

Every reviewer-named bypass from the review-team dossier
(alpha-direct-fixes-cdguard-abstention-20260611 @ 88641b25) is pinned here,
plus the allowed shapes from the hook's ALLOWS contract and the documented
policy decisions (strict trailing-statement rule, fail-open on payload).
Self-contained per testing conventions: no shared fixtures.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_ANALYZER = _REPO / "hooks" / "scripts" / "unguarded_cd_guard.py"
_WRAPPER = _REPO / "hooks" / "scripts" / "unguarded-cd-guard.sh"

_spec = importlib.util.spec_from_file_location("unguarded_cd_guard", _ANALYZER)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["unguarded_cd_guard"] = _mod
_spec.loader.exec_module(_mod)
analyze = _mod.analyze


def _blocked(command: str) -> bool:
    return analyze(command) is not None


# --- reviewer-named criticals: verified fail-open shapes must now block ---


def test_quoted_cd_target_blocks():
    # codex-1 / claude-1 critical: quote-stripping made `cd "$X"; y` invisible
    assert _blocked('cd "$HOME/proj"; git status')


def test_quoted_worktree_variable_blocks():
    assert _blocked('cd "$WORKTREE"; git add -A')


def test_single_quoted_target_blocks():
    assert _blocked("cd '/data/cache/x'; git add -A")


def test_set_e_after_cd_blocks():
    # codex-1 critical: errexit enabled only AFTER the fallible cd
    assert _blocked("cd missing; set -e; git add -A")


def test_set_e_substring_spoof_blocks():
    # claude-1: first line merely CONTAINING "set -e" used to allow everything
    assert _blocked('echo "never set -e here"\ncd /tmp\ngit status')


def test_or_true_swallows_failure_blocks():
    # claude-1 major: `|| true` recovers status, remainder runs in wrong dir
    assert _blocked("cd /tmp || true; rm -f foo")


def test_or_true_then_and_chain_blocks():
    # left-assoc: ((cd x || true) && rm) — rm runs after a swallowed failure
    assert _blocked("cd /missing || true && rm -rf scratch")


def test_subshell_internal_hazard_blocks():
    # claude-1 major: `(cd /tmp; git status)` — git runs in-subshell wrong dir
    assert _blocked("(cd /tmp; git status)")


def test_incident_shape_newline_blocks():
    # the original 2026-06-11 incident: failed cd, then git add in wrong tree
    assert _blocked("cd /data/cache/hapax/scratch/x\ngit add -A && git commit -m wip")


# --- documented-policy blocks (stricter than v1, deliberate) ---


def test_and_chain_with_trailing_statement_blocks():
    # `cd X && a; b` — b still runs when the cd fails. Policy: block.
    assert _blocked('cd "$HOME/proj" && git status; echo done')


def test_pushd_blocks_like_cd():
    assert _blocked("pushd /tmp; git add -A")


def test_builtin_cd_blocks():
    assert _blocked("builtin cd /tmp; ls")


def test_set_plus_e_reenables_hazard():
    assert _blocked("set -e; set +e; cd /tmp; git add -A")


def test_command_substitution_hazard_blocks():
    # wrong-directory READS were part of the incident class
    assert _blocked('echo "$(cd /missing; grep -r foo .)"')


def test_brace_group_hazard_blocks():
    # brace groups share the shell: interior failed cd poisons what follows
    assert _blocked("{ cd /tmp; git add -A; }")


def test_heredoc_then_real_cd_blocks():
    assert _blocked("cat <<EOF\nharmless text\nEOF\ncd /tmp\ngit status")


# --- ALLOWS contract ---


def test_set_e_first_line_allows():
    assert not _blocked("set -e\ncd /tmp\ngit add -A")


def test_set_euo_pipefail_allows():
    assert not _blocked("set -euo pipefail\ncd /tmp\ngit add -A")


def test_set_o_errexit_allows():
    assert not _blocked("set -o errexit\ncd /tmp\ngit add -A")


def test_real_set_e_on_line_two_gets_credit():
    # claude-1 minor (inverse): a real set -e BEFORE the cd counts, wherever
    assert not _blocked('echo "starting"\nset -e\ncd /tmp\ngit add -A')


def test_full_and_chain_allows():
    assert not _blocked("cd /tmp && git add -A && git commit -m x")


def test_or_exit_allows():
    assert not _blocked("cd /tmp || exit 1; git add -A")


def test_or_brace_exit_allows():
    assert not _blocked("cd /tmp || { echo no; exit 1; }; git add -A")


def test_final_cd_allows():
    assert not _blocked("git fetch -q\ncd /tmp")


def test_single_cd_allows():
    assert not _blocked('cd "$HOME/projects"')


def test_bare_cd_no_target_allows():
    assert not _blocked("cd\ngit status")


def test_git_dash_c_allows():
    assert not _blocked("git -C /tmp add -A; git -C /tmp commit -m x")


def test_guarded_subshell_with_trailing_allows():
    # inside: cd && git — failure skips git; parent cwd untouched after
    assert not _blocked("(cd /tmp && git status); echo done")


def test_backgrounded_cd_allows():
    # background job is a subshell with nothing after it inside
    assert not _blocked("cd /tmp & git status")


def test_cd_in_pipeline_allows():
    # each pipeline segment is a subshell; parent cwd unaffected
    assert not _blocked("cd /tmp | cat\ngit status")


def test_heredoc_body_cd_allows():
    assert not _blocked("cat <<EOF\ncd /tmp\ngit status\nEOF")


def test_quoted_heredoc_body_cd_allows():
    assert not _blocked("cat <<'EOF'\ncd /tmp\ngit status\nEOF")


def test_comment_cd_allows():
    assert not _blocked("# cd /tmp then work\ngit status")


def test_plain_multistatement_allows():
    assert not _blocked("echo a; echo b && echo c")


def test_cd_text_inside_quotes_allows():
    assert not _blocked('echo "cd /tmp; git status"\ngit log')


# --- adversarial-panel round (v3): execution-verified bypasses, pinned ---


def test_pipe_elsewhere_in_list_does_not_exempt_cd():
    # panel #1: `|` binds tighter than `&&`; the cd is NOT a pipeline segment
    assert _blocked("cd /nonexistent && git log --oneline | head; rm -f /tmp/lockfile")


def test_if_then_body_cd_blocks():
    assert _blocked("if true; then cd /nonexistent; fi; make")


def test_if_then_body_cd_with_inner_following_blocks():
    assert _blocked("if [ -d build ]; then cd build; make; fi")


def test_if_then_body_cd_outer_following_blocks():
    assert _blocked("if [ -d build ]; then cd build; fi; make")


def test_for_loop_body_cd_blocks():
    assert _blocked('for d in */; do cd "$d"; ./build.sh; done')


def test_while_loop_body_cd_blocks():
    assert _blocked('while read -r d; do cd "$d"; git pull; done')


def test_case_arm_cd_blocks():
    assert _blocked('case "$1" in build) cd /nonexistent; make ;; esac')


def test_case_arm_multiline_cd_blocks():
    assert _blocked('case "$1" in\n  build) cd /nonexistent_xyz; make;;\nesac\necho done')


def test_backslash_cd_blocks():
    assert _blocked("\\cd /nonexistent; git add -A")


def test_command_prefix_cd_blocks():
    assert _blocked("command cd /nonexistent; rm -rf tmp")


def test_time_prefix_cd_blocks():
    assert _blocked("time cd /nonexistent; make")


def test_eval_unquoted_cd_blocks():
    assert _blocked("eval cd /nonexistent; echo after")


def test_eval_quoted_cd_blocks():
    assert _blocked('eval "cd /x; git add"')


def test_heredoc_marker_inside_quotes_is_not_a_heredoc():
    # panel: a quoted `<<EOF` swallowed following REAL code as a body
    assert _blocked(
        'git commit -m "docs: document <<EOF heredoc syntax"\ncd dist && rm -rf old\ncp -r build/* .'
    )


def test_echoed_heredoc_marker_does_not_swallow_code():
    assert _blocked('echo "<<EOF"\ncd /nonexistent_xyz\necho poisoned')


def test_process_substitution_hazard_blocks():
    assert _blocked("diff <(cd /nonexistent_xyz; ls) /etc/hosts")


def test_output_process_substitution_hazard_blocks():
    assert _blocked("tee >(cd /nonexistent_xyz; cat) < /etc/hosts")


def test_unbalanced_brace_in_args_does_not_hide_cd():
    assert _blocked("echo {a\ncd /nonexistent_xyz\necho poisoned")


def test_conditional_set_e_gets_no_credit():
    # `set -e` behind && may never run — it must not arm errexit
    assert _blocked("[ -f .strict ] && set -e; cd build; make")


def test_set_plus_o_errexit_revokes():
    assert _blocked("set -e; pwd; set +o errexit; cd /x; git add -A")


def test_if_condition_cd_is_flow_controlled():
    # `if cd X; then ...` — the failure is consumed by the construct
    assert not _blocked("if cd /tmp; then make; fi")


def test_loop_or_continue_guard_allows():
    assert not _blocked('for d in */; do cd "$d" || continue; ./build.sh; done')


def test_brace_group_with_and_chain_then_and_successor_allows():
    # panel false-positive #30: the group's && successor is status-guarded
    assert not _blocked("{ cd /tmp/build && make; } && echo built")


def test_single_quoted_substitution_is_text():
    assert not _blocked(
        'echo \'ROOT=$(cd "$(dirname "$0")"; pwd)\' >> /tmp/snippet.sh; cat /tmp/snippet.sh'
    )


def test_single_quoted_backticks_are_text():
    assert not _blocked("git commit -m 'docs: replace `cd dir; make` with `git -C dir make`'")


def test_single_quoted_sed_program_is_text():
    assert not _blocked(
        "sed -i 's|$(cd src; make)|$(make -C src)|' Makefile.am; git diff Makefile.am"
    )


def test_hyphenated_heredoc_delimiter_strips_body():
    assert not _blocked(
        "cat <<'EOF-SCRIPT' > /tmp/deploy.sh\ncd /opt/app\ngit pull --ff-only\nEOF-SCRIPT\necho wrote"
    )


def test_quoted_cd_advice_in_echo_is_text():
    assert not _blocked(
        "echo 'Run `cd build; make` to compile' >> /tmp/README.md; cat /tmp/README.md"
    )


# --- wrapper / payload behavior (the documented fail-open choice) ---


def _run_wrapper(stdin_text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_WRAPPER)],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_wrapper_blocks_incident_shape_exit_2():
    payload = json.dumps({"tool_input": {"command": 'cd "$HOME/x"; git add -A'}})
    proc = _run_wrapper(payload)
    assert proc.returncode == 2
    assert "BLOCKED" in proc.stderr


def test_wrapper_allows_guarded_shape_exit_0():
    payload = json.dumps({"tool_input": {"command": "set -e\ncd /tmp\ngit add -A"}})
    assert _run_wrapper(payload).returncode == 0


def test_wrapper_malformed_payload_fails_open_exit_0():
    proc = _run_wrapper("this is not json")
    assert proc.returncode == 0
    assert "unparsable payload" in proc.stderr


def test_wrapper_empty_command_exit_0():
    assert _run_wrapper(json.dumps({"tool_input": {}})).returncode == 0


def test_analyzer_error_fails_open(monkeypatch=None):
    # alien grammar must not brick the shell: force an analyzer exception
    proc = subprocess.run(
        [sys.executable, str(_ANALYZER)],
        input=json.dumps({"tool_input": {"command": "cd /tmp; ls"}}),
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin", "HAPAX_UNGUARDED_CD_GUARD_OFF": "1"},
    )
    assert proc.returncode == 0  # killswitch honored == documented escape


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError:
                failures += 1
                print(f"FAIL {name}")
    sys.exit(1 if failures else 0)

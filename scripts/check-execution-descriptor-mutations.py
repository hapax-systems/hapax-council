#!/usr/bin/env python3
"""Run guard mutations in place, restoring each source byte-for-byte.

Run with uv run --no-sync python scripts/check-execution-descriptor-mutations.py.
No provider calls: the contract tests use captured fake harness invocations.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST = "tests/scripts/test_capability_execution_contract.py"
MUTATIONS = (
    (
        "literal model in dispatch",
        "scripts/hapax-methodology-dispatch",
        "from __future__ import annotations",
        'from __future__ import annotations\n# model="gpt-5.5"',
        "test_launchers_and_dispatch_have_no_literal_model_ids",
    ),
    (
        "restore config fallback",
        "config/codex/config.toml",
        'approval_policy = "never"',
        'model = "gpt-5.5"\nmodel_reasoning_effort = "low"\napproval_policy = "never"',
        "test_codex_config_has_no_identity_defaults",
    ),
    (
        "ignore missing descriptor",
        "shared/capability_execution.py",
        "except (KeyError, ValueError, PlatformCapabilityRegistryError) as exc:\n",
        "except (KeyError, ValueError, PlatformCapabilityRegistryError) as exc:\n"
        '        return ExecutionDescriptor(model_id=ModelId.GPT_5_5, effort="low")\n',
        "test_missing_descriptor_is_refused_before_invocation",
    ),
    (
        "substitute invocation model",
        "shared/capability_execution.py",
        'f"model={json.dumps(descriptor.model_id)}"',
        "'model=\"mutant-model\"'",
        "test_invocation_carries_exact_descriptor",
    ),
    (
        "substitute invocation effort",
        "shared/capability_execution.py",
        'f"model_reasoning_effort={json.dumps(descriptor.effort)}"',
        "'model_reasoning_effort=\"high\"'",
        "test_invocation_carries_exact_descriptor",
    ),
    (
        "drop headless invocation identity",
        "scripts/hapax-codex-headless",
        '  "${CODEX_EXECUTION_ARGS[@]}"',
        "  -c 'approval_policy=\"never\"'",
        "test_invocation_carries_exact_descriptor",
    ),
    (
        "drop interactive invocation identity",
        "scripts/hapax-codex",
        '  "${CODEX_EXECUTION_ARGS[@]}"',
        "  -c 'approval_policy=\"never\"'",
        "test_invocation_carries_exact_descriptor",
    ),
    (
        "allow identity override",
        "shared/capability_execution.py",
        "def reject_codex_identity_overrides(args: list[str]) -> None:\n",
        "def reject_codex_identity_overrides(args: list[str]) -> None:\n    return\n",
        "test_launcher_refuses_cli_override",
    ),
    (
        "refuse nonidentity arguments",
        "shared/capability_execution.py",
        "def reject_codex_identity_overrides(args: list[str]) -> None:\n",
        "def reject_codex_identity_overrides(args: list[str]) -> None:\n"
        '    raise ExecutionIdentityError("refusing all extra arguments")\n',
        "test_launcher_preserves_non_identity_arguments",
    ),
    (
        "ignore turn mismatch",
        "shared/codex_execution_receipt.py",
        "if any(value is not None and value != declared[axis] for axis, value in observed.items()):",
        "if False:",
        "test_turn_context_mismatch_is_misattributed",
    ),
    (
        "promote missing evidence to matched",
        "shared/codex_execution_receipt.py",
        'status = "unverified"',
        'status = "matched"',
        "test_partial_turn_observation_preserves_known_mismatch",
    ),
    (
        "read wrong native effort key",
        "shared/codex_execution_receipt.py",
        'payload.get("effort")',
        'payload.get("reasoning_effort")',
        "test_captured_native_turn_context_uses_observed_field_names",
    ),
    (
        "allow malformed descriptor arguments",
        "scripts/capability-execution.sh",
        "if not valid:",
        "if False:",
        "test_identity_helper_refuses_malformed_resolver_output",
    ),
    (
        "allow empty or nonstring identity values",
        "scripts/capability-execution.sh",
        "if not all(",
        "if False and not all(",
        "test_identity_helper_refuses_consistent_invalid_identity",
    ),
    (
        "decode with ambient Python modules",
        "scripts/capability-execution.sh",
        'execution_lines="$("$execution_python" -I -c',
        'execution_lines="$("$execution_python" -c',
        "test_identity_helper_ignores_caller_python_modules",
    ),
    (
        "resolve from ambient workdir",
        "scripts/capability-execution.sh",
        "sys.path.insert(0,sys.argv.pop(1))",
        'sys.argv.pop(1); sys.path.insert(0,".")',
        "test_interactive_reentry_keeps_selected_source_release",
    ),
    (
        "follow changed activation symlink during reentry",
        "scripts/hapax-codex",
        'EXECUTION_SOURCE_ROOT="$(cd -- "$EXECUTION_SOURCE_ROOT" && pwd -P)" || exit 9',
        ": # physical source selection removed",
        "test_interactive_reentry_keeps_selected_source_release",
    ),
    (
        "reenter through legacy launcher",
        "scripts/hapax-codex",
        "    printf 'exec %q' \"$EXECUTION_SOURCE_ROOT/scripts/hapax-codex\"",
        "    printf 'exec %q' \"$COUNCIL_DIR/scripts/hapax-codex\"",
        "test_interactive_reentry_keeps_selected_source_release",
    ),
    (
        "drop selected release during reentry",
        "scripts/hapax-codex",
        "    printf 'export HAPAX_SOURCE_ACTIVATE_WORKTREE=%q\\n' \"$EXECUTION_SOURCE_ROOT\"",
        "    : # selected release export removed",
        "test_interactive_reentry_keeps_selected_source_release",
    ),
    (
        "headless follows changed activation symlink",
        "scripts/hapax-codex-headless",
        'EXECUTION_SOURCE_ROOT="$(cd -- "$EXECUTION_SOURCE_ROOT" && pwd -P)" || exit 9',
        ": # physical source selection removed",
        "tests/scripts/test_hapax_codex_headless.py::"
        "test_installed_headless_observer_uses_activation_and_requires_fresh_receipt",
    ),
    (
        "observer reloads activation after native exit",
        "scripts/hapax-codex-headless",
        'local observer_root="$EXECUTION_SOURCE_ROOT"',
        'local observer_root="${HAPAX_SOURCE_ACTIVATE_WORKTREE:-$HOME/.cache/hapax/source-activation/worktree}"',
        "tests/scripts/test_hapax_codex_headless.py::"
        "test_installed_headless_observer_uses_activation_and_requires_fresh_receipt",
    ),
    (
        "allow snapshot and argv disagreement",
        "scripts/capability-execution.sh",
        'if not isinstance(descriptor, dict) or descriptor.get("model_id") != values["model"] or descriptor.get("effort") != values["model_reasoning_effort"]:',
        "if False:",
        "test_identity_helper_refuses_inconsistent_launch_snapshot",
    ),
    (
        "reload declaration after execution",
        "scripts/hapax-codex-headless",
        '  local observer_root="$EXECUTION_SOURCE_ROOT"',
        '  bind_codex_execution || return 9\n  local observer_root="$EXECUTION_SOURCE_ROOT"',
        "test_headless_identity_reaches_result_reader_with_frozen_declaration",
    ),
    (
        "trust receipt-carried identity",
        "scripts/hapax-methodology-dispatch",
        'observed["execution_identity"] = recheck_codex_run_identity(\n'
        '                observed.get("execution_identity"),\n'
        '                session_id=recomputed.get("session_id"),\n'
        "                owned_native_process=owned,\n"
        "            )",
        'observed["execution_identity"] = observed.get("execution_identity")',
        "tests/scripts/test_codex_identity_consumer.py::"
        "test_consumer_retains_native_mismatch_against_forged_match",
    ),
    (
        "replay whole current rollout instead of saved prefix",
        "shared/codex_execution_receipt.py",
        'expected_rollout=reported["rollout"],',
        "expected_rollout=None,",
        "tests/scripts/test_codex_identity_consumer.py::"
        "test_consumer_recomputes_frozen_identity_and_prefix_replay",
    ),
    (
        "ignore native prefix hash mismatch",
        "shared/codex_execution_receipt.py",
        'expected_rollout.get("sha256") != digest',
        "False",
        "tests/scripts/test_codex_identity_consumer.py::"
        "test_consumer_never_promotes_unavailable_identity",
    ),
    (
        "ignore native session mismatch",
        "shared/codex_execution_receipt.py",
        'payload.get("id") != session_id',
        "False",
        "test_headless_identity_reaches_result_reader_with_frozen_declaration",
    ),
    (
        "erase correlated evidence after prelaunch turn",
        "shared/codex_execution_receipt.py",
        '                if "native_turn_predates_launch" not in result["reason_codes"]:\n'
        '                    result["reason_codes"].append("native_turn_predates_launch")\n'
        "                continue",
        '                return refuse("native_turn_predates_launch")',
        "tests/shared/test_codex_run_identity.py::"
        "test_prelaunch_turn_does_not_erase_correlated_evidence",
    ),
    (
        "discard emitted mismatch on later malformed line",
        "shared/codex_execution_receipt.py",
        "for receipt in check_rollout(args.rollout, descriptor, route_id=args.route):",
        "for receipt in list(check_rollout(args.rollout, descriptor, route_id=args.route)):",
        "test_checker_emits_known_mismatch_before_later_malformed_line",
    ),
    (
        "allow cross-route identity selection",
        "scripts/hapax-methodology-dispatch",
        'if selected.split("#", 1)[0] != route_id:',
        "if False:",
        "test_dispatch_refuses_cross_route_identity_with_next_action",
    ),
    (
        "promote unavailable result identity",
        "shared/codex_execution_receipt.py",
        'return {"status": "unverified", "reason_codes": [reason], "may_authorize": False}',
        'return {"status": "matched", "reason_codes": [reason], "may_authorize": False}',
        "tests/scripts/test_codex_identity_consumer.py::"
        "test_consumer_never_promotes_unavailable_identity",
    ),
    (
        "retain relative native bindings",
        "shared/codex_execution_receipt.py",
        "native_home, workdir = native_home.resolve(), workdir.resolve()",
        "pass # physical binding removed",
        "tests/shared/test_codex_run_identity.py::"
        "test_relative_bindings_are_frozen_as_physical_absolute_paths",
    ),
    (
        "promote contradictory receipt to matched",
        "shared/codex_execution_receipt.py",
        'if recomputed["status"] == "matched":',
        "if False:",
        "tests/scripts/test_codex_identity_consumer.py::"
        "test_consumer_classifies_inconsistent_matching_receipt_as_unverified",
    ),
    (
        "erase completion after native path resolution failure",
        "shared/codex_execution_receipt.py",
        "except (ValueError, KeyError, TypeError, OSError, RuntimeError):",
        "except (ValueError, KeyError, TypeError, OSError):",
        "tests/scripts/test_codex_identity_consumer.py::"
        "test_consumer_never_promotes_unavailable_identity[native_home_symlink_loop]",
    ),
    (
        "watchdog depends on model footer",
        "scripts/hapax-lane-idle-watchdog",
        '    # Idle if we see the "› " prompt line without Working above it',
        '    if echo "$pane" | tail -5 | grep -qE "gpt-[0-9].*~/projects/"; then\n'
        "        return 0\n    fi\n"
        '    # Idle if we see the "› " prompt line without Working above it',
        "test_watchdog_idle_is_independent_of_model",
    ),
)


def run_tests(test: str) -> subprocess.CompletedProcess[str]:
    target = test if "::" in test else f"{TEST}::{test}"
    return subprocess.run(
        [sys.executable, "-B", "-m", "pytest", target, "-q", "--tb=short"],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
    )


def main() -> int:
    # Every selected test must first be green: pre-existing failures cannot kill mutants.
    for test in dict.fromkeys(mutation[4] for mutation in MUTATIONS):
        result = run_tests(test)
        if result.returncode != 0:
            print(result.stdout)
            raise SystemExit(f"baseline failed: {test}")
    survived = []
    for name, relative, before, after, test in MUTATIONS:
        path = ROOT / relative
        original = path.read_bytes()
        text = original.decode()
        if text.count(before) != 1:
            raise SystemExit(f"mutation anchor must occur once: {name}")
        try:
            path.write_text(text.replace(before, after, 1))
            result = run_tests(test)
        finally:
            path.write_bytes(original)
        killed = result.returncode == 1 and " failed" in result.stdout
        print(
            json.dumps(
                {
                    "mutation": name,
                    "test": test,
                    "killed": killed,
                    "exit_code": result.returncode,
                    "restored_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            ),
            flush=True,
        )
        if not killed:
            survived.append(name)
            print(result.stdout)
    return int(bool(survived))


if __name__ == "__main__":
    raise SystemExit(main())

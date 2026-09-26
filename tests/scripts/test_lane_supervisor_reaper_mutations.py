"""Opt-in mutation witnesses; run directly in an isolated, claimed checkout.

This is deliberately not a pytest test: it edits the supervisor temporarily.
Each mutation must produce assertion failures in every selected case, then exact
source bytes are restored. The final run checks all selected cases on that source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/hapax-lane-supervisor"
REAPER = "tests/scripts/test_lane_supervisor_reaper.py::"
SESSION = "tests/scripts/test_lane_supervisor_session_liveness.py::"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    original = SOURCE.read_bytes()
    (output / "supervisor-preimage").write_bytes(original)
    mutations = []

    def add(name, before, after, tests, count):
        assert original.count(before.encode()) == 1, name
        mutations.append((name, original.replace(before.encode(), after.encode()), tests, count))

    add(
        "skip_empty_publication",
        """        if not task:
            held = True
            print(f"{lane}: claim_orphan_unresolved:empty_claim; preserve claim and inspect publication at {path}", flush=True)
            record_claim_observation(path, sid, None, "unknown", "empty_claim", None)
            continue""",
        "        if not task:\n            continue",
        [REAPER + "test_empty_parallel_claim_holds_bound_terminal_launcher"],
        2,
    )
    add(
        "unrelated_terminal_authorizes_reap",
        "            sid, task = launcher_binding()",
        """            sid, task = next(iter(terminal_claims))
            launcher_binding = lambda: (sid, task)""",
        [REAPER + "test_terminal_cleanup_requires_current_launcher_binding"],
        6,
    )
    add(
        "ignore_session_pid",
        "if read_input(path).strip() != reap_pid:",
        "if False:",
        [REAPER + "test_terminal_cleanup_requires_current_launcher_binding[wrong_pid]"],
        1,
    )
    add(
        "accept_reused_pid_binding",
        " or path.stat().st_mtime < started",
        "",
        [REAPER + "test_terminal_cleanup_requires_current_launcher_binding[stale_pid]"],
        1,
    )
    add(
        "ignore_launcher_role",
        "if read_input(session_role_marker_path(sid, cache_dir=cache)).strip() != lane:",
        "if False:",
        [REAPER + "test_terminal_cleanup_requires_current_launcher_binding[wrong_role]"],
        1,
    )
    add(
        "accept_ambiguous_session",
        "if len(bindings) != 1:",
        "if not bindings:",
        [REAPER + "test_terminal_cleanup_requires_current_launcher_binding[ambiguous]"],
        1,
    )
    add(
        "ignore_current_task",
        'task = read_input(Path(runtime) / f"{lane}.current-task").strip()',
        'task = (cache / f"{prefix}-{bindings[0]}").read_text().strip()',
        [REAPER + "test_terminal_cleanup_requires_current_launcher_binding[wrong_task]"],
        1,
    )
    gate = """  if ! claim_holder_guard "$lane" reap "$pid"; then
    log "$lane: reap_hold:active_or_unresolved_claim — preserve launcher; inspect claim-holder evidence and task state"
    return 1
  fi"""
    add(
        "remove_signal_claim_check",
        gate,
        "  :",
        [
            REAPER + "test_old_terminal_claim_cannot_authorize_current_launcher",
            REAPER + "test_empty_claim_published_after_admission_holds_reap",
        ],
        7,
    )
    add(
        "invalid_writer_pid_allows_recovery",
        """      log "$lane: writer_unresolved:invalid_pid — inspect $pidfile"
      return 0""",
        """      log "$lane: writer_unresolved:invalid_pid — inspect $pidfile"
      return 1""",
        [SESSION + "test_invalid_role_pidfile_holds_unclaimed_lane"],
        4,
    )
    add(
        "disable_bound_terminal_cleanup",
        'if ! kill -TERM "$pid" 2>/dev/null; then',
        "if ! false; then",
        [REAPER + "test_supervisor_reaps_launcher_when_task_terminal"],
        8,
    )
    results = []
    command = [sys.executable, "-m", "pytest", "-q", "--tb=short"]
    env = {**os.environ, "HAPAX_TEST_REQUIRE_TMUX": "1"}
    try:
        for name, mutant, tests, count in mutations:
            SOURCE.write_bytes(mutant)
            report = output / f"{name}.xml"
            result = subprocess.run(
                command + tests + [f"--junitxml={report}"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )
            (output / f"{name}.txt").write_text(result.stdout + result.stderr)
            SOURCE.write_bytes(original)
            assert SOURCE.read_bytes() == original
            cases = ET.parse(report).findall(".//testcase")
            killed = (
                result.returncode == 1
                and len(cases) == count
                and all(case.find("failure") is not None for case in cases)
            )
            results.append(
                dict(
                    name=name,
                    killed=killed,
                    tests=tests,
                    count=count,
                    restored_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                )
            )
            print(name, "RED; exact bytes restored" if killed else "UNEXPECTED", flush=True)
            assert killed, name
    finally:
        SOURCE.write_bytes(original)
        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    tests = sorted({test for _, _, selected, _ in mutations for test in selected})
    result = subprocess.run(command + tests, cwd=ROOT, env=env, capture_output=True, text=True)
    (output / "restored-green.txt").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout, flush=True)


if __name__ == "__main__":
    main()

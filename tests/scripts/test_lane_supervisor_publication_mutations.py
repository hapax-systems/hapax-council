"""Deliberately break publication/respawn protections in an isolated claimed checkout.

Run directly with --output <new-directory>. This is not a pytest test: it edits
source temporarily and preserves every failure, exact restoration and green run.
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
RUNBOOK = ROOT / "docs/runbooks/lane-death-forensics.md"
REAPER = "tests/scripts/test_lane_supervisor_reaper.py::"
PANES = "tests/scripts/test_lane_supervisor_pane_death_forensics.py::"
RECEIPTS = "tests/scripts/test_lane_supervisor_receipts.py::"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    originals = {p: p.read_bytes() for p in (SOURCE, RUNBOOK)}
    for path, data in originals.items():
        (output / (path.name + ".preimage")).write_bytes(data)
    mutations = []

    def add(name, path, before, after, tests, count):
        assert originals[path].count(before.encode()) == 1, name
        mutations.append(
            (name, path, originals[path].replace(before.encode(), after.encode()), tests, count)
        )

    add(
        "ignore_session_epoch",
        SOURCE,
        "                check_epoch(path, task)",
        "                pass",
        [REAPER + "test_new_epoch_for_old_terminal_claim_holds[session]"],
        1,
    )
    add(
        "ignore_role_epoch",
        SOURCE,
        "                check_epoch(legacy, task)",
        "                pass",
        [REAPER + "test_new_epoch_for_old_terminal_claim_holds[role]"],
        1,
    )
    add(
        "accept_malformed_epoch",
        SOURCE,
        "if len(parts) != 2 or not parts[0].isdecimal() or int(parts[0]) <= 0 or parts[1] != task:",
        "if False:",
        [
            REAPER + f"test_reaper_holds_claim_publication_window[{age}-{state}]"
            for age in ("0", "21600")
            for state in ("empty", "malformed", "zero")
        ],
        6,
    )
    add(
        "ignore_note_first_publication",
        SOURCE,
        'if field(front, "assigned_to") == lane and field(front, "status") not in terminal:',
        "if False:",
        [REAPER + "test_new_owned_note_before_epoch_publication_holds_reap"],
        1,
    )
    add(
        "ignore_changed_input",
        SOURCE,
        "if stamp(before) != stamp(after) or (path in reap_inputs and reap_inputs[path] != observed):",
        "if False:",
        [
            REAPER + f"test_reaper_rejects_input_changed_during_observation[{kind}]"
            for kind in ("epoch", "note")
        ],
        2,
    )
    add(
        "ignore_new_claim",
        SOURCE,
        'if sorted(cache.glob(prefix + "-*")) != claim_paths:',
        "if False:",
        [REAPER + "test_reaper_rejects_input_changed_during_observation[new_claim]"],
        1,
    )
    add(
        "ignore_new_note",
        SOURCE,
        'if sorted((Path(vault) / "active").glob("*.md")) != active_notes:',
        "if False:",
        [REAPER + "test_reaper_rejects_input_changed_during_observation[new_note]"],
        1,
    )
    add(
        "omit_terminal_statuses",
        SOURCE,
        '"done", "completed", "closed", "withdrawn", "superseded"',
        '"done", "closed", "superseded"',
        [
            REAPER + f"test_supervisor_reaps_launcher_when_task_terminal[{status}-{location}]"
            for status in ("completed", "withdrawn")
            for location in ("active", "closed")
        ],
        4,
    )
    add(
        "codex_relaunch_over_revived_pane",
        SOURCE,
        """      if tmux_session_alive "hapax-codex-$lane"; then
        log "$lane: respawn_hold:occupancy_changed — recheck next tick"
        return 0
      fi""",
        "      :",
        [PANES + "test_pane_becoming_live_during_capture_is_preserved[codex]"],
        1,
    )
    add(
        "partial_receipt_traceback",
        RUNBOOK,
        """task = receipt.get('task_id')
if not isinstance(task, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', task):
    sys.exit('receipt_task_unresolved: missing or invalid task; preserve receipt and inspect claim publication')""",
        "task = receipt['task_id']",
        [RECEIPTS + "test_runbook_partial_task_is_typed_hold"],
        3,
    )
    start = originals[RUNBOOK].decode().index("    if path.name.startswith('cc-active-task-')")
    end = originals[RUNBOOK].decode().index("pidfile = runtime", start)
    add(
        "runbook_omits_note",
        RUNBOOK,
        originals[RUNBOOK].decode()[start:end],
        "",
        [REAPER + "test_runbook_displays_launcher_note_and_epoch"],
        2,
    )
    add(
        "runbook_omits_epoch",
        RUNBOOK,
        ",\n              cache / f'cc-claim-epoch-{lane}-{sid}'",
        "",
        [REAPER + "test_runbook_displays_launcher_note_and_epoch"],
        2,
    )

    results = []
    env = {**os.environ, "HAPAX_TEST_REQUIRE_TMUX": "1"}
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short"]
    try:
        for name, path, content, tests, count in mutations:
            path.write_bytes(content)
            report = output / f"{name}.xml"
            result = subprocess.run(
                cmd + tests + [f"--junitxml={report}"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )
            (output / f"{name}.txt").write_text(result.stdout + result.stderr)
            path.write_bytes(originals[path])
            assert all(p.read_bytes() == b for p, b in originals.items())
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
                    restored_sha256={
                        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in originals
                    },
                )
            )
            print(name, "RED; exact bytes restored" if killed else "UNEXPECTED", flush=True)
            assert killed, name
    finally:
        for p, data in originals.items():
            p.write_bytes(data)
        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    tests = sorted({t for _, _, _, selected, _ in mutations for t in selected})
    result = subprocess.run(
        cmd + tests, cwd=ROOT, env=env, capture_output=True, text=True, timeout=180
    )
    (output / "restored-green.txt").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout, flush=True)


if __name__ == "__main__":
    main()

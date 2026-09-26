"""Opt-in mutation witnesses for receipts; run directly in an isolated claimed checkout.

Temporarily break each protection, require every selected test to fail, restore
exact source bytes, then run all receipt regressions on the restored files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = ROOT / "scripts/hapax-lane-supervisor"
RUNBOOK = ROOT / "docs/runbooks/lane-death-forensics.md"
TEST = "tests/scripts/test_lane_supervisor_receipts.py"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    originals = {path: path.read_bytes() for path in (SUPERVISOR, RUNBOOK)}
    for path, content in originals.items():
        (output / (path.name + ".preimage")).write_bytes(content)
    mutations = []

    def add(name, path, before, after, tests):
        assert originals[path].count(before.encode()) == 1, name
        mutant = originals[path].replace(before.encode(), after.encode())
        mutations.append((name, path, mutant, [TEST + "::" + test for test in tests]))

    add(
        "omit_observed_path",
        SUPERVISOR,
        "claim_path=str(path), ",
        "",
        [
            "test_observed_claim_path_round_trips_through_runbook[]",
            "test_observed_claim_path_round_trips_through_runbook[-a81c4e9a-1111-4444-8888-123456abcdef]",
            "test_observed_claim_path_round_trips_through_runbook[-12345]",
        ],
    )
    add(
        "reconstruct_legacy_path",
        SUPERVISOR,
        "claim_path=str(path)",
        'claim_path=str(cache / (prefix + ("-" + sid if sid else "")))',
        ["test_observed_claim_path_round_trips_through_runbook[-12345]"],
    )
    add(
        "runbook_reconstructs_legacy_path",
        RUNBOOK,
        "claim = Path(raw_path)",
        "claim = cache / ('cc-active-task-' + lane + ('-' + receipt['session_id'] if receipt['session_id'] else ''))",
        ["test_observed_claim_path_round_trips_through_runbook[-12345]"],
    )
    add(
        "producer_follows_symlinks",
        SUPERVISOR,
        "or path.is_symlink() or epoch.is_symlink()",
        "or False",
        [
            "test_symlinked_receipt_input_holds_without_redirecting_evidence[claim]",
            "test_symlinked_receipt_input_holds_without_redirecting_evidence[epoch]",
        ],
    )
    add(
        "runbook_accepts_outside_namespace",
        RUNBOOK,
        "if claim.parent != cache or not (claim.name == prefix or claim.name.startswith(prefix + '-')):",
        "if False:",
        [
            f"test_runbook_refuses_unbounded_receipt_path[{case}]"
            for case in ("outside", "relative", "traversal", "sibling")
        ],
    )
    add(
        "runbook_follows_symlinks",
        RUNBOOK,
        "if claim.is_symlink() or epoch.is_symlink():",
        "if False:",
        [
            "test_runbook_refuses_unbounded_receipt_path[claim_symlink]",
            "test_runbook_refuses_unbounded_receipt_path[epoch_symlink]",
        ],
    )
    add(
        "runbook_guesses_missing_path",
        RUNBOOK,
        "raw_path = receipt.get('claim_path')",
        "raw_path = receipt.get('claim_path', str(cache / ('cc-active-task-' + lane)))",
        ["test_runbook_refuses_unbounded_receipt_path[missing]"],
    )
    command = [sys.executable, "-m", "pytest", "-q", "--tb=short"]
    results = []
    try:
        for name, path, mutant, tests in mutations:
            path.write_bytes(mutant)
            report = output / f"{name}.xml"
            result = subprocess.run(
                command + tests + [f"--junitxml={report}"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=120,
            )
            (output / f"{name}.txt").write_text(result.stdout + result.stderr)
            path.write_bytes(originals[path])
            assert all(p.read_bytes() == original for p, original in originals.items())
            cases = ET.parse(report).findall(".//testcase")
            killed = (
                result.returncode == 1
                and len(cases) == len(tests)
                and all(case.find("failure") is not None for case in cases)
            )
            results.append(
                dict(
                    name=name,
                    killed=killed,
                    tests=tests,
                    restored_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
            print(name, "RED; exact bytes restored" if killed else "UNEXPECTED", flush=True)
            assert killed, name
    finally:
        for path, original in originals.items():
            path.write_bytes(original)
        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    result = subprocess.run(command + [TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
    (output / "restored-green.txt").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout, flush=True)


if __name__ == "__main__":
    main()

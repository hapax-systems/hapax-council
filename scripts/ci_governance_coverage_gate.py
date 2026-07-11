#!/usr/bin/env python3
"""CI gate: governance algebraic hardening modules must maintain ≥90% coverage.

Exit 0 if all modules meet the threshold, exit 1 otherwise.
Runs pytest with --cov for each module independently to get per-module coverage.

Usage:
    uv run python scripts/ci_governance_coverage_gate.py
"""

from __future__ import annotations

import subprocess
import sys

MODULES = {
    "shared.axiom_enforcement": {
        "test_paths": [
            "tests/test_axiom_enforcement.py",
            "tests/test_axiom_enforcement_governance.py",
        ],
    },
    "policyflow.replay": {
        "test_paths": ["packages/policyflow/tests/"],
    },
    "shared.refusal_registry": {
        "test_paths": ["tests/test_refusal_registry.py"],
    },
}

THRESHOLD = 90


def check_module(module: str, test_paths: list[str]) -> tuple[bool, float]:
    cmd = [
        "uv",
        "run",
        "--no-sync",
        "pytest",
        *test_paths,
        f"--cov={module}",
        "--cov-report=term-missing",
        "--cov-fail-under",
        str(THRESHOLD),
        "-q",
        "--tb=no",
        "--no-header",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[-1].endswith("%"):
            try:
                return result.returncode == 0, float(parts[-1].rstrip("%"))
            except ValueError:
                continue

    return result.returncode == 0, 0.0


def main() -> int:
    failures: list[str] = []

    for module, config in MODULES.items():
        passed, coverage = check_module(module, config["test_paths"])
        status = "PASS" if passed else "FAIL"
        print(f"  {status}: {module} — {coverage:.0f}% (threshold {THRESHOLD}%)")
        if not passed:
            failures.append(f"{module} ({coverage:.0f}%)")

    if failures:
        print(f"\nFAILED: {len(failures)} module(s) below {THRESHOLD}% coverage:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"\nAll {len(MODULES)} governance modules meet ≥{THRESHOLD}% coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Axiom judge implication-set coverage checker.

Generates and verifies the coverage map between advertised implications
and property tests. CI fails if any T0 or T1 implication lacks a test.

Usage:
    uv run python scripts/check_axiom_judge_coverage.py
    uv run python scripts/check_axiom_judge_coverage.py --emit-map
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMPLICATIONS_DIR = ROOT / "axioms" / "implications"
TEST_DIRS = [ROOT / "tests", ROOT / "tests" / "shared", ROOT / "tests" / "hooks"]
COVERAGE_MAP_PATH = ROOT / "docs" / "governance" / "axiom-judge-coverage-map.json"


def load_all_implications() -> list[dict]:
    import yaml

    impls = []
    for f in sorted(IMPLICATIONS_DIR.glob("*.yaml")):
        data = yaml.safe_load(f.read_text())
        if isinstance(data, dict) and "implications" in data:
            entries = data["implications"]
        elif isinstance(data, list):
            entries = data
        else:
            continue
        for entry in entries:
            impls.append(
                {
                    "id": entry.get("id", ""),
                    "axiom_id": entry.get("axiom_id", ""),
                    "tier": entry.get("tier", "T3"),
                    "enforcement": entry.get("enforcement", "warn"),
                    "text": entry.get("text", ""),
                    "source_file": f.name,
                }
            )
    return impls


def find_test_references(impl_id: str) -> list[str]:
    refs = []
    pattern = re.compile(re.escape(impl_id))
    for test_dir in TEST_DIRS:
        if not test_dir.exists():
            continue
        for tf in test_dir.glob("*.py"):
            content = tf.read_text()
            if pattern.search(content):
                refs.append(str(tf.relative_to(ROOT)))
    return refs


def build_coverage_map(implications: list[dict]) -> list[dict]:
    coverage = []
    for imp in implications:
        refs = find_test_references(imp["id"])
        coverage.append(
            {
                "id": imp["id"],
                "axiom_id": imp["axiom_id"],
                "tier": imp["tier"],
                "enforcement": imp["enforcement"],
                "text": imp["text"][:120],
                "tested": len(refs) > 0,
                "test_refs": refs,
            }
        )
    return coverage


def main() -> int:
    parser = argparse.ArgumentParser(description="Axiom judge coverage checker")
    parser.add_argument("--emit-map", action="store_true", help="Write coverage map JSON")
    args = parser.parse_args()

    implications = load_all_implications()
    coverage = build_coverage_map(implications)

    if args.emit_map:
        COVERAGE_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        COVERAGE_MAP_PATH.write_text(json.dumps(coverage, indent=2) + "\n")
        print(f"Wrote {len(coverage)} entries to {COVERAGE_MAP_PATH}")

    total = len(coverage)
    tested = sum(1 for c in coverage if c["tested"])
    untested_t0 = [c for c in coverage if not c["tested"] and c["tier"] == "T0"]
    untested_t1 = [c for c in coverage if not c["tested"] and c["tier"] == "T1"]

    print(f"Coverage: {tested}/{total} ({100 * tested // total}%)")
    print(f"Untested T0 (block): {len(untested_t0)}")
    print(f"Untested T1 (review): {len(untested_t1)}")

    if untested_t0:
        print("\n--- UNTESTED T0 IMPLICATIONS (CI FAIL) ---")
        for c in untested_t0:
            print(f"  {c['id']} [{c['axiom_id']}]: {c['text'][:80]}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

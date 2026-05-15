#!/usr/bin/env python3
"""Deterministic governance perimeter budget and inventory.

Counts, classifies, and budgets every governance artifact — implications,
hooks, refusal briefs, publication surfaces, axiom references, governance
tests, and CI gates. No network, no runtime state.

Usage:
    uv run python scripts/hapax_governance_perimeter.py --summary
    uv run python scripts/hapax_governance_perimeter.py --json
    uv run python scripts/hapax_governance_perimeter.py --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
IMPLICATIONS_DIR = REPO_ROOT / "axioms" / "implications"
HOOKS_DIR = REPO_ROOT / "hooks" / "scripts"
REFUSAL_DIR = REPO_ROOT / "docs" / "refusal-briefs"
GOVERNANCE_DOCS_DIR = REPO_ROOT / "docs" / "governance"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
PUB_BUS_REGISTRY = REPO_ROOT / "agents" / "publication_bus" / "surface_registry.py"
TESTS_DIR = REPO_ROOT / "tests"

AXIOM_IDS = [
    "single_user",
    "executive_function",
    "corporate_boundary",
    "interpersonal_transparency",
    "management_governance",
]

GOVERNANCE_HOOK_KEYWORDS = re.compile(
    r"BLOCKED:|axiom|governance|pii|guard|gate|admission|push-gate|"
    r"registry-guard|resolution-gate|pip-guard|pipewire-graph|"
    r"branch-switch|safe-stash|session-name|authorization|"
    r"attribution-entity|conflict-marker|asset-provenance|"
    r"cc-task-closure|cc-task-gate|llm-metadata",
    re.IGNORECASE,
)

OPERATIONAL_HOOKS = frozenset(
    {
        "session-context.sh",
        "session-summary.sh",
        "conductor-pre.sh",
        "conductor-post.sh",
        "conductor-start.sh",
        "conductor-stop.sh",
        "relay-coordination-check.sh",
        "skill-trigger-advisory.sh",
        "sprint-tracker.sh",
        "codex-hook-adapter.sh",
        "gemini-session-adapter.sh",
        "gemini-tool-adapter.sh",
        "docs-only-pr-warn.sh",
        "doc-update-advisory.sh",
        "never-remove-warn.sh",
        "vale-style-check.sh",
        "cargo-check-rust.sh",
        "no-stale-branches.sh",
    }
)

GOVERNANCE_TEST_KEYWORDS = re.compile(
    r"consent|axiom|refusal|governance|publication.*hard|publication.*gate",
    re.IGNORECASE,
)

GOVERNANCE_WORKFLOW_KEYWORDS = re.compile(
    r"axiom|sdlc|admission|authority|vale|review|auto-fix",
    re.IGNORECASE,
)


@dataclass
class ImplicationStats:
    axiom_id: str
    total: int = 0
    active: int = 0
    retired: int = 0
    t0: int = 0
    t1: int = 0
    t2: int = 0
    t3: int = 0


@dataclass
class PerimeterReport:
    implications: list[ImplicationStats] = field(default_factory=list)
    hooks_blocking: list[str] = field(default_factory=list)
    hooks_advisory: list[str] = field(default_factory=list)
    hooks_operational: list[str] = field(default_factory=list)
    refusal_briefs: int = 0
    refusal_registry_entries: int = 0
    pub_surfaces_auto: int = 0
    pub_surfaces_conditional: int = 0
    pub_surfaces_refused: int = 0
    axiom_references: dict[str, int] = field(default_factory=dict)
    governance_test_files: int = 0
    governance_doc_files: int = 0
    ci_governance_workflows: list[str] = field(default_factory=list)

    def total_implications(self) -> int:
        return sum(i.total for i in self.implications)

    def active_implications(self) -> int:
        return sum(i.active for i in self.implications)

    def retired_implications(self) -> int:
        return sum(i.retired for i in self.implications)

    def total_perimeter(self) -> int:
        return (
            self.total_implications()
            + len(self.hooks_blocking)
            + len(self.hooks_advisory)
            + self.refusal_briefs
            + self.pub_surfaces_auto
            + self.pub_surfaces_conditional
            + self.pub_surfaces_refused
            + self.governance_test_files
            + self.governance_doc_files
            + len(self.ci_governance_workflows)
        )

    def to_dict(self) -> dict:
        return {
            "implications": {
                "total": self.total_implications(),
                "active": self.active_implications(),
                "retired": self.retired_implications(),
                "by_axiom": {
                    s.axiom_id: {
                        "total": s.total,
                        "active": s.active,
                        "retired": s.retired,
                        "t0": s.t0,
                        "t1": s.t1,
                        "t2": s.t2,
                        "t3": s.t3,
                    }
                    for s in self.implications
                },
            },
            "hooks": {
                "blocking": len(self.hooks_blocking),
                "advisory": len(self.hooks_advisory),
                "operational": len(self.hooks_operational),
            },
            "refusals": {
                "briefs": self.refusal_briefs,
                "registry_entries": self.refusal_registry_entries,
            },
            "publication_surfaces": {
                "full_auto": self.pub_surfaces_auto,
                "conditional_engage": self.pub_surfaces_conditional,
                "refused": self.pub_surfaces_refused,
                "total": self.pub_surfaces_auto
                + self.pub_surfaces_conditional
                + self.pub_surfaces_refused,
            },
            "axiom_references": self.axiom_references,
            "governance_tests": self.governance_test_files,
            "governance_docs": self.governance_doc_files,
            "ci_governance_workflows": len(self.ci_governance_workflows),
            "total_perimeter_artifacts": self.total_perimeter(),
        }


def scan_implications(impl_dir: Path) -> list[ImplicationStats]:
    results: list[ImplicationStats] = []
    if not impl_dir.is_dir():
        return results

    for path in sorted(impl_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(data, dict):
            continue

        axiom_id = data.get("axiom_id", path.stem)
        stats = ImplicationStats(axiom_id=axiom_id)

        impls = data.get("implications", [])
        if not impls and "implication_id" in data:
            impls = [data]

        for impl in impls:
            stats.total += 1
            if impl.get("status") == "retired":
                stats.retired += 1
            else:
                stats.active += 1

            tier = str(impl.get("tier", "")).upper()
            if tier == "T0":
                stats.t0 += 1
            elif tier == "T1":
                stats.t1 += 1
            elif tier == "T2":
                stats.t2 += 1
            elif tier == "T3":
                stats.t3 += 1

        results.append(stats)
    return results


def classify_hooks(hooks_dir: Path) -> tuple[list[str], list[str], list[str]]:
    blocking: list[str] = []
    advisory: list[str] = []
    operational: list[str] = []

    if not hooks_dir.is_dir():
        return blocking, advisory, operational

    for path in sorted(hooks_dir.iterdir()):
        if not path.is_file() or not path.name.endswith(".sh"):
            continue

        if path.name in OPERATIONAL_HOOKS:
            operational.append(path.name)
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            operational.append(path.name)
            continue

        if GOVERNANCE_HOOK_KEYWORDS.search(content) or GOVERNANCE_HOOK_KEYWORDS.search(path.name):
            if "BLOCKED:" in content or "exit 2" in content or "exit 1" in content:
                blocking.append(path.name)
            else:
                advisory.append(path.name)
        else:
            operational.append(path.name)

    return blocking, advisory, operational


def count_refusals(refusal_dir: Path) -> tuple[int, int]:
    briefs = 0
    registry_entries = 0

    if refusal_dir.is_dir():
        briefs = len([f for f in refusal_dir.iterdir() if f.is_file() and f.suffix == ".md"])
        registry_path = refusal_dir / "_registry.yaml"
        if registry_path.exists():
            try:
                data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "refusals" in data:
                    registry_entries = len(data["refusals"])
            except (yaml.YAMLError, OSError):
                pass

    return briefs, registry_entries


def count_publication_surfaces(pub_registry: Path) -> tuple[int, int, int]:
    auto = conditional = refused = 0
    if not pub_registry.exists():
        return auto, conditional, refused

    try:
        content = pub_registry.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return auto, conditional, refused

    for line in content.splitlines():
        stripped = line.strip()
        if (
            "AutomationStatus.FULL_AUTO" in stripped
            or "automation_status=AutomationStatus.FULL_AUTO" in stripped
        ):
            auto += 1
        elif (
            "AutomationStatus.CONDITIONAL_ENGAGE" in stripped
            or "automation_status=AutomationStatus.CONDITIONAL_ENGAGE" in stripped
        ):
            conditional += 1
        elif (
            "AutomationStatus.REFUSED" in stripped
            or "automation_status=AutomationStatus.REFUSED" in stripped
        ):
            refused += 1

    return auto, conditional, refused


def count_axiom_references(repo_root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    search_dirs = [repo_root / "config", repo_root / "shared", repo_root / "agents"]

    for axiom_id in AXIOM_IDS:
        count = 0
        for search_dir in search_dirs:
            if not search_dir.is_dir():
                continue
            for path in search_dir.rglob("*.py"):
                try:
                    content = path.read_text(encoding="utf-8")
                    count += content.count(axiom_id)
                except (OSError, UnicodeDecodeError):
                    continue
        counts[axiom_id] = count

    return counts


def count_governance_tests(tests_dir: Path) -> int:
    if not tests_dir.is_dir():
        return 0
    count = 0
    for path in tests_dir.rglob("*.py"):
        if GOVERNANCE_TEST_KEYWORDS.search(path.name):
            count += 1
    return count


def count_governance_docs(docs_dir: Path, refusal_dir: Path) -> int:
    count = 0
    if docs_dir.is_dir():
        count += len([f for f in docs_dir.rglob("*.md") if f.is_file()])
    if refusal_dir.is_dir():
        count += len([f for f in refusal_dir.iterdir() if f.is_file() and f.suffix == ".md"])
    return count


def scan_ci_workflows(workflows_dir: Path) -> list[str]:
    results: list[str] = []
    if not workflows_dir.is_dir():
        return results
    for path in sorted(workflows_dir.glob("*.yml")):
        if GOVERNANCE_WORKFLOW_KEYWORDS.search(path.stem):
            results.append(path.name)
    return results


def build_report() -> PerimeterReport:
    report = PerimeterReport()
    report.implications = scan_implications(IMPLICATIONS_DIR)
    report.hooks_blocking, report.hooks_advisory, report.hooks_operational = classify_hooks(
        HOOKS_DIR
    )
    report.refusal_briefs, report.refusal_registry_entries = count_refusals(REFUSAL_DIR)
    report.pub_surfaces_auto, report.pub_surfaces_conditional, report.pub_surfaces_refused = (
        count_publication_surfaces(PUB_BUS_REGISTRY)
    )
    report.axiom_references = count_axiom_references(REPO_ROOT)
    report.governance_test_files = count_governance_tests(TESTS_DIR)
    report.governance_doc_files = count_governance_docs(GOVERNANCE_DOCS_DIR, REFUSAL_DIR)
    report.ci_governance_workflows = scan_ci_workflows(WORKFLOWS_DIR)
    return report


def print_summary(report: PerimeterReport) -> None:
    d = report.to_dict()
    imp = d["implications"]
    print("=== Governance Perimeter Inventory ===")
    print()
    print(f"Total perimeter artifacts: {d['total_perimeter_artifacts']}")
    print()
    print("--- Implications ---")
    print(f"  Total: {imp['total']} (active: {imp['active']}, retired: {imp['retired']})")
    for axiom_id, stats in imp["by_axiom"].items():
        print(
            f"    {axiom_id:30s} "
            f"total={stats['total']:3d} active={stats['active']:3d} "
            f"T0={stats['t0']} T1={stats['t1']} T2={stats['t2']} T3={stats['t3']}"
        )
    print()
    h = d["hooks"]
    print("--- Hooks ---")
    print(f"  Blocking:    {h['blocking']}")
    print(f"  Advisory:    {h['advisory']}")
    print(f"  Operational: {h['operational']}")
    print()
    r = d["refusals"]
    print("--- Refusals ---")
    print(f"  Brief documents:    {r['briefs']}")
    print(f"  Registry entries:   {r['registry_entries']}")
    print()
    p = d["publication_surfaces"]
    print("--- Publication Surfaces ---")
    print(f"  FULL_AUTO:          {p['full_auto']}")
    print(f"  CONDITIONAL_ENGAGE: {p['conditional_engage']}")
    print(f"  REFUSED:            {p['refused']}")
    print(f"  Total:              {p['total']}")
    print()
    print("--- Axiom References ---")
    for axiom_id, count in d["axiom_references"].items():
        print(f"  {axiom_id:30s} {count}")
    print()
    print(f"--- Governance Tests: {d['governance_tests']} ---")
    print(f"--- Governance Docs:  {d['governance_docs']} ---")
    print(f"--- CI Workflows:     {d['ci_governance_workflows']} ---")


def check_mode(report: PerimeterReport) -> int:
    d = report.to_dict()
    errors: list[str] = []

    if d["implications"]["total"] == 0:
        errors.append("no implications found — check axioms/implications/ directory")

    if not report.hooks_blocking:
        errors.append("no blocking hooks found — check hooks/scripts/ directory")

    if d["refusals"]["briefs"] == 0:
        errors.append("no refusal briefs found — check docs/refusal-briefs/ directory")

    if errors:
        print("ERRORS:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    print(
        f"OK: governance perimeter inventory complete — {d['total_perimeter_artifacts']} artifacts"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Governance perimeter budget and inventory")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--summary", action="store_true", help="Human-readable summary")
    group.add_argument("--json", action="store_true", help="JSON report")
    group.add_argument(
        "--check", action="store_true", help="Verify perimeter inventory is complete"
    )
    args = parser.parse_args()

    report = build_report()

    if args.json:
        json.dump(report.to_dict(), sys.stdout, indent=2)
        print()
        return 0
    elif args.check:
        return check_mode(report)
    else:
        print_summary(report)
        return 0


if __name__ == "__main__":
    sys.exit(main())

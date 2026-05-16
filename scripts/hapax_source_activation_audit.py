#!/usr/bin/env python3
"""Deterministic source activation consumer audit.

Identifies every consumer of council source paths, classifies each as
canonical/activation/symlink/doc-only, and reports stale or misconfigured
consumers. No network, no runtime state.

Usage:
    uv run python scripts/hapax_source_activation_audit.py --summary
    uv run python scripts/hapax_source_activation_audit.py --json
    uv run python scripts/hapax_source_activation_audit.py --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UNITS_DIR = REPO_ROOT / "systemd" / "units"
HOOKS_DIR = REPO_ROOT / "hooks" / "scripts"
SCRIPTS_DIR = REPO_ROOT / "scripts"
BIN_DIR = Path.home() / ".local" / "bin"
ACTIVATION_WORKTREE = Path.home() / ".cache" / "hapax" / "source-activation" / "worktree"

CANONICAL_PATH = str(Path.home() / "projects" / "hapax-council")

CANONICAL_PATTERN = re.compile(re.escape(CANONICAL_PATH))

INTENTIONAL_CANONICAL = frozenset(
    {
        "canonical-worktree-protect.sh",
    }
)

INTENTIONAL_CANONICAL_SYMLINKS = frozenset(
    {
        "hapax-audio-routing-check",
    }
)


@dataclass
class ConsumerEntry:
    file: str
    category: str
    usage: str
    classification: str


@dataclass
class AuditReport:
    systemd_units: list[ConsumerEntry] = field(default_factory=list)
    symlinks: list[ConsumerEntry] = field(default_factory=list)
    hooks: list[ConsumerEntry] = field(default_factory=list)
    scripts: list[ConsumerEntry] = field(default_factory=list)

    def needs_migration(self) -> list[ConsumerEntry]:
        return [
            e
            for entries in [self.systemd_units, self.symlinks, self.hooks, self.scripts]
            for e in entries
            if e.classification == "needs-migration"
        ]

    def to_dict(self) -> dict:
        def _entries(lst: list[ConsumerEntry]) -> list[dict]:
            return [
                {
                    "file": e.file,
                    "category": e.category,
                    "usage": e.usage,
                    "classification": e.classification,
                }
                for e in lst
            ]

        needs = self.needs_migration()
        return {
            "systemd_units": {
                "total": len(self.systemd_units),
                "by_classification": _count_by(self.systemd_units),
                "entries": _entries(self.systemd_units),
            },
            "symlinks": {
                "total": len(self.symlinks),
                "by_classification": _count_by(self.symlinks),
            },
            "hooks": {
                "total": len(self.hooks),
                "entries": _entries(self.hooks),
            },
            "scripts": {
                "total": len(self.scripts),
                "entries": _entries(self.scripts),
            },
            "needs_migration_count": len(needs),
        }


def _count_by(entries: list[ConsumerEntry]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.classification] = counts.get(e.classification, 0) + 1
    return dict(sorted(counts.items()))


def _classify_unit_usage(content: str, canonical: str = CANONICAL_PATH) -> str:
    has_workdir = bool(re.search(rf"WorkingDirectory\s*=\s*{re.escape(canonical)}", content))
    has_execstart = bool(re.search(rf"ExecStart.*{re.escape(canonical)}", content))
    has_doc_only = bool(re.search(rf"Documentation.*{re.escape(canonical)}", content))

    if has_workdir and has_execstart:
        return "workdir+exec"
    if has_workdir:
        return "workdir"
    if has_execstart:
        return "execstart"
    if has_doc_only:
        return "doc-only"
    return "other"


def scan_systemd_units(units_dir: Path) -> list[ConsumerEntry]:
    entries: list[ConsumerEntry] = []
    if not units_dir.is_dir():
        return entries

    for path in sorted(units_dir.iterdir()):
        if not path.is_file() or not path.name.endswith(".service"):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if CANONICAL_PATH not in content:
            continue

        usage = _classify_unit_usage(content)
        if usage == "doc-only":
            classification = "doc-only"
        else:
            classification = "intentional-canonical"
        entries.append(
            ConsumerEntry(
                file=path.name, category="systemd", usage=usage, classification=classification
            )
        )

    return entries


def scan_symlinks(bin_dir: Path) -> list[ConsumerEntry]:
    entries: list[ConsumerEntry] = []
    if not bin_dir.is_dir():
        return entries

    for path in sorted(bin_dir.iterdir()):
        if not path.name.startswith("hapax-"):
            continue
        if not path.is_symlink():
            continue

        target = str(path.resolve())
        if "source-activation" in target:
            classification = "already-migrated"
            usage = "activation-symlink"
        elif CANONICAL_PATH in target:
            if path.name in INTENTIONAL_CANONICAL_SYMLINKS:
                classification = "intentional-canonical"
            else:
                classification = "needs-migration"
            usage = "canonical-symlink"
        else:
            classification = "other"
            usage = "external"

        entries.append(
            ConsumerEntry(
                file=path.name, category="symlink", usage=usage, classification=classification
            )
        )

    return entries


def scan_hooks(hooks_dir: Path, canonical: str = CANONICAL_PATH) -> list[ConsumerEntry]:
    entries: list[ConsumerEntry] = []
    if not hooks_dir.is_dir():
        return entries

    for path in sorted(hooks_dir.iterdir()):
        if not path.is_file() or not path.name.endswith(".sh"):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if canonical not in content:
            continue

        classification = (
            "intentional-canonical" if path.name in INTENTIONAL_CANONICAL else "needs-migration"
        )
        entries.append(
            ConsumerEntry(
                file=path.name,
                category="hook",
                usage="hardcoded-path",
                classification=classification,
            )
        )

    return entries


def scan_scripts(scripts_dir: Path) -> list[ConsumerEntry]:
    entries: list[ConsumerEntry] = []
    if not scripts_dir.is_dir():
        return entries

    for path in sorted(scripts_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name.startswith("hapax_") and path.suffix == ".py":
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if CANONICAL_PATH not in content:
            continue

        has_env_var = "HAPAX_COUNCIL_DIR" in content or "COUNCIL_DIR" in content
        classification = "env-var-with-fallback" if has_env_var else "needs-migration"
        entries.append(
            ConsumerEntry(
                file=path.name,
                category="script",
                usage="hardcoded-path",
                classification=classification,
            )
        )

    return entries


def build_report() -> AuditReport:
    report = AuditReport()
    report.systemd_units = scan_systemd_units(UNITS_DIR)
    report.symlinks = scan_symlinks(BIN_DIR)
    report.hooks = scan_hooks(HOOKS_DIR)
    report.scripts = scan_scripts(SCRIPTS_DIR)
    return report


def print_summary(report: AuditReport) -> None:
    d = report.to_dict()
    print("=== Source Activation Consumer Audit ===")
    print()

    su = d["systemd_units"]
    print(f"--- Systemd Units: {su['total']} with canonical path ---")
    for k, v in su["by_classification"].items():
        print(f"  {k:25s} {v}")
    print()

    sl = d["symlinks"]
    print(f"--- Symlinks: {sl['total']} total ---")
    for k, v in sl["by_classification"].items():
        print(f"  {k:25s} {v}")
    print()

    h = d["hooks"]
    print(f"--- Hooks: {h['total']} with canonical path ---")
    for e in h["entries"]:
        print(f"  {e['classification']:25s} {e['file']}")
    print()

    s = d["scripts"]
    print(f"--- Scripts: {s['total']} with canonical path ---")
    for e in s["entries"]:
        print(f"  {e['file']}")
    print()

    print(f"=== TOTAL NEEDS MIGRATION: {d['needs_migration_count']} ===")


def check_mode(report: AuditReport) -> int:
    needs = report.needs_migration()
    if not needs:
        print("OK: no non-allowlisted canonical consumers found")
        return 0

    print(f"MIGRATION NEEDED: {len(needs)} consumers reference canonical path", file=sys.stderr)
    for e in needs:
        print(f"  [{e.category}] {e.file} ({e.usage})", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Source activation consumer audit")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--summary", action="store_true")
    group.add_argument("--json", action="store_true")
    group.add_argument("--check", action="store_true")
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

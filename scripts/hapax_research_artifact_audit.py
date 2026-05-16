#!/usr/bin/env python3
"""Deterministic research artifact disposition audit.

Scans research docs, specs, and relay files. Classifies each artifact by
disposition state and reports gaps. No network, no runtime state.

Usage:
    uv run python scripts/hapax_research_artifact_audit.py --summary
    uv run python scripts/hapax_research_artifact_audit.py --json
    uv run python scripts/hapax_research_artifact_audit.py --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = REPO_ROOT / "docs" / "research"
SPECS_DIR = REPO_ROOT / "docs" / "superpowers" / "specs"
VAULT_RESEARCH = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-research"
RELAY_DIR = Path.home() / ".cache" / "hapax" / "relay"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
TASK_REF_RE = re.compile(r"Task:\s*(.+)", re.IGNORECASE)
STATUS_RE = re.compile(r"Status:\s*(.+)", re.IGNORECASE)
DATE_RE = re.compile(r"Date:\s*(.+)", re.IGNORECASE)


@dataclass
class ArtifactEntry:
    file: str
    category: str
    has_frontmatter: bool = False
    has_date: bool = False
    has_task_ref: bool = False
    has_status: bool = False
    disposition: str = "unclassified"


@dataclass
class ResearchAuditReport:
    research_docs: list[ArtifactEntry] = field(default_factory=list)
    specs: list[ArtifactEntry] = field(default_factory=list)
    vault_files: int = 0
    vault_index_entries: int = 0
    relay_files: int = 0
    relay_stale: int = 0

    def _classify(self, entries: list[ArtifactEntry]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in entries:
            counts[e.disposition] = counts.get(e.disposition, 0) + 1
        return dict(sorted(counts.items()))

    def unclassified_count(self) -> int:
        return sum(
            1
            for entries in [self.research_docs, self.specs]
            for e in entries
            if e.disposition == "unclassified"
        )

    def to_dict(self) -> dict:
        return {
            "research_docs": {
                "total": len(self.research_docs),
                "by_disposition": self._classify(self.research_docs),
            },
            "specs": {
                "total": len(self.specs),
                "by_disposition": self._classify(self.specs),
            },
            "vault": {
                "research_files": self.vault_files,
                "index_entries": self.vault_index_entries,
            },
            "relay": {
                "total": self.relay_files,
                "stale_30d": self.relay_stale,
            },
            "unclassified_total": self.unclassified_count(),
        }


def _parse_frontmatter(content: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}
    fm: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip().lower()] = val.strip()
    return fm


def _classify_artifact(fm: dict[str, str], has_fm: bool) -> str:
    if not has_fm:
        return "missing-frontmatter"
    has_date = bool(fm.get("date"))
    has_status = bool(fm.get("status"))
    has_task = bool(fm.get("task"))
    if has_date and has_status and has_task:
        return "fully-attributed"
    if has_date and has_status:
        return "attributed-no-task"
    if has_date:
        return "date-only"
    return "unclassified"


def scan_markdown_dir(directory: Path, category: str) -> list[ArtifactEntry]:
    entries: list[ArtifactEntry] = []
    if not directory.is_dir():
        return entries
    for path in sorted(directory.glob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        fm = _parse_frontmatter(content)
        has_fm = bool(fm)
        disposition = _classify_artifact(fm, has_fm)
        entries.append(
            ArtifactEntry(
                file=path.name,
                category=category,
                has_frontmatter=has_fm,
                has_date=bool(fm.get("date")),
                has_task_ref=bool(fm.get("task")),
                has_status=bool(fm.get("status")),
                disposition=disposition,
            )
        )
    return entries


def count_vault_research(vault_dir: Path) -> tuple[int, int]:
    files = 0
    index_entries = 0
    if vault_dir.is_dir():
        files = sum(1 for _ in vault_dir.rglob("*.md"))
        index_file = vault_dir / "research-index.md"
        if index_file.exists():
            content = index_file.read_text(encoding="utf-8")
            index_entries = content.count("[[")
    return files, index_entries


def count_relay_files(relay_dir: Path) -> tuple[int, int]:
    total = 0
    stale = 0
    if not relay_dir.is_dir():
        return total, stale
    import time

    now = time.time()
    thirty_days = 30 * 86400
    for path in relay_dir.iterdir():
        if path.is_file() and path.suffix == ".md":
            total += 1
            if now - path.stat().st_mtime > thirty_days:
                stale += 1
    return total, stale


def build_report() -> ResearchAuditReport:
    report = ResearchAuditReport()
    report.research_docs = scan_markdown_dir(RESEARCH_DIR, "research")
    report.specs = scan_markdown_dir(SPECS_DIR, "spec")
    report.vault_files, report.vault_index_entries = count_vault_research(VAULT_RESEARCH)
    report.relay_files, report.relay_stale = count_relay_files(RELAY_DIR)
    return report


def print_summary(report: ResearchAuditReport) -> None:
    d = report.to_dict()
    print("=== Research Artifact Disposition Audit ===")
    print()
    rd = d["research_docs"]
    print(f"--- Research Docs: {rd['total']} ---")
    for k, v in rd["by_disposition"].items():
        print(f"  {k:25s} {v}")
    print()
    sp = d["specs"]
    print(f"--- Specs: {sp['total']} ---")
    for k, v in sp["by_disposition"].items():
        print(f"  {k:25s} {v}")
    print()
    v = d["vault"]
    print(f"--- Vault: {v['research_files']} files, {v['index_entries']} index entries ---")
    print()
    r = d["relay"]
    print(f"--- Relay: {r['total']} files, {r['stale_30d']} stale (>30d) ---")
    print()
    print(f"=== UNCLASSIFIED: {d['unclassified_total']} ===")


def check_mode(report: ResearchAuditReport) -> int:
    d = report.to_dict()
    missing_fm = sum(
        v
        for entries in [d["research_docs"], d["specs"]]
        for k, v in entries["by_disposition"].items()
        if k == "missing-frontmatter"
    )
    if missing_fm > 0:
        print(
            f"WARN: {missing_fm} artifacts missing frontmatter",
            file=sys.stderr,
        )
    print(
        f"OK: audit complete — {d['research_docs']['total']} research docs, {d['specs']['total']} specs"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Research artifact disposition audit")
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

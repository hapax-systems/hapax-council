#!/usr/bin/env python3
"""Deterministic systemd + agent topology inventory.

Classifies all systemd units and agent modules by kind, tier, and governance
role. Produces a JSON report or human-readable summary. No network, no runtime
state — output is deterministic on identical tree state.

Usage:
    uv run python scripts/hapax_topology_inventory.py --summary
    uv run python scripts/hapax_topology_inventory.py --json
    uv run python scripts/hapax_topology_inventory.py --check
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
AGENTS_DIR = REPO_ROOT / "agents"
MANIFESTS_DIR = AGENTS_DIR / "manifests"

GOVERNANCE_KEYWORDS = re.compile(
    r"watchdog|safety|invariant|guard|topology|routing|quarantine|"
    r"leak|preflight|assertion|usb-bandwidth|xhci|broadcast-orchestrat",
    re.IGNORECASE,
)

AUDIO_KEYWORDS = re.compile(
    r"audio|broadcast|livestream|loudnorm|voice-fx|l12|"
    r"music-duck|tts-duck|av-correlat|contact-mic|recorder",
    re.IGNORECASE,
)

SYNC_KEYWORDS = re.compile(
    r"sync|chrome-sync|gdrive|gmail|youtube-sync|obsidian|langfuse|weather",
    re.IGNORECASE,
)

MAINTENANCE_KEYWORDS = re.compile(
    r"backup|cleanup|cache-clean|rotate|retention|rebuild|"
    r"storage-arbiter|disk-space|tmp-monitor|container-cleanup|tailscale-cleanup",
    re.IGNORECASE,
)


@dataclass
class ServiceInfo:
    name: str
    unit_type: str
    service_type: str = "unknown"
    tier: int = 3
    classification: str = "maintenance"
    paired_timer: str | None = None


@dataclass
class InventoryReport:
    services: list[ServiceInfo] = field(default_factory=list)
    timers: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    timer_pairings: list[tuple[str, str]] = field(default_factory=list)
    agent_dirs: int = 0
    agent_runnable: int = 0
    agent_registered: int = 0
    agent_unregistered_runnable: int = 0

    def service_type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for svc in self.services:
            counts[svc.service_type] = counts.get(svc.service_type, 0) + 1
        return dict(sorted(counts.items()))

    def tier_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for svc in self.services:
            label = f"tier-{svc.tier}-{svc.classification}"
            counts[label] = counts.get(label, 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict:
        return {
            "unit_counts": {
                "services": len(self.services),
                "timers": len(self.timers),
                "paths": len(self.paths),
                "targets": len(self.targets),
                "total": len(self.services)
                + len(self.timers)
                + len(self.paths)
                + len(self.targets),
            },
            "service_types": self.service_type_counts(),
            "governance_tiers": self.tier_counts(),
            "timer_pairings": len(self.timer_pairings),
            "agents": {
                "directories": self.agent_dirs,
                "runnable": self.agent_runnable,
                "manifest_registered": self.agent_registered,
                "unregistered_runnable": self.agent_unregistered_runnable,
            },
        }


def parse_service_type(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "unknown"
    match = re.search(r"^Type\s*=\s*(\S+)", content, re.MULTILINE)
    return match.group(1).lower() if match else "simple"


def classify_service(name: str) -> tuple[int, str]:
    if GOVERNANCE_KEYWORDS.search(name):
        return 0, "governance"
    if AUDIO_KEYWORDS.search(name):
        return 1, "audio-egress"
    if SYNC_KEYWORDS.search(name):
        return 2, "sync"
    if MAINTENANCE_KEYWORDS.search(name):
        return 3, "maintenance"
    stem = name.removesuffix(".service")
    if stem.startswith("hapax-") and not any(
        kw in stem for kw in ("backup", "rebuild", "cleanup", "sync")
    ):
        return 1, "platform"
    return 2, "operational"


def scan_units(units_dir: Path) -> InventoryReport:
    report = InventoryReport()
    if not units_dir.is_dir():
        return report

    for path in sorted(units_dir.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if name.endswith(".service"):
            stype = parse_service_type(path)
            tier, classification = classify_service(name)
            report.services.append(
                ServiceInfo(
                    name=name,
                    unit_type="service",
                    service_type=stype,
                    tier=tier,
                    classification=classification,
                )
            )
        elif name.endswith(".timer"):
            report.timers.append(name)
        elif name.endswith(".path"):
            report.paths.append(name)
        elif name.endswith(".target"):
            report.targets.append(name)

    timer_basenames = {t.removesuffix(".timer") for t in report.timers}
    for svc in report.services:
        base = svc.name.removesuffix(".service")
        if base in timer_basenames:
            svc.paired_timer = f"{base}.timer"
            report.timer_pairings.append((f"{base}.timer", svc.name))

    return report


def scan_agents(agents_dir: Path, manifests_dir: Path) -> tuple[int, int, int]:
    dirs = 0
    runnable = 0
    registered_names: set[str] = set()

    if manifests_dir.is_dir():
        for mf in manifests_dir.glob("*.yaml"):
            registered_names.add(mf.stem)
        for mf in manifests_dir.glob("*.yml"):
            registered_names.add(mf.stem)

    if agents_dir.is_dir():
        for d in sorted(agents_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("_") or d.name == "__pycache__":
                continue
            dirs += 1
            if (d / "__main__.py").exists():
                runnable += 1

    return dirs, runnable, len(registered_names)


def build_report() -> InventoryReport:
    report = scan_units(UNITS_DIR)
    dirs, runnable, registered = scan_agents(AGENTS_DIR, MANIFESTS_DIR)
    report.agent_dirs = dirs
    report.agent_runnable = runnable
    report.agent_registered = registered
    report.agent_unregistered_runnable = max(0, runnable - registered)
    return report


def print_summary(report: InventoryReport) -> None:
    d = report.to_dict()
    u = d["unit_counts"]
    a = d["agents"]
    print("=== Systemd Unit Inventory ===")
    print(f"  Services:  {u['services']}")
    print(f"  Timers:    {u['timers']}")
    print(f"  Paths:     {u['paths']}")
    print(f"  Targets:   {u['targets']}")
    print(f"  Total:     {u['total']}")
    print()
    print("=== Service Type Breakdown ===")
    for k, v in d["service_types"].items():
        print(f"  {k:12s} {v}")
    print()
    print("=== Governance Tier Classification ===")
    for k, v in d["governance_tiers"].items():
        print(f"  {k:30s} {v}")
    print()
    print(f"=== Timer-Service Pairings: {d['timer_pairings']} ===")
    print()
    print("=== Agent Inventory ===")
    print(f"  Directories:            {a['directories']}")
    print(f"  Runnable (__main__.py):  {a['runnable']}")
    print(f"  Manifest-registered:    {a['manifest_registered']}")
    print(f"  Unregistered runnable:  {a['unregistered_runnable']}")


def check_mode(report: InventoryReport) -> int:
    readme = REPO_ROOT / "systemd" / "README.md"
    if not readme.exists():
        print("WARN: systemd/README.md not found", file=sys.stderr)
        return 1

    content = readme.read_text(encoding="utf-8")
    errors: list[str] = []

    for tag, actual in [
        ("timers", len(report.timers)),
        ("services", len(report.services)),
    ]:
        pattern = (
            rf"<!--\s*topology-inventory:{tag}\s*-->(\d+)<!--\s*/topology-inventory:{tag}\s*-->"
        )
        match = re.search(pattern, content)
        if not match:
            errors.append(f"missing anchor: topology-inventory:{tag}")
            continue
        documented = int(match.group(1))
        if documented != actual:
            errors.append(f"{tag}: documented={documented} actual={actual}")

    if errors:
        print("STALE counts detected:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    print("OK: all topology-inventory anchors match actual counts")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Systemd + agent topology inventory")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--summary", action="store_true", help="Human-readable summary")
    group.add_argument("--json", action="store_true", help="JSON report")
    group.add_argument("--check", action="store_true", help="Verify README counts match actual")
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

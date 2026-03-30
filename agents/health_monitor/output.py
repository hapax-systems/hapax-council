"""Output formatting: human-readable, fix mode, history."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
from collections import Counter

from .constants import PROFILES_DIR
from .models import HealthReport, Status
from .utils import run_cmd

log = logging.getLogger("agents.health_monitor")

# ── Formatters ───────────────────────────────────────────────────────────────

_STATUS_ICON = {
    Status.HEALTHY: "[OK]  ",
    Status.DEGRADED: "[WARN]",
    Status.FAILED: "[FAIL]",
}

_STATUS_COLOR = {
    Status.HEALTHY: "\033[32m",  # green
    Status.DEGRADED: "\033[33m",  # yellow
    Status.FAILED: "\033[31m",  # red
}
_RESET = "\033[0m"


def format_human(report: HealthReport, verbose: bool = False, color: bool = True) -> str:
    """Format report as human-readable text."""
    lines: list[str] = []

    overall = report.overall_status.value.upper()
    if color:
        c = _STATUS_COLOR[report.overall_status]
        header = f"Stack Health: {c}{overall}{_RESET} ({report.summary}) [{report.duration_ms / 1000:.1f}s]"
    else:
        header = f"Stack Health: {overall} ({report.summary}) [{report.duration_ms / 1000:.1f}s]"
    lines.append(header)
    lines.append("")

    for gr in report.groups:
        group_label = gr.group
        group_status = gr.status.value.upper()
        if color:
            c = _STATUS_COLOR[gr.status]
            lines.append(f"[{group_label}] {c}{group_status}{_RESET}")
        else:
            lines.append(f"[{group_label}] {group_status}")

        for check in gr.checks:
            icon = _STATUS_ICON[check.status]
            if color:
                c = _STATUS_COLOR[check.status]
                prefix = f"  {c}{icon}{_RESET}"
            else:
                prefix = f"  {icon}"

            name_display = check.name
            padding = max(1, 35 - len(name_display))
            dots = "." * padding
            lines.append(f"{prefix} {name_display} {dots} {check.message}")

            if verbose and check.detail:
                lines.append(f"         {check.detail}")

            if check.remediation and check.status != Status.HEALTHY:
                lines.append(f"         Fix: {check.remediation}")

        lines.append("")

    return "\n".join(lines)


# ── Fix mode ─────────────────────────────────────────────────────────────────


async def run_fixes(report: HealthReport, yes: bool = False) -> int:
    """Run remediation commands for failed/degraded checks."""
    fixable = [
        c for gr in report.groups for c in gr.checks if c.remediation and c.status != Status.HEALTHY
    ]
    if not fixable:
        print("No remediations available.")
        return 0

    print(f"\n{len(fixable)} fixable issue(s):\n")
    for c in fixable:
        icon = _STATUS_ICON[c.status]
        print(f"  {icon} {c.name}: {c.message}")
        print(f"         Run: {c.remediation}")
    print()

    if not yes:
        try:
            answer = input("Run these fixes? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 0
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 0

    try:
        from agents._service_graph import remediation_order

        service_names = []
        for c in fixable:
            parts = c.name.split(".", 1)
            service_names.append(parts[1] if len(parts) > 1 else parts[0])
        ordered = remediation_order(service_names)
        name_to_order = {n: i for i, n in enumerate(ordered)}
        fixable.sort(key=lambda c: name_to_order.get(c.name.split(".", 1)[-1], len(ordered)))
    except Exception:
        pass

    count = 0
    for c in fixable:
        assert c.remediation is not None
        print(f"  Running: {c.remediation}")
        rc, out, err = await run_cmd(["bash", "-c", c.remediation], timeout=30.0)
        if rc == 0:
            print("    OK")
        else:
            print(f"    Failed (rc={rc}): {err or out}")
        count += 1

    return count


async def run_fixes_v2(report: HealthReport, mode: str = "apply") -> int:
    """Run LLM-evaluated fix pipeline."""
    try:
        from agents._fix_capabilities import load_builtin_capabilities, run_fix_pipeline
    except ImportError:
        log.warning("fix_capabilities not available; run_fixes_v2 is a no-op")
        return 0

    load_builtin_capabilities()
    try:
        result = await asyncio.wait_for(run_fix_pipeline(report, mode=mode), timeout=240.0)
    except TimeoutError:
        log.error("Fix pipeline timed out after 240s")
        print("Fix pipeline timed out after 240s")
        return 0

    if result.total == 0:
        print("No fix proposals generated.")
        return 0

    for outcome in result.outcomes:
        if outcome.executed and outcome.execution_result:
            icon = "OK" if outcome.execution_result.success else "FAIL"
            print(f"  [{icon}] {outcome.check_name}: {outcome.execution_result.message}")
            if outcome.proposal:
                print(f"         Rationale: {outcome.proposal.rationale}")
        elif outcome.notified:
            print(f"  [HELD] {outcome.check_name}: destructive \u2014 notification sent")
            if outcome.proposal:
                print(
                    f"         Proposed: {outcome.proposal.action_name}({outcome.proposal.params})"
                )
        elif outcome.rejected_reason:
            print(f"  [SKIP] {outcome.check_name}: {outcome.rejected_reason}")
        elif mode == "dry_run" and outcome.proposal:
            print(
                f"  [DRY ] {outcome.check_name}: would run {outcome.proposal.action_name}({outcome.proposal.params})"
            )
            print(f"         Rationale: {outcome.proposal.rationale}")

    return result.total


# ── History ──────────────────────────────────────────────────────────────────

HISTORY_FILE = PROFILES_DIR / "health-history.jsonl"
INFRA_SNAPSHOT_FILE = PROFILES_DIR / "infra-snapshot.json"

MAX_HISTORY_LINES = 10_000
KEEP_HISTORY_LINES = 5_000

_STATUS_SYMBOLS = {"healthy": "OK", "degraded": "!!", "failed": "XX"}


def rotate_history() -> None:
    """Truncate health history if it exceeds MAX_HISTORY_LINES (atomic)."""
    if not HISTORY_FILE.is_file():
        return
    lines = HISTORY_FILE.read_text().strip().splitlines()
    if len(lines) <= MAX_HISTORY_LINES:
        return
    trimmed = lines[-KEEP_HISTORY_LINES:]

    fd, tmp = tempfile.mkstemp(dir=HISTORY_FILE.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(trimmed) + "\n")
        os.replace(tmp, HISTORY_FILE)
        log.info("Rotated health history: %d \u2192 %d lines", len(lines), len(trimmed))
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def format_history(n: int = 20) -> str:
    """Read recent health history entries and format for display."""
    if not HISTORY_FILE.is_file():
        return "No health history found. History is recorded by the health-watchdog timer."

    entries = []
    for line in HISTORY_FILE.read_text().strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not entries:
        return "Health history file is empty."

    recent = entries[-n:]
    lines = [f"Health History (last {len(recent)} of {len(entries)} entries):", ""]

    for e in recent:
        ts = e.get("timestamp", "?")[:19].replace("T", " ")
        status = e.get("status", "?")
        sym = _STATUS_SYMBOLS.get(status, "??")
        h, d, f = e.get("healthy", 0), e.get("degraded", 0), e.get("failed", 0)
        dur = e.get("duration_ms", 0)
        failed_checks = e.get("failed_checks", [])
        detail = f"  [{', '.join(failed_checks)}]" if failed_checks else ""
        lines.append(f"  [{sym}] {ts}  {h}ok {d}warn {f}fail  {dur}ms{detail}")

    total = len(entries)
    healthy_runs = sum(1 for e in entries if e.get("status") == "healthy")
    lines.append("")
    lines.append(
        f"Uptime: {healthy_runs}/{total} runs healthy ({100 * healthy_runs // total if total else 0}%)"
    )

    fail_counts: Counter[str] = Counter()
    for e in entries:
        for c in e.get("failed_checks", []):
            fail_counts[c] += 1
    if fail_counts:
        lines.append("Most frequent issues:")
        for check, count in fail_counts.most_common(5):
            lines.append(f"  {check}: {count}/{total} runs")

    return "\n".join(lines)

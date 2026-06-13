"""Canary: every raw high-priority system alert must route through governed P0 intake.

Class-closure regression guard for the PR #4109 finding ("raw high-priority
alert sources bypass P0 intake"). Standalone watchdog / health scripts used to
call ``notify-send -u critical`` or POST ntfy ``Priority: high`` directly, so
their alerts never created a governed incident record AND stacked un-coalesced
in the desktop queue.

PER-EMIT, not per-file. An earlier version of this canary only checked that a
governed-routing substring appeared *somewhere* in a file — so a file that
routed one branch passed even while another branch emitted raw (the exact gap
the #4109 review caught at lane-idle-watchdog:639 and lane-supervisor:571). This
version enumerates EVERY raw emit and asserts governed routing for each:

  * Desktop: a raw ``notify-send`` at critical/urgent urgency is ALWAYS a
    violation — high/urgent desktop alerts must go through hapax-alert so intake
    emits ONE replace_id-coalesced pointer instead of an accumulating mako queue.
  * ntfy: each ``Priority: high|urgent|max`` header must have a governed call
    (hapax-alert / hapax-p0-incident-intake) within +/- WINDOW lines (same block).
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"

# The one governed emitter. Exempt from the scan: it legitimately owns the
# desktop notify-send fallback that every other producer must NOT call raw.
SINK = "hapax-alert"

# A raw high-priority desktop emit: notify-send at critical/urgent urgency.
RAW_DESKTOP = re.compile(
    r"notify-send\b[^\n]*?(?:-u\s+(?:critical|urgent)|--urgency=(?:critical|urgent))"
)
# A raw high-priority ntfy emit: a Priority header at high/urgent/max.
RAW_NTFY = re.compile(r"Priority:\s*(?:high|urgent|max)\b", re.IGNORECASE)
# Governed routing: the wrapper, or a direct call to the intake CLI / module.
GOVERNED = re.compile(r"hapax-alert|hapax-p0-incident-intake|p0_incident_intake")

# Lines of proximity within which an ntfy emit's governed call must appear.
# Routing follows the emit (a multi-line curl/cmd then the hapax-alert call), so
# this must clear a python cmd-list + try/except (~13 lines in echo-probe) while
# staying under the ~25-line gap between lane-idle-watchdog's distinct branches.
WINDOW = 20

# Explicitly NOT incident producers: their high-priority emit is informational,
# not a technical incident. Each entry carries a rationale — this dict IS the
# governance record for the exception, kept honest by ``test_allowlist_entries_are_live``.
ALLOWLIST = {
    # Routine user-initiated working-mode switch ping (research <-> R&D). The
    # `priority: high` at line ~114 is relay-inflection frontmatter (data written
    # via heredoc), and line ~190 posts ntfy with a *variable* Priority, not a
    # literal high/urgent.
    "hapax-working-mode": "informational mode-switch ntfy, not a system incident",
}

# Producers pinned as known high-priority alert sources — each MUST keep governed
# routing (regression guard against a fix being silently reverted).
KNOWN_PRODUCERS = (
    "hapax-disk-space-check",
    "hapax-vram-watchdog",
    "hapax-backup-watchdog",
    "hapax-audio-stage-check",
    "hapax-v4l2-watchdog.sh",
    "usb-bandwidth-preflight.sh",
    "hapax-cache-cleanup",
    "hapax-audio-safe-restart",
    "hapax-lane-idle-watchdog",
    "hapax-lane-reaper",
    "hapax-lane-supervisor",
    "hapax-post-merge-deploy",
    "hapax-worktree-gc.sh",
    "private-broadcast-echo-probe.py",
)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _emit_violations(path: Path) -> list[str]:
    """Return per-emit routing violations in one file (empty if clean)."""
    text = _read(path)
    if text is None or path.name == SINK or path.name in ALLOWLIST:
        return []
    lines = text.splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        if RAW_DESKTOP.search(line):
            # A raw critical/urgent notify-send is acceptable ONLY as a fallback
            # AFTER a governed attempt (the canonical intake-then-notify-send
            # pattern, e.g. lane-supervisor, which short-circuits on intake
            # success). An UNCONDITIONAL one — or one whose only routing is a
            # later --record-only call (backup-watchdog) — stacks un-coalesced in
            # the mako queue. So require a governed call in the PRECEDING lines.
            before = "\n".join(lines[max(0, i - WINDOW) : i + 1])
            if not GOVERNED.search(before):
                out.append(
                    f"{path.name}:{i + 1} raw critical/urgent notify-send with no governed "
                    f"call in the preceding {WINDOW} lines — route through hapax-alert (one "
                    "coalesced pointer) or place it after a governed intake attempt"
                )
        if RAW_NTFY.search(line):
            lo, hi = max(0, i - WINDOW), min(len(lines), i + WINDOW + 1)
            if not GOVERNED.search("\n".join(lines[lo:hi])):
                out.append(
                    f"{path.name}:{i + 1} ntfy high/urgent emit with no governed "
                    f"routing within +/-{WINDOW} lines"
                )
    return out


def test_sink_exists_and_is_executable() -> None:
    sink = SCRIPTS / SINK
    assert sink.is_file(), f"governed emitter missing: {sink}"
    assert sink.stat().st_mode & stat.S_IXUSR, f"{SINK} must be executable (producers exec it)"


def test_sink_routes_through_intake_and_supports_record_only() -> None:
    text = _read(SCRIPTS / SINK) or ""
    assert "hapax-p0-incident-intake" in text, "hapax-alert must call the intake CLI"
    assert "--record-only" in text, "hapax-alert must support --record-only"
    assert "--no-desktop" in text, "record-only must suppress desktop via --no-desktop"


@pytest.mark.parametrize("name", KNOWN_PRODUCERS)
def test_known_producer_routes_through_governed_intake(name: str) -> None:
    path = SCRIPTS / name
    assert path.is_file(), f"known high-priority producer missing: {name}"
    text = _read(path) or ""
    assert GOVERNED.search(text), (
        f"{name} is a known high-priority alert source but no longer routes "
        "through hapax-alert / hapax-p0-incident-intake"
    )


def test_no_unrouted_raw_high_priority_emit_per_emit() -> None:
    """Tripwire: EVERY raw high-priority emit anywhere in scripts/ must be governed."""
    violations: list[str] = []
    for path in sorted(SCRIPTS.rglob("*")):
        if path.is_file():
            violations.extend(_emit_violations(path))
    assert not violations, "Raw high-priority alert(s) bypass governed P0 intake:\n" + "\n".join(
        violations
    )


@pytest.mark.parametrize("name", sorted(ALLOWLIST))
def test_allowlist_entries_are_live(name: str) -> None:
    """A stale allowlist hides regressions — every entry must exist, still emit a raw
    high-priority signal, and carry a non-empty rationale."""
    path = SCRIPTS / name
    assert path.is_file(), f"allowlisted script missing — remove from ALLOWLIST: {name}"
    text = _read(path) or ""
    assert RAW_DESKTOP.search(text) or RAW_NTFY.search(text), (
        f"{name} no longer emits a raw high-priority signal — remove it from "
        "ALLOWLIST so the tripwire stays meaningful"
    )
    assert ALLOWLIST[name].strip(), f"allowlist entry {name} needs a rationale"

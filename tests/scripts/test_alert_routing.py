"""Canary: every raw high-priority system alert must route through governed P0 intake.

Class-closure regression guard for the PR #4109 finding ("raw high-priority
alert sources bypass P0 intake"). Standalone watchdog / health scripts used to
call ``notify-send -u critical`` or POST ntfy ``Priority: high`` directly, so
their alerts never created a governed incident record. The fix routes every such
producer through ``scripts/hapax-alert`` (the one governed emitter) or, for
scripts that already did, directly through ``hapax-p0-incident-intake``.

This test fails any NEW raw high-priority emitter that lacks governed routing,
so the class stays closed — not just today's instances.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"

# The one governed emitter. Exempt from the raw-emit scan: it legitimately owns
# the desktop notify-send fallback that every other producer must NOT call raw.
SINK = "hapax-alert"

# Raw high-priority emit signatures that bypass intake when used directly.
RAW_DESKTOP = re.compile(r"notify-send\b[^\n]*?(?:-u\s+critical|--urgency=critical)")
RAW_NTFY = re.compile(r"Priority:\s*(?:high|urgent|max)\b", re.IGNORECASE)

# Governed routing: the wrapper, or a direct call to the intake CLI / module.
GOVERNED = re.compile(r"hapax-alert|hapax-p0-incident-intake|p0_incident_intake")

# Explicitly NOT incident producers: their high-priority emit is informational,
# not a technical incident, so it deliberately does not create a P0 record.
# Each entry carries a rationale — this dict IS the governance record for the
# exception, and ``test_allowlist_entries_are_live`` keeps it from going stale.
ALLOWLIST = {
    # Routine user-initiated working-mode switch ping (research <-> R&D). The
    # `priority: high` at line ~114 is relay-inflection frontmatter (data
    # written via heredoc), not an alert emit.
    "hapax-working-mode": "informational mode-switch ntfy, not a system incident",
}

# Producers pinned as known high-priority alert sources — each MUST keep
# governed routing (regression guard against a fix being silently reverted).
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


def _matches_raw(text: str) -> bool:
    return bool(RAW_DESKTOP.search(text) or RAW_NTFY.search(text))


def _raw_emitters() -> list[Path]:
    hits: list[Path] = []
    for path in sorted(SCRIPTS.rglob("*")):
        if not path.is_file() or path.name == SINK or path.name in ALLOWLIST:
            continue
        text = _read(path)
        if text is None:
            continue
        if _matches_raw(text):
            hits.append(path)
    return hits


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


def test_no_unrouted_raw_high_priority_emitters() -> None:
    """Tripwire: any raw high-priority emit anywhere in scripts/ must route to intake."""
    violations = [p.name for p in _raw_emitters() if not GOVERNED.search(_read(p) or "")]
    assert not violations, (
        "Raw high-priority alert(s) bypass the governed P0 intake — route them "
        f"through scripts/hapax-alert: {violations}"
    )


@pytest.mark.parametrize("name", sorted(ALLOWLIST))
def test_allowlist_entries_are_live(name: str) -> None:
    """A stale allowlist hides regressions — every entry must exist, still emit a
    raw high-priority signal, and carry a non-empty rationale."""
    path = SCRIPTS / name
    assert path.is_file(), f"allowlisted script missing — remove from ALLOWLIST: {name}"
    text = _read(path) or ""
    assert _matches_raw(text), (
        f"{name} no longer emits a raw high-priority signal — remove it from "
        "ALLOWLIST so the tripwire stays meaningful"
    )
    assert ALLOWLIST[name].strip(), f"allowlist entry {name} needs a rationale"

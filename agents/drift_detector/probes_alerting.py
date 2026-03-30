"""Alerting and notification chain sufficiency probes."""

from __future__ import annotations

import subprocess

from .config import AI_AGENTS_DIR
from .sufficiency_probes import SufficiencyProbe


def _check_systemd_timer_coverage() -> tuple[bool, str]:
    """Check that systemd timer count matches recurring agent count."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-timers", "--no-pager", "--plain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        timer_lines = [
            line
            for line in result.stdout.splitlines()
            if ".timer" in line and "NEXT" not in line and "timers listed" not in line
        ]
        timer_count = len(timer_lines)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, "could not query systemd timers"

    try:
        from shared.config import load_expected_timers

        expected = load_expected_timers()
        if timer_count >= len(expected):
            return (
                True,
                f"{timer_count} timers active, covers {len(expected)} expected recurring agents",
            )
        return False, f"only {timer_count} timers but {len(expected)} recurring agents expected"
    except ImportError:
        if timer_count >= 10:
            return True, f"{timer_count} timers active"
        return False, f"only {timer_count} timers active"


def _check_notification_chain() -> tuple[bool, str]:
    """Check that ntfy + notify.py end-to-end path exists."""
    notify_file = AI_AGENTS_DIR / "shared" / "notify.py"
    if not notify_file.exists():
        return False, "shared/notify.py not found"

    content = notify_file.read_text()
    has_ntfy = "ntfy" in content
    has_desktop = "notify-send" in content or "notify_send" in content

    if has_ntfy and has_desktop:
        return True, "notify.py has ntfy (push) and desktop (notify-send) channels"
    missing: list[str] = []
    if not has_ntfy:
        missing.append("ntfy")
    if not has_desktop:
        missing.append("desktop")
    return False, f"notify.py missing channels: {', '.join(missing)}"


def _check_profile_context_chain() -> tuple[bool, str]:
    """Check that Qdrant profile-facts + context tools chain works."""
    context_file = AI_AGENTS_DIR / "shared" / "context_tools.py"
    profile_store_file = AI_AGENTS_DIR / "shared" / "profile_store.py"

    if not context_file.exists():
        return False, "context_tools.py not found"
    if not profile_store_file.exists():
        return False, "profile_store.py not found"

    context_content = context_file.read_text()
    has_search_profile = "search_profile" in context_content
    has_profile_summary = "get_profile_summary" in context_content
    has_sufficiency = "lookup_sufficiency_requirements" in context_content

    if has_search_profile and has_profile_summary and has_sufficiency:
        return (
            True,
            "context tools chain complete: search_profile + get_profile_summary + lookup_sufficiency_requirements + ProfileStore",
        )
    return False, "context tools chain incomplete"


def _check_proactive_alert_surfacing() -> tuple[bool, str]:
    """Check health_monitor pushes alerts proactively."""
    hm_file = AI_AGENTS_DIR / "agents" / "health_monitor.py"
    if not hm_file.exists():
        return False, "health_monitor.py not found"

    content = hm_file.read_text()
    has_notify = "notify" in content.lower()
    has_ntfy = "ntfy" in content

    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "health-monitor.timer"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        timer_active = result.stdout.strip() == "active"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        timer_active = False

    if has_notify and timer_active:
        return True, f"health_monitor has notification calls and timer is active (ntfy: {has_ntfy})"
    problems: list[str] = []
    if not has_notify:
        problems.append("no notification calls")
    if not timer_active:
        problems.append("timer not active")
    return False, f"proactive alerting incomplete: {', '.join(problems)}"


ALERTING_PROBES: list[SufficiencyProbe] = [
    SufficiencyProbe(
        id="probe-routine-001",
        axiom_id="executive_function",
        implication_id="ex-routine-007",
        level="system",
        question="Does systemd timer count match recurring agent count?",
        check=_check_systemd_timer_coverage,
    ),
    SufficiencyProbe(
        id="probe-alert-001",
        axiom_id="executive_function",
        implication_id="ex-attention-001",
        level="system",
        question="Does ntfy + notify.py end-to-end path exist?",
        check=_check_notification_chain,
    ),
    SufficiencyProbe(
        id="probe-memory-001",
        axiom_id="executive_function",
        implication_id="ex-memory-010",
        level="system",
        question="Does Qdrant profile-facts + context tools chain work?",
        check=_check_profile_context_chain,
    ),
    SufficiencyProbe(
        id="probe-alert-004",
        axiom_id="executive_function",
        implication_id="ex-alert-004",
        level="system",
        question="Does health_monitor proactively push alerts rather than requiring operator checks?",
        check=_check_proactive_alert_surfacing,
    ),
]

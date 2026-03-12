"""shared/alert_state.py — Alert state machine for health-watchdog.

Provides deduplication, escalation, grouping, and recovery notifications
for health check results. State persists in a JSON file.

Usage (from health-watchdog):
    from shared.alert_state import process_report
    actions = process_report(report_dict, state_path="profiles/alert-state.json")
    for action in actions:
        send_notification(action["title"], action["message"], priority=action["priority"], tags=action["tags"])
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

_log = logging.getLogger(__name__)

# Dedup window: don't re-alert same check+status within this many seconds
DEDUP_WINDOW_S = 30 * 60  # 30 minutes

# Escalation thresholds (in consecutive failure cycles)
DEGRADED_ESCALATION_CYCLES = 4  # degraded >1h (4 × 15min) → high priority
T0_URGENT_CYCLES = 2  # T0 failed >30min (2 × 15min) → urgent priority

# T0 (critical) check groups — failures here escalate faster
T0_GROUPS = {"docker", "gpu", "litellm", "langfuse", "qdrant", "postgres"}


def process_report(
    report: dict,
    state_path: str | Path = "profiles/alert-state.json",
) -> list[dict]:
    """Process a health report and return a list of alert actions.

    Each action is a dict with keys: title, message, priority, tags.
    The caller is responsible for sending notifications.

    Args:
        report: Parsed JSON health report with groups/checks structure.
        state_path: Path to the persistent state JSON file.

    Returns:
        List of alert action dicts to send as notifications.
    """
    state_path = Path(state_path)
    state = _load_state(state_path)
    now = time.time()
    actions: list[dict] = []

    # Collect current check statuses
    current_checks: dict[str, dict] = {}
    for group in report.get("groups", []):
        group_name = group.get("name", "unknown")
        for check in group.get("checks", []):
            check_name = check.get("name", "unknown")
            check_status = check.get("status", "unknown")
            current_checks[check_name] = {
                "status": check_status,
                "group": group_name,
                "message": check.get("message", ""),
            }

    # Process each check
    failed_by_group: dict[str, list[str]] = {}

    for check_name, check_info in current_checks.items():
        status = check_info["status"]
        group = check_info["group"]
        prev = state.get(check_name, {})

        if status == "healthy":
            # Recovery: was previously alerted and now healthy
            if prev.get("alerted") and prev.get("status") != "healthy":
                actions.append(
                    {
                        "title": "Recovered",
                        "message": f"{check_name} is healthy again",
                        "priority": "default",
                        "tags": ["white_check_mark"],
                    }
                )
            state[check_name] = {"status": "healthy", "since": now, "cycles": 0, "alerted": False}
            continue

        # Failed or degraded
        if prev.get("status") == status:
            cycles = prev.get("cycles", 0) + 1
        else:
            cycles = 1

        last_alert_time = prev.get("last_alert_time", 0)
        is_t0 = group.lower() in T0_GROUPS

        # Determine priority
        if status == "failed" and is_t0 and cycles >= T0_URGENT_CYCLES:
            priority = "urgent"
        elif cycles >= DEGRADED_ESCALATION_CYCLES or status == "failed":
            priority = "high"
        else:
            priority = "default"

        # Dedup: skip if same status was alerted within window
        should_alert = True
        if prev.get("alerted") and prev.get("alert_status") == status:
            if (now - last_alert_time) < DEDUP_WINDOW_S:
                # But still alert on escalation (priority change)
                if priority == prev.get("alert_priority"):
                    should_alert = False

        if should_alert:
            failed_by_group.setdefault(group, []).append(
                f"{check_name}: {check_info['message'] or status}"
            )

        state[check_name] = {
            "status": status,
            "since": prev.get("since", now) if prev.get("status") == status else now,
            "cycles": cycles,
            "alerted": should_alert or prev.get("alerted", False),
            "alert_status": status if should_alert else prev.get("alert_status"),
            "alert_priority": priority if should_alert else prev.get("alert_priority"),
            "last_alert_time": now if should_alert else last_alert_time,
        }

    # Group failures into per-group notifications
    for group, check_messages in failed_by_group.items():
        is_t0 = group.lower() in T0_GROUPS
        # Use highest priority from checks in this group
        group_priority = "default"
        for check_name in current_checks:
            cs = state.get(check_name, {})
            if cs.get("alert_priority") == "urgent":
                group_priority = "urgent"
                break
            if cs.get("alert_priority") == "high" and group_priority != "urgent":
                group_priority = "high"

        tag = "rotating_light" if group_priority in ("urgent", "high") else "warning"
        actions.append(
            {
                "title": f"Health: {group}",
                "message": "\n".join(check_messages),
                "priority": group_priority,
                "tags": [tag],
            }
        )

    _save_state(state_path, state)
    return actions


def _load_state(path: Path) -> dict:
    """Load alert state from JSON file, returning empty dict on any error."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _log.warning("Corrupt alert state file %s, resetting: %s", path, exc)
    return {}


def _save_state(path: Path, state: dict) -> None:
    """Atomically save alert state to JSON file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.rename(path)
    except Exception as exc:
        _log.warning("Failed to save alert state: %s", exc)

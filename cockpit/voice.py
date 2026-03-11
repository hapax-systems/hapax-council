"""voice — warm copilot personality for the cockpit."""

from __future__ import annotations

from datetime import datetime


def operator_name() -> str:
    """Operator first name from profile, fallback 'Operator'."""
    try:
        from shared.operator import get_operator

        op = get_operator().get("operator", {})
        return op.get("name", "Operator").split()[0]
    except Exception:
        return "Operator"


def greeting() -> str:
    """Time-of-day greeting with operator name."""
    h = datetime.now().hour
    name = operator_name()
    if 4 <= h < 12:
        return f"morning, {name}"
    if 12 <= h < 17:
        return f"afternoon, {name}"
    if 17 <= h < 21:
        return f"evening, {name}"
    return f"late one, {name}"

"""Notification capability — recruited affordance for operator alerting.

Routes through shared/notify.py infrastructure (ntfy + desktop + watershed).
Salience maps to notification priority. Material maps to tag emoji.
"""

from __future__ import annotations

import logging

from shared.notify import send_notification

log = logging.getLogger("notification.capability")

_SALIENCE_TO_PRIORITY = [
    (0.8, "high"),
    (0.6, "default"),
    (0.4, "low"),
    (0.0, "min"),
]

_MATERIAL_TO_TAG = {
    "fire": "fire",
    "water": "droplet",
    "earth": "mountain",
    "air": "cloud",
    "void": "black_circle",
}


def activate_notification(narrative: str, salience: float, material: str = "void") -> bool:
    """Send a notification recruited by the affordance pipeline.

    Args:
        narrative: The imagination narrative or impingement content to surface.
        salience: 0.0-1.0, maps to ntfy priority level.
        material: Bachelardian element, maps to tag emoji.
    """
    priority = "min"
    for threshold, prio in _SALIENCE_TO_PRIORITY:
        if salience >= threshold:
            priority = prio
            break

    tag = _MATERIAL_TO_TAG.get(material, "bell")

    return send_notification(
        title="Hapax",
        message=narrative[:200],
        priority=priority,
        tags=[tag],
    )

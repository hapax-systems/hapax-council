"""LRR Phase 8 item 5 — hero-mode camera switching by active objective.

Reads the active objectives (same path as ``objectives_overlay`` +
``director_loop._render_active_objectives_block``) and returns a
recommended hero camera role for the compositor to switch to. Pure
logic: no compositor state mutation — the caller (systemd timer
driver, compositor integration) is responsible for actually issuing
the layout change.

Mapping from objective-activity → hero camera role (initial draft,
operator-tunable):

    vinyl        → "hardware"  (turntable view)
    react        → "hardware"  (whatever Hapax is reacting to)
    study        → "operator"  (face; study-mode framing)
    chat         → "operator"  (face; conversation framing)
    observe      → None        (no hero; balanced grid)
    silence      → None        (no hero; passive)

The highest-priority active objective with a mapped activity wins.
Ties → most-recently-opened wins (same ordering as the overlay + the
director's prompt block).

Not in scope here:
- The systemd timer unit that invokes this on a cadence
- Integration with ``LayoutState.mutate()`` — the caller applies the
  returned hero role via the compositor's existing layout machinery
- Operator-editable config surface for the mapping (currently hardcoded;
  moving to ``config/objective-hero-map.yaml`` is a follow-up if the
  mapping needs tuning in production)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_OBJECTIVES_DIR = Path.home() / "Documents" / "Personal" / "30-areas" / "hapax-objectives"

# Activity → preferred camera role. Activities not in this map do not
# produce a hero recommendation. Order mirrors the current Objective
# schema whitelist: react / chat / vinyl / study / observe / silence.
ACTIVITY_HERO_MAP: dict[str, str | None] = {
    "vinyl": "hardware",
    "react": "hardware",
    "study": "operator",
    "chat": "operator",
    "observe": None,
    "silence": None,
}


def hero_for_active_objectives(
    objectives_dir: Path | None = None,
    *,
    allowed_roles: frozenset[str] | None = None,
) -> str | None:
    """Return the hero camera role for the top active objective, or None.

    Args:
        objectives_dir: Vault path for objective markdown files. Defaults
            to the shared vault location.
        allowed_roles: Optional whitelist — if given, only roles in this
            set are returned (callers pass the set of *currently-available*
            camera roles so a mapping to e.g. 'hardware' doesn't return
            if no hardware camera is connected).

    Returns:
        A camera role string matching ``CameraSpec.role`` in the
        compositor's camera registry, or ``None`` when no active
        objective has a mapped activity (or the mapped role is filtered
        by ``allowed_roles``).
    """
    directory = objectives_dir or DEFAULT_OBJECTIVES_DIR
    active = _load_active_objectives(directory)
    if not active:
        return None

    for obj in active:
        for activity in obj.get("activities", []):
            role = ACTIVITY_HERO_MAP.get(activity)
            if role is None:
                continue
            if allowed_roles is not None and role not in allowed_roles:
                continue
            return role

    return None


def _load_active_objectives(directory: Path) -> list[dict[str, Any]]:
    """Load + sort active objectives. Returns list of dicts (title + priority + activities)."""
    try:
        from shared.frontmatter import parse_frontmatter
        from shared.objective_schema import (
            Objective,
            ObjectivePriority,
            ObjectiveStatus,
        )
    except Exception:
        log.debug("objective-schema import failed", exc_info=True)
        return []

    if not directory.exists():
        return []

    priority_rank = {
        ObjectivePriority.high: 3,
        ObjectivePriority.normal: 2,
        ObjectivePriority.low: 1,
    }

    active: list[Objective] = []
    for path in sorted(directory.glob("obj-*.md")):
        try:
            fm, _ = parse_frontmatter(path)
            if not fm:
                continue
            obj = Objective(**fm)
            if obj.status == ObjectiveStatus.active:
                active.append(obj)
        except Exception:
            continue

    active.sort(
        key=lambda o: (priority_rank[o.priority], -o.opened_at.timestamp()),
        reverse=True,
    )
    return [
        {
            "title": o.title,
            "priority": o.priority.value,
            "activities": list(o.activities_that_advance),
        }
        for o in active
    ]

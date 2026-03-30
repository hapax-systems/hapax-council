"""Negotiated accommodation engine.

Translates discovered neurocognitive patterns into concrete system behavior
changes, confirmed by the operator. Nothing assumed from patterns alone —
every accommodation must be proposed and confirmed.

State persisted to profiles/accommodations.json.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime

from logos._config import PROFILES_DIR

_ACCOMMODATIONS_PATH = PROFILES_DIR / "accommodations.json"


@dataclass
class Accommodation:
    """A single system behavior adaptation."""

    id: str  # e.g. "time_anchor"
    pattern_category: str  # neurocognitive category it's derived from
    description: str  # human-readable: "Show elapsed session time"
    active: bool  # operator confirmed this helps
    proposed_at: str  # ISO timestamp
    confirmed_at: str = ""  # ISO timestamp when confirmed


@dataclass
class AccommodationSet:
    """Active accommodations and derived convenience flags."""

    accommodations: list[Accommodation] = field(default_factory=list)

    # Derived convenience flags (from confirmed accommodations)
    time_anchor_enabled: bool = False
    soft_framing: bool = False
    energy_aware: bool = False
    peak_hours: list[int] = field(default_factory=list)
    low_hours: list[int] = field(default_factory=list)


# ── Proposal templates ──────────────────────────────────────────────────────
# Maps pattern category → list of (accommodation_id, description)

_PROPOSALS: dict[str, list[tuple[str, str]]] = {
    "time_perception": [
        ("time_anchor", "Show elapsed session time in copilot messages"),
    ],
    "demand_sensitivity": [
        (
            "soft_framing",
            "Use observational framing ('I notice...') instead of imperatives ('you should...')",
        ),
    ],
    "energy_cycles": [
        ("energy_aware", "Reduce non-urgent nudge priority during identified low-energy hours"),
    ],
    "task_initiation": [
        ("smallest_step", "For stalled items, surface the smallest possible next step"),
    ],
}


def load_accommodations() -> AccommodationSet:
    """Read confirmed accommodations from profiles/accommodations.json. Deterministic."""
    result = AccommodationSet()

    if not _ACCOMMODATIONS_PATH.exists():
        return result

    try:
        data = json.loads(_ACCOMMODATIONS_PATH.read_text())
        for item in data.get("accommodations", []):
            result.accommodations.append(
                Accommodation(
                    id=item["id"],
                    pattern_category=item.get("pattern_category", ""),
                    description=item.get("description", ""),
                    active=item.get("active", False),
                    proposed_at=item.get("proposed_at", ""),
                    confirmed_at=item.get("confirmed_at", ""),
                )
            )
    except (json.JSONDecodeError, KeyError):
        return result

    # Derive convenience flags from active accommodations
    active_ids = {a.id for a in result.accommodations if a.active}
    result.time_anchor_enabled = "time_anchor" in active_ids
    result.soft_framing = "soft_framing" in active_ids
    result.energy_aware = "energy_aware" in active_ids

    # Parse energy hours if energy_aware
    if result.energy_aware:
        try:
            hours_data = data.get("energy_hours", {})
            result.peak_hours = hours_data.get("peak", [])
            result.low_hours = hours_data.get("low", [])
        except Exception:
            pass

    return result


def save_accommodations(acc_set: AccommodationSet) -> None:
    """Write accommodations to profiles/accommodations.json."""
    data = {
        "accommodations": [
            {
                "id": a.id,
                "pattern_category": a.pattern_category,
                "description": a.description,
                "active": a.active,
                "proposed_at": a.proposed_at,
                "confirmed_at": a.confirmed_at,
            }
            for a in acc_set.accommodations
        ],
    }
    if acc_set.energy_aware:
        data["energy_hours"] = {
            "peak": acc_set.peak_hours,
            "low": acc_set.low_hours,
        }
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=PROFILES_DIR, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, _ACCOMMODATIONS_PATH)
    except BaseException:
        os.unlink(tmp_path)
        raise


def propose_accommodation(pattern_category: str) -> list[Accommodation]:
    """Given a newly discovered pattern, generate accommodation proposals. Deterministic."""
    templates = _PROPOSALS.get(pattern_category, [])
    now = datetime.now(UTC).isoformat()
    proposals = []
    for acc_id, description in templates:
        proposals.append(
            Accommodation(
                id=acc_id,
                pattern_category=pattern_category,
                description=description,
                active=False,
                proposed_at=now,
            )
        )
    return proposals


def confirm_accommodation(acc_set: AccommodationSet, acc_id: str) -> bool:
    """Confirm an accommodation by ID. Returns True if found and activated."""
    now = datetime.now(UTC).isoformat()
    for a in acc_set.accommodations:
        if a.id == acc_id:
            a.active = True
            a.confirmed_at = now
            save_accommodations(acc_set)
            return True
    return False


def disable_accommodation(acc_set: AccommodationSet, acc_id: str) -> bool:
    """Disable an accommodation by ID. Returns True if found and deactivated."""
    for a in acc_set.accommodations:
        if a.id == acc_id:
            a.active = False
            a.confirmed_at = ""
            save_accommodations(acc_set)
            return True
    return False

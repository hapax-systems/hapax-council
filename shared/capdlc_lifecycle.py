"""CapDLC lifecycle registry.

Phase 0 only registers the monetary/capability lifecycle as an honest dark
stub. Measurement and scorer logic belong to later phases.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

CAPDLC_CANONICAL_LABEL: Final = "CapDLC"
CAPDLC_SLUG: Final = "capdlc"
CAPDLC_LEGACY_LABELS: Final = ("MDLC",)


class CapDLCLifecycleState(StrEnum):
    """Lifecycle states for CapDLC measurement capability registration."""

    DARK_SPECIFIED = "dark_specified"
    MEASURED = "measured"


@dataclass(frozen=True)
class CapDLCLifecycleEntry:
    """Registered CapDLC lifecycle row.

    ``bool(entry)`` is intentionally tied to measured value presence so a dark
    stub cannot accidentally pass a truthiness check downstream.
    """

    slug: str
    canonical_label: str
    lifecycle_state: CapDLCLifecycleState
    measured_value: float | None
    legacy_labels: tuple[str, ...] = ()
    description: str = ""

    def __bool__(self) -> bool:
        return self.is_measured

    @property
    def is_measured(self) -> bool:
        return (
            self.lifecycle_state is CapDLCLifecycleState.MEASURED
            and self.measured_value is not None
        )


CAPDLC_DARK_STUB: Final = CapDLCLifecycleEntry(
    slug=CAPDLC_SLUG,
    canonical_label=CAPDLC_CANONICAL_LABEL,
    lifecycle_state=CapDLCLifecycleState.DARK_SPECIFIED,
    measured_value=None,
    legacy_labels=CAPDLC_LEGACY_LABELS,
    description=(
        "CapDLC monetary/capability lifecycle is specified but not measured; "
        "legacy MDLC references are provenance only."
    ),
)

CAPDLC_LIFECYCLE_REGISTRY: Final = {CAPDLC_DARK_STUB.slug: CAPDLC_DARK_STUB}


def resolve_capdlc_lifecycle(label: str) -> CapDLCLifecycleEntry | None:
    """Resolve the canonical CapDLC label or preserved legacy aliases."""

    normalized = label.strip().casefold()
    for entry in CAPDLC_LIFECYCLE_REGISTRY.values():
        labels = (entry.slug, entry.canonical_label, *entry.legacy_labels)
        if normalized in {candidate.casefold() for candidate in labels}:
            return entry
    return None


def measured_capdlc_entries() -> tuple[CapDLCLifecycleEntry, ...]:
    """Return only entries that carry measured value."""

    return tuple(entry for entry in CAPDLC_LIFECYCLE_REGISTRY.values() if entry.is_measured)


__all__ = [
    "CAPDLC_CANONICAL_LABEL",
    "CAPDLC_DARK_STUB",
    "CAPDLC_LEGACY_LABELS",
    "CAPDLC_LIFECYCLE_REGISTRY",
    "CAPDLC_SLUG",
    "CapDLCLifecycleEntry",
    "CapDLCLifecycleState",
    "measured_capdlc_entries",
    "resolve_capdlc_lifecycle",
]

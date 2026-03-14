"""Epistemic carrier dynamics: bounded cross-domain fact carrying.

Implements DD-24 (carrier slots), DD-25 (frequency-weighted displacement).
Each agent carries a small set of foreign-domain facts observed incidentally
through contact topology. Carrier facts are Labeled[Any] values — consent
labels travel with carried facts via the DLM join.

The carrier mechanism provides near-optimal cross-domain error correction
(§9.4, factor graph equivalence) with O(1) carrier capacity per agent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from shared.consent_label import ConsentLabel
from shared.labeled import Labeled


@dataclass(frozen=True)
class CarrierFact:
    """A foreign-domain fact carried incidentally by an agent.

    Wraps a Labeled[Any] with source domain metadata and observation
    frequency for displacement decisions (DD-25).
    """

    labeled: Labeled[Any]
    source_domain: str
    observation_count: int = 1
    first_seen: float = 0.0
    last_seen: float = 0.0

    def observe(self, timestamp: float) -> CarrierFact:
        """Return a new instance with incremented count and updated last_seen."""
        return CarrierFact(
            labeled=self.labeled,
            source_domain=self.source_domain,
            observation_count=self.observation_count + 1,
            first_seen=self.first_seen,
            last_seen=timestamp,
        )

    def same_fact(self, other: CarrierFact) -> bool:
        """Check if two carrier facts represent the same observation."""
        return (
            self.labeled.value == other.labeled.value and self.source_domain == other.source_domain
        )

    @property
    def consent_label(self) -> ConsentLabel:
        """Consent label of the carried value."""
        return self.labeled.label

    @property
    def provenance(self) -> frozenset[str]:
        """Contract IDs justifying this fact's existence."""
        return self.labeled.provenance


@dataclass(frozen=True)
class DisplacementResult:
    """Outcome of offering a carrier fact to a registry."""

    inserted: bool
    displaced: CarrierFact | None = None
    reason: str = ""


class CarrierRegistry:
    """Mutable registry of carrier facts per principal.

    Enforces bounded capacity per principal (DD-24). Displacement
    follows frequency-weighted policy (DD-25): new facts must be
    observed significantly more frequently than the least-observed
    existing fact to displace it.
    """

    __slots__ = ("_slots", "_capacities", "displacement_threshold")

    def __init__(self, displacement_threshold: float = 2.0) -> None:
        self._slots: dict[str, list[CarrierFact]] = {}
        self._capacities: dict[str, int] = {}
        self.displacement_threshold = displacement_threshold

    def register(self, principal_id: str, capacity: int) -> None:
        """Register a principal with a given carrier capacity."""
        if capacity < 0:
            raise ValueError(f"Carrier capacity must be non-negative, got {capacity}")
        self._slots.setdefault(principal_id, [])
        self._capacities[principal_id] = capacity

    def facts(self, principal_id: str) -> tuple[CarrierFact, ...]:
        """Return current carrier facts for a principal."""
        return tuple(self._slots.get(principal_id, []))

    def offer(self, principal_id: str, fact: CarrierFact) -> DisplacementResult:
        """Offer a carrier fact to a principal's slots.

        1. If duplicate, update observation count.
        2. If under capacity, insert.
        3. If at capacity, displace least-observed if new >> least (threshold).
        4. Otherwise reject.
        """
        if principal_id not in self._capacities:
            raise ValueError(f"Principal {principal_id} not registered")

        slots = self._slots[principal_id]
        capacity = self._capacities[principal_id]

        # Check for duplicate — update observation count
        for i, existing in enumerate(slots):
            if existing.same_fact(fact):
                slots[i] = existing.observe(fact.last_seen)
                return DisplacementResult(inserted=True, reason="updated existing")

        # Under capacity — insert directly
        if len(slots) < capacity:
            slots.append(fact)
            return DisplacementResult(inserted=True, reason="slot available")

        # At capacity — attempt frequency-weighted displacement
        if not slots:
            return DisplacementResult(inserted=False, reason="zero capacity")

        least_idx = min(range(len(slots)), key=lambda i: slots[i].observation_count)
        least = slots[least_idx]

        if fact.observation_count > least.observation_count * self.displacement_threshold:
            displaced = slots[least_idx]
            slots[least_idx] = fact
            return DisplacementResult(inserted=True, displaced=displaced, reason="displaced")

        return DisplacementResult(
            inserted=False,
            reason=f"insufficient frequency: {fact.observation_count} <= "
            f"{least.observation_count} * {self.displacement_threshold}",
        )

    def purge_by_provenance(self, contract_id: str) -> int:
        """Remove carrier facts whose provenance includes contract_id.

        Returns the number of facts purged. Supports consent revocation (DD-8).
        """
        purged = 0
        for slots in self._slots.values():
            before = len(slots)
            slots[:] = [f for f in slots if contract_id not in f.provenance]
            purged += before - len(slots)
        return purged


def epistemic_contradiction_veto(
    local_knowledge: Callable[[str, Any], bool],
) -> Callable[[CarrierFact], bool]:
    """Create a predicate that checks carrier facts against local knowledge.

    local_knowledge(source_domain, value) -> True if consistent, False if contradicts.
    Returns a predicate suitable for filtering carrier facts before propagation.
    """

    def _check(fact: CarrierFact) -> bool:
        return local_knowledge(fact.source_domain, fact.labeled.value)

    return _check

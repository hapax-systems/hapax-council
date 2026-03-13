"""ResourceClaim + ResourceArbiter — priority-based resource contention resolution.

When multiple governance chains want the same physical resource (e.g., audio output),
the arbiter resolves contention using a static priority map. Higher priority wins.
Equal priority resolves FIFO by creation time.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResourceClaim:
    """A claim on a physical resource by a governance chain.

    Frozen dataclass — immutable like Command and Schedule.
    """

    resource: str
    chain: str
    priority: int
    command: object  # Command or any action descriptor
    hold_until: float = 0.0  # wall-clock time; 0 = one-shot (released after drain)
    max_hold_s: float = 30.0
    created_at: float = field(default_factory=time.monotonic)


class ResourceArbiter:
    """Priority-based resource contention resolver.

    Each (resource, chain) pair must have a configured priority. Claims are
    resolved per-resource: highest priority wins. Equal priority resolves
    FIFO (earliest created_at).
    """

    __slots__ = ("_priorities", "_claims")

    def __init__(self, priorities: dict[tuple[str, str], int]) -> None:
        self._priorities = dict(priorities)
        self._claims: dict[str, list[ResourceClaim]] = {}

    def claim(self, rc: ResourceClaim) -> None:
        """Register a resource claim. Replaces existing claim from same chain.

        Raises ValueError if (resource, chain) pair has no configured priority.
        """
        key = (rc.resource, rc.chain)
        if key not in self._priorities:
            raise ValueError(f"No priority configured for {key}")
        if rc.priority != self._priorities[key]:
            raise ValueError(
                f"Claim priority {rc.priority} != configured {self._priorities[key]} for {key}"
            )

        claims = self._claims.setdefault(rc.resource, [])
        # Remove existing claim from same chain
        self._claims[rc.resource] = [c for c in claims if c.chain != rc.chain]
        # Insert maintaining priority desc, then created_at asc order
        self._claims[rc.resource].append(rc)
        self._claims[rc.resource].sort(key=lambda c: (-c.priority, c.created_at))

    def release(self, resource: str, chain: str) -> None:
        """Release a chain's claim on a resource."""
        if resource in self._claims:
            self._claims[resource] = [
                c for c in self._claims[resource] if c.chain != chain
            ]
            if not self._claims[resource]:
                del self._claims[resource]

    def resolve(self, resource: str) -> ResourceClaim | None:
        """Return the highest-priority claim for a resource, or None."""
        claims = self._claims.get(resource, [])
        return claims[0] if claims else None

    def drain_winners(self, now: float | None = None) -> list[ResourceClaim]:
        """Return one winner per resource. GC expired holds, remove one-shot claims.

        Returns the winning claim for each contested resource.
        One-shot claims (hold_until == 0) are removed after being returned.
        Held claims past max_hold_s are garbage collected.
        """
        if now is None:
            now = time.monotonic()

        winners: list[ResourceClaim] = []
        resources_to_clean: list[str] = []

        for resource, claims in self._claims.items():
            # GC expired holds
            surviving: list[ResourceClaim] = []
            for c in claims:
                if c.hold_until > 0 and now > c.created_at + c.max_hold_s:
                    log.debug("GC expired hold: %s/%s (age=%.1fs)", c.resource, c.chain, now - c.created_at)
                    continue
                surviving.append(c)

            if not surviving:
                resources_to_clean.append(resource)
                continue

            self._claims[resource] = surviving
            winner = surviving[0]
            winners.append(winner)

            # Remove one-shot claims after winning
            if winner.hold_until == 0.0:
                self._claims[resource] = [c for c in surviving if c is not winner]
                if not self._claims[resource]:
                    resources_to_clean.append(resource)

        for r in resources_to_clean:
            self._claims.pop(r, None)

        return winners

    @property
    def active_claims(self) -> dict[str, list[ResourceClaim]]:
        """Snapshot of all active claims by resource."""
        return {r: list(cs) for r, cs in self._claims.items()}

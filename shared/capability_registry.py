"""Capability registry — unified activation interface for the impingement cascade.

Every capability — internal component or external tool — registers with one
interface. There is no distinction between "component" and "tool." Speech
production, camera classification, fortress governance, and a Qdrant query
are all capabilities with the same registration protocol.

Capabilities self-select by evaluating their affordance match against
broadcast impingement signals. The registry handles broadcast, competition
resolution, and cascade tracking.

Follows the PerceptionBackend protocol pattern from hapax_daimonion/perception.py.
Extends (does not replace) AgentManifest/AgentRegistry for static metadata.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from shared.impingement import Impingement

log = logging.getLogger("capability_registry")


@runtime_checkable
class Capability(Protocol):
    """Protocol that any activatable component/tool must satisfy."""

    @property
    def name(self) -> str: ...

    @property
    def affordance_signature(self) -> set[str]: ...

    @property
    def activation_cost(self) -> float: ...

    @property
    def activation_level(self) -> float: ...

    @property
    def consent_required(self) -> bool: ...

    @property
    def priority_floor(self) -> bool: ...

    def can_resolve(self, impingement: Impingement) -> float:
        """Return activation strength (0.0 = irrelevant, 1.0 = perfect match)."""
        ...

    def activate(self, impingement: Impingement, level: float) -> Any:
        """Attempt to resolve the impingement at the given activation level."""
        ...

    def deactivate(self) -> None:
        """Return to dormant state."""
        ...


@dataclass
class CapabilityMatch:
    """A capability that matched an impingement, with its computed score."""

    capability: Capability
    match_score: float  # from can_resolve()
    effective_score: float  # after cost weighting and competition
    impingement: Impingement


@dataclass
class InhibitionEntry:
    """Tracks inhibition of return — prevents re-processing resolved signals."""

    impingement_source: str
    impingement_content_hash: str
    inhibited_until: float  # monotonic time


class CapabilityRegistry:
    """Runtime capability registry with broadcast and competition resolution."""

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._inhibitions: list[InhibitionEntry] = []
        self._cascade_log: list[dict[str, Any]] = []

    def register(self, capability: Capability) -> None:
        """Register a capability for broadcast reception."""
        self._capabilities[capability.name] = capability
        log.info(
            "Registered capability: %s (affordances=%s, cost=%.2f)",
            capability.name,
            capability.affordance_signature,
            capability.activation_cost,
        )

    def deregister(self, name: str) -> None:
        """Remove a capability from the registry."""
        self._capabilities.pop(name, None)

    @property
    def capabilities(self) -> dict[str, Capability]:
        return dict(self._capabilities)

    def is_inhibited(self, impingement: Impingement) -> bool:
        """Check if this impingement type is in inhibition-of-return period."""
        now = time.monotonic()
        # Prune expired inhibitions
        self._inhibitions = [e for e in self._inhibitions if e.inhibited_until > now]
        content_hash = (
            str(hash(frozenset(impingement.content.items()))) if impingement.content else ""
        )
        return any(
            e.impingement_source == impingement.source
            and e.impingement_content_hash == content_hash
            for e in self._inhibitions
        )

    def add_inhibition(self, impingement: Impingement, duration_s: float = 30.0) -> None:
        """Add inhibition-of-return for a resolved impingement."""
        content_hash = (
            str(hash(frozenset(impingement.content.items()))) if impingement.content else ""
        )
        self._inhibitions.append(
            InhibitionEntry(
                impingement_source=impingement.source,
                impingement_content_hash=content_hash,
                inhibited_until=time.monotonic() + duration_s,
            )
        )

    def broadcast(self, impingement: Impingement) -> list[CapabilityMatch]:
        """Broadcast an impingement to all registered capabilities.

        Returns matched capabilities sorted by effective score (highest first).
        Applies:
        - Inhibition of return (skip if recently resolved)
        - Affordance matching (can_resolve)
        - Cost weighting (cheap capabilities score higher)
        - Priority floor (safety-critical bypass competition)
        - Mutual suppression (competing capabilities reduce each other's scores)
        """
        if self.is_inhibited(impingement):
            log.debug("Impingement %s inhibited (recently resolved)", impingement.source)
            return []

        matches: list[CapabilityMatch] = []
        priority_matches: list[CapabilityMatch] = []

        for cap in self._capabilities.values():
            match_score = cap.can_resolve(impingement)
            if match_score <= 0.0:
                continue

            # Cost-weighted effective score
            effective = match_score * (1.0 - cap.activation_cost * 0.5)

            # Consent check (synchronous, <1ms)
            if cap.consent_required:
                try:
                    from shared.governance.consent_gate import ConsentGatedWriter

                    gate = ConsentGatedWriter()
                    decision = gate.check()
                    if not decision.allowed:
                        log.debug("Capability %s blocked by consent gate", cap.name)
                        continue
                except Exception:
                    pass  # consent infrastructure not available — allow

            entry = CapabilityMatch(
                capability=cap,
                match_score=match_score,
                effective_score=effective,
                impingement=impingement,
            )

            if cap.priority_floor:
                priority_matches.append(entry)
            else:
                matches.append(entry)

        # Priority floor capabilities bypass competition
        if priority_matches:
            log.info("Priority floor activation: %s", [m.capability.name for m in priority_matches])
            return sorted(priority_matches, key=lambda m: -m.effective_score)

        # Mutual suppression: top match suppresses others in same affordance category
        if len(matches) > 1:
            matches.sort(key=lambda m: -m.effective_score)
            winner_score = matches[0].effective_score
            for m in matches[1:]:
                # Suppress by 30% of winner's advantage
                suppression = (winner_score - m.effective_score) * 0.3
                m.effective_score = max(0.0, m.effective_score - suppression)

        # Filter out suppressed capabilities (below minimum threshold)
        matches = [m for m in matches if m.effective_score > 0.05]
        matches.sort(key=lambda m: -m.effective_score)

        # Log cascade
        if matches:
            self._cascade_log.append(
                {
                    "timestamp": time.time(),
                    "impingement_id": impingement.id,
                    "impingement_source": impingement.source,
                    "impingement_strength": impingement.strength,
                    "matched": [(m.capability.name, m.effective_score) for m in matches],
                }
            )
            log.info(
                "Broadcast %s (strength=%.2f) → matched %d capabilities: %s",
                impingement.source,
                impingement.strength,
                len(matches),
                [(m.capability.name, f"{m.effective_score:.2f}") for m in matches],
            )

        return matches

    @property
    def recent_cascades(self) -> list[dict[str, Any]]:
        """Return recent cascade log for observability."""
        return self._cascade_log[-50:]

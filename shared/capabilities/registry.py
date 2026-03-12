"""Capability Registry: register, discover, and health-check adapters.

Central registry for all capability adapters. Each adapter registers
under a Protocol type. Only one adapter per capability type is active
at a time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from shared.capabilities.protocols import HealthStatus

log = logging.getLogger(__name__)


@dataclass
class RegistryEntry:
    """An adapter registered in the capability registry."""

    capability_type: str
    adapter: object
    name: str


class CapabilityRegistry:
    """Registry for capability adapters.

    Register adapters by capability type name. Get the active adapter,
    check health across all registered capabilities.
    """

    def __init__(self) -> None:
        self._entries: dict[str, RegistryEntry] = {}

    def register(self, capability_type: str, adapter: object) -> None:
        """Register an adapter for a capability type.

        Raises ValueError if an adapter is already registered for this type.
        """
        if capability_type in self._entries:
            existing = self._entries[capability_type].name
            raise ValueError(f"Capability '{capability_type}' already registered by '{existing}'")
        name = getattr(adapter, "name", type(adapter).__name__)
        if not hasattr(adapter, "available") or not hasattr(adapter, "health"):
            raise TypeError(f"Adapter {name} must implement available() and health() methods")
        self._entries[capability_type] = RegistryEntry(
            capability_type=capability_type,
            adapter=adapter,
            name=name,
        )
        log.info("Registered capability %s: %s", capability_type, name)

    def get(self, capability_type: str) -> object | None:
        """Get the registered adapter for a capability type, or None."""
        entry = self._entries.get(capability_type)
        if entry is None:
            return None
        return entry.adapter

    def health(self) -> dict[str, HealthStatus]:
        """Check health of all registered adapters."""
        results: dict[str, HealthStatus] = {}
        for cap_type, entry in self._entries.items():
            try:
                status = entry.adapter.health()  # type: ignore[union-attr]
                results[cap_type] = status
            except Exception as e:
                results[cap_type] = HealthStatus(healthy=False, message=str(e))
        return results

    @property
    def registered(self) -> dict[str, str]:
        """Return mapping of capability_type → adapter name."""
        return {k: v.name for k, v in self._entries.items()}

    def __contains__(self, capability_type: str) -> bool:
        return capability_type in self._entries

    def __len__(self) -> int:
        return len(self._entries)

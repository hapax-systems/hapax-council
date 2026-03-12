"""Disposable capability layer: Protocols, Registry, and Adapters.

Capabilities are runtime-discovered, health-checked abstractions over
external services (LLMs, vector DBs, desktop environments, etc.).
Each capability is defined by a Protocol and backed by one or more
disposable Adapters that can fail independently.
"""

from shared.capabilities.protocols import (
    DesktopCapability,
    DesktopResult,
    EmbeddingCapability,
    EmbeddingResult,
)
from shared.capabilities.registry import CapabilityRegistry

__all__ = [
    "CapabilityRegistry",
    "DesktopCapability",
    "DesktopResult",
    "EmbeddingCapability",
    "EmbeddingResult",
]

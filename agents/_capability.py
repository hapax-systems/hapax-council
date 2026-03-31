"""agents/_capability.py — Re-export shim for shared.capability.

All capability types are defined in shared/capability.py (canonical source).
This module re-exports them for agents/ import convenience.
"""

from shared.capability import (  # noqa: F401
    Capability,
    CapabilityCategory,
    CapabilityRegistry,
    ResourceTier,
    SystemContext,
)

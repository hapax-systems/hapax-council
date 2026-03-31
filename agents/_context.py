"""agents/_context.py — Re-export shim for shared.context.

All context types are defined in shared/context.py (canonical source).
This module re-exports them for agents/ import convenience.
"""

from shared.context import (  # noqa: F401
    ContextAssembler,
    EnrichmentContext,
)

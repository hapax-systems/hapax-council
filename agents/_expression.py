"""Vendored shim: re-exports shared.expression for consumer code.

Consumer code (agents/, logos/) must import from here, not from shared/.
"""

from __future__ import annotations

from shared.expression import (  # noqa: F401
    FRAGMENT_TO_SHADER,
    MATERIAL_TO_UNIFORM,
    ExpressionCoordinator,
    map_fragment_to_material_uniform,
    map_fragment_to_visual,
)

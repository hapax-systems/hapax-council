"""HACL — Hapax Adaptive Compression Layer.

Four organs: the Lens (seam), the Surface Registry (classifier), the
Compressibility Gate (fail-closed guardrail), and the Ledger (meter). This
package currently ships the Surface Registry; subsequent HACL tasks add the
gate, the lens, and the ledger.

Spec: hapax-research/specs/2026-06-08-hacl-context-compression-design.md
"""

from __future__ import annotations

from shared.compression.registry import (
    DENY_DEFAULT,
    Codec,
    RegistryError,
    SurfaceSpec,
    Tier,
    get_surface_spec,
    load_registry,
)

__all__ = [
    "Tier",
    "Codec",
    "SurfaceSpec",
    "RegistryError",
    "DENY_DEFAULT",
    "load_registry",
    "get_surface_spec",
]

"""Aesthetic library — canonical ingest of authentic BitchX + Enlightenment + Px437 assets.

All downstream aesthetic work (HOMAGE refinement, scrim palettes, omg.lol surfaces,
LORE wards, credits page) reads from this library rather than re-sourcing. Provenance
+ license + SHA-256 tracked per asset.

Spec: docs/superpowers/specs/2026-04-24-operator-referent-policy-design.md (sibling PR)
Task: ytb-AUTH1 (see cc-tasks/active/ytb-AUTH1-aesthetic-library.md)
"""

from shared.aesthetic_library.integrity import IntegrityError
from shared.aesthetic_library.loader import (
    AestheticLibrary,
    Asset,
    library,
)
from shared.aesthetic_library.manifest import Manifest, ManifestEntry
from shared.aesthetic_library.provenance import Provenance

__all__ = [
    "Asset",
    "AestheticLibrary",
    "IntegrityError",
    "Manifest",
    "ManifestEntry",
    "Provenance",
    "library",
]

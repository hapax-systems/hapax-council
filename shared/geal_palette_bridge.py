"""GEAL palette bridge (spec §8).

Resolves stance → palette (§8.1) and register → halo-role permutations
(§8.2), with pre-computed grounding-extrusion LAB anchors (§8.3) that
GEAL's sub-triangle latch-and-fade uses without a palette swap.

The bridge is backed by ``shared/geal_stance_palette_map.yaml`` (the
operator-editable mapping) and ``shared/palette_registry.py`` (which
owns the actual palette anchors). It caches resolved palettes per
stance so the render tick never pays a registry lookup.

Entry point: :meth:`GealPaletteBridge.load_default`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from shared.palette_registry import PaletteRegistry

_DEFAULT_MAPPING_PATH = Path(__file__).with_name("geal_stance_palette_map.yaml")

Apex = Literal["top", "bl", "br"]


@dataclass(frozen=True)
class HaloRoleAssignment:
    """Register → halo-role permutation for one palette (spec §8.2).

    Roles are string tokens that GEAL resolves to concrete LAB anchors
    when painting each halo. ``lp_omega_override`` lets a register
    (currently only ``ritual``) slow the V2 SecondOrderLP for the
    "slow-breathing" signature.
    """

    apex: str
    bl: str
    br: str
    halo_alpha_boost: float = 0.0
    lp_omega_override: float | None = None


@dataclass(frozen=True)
class ResolvedPalette:
    """A stance's active palette plus the rationale + fallback id.

    Holds a reference into the :class:`PaletteRegistry` so callers can
    reach ``dominant_lab`` / ``accent_lab`` / ``curve`` / etc. without
    another lookup on the hot path.
    """

    stance: str
    palette: object  # shared.palette_family.ScrimPalette (avoid heavy import at module top)
    fallback_id: str
    rationale: str


class GealPaletteBridge:
    """Stance → palette, register → halo-roles, grounding → accent-LAB.

    Construct via :meth:`load_default`, which reads the canonical YAML
    mapping + the palette registry. Tests that want an isolated bridge
    should call :meth:`load` with explicit paths.
    """

    def __init__(
        self,
        *,
        mapping: dict,
        registry: PaletteRegistry,
    ) -> None:
        self._mapping = mapping
        self._registry = registry
        self._resolved_cache: dict[str, ResolvedPalette] = {}

    @classmethod
    def load_default(cls) -> GealPaletteBridge:
        """Load from the repo-default YAML + palette registry."""
        registry = PaletteRegistry.load()
        return cls.load(mapping_path=_DEFAULT_MAPPING_PATH, registry=registry)

    @classmethod
    def load(
        cls,
        *,
        mapping_path: Path,
        registry: PaletteRegistry,
    ) -> GealPaletteBridge:
        raw = yaml.safe_load(Path(mapping_path).read_text(encoding="utf-8")) or {}
        return cls(mapping=raw, registry=registry)

    # -- §8.1 stance → palette ----------------------------------------------

    def resolve_palette(self, stance: str) -> ResolvedPalette:
        """Return the active palette for ``stance`` (primary, or fallback).

        Unknown stances fall back to NOMINAL — GEAL never renders
        uncoloured; the governance principle is "always a palette,
        never a crash".
        """
        cached = self._resolved_cache.get(stance)
        if cached is not None:
            return cached

        stance_map = self._mapping.get("stance_palette", {})
        entry = stance_map.get(stance) or stance_map.get("NOMINAL")
        if entry is None:
            raise RuntimeError(
                "geal_stance_palette_map.yaml missing NOMINAL entry — cannot resolve GEAL palette"
            )

        primary_id = entry["primary"]
        fallback_id = entry.get("fallback", primary_id)
        rationale = entry.get("rationale", "")

        palette = self._registry.find_palette(primary_id)
        if palette is None:
            palette = self._registry.find_palette(fallback_id)
        if palette is None:
            raise RuntimeError(
                f"neither primary={primary_id!r} nor fallback={fallback_id!r} "
                f"resolves in the palette registry"
            )

        resolved = ResolvedPalette(
            stance=stance,
            palette=palette,
            fallback_id=fallback_id,
            rationale=rationale,
        )
        self._resolved_cache[stance] = resolved
        return resolved

    # -- §8.2 register → halo roles -----------------------------------------

    def halo_roles(self, palette_id: str, register: str) -> HaloRoleAssignment:
        """Return apex / BL / BR halo role assignment for ``register``.

        ``palette_id`` is accepted so callers can reach for palette-
        specific overrides in the future; v1 uses the same table across
        all palettes (the per-register permutation is palette-agnostic).

        Unknown registers fall back to ``conversing`` (the default
        operator register) so a typo in a SHM write doesn't strand the
        halos in an off state.
        """
        table = self._mapping.get("register_halo_roles", {})
        entry = table.get(register) or table.get("conversing")
        if entry is None:
            # Last-resort hardcoded default — keeps the render path
            # alive even if the YAML is mis-shaped.
            return HaloRoleAssignment(
                apex="duotone_high",
                bl="duotone_high",
                br="duotone_high",
                halo_alpha_boost=0.0,
            )
        return HaloRoleAssignment(
            apex=entry.get("apex_role", "duotone_high"),
            bl=entry.get("bl_role", "duotone_high"),
            br=entry.get("br_role", "duotone_high"),
            halo_alpha_boost=float(entry.get("halo_alpha_boost", 0.0)),
            lp_omega_override=(
                float(entry["lp_omega_override"]) if "lp_omega_override" in entry else None
            ),
        )

    # -- §8.3 grounding extrusion → accent LAB ------------------------------

    def grounding_latch_lab(self, palette_id: str, apex: Apex) -> tuple[float, float, float]:
        """Return the LAB colour GEAL's G2 latch-and-fade paints per apex.

        Top = dominant, BL = accent, BR = midpoint. Never triggers a
        palette swap — only draws from the active palette's anchors.
        """
        palette = self._registry.find_palette(palette_id)
        if palette is None:
            raise KeyError(f"palette not registered: {palette_id}")
        dominant = tuple(palette.dominant_lab)
        accent = tuple(palette.accent_lab)
        if apex == "top":
            return dominant  # type: ignore[return-value]
        if apex == "bl":
            return accent  # type: ignore[return-value]
        if apex == "br":
            lerped = tuple((d + a) * 0.5 for d, a in zip(dominant, accent, strict=True))
            return lerped  # type: ignore[return-value]
        raise ValueError(f"unknown apex: {apex}")

    def grounding_latch_lab_all_apices(
        self, palette_id: str
    ) -> dict[str, tuple[float, float, float]]:
        """Three-apex batch for imagination-converge events (§8.3)."""
        return {
            "top": self.grounding_latch_lab(palette_id, "top"),
            "bl": self.grounding_latch_lab(palette_id, "bl"),
            "br": self.grounding_latch_lab(palette_id, "br"),
        }


__all__ = ["Apex", "GealPaletteBridge", "HaloRoleAssignment", "ResolvedPalette"]

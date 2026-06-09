"""shared/compression/registry.py — HACL Surface Registry loader.

Loads the static, reviewable surface-tier classification table
(``config/compression-surface-registry.yaml``) and exposes a fail-closed
lookup. This is the *classifier* organ of the Hapax Adaptive Compression Layer:
every compressing call site asks the registry what (if anything) a given
surface is allowed to do.

Fail-closed invariants enforced at load time:
- An unknown surface resolves to ``DENY`` / ``passthrough`` (never compressed).
- ``deny`` and ``hot_path`` tiers MUST use ``passthrough`` and MUST NOT enable
  the lossy Headroom codec (structurally forbidden — a config that violates this
  raises at load, not at runtime).
- ``lossless_only`` MUST NOT enable Headroom (lossy) — to_toon only.

Spec: hapax-research/specs/2026-06-08-hacl-context-compression-design.md
"""

from __future__ import annotations

import enum
import functools
from dataclasses import dataclass
from pathlib import Path

import yaml

__all__ = [
    "Tier",
    "Codec",
    "SurfaceSpec",
    "RegistryError",
    "DENY_DEFAULT",
    "load_registry",
    "get_surface_spec",
]

_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "compression-surface-registry.yaml"
)


class Tier(enum.Enum):
    """Compression eligibility class for a surface."""

    LOSSLESS_OK = "lossless_ok"
    LOSSLESS_ONLY = "lossless_only"
    DENY = "deny"
    HOT_PATH = "hot_path"


class Codec(enum.Enum):
    """How a surface may be compressed."""

    TOON = "toon"
    HEADROOM = "headroom"
    PASSTHROUGH = "passthrough"


class RegistryError(ValueError):
    """Raised when the registry YAML violates a fail-closed structural invariant."""


@dataclass(frozen=True)
class SurfaceSpec:
    """Per-surface compression policy."""

    surface: str
    tier: Tier
    codec: Codec
    headroom_enabled: bool = False
    max_ratio: float = 1.0
    floor: float = 0.0
    alert_threshold: float = 1.0
    route_constraint: str = "any"

    @property
    def lossy_allowed(self) -> bool:
        """True only when lossy compression is permitted for this surface."""
        return self.tier is Tier.LOSSLESS_OK and self.headroom_enabled

    @property
    def lossless_allowed(self) -> bool:
        """True when lossless to_toon compression is permitted."""
        return self.tier in (Tier.LOSSLESS_OK, Tier.LOSSLESS_ONLY) and self.codec is Codec.TOON


#: The fail-closed verdict for any surface not present in the registry.
DENY_DEFAULT = SurfaceSpec(
    surface="<unknown>", tier=Tier.DENY, codec=Codec.PASSTHROUGH, headroom_enabled=False
)

_PROTECTED_TIERS = (Tier.DENY, Tier.HOT_PATH)


def _build_spec(surface: str, raw: dict) -> SurfaceSpec:
    try:
        tier = Tier(raw["tier"])
    except (KeyError, ValueError) as exc:
        raise RegistryError(f"surface {surface!r}: invalid/missing tier") from exc
    codec = Codec(raw.get("codec", "passthrough"))
    headroom = bool(raw.get("headroom_enabled", False))

    # Fail-closed structural invariants.
    if tier in _PROTECTED_TIERS:
        if codec is not Codec.PASSTHROUGH:
            raise RegistryError(f"surface {surface!r}: {tier.value} must use passthrough codec")
        if headroom:
            raise RegistryError(f"surface {surface!r}: {tier.value} cannot enable Headroom (lossy)")
    if tier is Tier.LOSSLESS_ONLY and headroom:
        raise RegistryError(f"surface {surface!r}: lossless_only cannot enable Headroom (lossy)")
    if headroom and codec is not Codec.HEADROOM and tier is Tier.LOSSLESS_OK:
        # headroom_enabled only meaningful when codec can dispatch to it; allow toon+pilot flag.
        pass

    return SurfaceSpec(
        surface=surface,
        tier=tier,
        codec=codec,
        headroom_enabled=headroom,
        max_ratio=float(raw.get("max_ratio", 1.0)),
        floor=float(raw.get("floor", 0.0)),
        alert_threshold=float(raw.get("alert_threshold", 1.0)),
        route_constraint=str(raw.get("route_constraint", "any")),
    )


def load_registry(path: Path | None = None) -> dict[str, SurfaceSpec]:
    """Parse + validate the surface registry YAML into ``{surface: SurfaceSpec}``.

    Raises ``RegistryError`` on any fail-closed invariant violation.
    """
    registry_path = path or _REGISTRY_PATH
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    default_tier = Tier(data.get("default_tier", "deny"))
    if default_tier is not Tier.DENY:
        raise RegistryError("default_tier MUST be 'deny' (fail-closed)")
    surfaces = data.get("surfaces", {}) or {}
    return {name: _build_spec(name, raw or {}) for name, raw in surfaces.items()}


@functools.lru_cache(maxsize=1)
def _cached_registry() -> dict[str, SurfaceSpec]:
    return load_registry()


def get_surface_spec(surface: str, registry: dict[str, SurfaceSpec] | None = None) -> SurfaceSpec:
    """Look up a surface's policy. Fail-closed: unknown surfaces resolve to DENY."""
    table = registry if registry is not None else _cached_registry()
    return table.get(surface, DENY_DEFAULT)

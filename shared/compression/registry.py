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
import math
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

__all__ = [
    "Tier",
    "Codec",
    "SurfaceSpec",
    "RegistryError",
    "DENY_DEFAULT",
    "parse_registry",
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
_SURFACE_FIELDS = {
    "alert_threshold",
    "codec",
    "floor",
    "headroom_enabled",
    "max_ratio",
    "route_constraint",
    "tier",
}


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects last-wins duplicate mappings."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise RegistryError("compression registry mapping keys MUST be scalar") from exc
        if duplicate:
            raise RegistryError(f"compression registry duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _strict_unit_float(raw: dict, field: str, default: float) -> float:
    value = raw.get(field, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RegistryError(f"surface numeric field {field!r} MUST be a number")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise RegistryError(f"surface numeric field {field!r} MUST be within [0, 1]")
    return result


def _build_spec(surface: str, raw: dict) -> SurfaceSpec:
    unknown_fields = set(raw) - _SURFACE_FIELDS
    if unknown_fields:
        raise RegistryError(f"surface {surface!r}: unknown fields {sorted(unknown_fields)!r}")
    raw_tier = raw.get("tier")
    if not isinstance(raw_tier, str):
        raise RegistryError(f"surface {surface!r}: invalid/missing tier")
    try:
        tier = Tier(raw_tier)
    except ValueError as exc:
        raise RegistryError(f"surface {surface!r}: invalid/missing tier") from exc
    raw_codec = raw.get("codec", "passthrough")
    if not isinstance(raw_codec, str):
        raise RegistryError(f"surface {surface!r}: codec MUST be a string")
    try:
        codec = Codec(raw_codec)
    except ValueError as exc:
        raise RegistryError(f"surface {surface!r}: codec is invalid") from exc
    headroom = raw.get("headroom_enabled", False)
    if not isinstance(headroom, bool):
        raise RegistryError(f"surface {surface!r}: headroom_enabled MUST be boolean")
    route_constraint = raw.get("route_constraint", "any")
    if (
        not isinstance(route_constraint, str)
        or not route_constraint.strip()
        or route_constraint != route_constraint.strip()
    ):
        raise RegistryError(f"surface {surface!r}: route_constraint MUST be nonblank")

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
        max_ratio=_strict_unit_float(raw, "max_ratio", 1.0),
        floor=_strict_unit_float(raw, "floor", 0.0),
        alert_threshold=_strict_unit_float(raw, "alert_threshold", 1.0),
        route_constraint=route_constraint,
    )


def _read_registry(path: Path | None) -> str:
    if path is not None:
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RegistryError(f"compression registry unreadable: {path}") from exc
    if _REGISTRY_PATH.is_file():
        return _read_registry(_REGISTRY_PATH)
    packaged = resources.files("shared").joinpath("_data", "compression-surface-registry.yaml")
    try:
        return packaged.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError("packaged compression registry is missing or unreadable") from exc


def parse_registry(raw_text: str) -> dict[str, SurfaceSpec]:
    """Parse one already-read registry snapshot into ``{surface: SurfaceSpec}``.

    Raises ``RegistryError`` on any fail-closed invariant violation.
    """
    try:
        data = yaml.load(raw_text, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise RegistryError("compression registry YAML is malformed") from exc
    if not isinstance(data, dict):
        raise RegistryError("compression registry root MUST be a mapping")
    if set(data) != {"version", "default_tier", "surfaces"}:
        raise RegistryError(
            "compression registry root requires only version, default_tier, and surfaces"
        )
    if type(data["version"]) is not int or data["version"] != 1:
        raise RegistryError("compression registry version MUST be integer 1")
    if not isinstance(data["default_tier"], str):
        raise RegistryError("compression registry default_tier MUST be a string")
    try:
        default_tier = Tier(data.get("default_tier", "deny"))
    except ValueError as exc:
        raise RegistryError("compression registry default_tier is invalid") from exc
    if default_tier is not Tier.DENY:
        raise RegistryError("default_tier MUST be 'deny' (fail-closed)")
    surfaces = data.get("surfaces", {})
    if not isinstance(surfaces, dict):
        raise RegistryError("compression registry surfaces MUST be a mapping")
    result: dict[str, SurfaceSpec] = {}
    for name, raw in surfaces.items():
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise RegistryError("compression registry surface names MUST be nonblank strings")
        if raw is not None and not isinstance(raw, dict):
            raise RegistryError(f"surface {name!r}: definition MUST be a mapping")
        result[name] = _build_spec(name, raw or {})
    return result


def load_registry(path: Path | None = None) -> dict[str, SurfaceSpec]:
    """Read, parse, and validate the surface registry without fallback."""

    return parse_registry(_read_registry(path))


@functools.lru_cache(maxsize=1)
def _cached_registry() -> dict[str, SurfaceSpec]:
    return load_registry()


def get_surface_spec(surface: str, registry: dict[str, SurfaceSpec] | None = None) -> SurfaceSpec:
    """Look up a surface's policy. Fail-closed: unknown surfaces resolve to DENY."""
    table = registry if registry is not None else _cached_registry()
    return table.get(surface, DENY_DEFAULT)

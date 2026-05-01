"""x402 license-class registry — operator-curated YAML + loader.

Per cc-task ``x402-license-class-registry``. Each Hapax license class
(``commercial`` / ``research`` / ``review``) maps to default x402 v2
``Accept`` fields (amount, asset, network) plus a description. The
class identifier rides in ``Accept.extra["hapax_license_class"]`` so
operator-side downstream surfaces can branch on tier without changing
the wire format the x402 v2 client sees.

Standard x402 clients are not required to interpret the
``hapax_license_class`` extra field — it's advisory at best per the
2026-05-01 spec research drop. Operator-side consumers (refusal annex,
repo-pres-license matrix) read it for per-class billing decisions.

YAML at ``config/x402-license-classes.yaml`` is the canonical source.
This module loads it once at import time; runtime mutation is
forbidden per ``single_user``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from agents.payment_processors.x402.models import Accept, validate_caip_network

DEFAULT_CONFIG_PATH: Path = (
    Path(__file__).resolve().parents[3] / "config" / "x402-license-classes.yaml"
)
"""Repository-relative path to the operator-curated YAML."""

EXTRA_KEY: str = "hapax_license_class"
"""The key under which ``apply_to_accept`` injects the class id into
``Accept.extra``. Hapax-namespaced so it does not collide with x402
v2's documented ``extra`` keys (``name``, ``version``, etc.)."""


class LicenseClass(StrEnum):
    """Three Hapax-defined classes for operator-licensed resources.

    StrEnum so values serialize cleanly into JSON / YAML without an
    explicit dump hook.
    """

    COMMERCIAL = "commercial"
    RESEARCH = "research"
    REVIEW = "review"


@dataclass(frozen=True)
class LicenseClassEntry:
    """One license-class row from the registry. Frozen so the registry
    is immutable per ``single_user``.
    """

    class_id: LicenseClass
    default_amount: str
    default_asset: str
    default_network: str
    description: str
    notes: str = ""


class LicenseRegistryError(Exception):
    """Raised when YAML parsing, validation, or lookup fails."""


def _parse_entry(raw: dict[str, Any]) -> LicenseClassEntry:
    """Validate one YAML row → :class:`LicenseClassEntry`."""
    try:
        class_id = LicenseClass(raw["id"])
    except (KeyError, ValueError) as exc:
        raise LicenseRegistryError(f"unknown or missing license class id: {raw!r}") from exc
    amount = str(raw.get("default_amount", "")).strip()
    if not amount.isdigit():
        raise LicenseRegistryError(
            f"license class {class_id.value}: default_amount must be a non-negative "
            f"integer string in base units; got {amount!r}"
        )
    network = str(raw.get("default_network", "")).strip()
    try:
        validate_caip_network(network)
    except ValueError as exc:
        raise LicenseRegistryError(f"license class {class_id.value}: {exc}") from exc
    asset = str(raw.get("default_asset", "")).strip()
    if not asset:
        raise LicenseRegistryError(
            f"license class {class_id.value}: default_asset must be non-empty"
        )
    return LicenseClassEntry(
        class_id=class_id,
        default_amount=amount,
        default_asset=asset,
        default_network=network,
        description=str(raw.get("description", "")).strip(),
        notes=str(raw.get("notes", "")).strip(),
    )


def load_registry(
    path: Path = DEFAULT_CONFIG_PATH,
) -> dict[LicenseClass, LicenseClassEntry]:
    """Load + validate the YAML registry. Raises on malformed config.

    Returns a dict keyed by :class:`LicenseClass`. Every defined enum
    member must have a corresponding YAML row, or
    :class:`LicenseRegistryError` is raised — the registry is
    expected to be exhaustive, not partial.
    """
    if not path.is_file():
        raise LicenseRegistryError(f"license-class config missing at {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "classes" not in payload:
        raise LicenseRegistryError(
            f"{path} must be a mapping with a 'classes' key carrying a list of entries"
        )
    rows = payload["classes"]
    if not isinstance(rows, list) or not rows:
        raise LicenseRegistryError(f"{path}::classes must be a non-empty list")
    by_id: dict[LicenseClass, LicenseClassEntry] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise LicenseRegistryError(f"{path}::classes entry must be a mapping; got {raw!r}")
        entry = _parse_entry(raw)
        if entry.class_id in by_id:
            raise LicenseRegistryError(
                f"duplicate license class id in {path}: {entry.class_id.value}"
            )
        by_id[entry.class_id] = entry
    missing = set(LicenseClass) - by_id.keys()
    if missing:
        raise LicenseRegistryError(
            f"{path} is incomplete; missing classes: {sorted(c.value for c in missing)}"
        )
    return by_id


# Eager load at module import; callers consume the immutable mapping.
LICENSE_CLASS_REGISTRY: dict[LicenseClass, LicenseClassEntry] = load_registry()


def apply_to_accept(accept: Accept, cls: LicenseClass) -> Accept:
    """Return a new ``Accept`` enriched with class-id metadata.

    Behavior:
    - Adds ``"hapax_license_class": cls.value`` to the per-accept
      ``extra`` dict (preserving any caller-set entries).
    - Sets per-class ``amount`` / ``asset`` / ``network`` defaults
      *only* when the caller's accept carries the model defaults
      (empty / sentinel) — caller-set values are never overwritten.
    - Idempotent: calling twice with the same class produces the
      same result; calling with a different class replaces the
      ``hapax_license_class`` value but keeps everything else.
    """
    entry = LICENSE_CLASS_REGISTRY[cls]
    new_extra = {**accept.extra, EXTRA_KEY: cls.value}
    update: dict[str, Any] = {"extra": new_extra}
    if not accept.amount:
        update["amount"] = entry.default_amount
    if not accept.asset:
        update["asset"] = entry.default_asset
    if not accept.network:
        update["network"] = entry.default_network
    return accept.model_copy(update=update)


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "EXTRA_KEY",
    "LICENSE_CLASS_REGISTRY",
    "LicenseClass",
    "LicenseClassEntry",
    "LicenseRegistryError",
    "apply_to_accept",
    "load_registry",
]

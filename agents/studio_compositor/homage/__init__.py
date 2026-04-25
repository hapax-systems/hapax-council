"""HOMAGE package registry + active-package resolution.

HOMAGE spec §4.1. One package is active at a time. Packages are
registered at module import; the active name is resolved via
``/dev/shm/hapax-compositor/homage-active.json`` (written by the
structural director or operator CLI), falling back to the compiled-in
default when the file is missing or malformed.

Consumers:

- The choreographer reads the active package to pick the transition
  vocabulary and coupling rules for the tick.
- Cairo source render callbacks read the active package's grammar +
  palette.
- The daimonion's voice-register reader (Phase 7) reads
  ``voice_register_default`` when the SHM override is absent.

Registering a new package is adding a file under this directory that
imports and calls ``register_package()`` at module load. No runtime
mutation — packages are immutable after registration.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Final

from shared.homage_package import HomagePackage

log = logging.getLogger(__name__)

_ACTIVE_FILE: Final[Path] = Path("/dev/shm/hapax-compositor/homage-active.json")
_DEFAULT_PACKAGE_NAME: Final[str] = "bitchx-authentic-v1"
# Phase 12: the consent-safe variant the choreographer falls back to when
# the consent gate flips to compose-safe. Registered below at import time.
CONSENT_SAFE_PACKAGE_NAME: Final[str] = "bitchx_consent_safe"

_registry: dict[str, HomagePackage] = {}
_lock = threading.Lock()


def register_package(package: HomagePackage) -> None:
    """Register a package under its ``name``. Idempotent if the same
    instance is registered twice; raises if two distinct packages try
    to claim the same name."""
    with _lock:
        existing = _registry.get(package.name)
        if existing is not None and existing is not package:
            raise ValueError(
                f"HomagePackage name collision: {package.name!r} already "
                "registered with a different instance"
            )
        _registry[package.name] = package


def registered_package_names() -> tuple[str, ...]:
    with _lock:
        return tuple(sorted(_registry.keys()))


def get_package(name: str) -> HomagePackage | None:
    with _lock:
        return _registry.get(name)


def _read_active_name() -> str | None:
    try:
        if not _ACTIVE_FILE.exists():
            return None
        payload = json.loads(_ACTIVE_FILE.read_text(encoding="utf-8"))
        name = payload.get("package")
        if isinstance(name, str) and name:
            return name
        return None
    except Exception:
        log.debug("homage-active.json unreadable; falling back", exc_info=True)
        return None


def get_active_package(*, consent_safe: bool = False) -> HomagePackage | None:
    """Resolve the currently active HomagePackage.

    Returns ``None`` when ``consent_safe`` is True — HOMAGE is disabled
    under the consent-safe layout per spec §3.3 gate 4 and the
    ``it-irreversible-broadcast`` axiom.

    Otherwise: read ``homage-active.json``; fall back to the default
    package if the file is missing, malformed, or names a package that
    has not been registered.
    """
    if consent_safe:
        return None
    name = _read_active_name() or _DEFAULT_PACKAGE_NAME
    pkg = get_package(name)
    if pkg is None and name != _DEFAULT_PACKAGE_NAME:
        log.warning(
            "active homage package %r not registered; falling back to default %r",
            name,
            _DEFAULT_PACKAGE_NAME,
        )
        pkg = get_package(_DEFAULT_PACKAGE_NAME)
    return pkg


def get_consent_safe_package() -> HomagePackage | None:
    """Return the registered consent-safe package variant.

    Phase 12 introduced ``bitchx_consent_safe`` — BitchX grammar with
    every accent colour collapsed to muted grey and the signature
    artefact corpus stripped. The choreographer uses this variant when
    the consent gate flips the compositor into compose-safe layout, so
    HOMAGE keeps running structurally without emitting anything that
    could carry operator identity into the broadcast.

    Returns ``None`` if the variant was never registered (e.g., a
    compositor build that stripped the consent-safe module). Callers
    should treat that as "hard-disable HOMAGE" rather than silently
    falling back to the coloured default — the safer posture under the
    ``it-irreversible-broadcast`` axiom.
    """
    return get_package(CONSENT_SAFE_PACKAGE_NAME)


def set_active_package(name: str) -> None:
    """Write ``name`` into the active-package SHM file atomically.

    Writer side of the contract. No-op if the registry does not know
    the name (prevents typo-activation). Caller is responsible for
    axiom gating (consent-safe, stream-mode).
    """
    if get_package(name) is None:
        raise ValueError(f"cannot activate unregistered package {name!r}")
    _ACTIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _ACTIVE_FILE.with_suffix(_ACTIVE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps({"package": name}), encoding="utf-8")
    tmp.replace(_ACTIVE_FILE)


# Register the built-in BitchX packages at import time.
from agents.studio_compositor.homage.bitchx import (  # noqa: E402
    BITCHX_CONSENT_SAFE_PACKAGE,
    BITCHX_PACKAGE,
)
from agents.studio_compositor.homage.bitchx_authentic import (  # noqa: E402
    BITCHX_AUTHENTIC_PACKAGE,
)
from agents.studio_compositor.homage.enlightenment_moksha import (  # noqa: E402
    ENLIGHTENMENT_MOKSHA_PACKAGE,
)
from agents.studio_compositor.homage.enlightenment_moksha_authentic import (  # noqa: E402
    ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE,
)

register_package(BITCHX_PACKAGE)
register_package(BITCHX_CONSENT_SAFE_PACKAGE)
register_package(BITCHX_AUTHENTIC_PACKAGE)
register_package(ENLIGHTENMENT_MOKSHA_PACKAGE)
register_package(ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE)


__all__ = [
    "BITCHX_AUTHENTIC_PACKAGE",
    "BITCHX_CONSENT_SAFE_PACKAGE",
    "BITCHX_PACKAGE",
    "CONSENT_SAFE_PACKAGE_NAME",
    "ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE",
    "ENLIGHTENMENT_MOKSHA_PACKAGE",
    "get_active_package",
    "get_consent_safe_package",
    "get_package",
    "register_package",
    "registered_package_names",
    "set_active_package",
]

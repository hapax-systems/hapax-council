"""shared/browser_services.py — Python-side service registry for browser agents.

Mirrors the Rust-side ServiceRegistry. Loads ~/.hapax/browser-services.json
and provides URL resolution + domain allowlist checking.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REGISTRY_PATH = Path.home() / ".hapax" / "browser-services.json"


def load_registry() -> dict[str, Any]:
    """Load service registry from disk. Returns empty dict if missing."""
    if not REGISTRY_PATH.exists():
        log.info("No browser-services.json found at %s", REGISTRY_PATH)
        return {}
    try:
        return json.loads(REGISTRY_PATH.read_text())
    except Exception:
        log.warning("Failed to parse browser-services.json", exc_info=True)
        return {}


def is_allowed(url: str) -> bool:
    """Check if a URL is within an allowlisted service domain."""
    registry = load_registry()
    return any(url.startswith(svc.get("base", "")) for svc in registry.values())


def resolve_url(service: str, pattern: str, params: dict[str, str] | None = None) -> str | None:
    """Resolve a service + pattern + params to a full URL."""
    registry = load_registry()
    svc = registry.get(service)
    if not svc:
        return None

    template = svc.get("patterns", {}).get(pattern)
    if not template:
        return None

    url = svc["base"] + template
    for key, value in (params or {}).items():
        url = url.replace(f"{{{key}}}", value)

    # Fill defaults
    if default_repo := svc.get("default_repo"):
        url = url.replace("{repo}", default_repo)

    return url

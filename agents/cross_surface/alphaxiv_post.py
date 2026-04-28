"""Retired alphaXiv comments publisher.

alphaXiv comments are refused by the canonical publication-bus registry
(``agents.publication_bus.surface_registry``) because the surface prohibits
LLM-generated comments. This module remains as a defensive compatibility shim
for old import paths; it never performs network I/O.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def publish_artifact(artifact) -> str:  # type: ignore[no-untyped-def]
    """Refuse direct alphaXiv comment publication without side effects."""
    log.warning(
        "alphaxiv-comments is refused and not runtime-wired; artifact=%s",
        getattr(artifact, "slug", "?"),
    )
    return "denied"


__all__ = ["publish_artifact"]

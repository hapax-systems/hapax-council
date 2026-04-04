"""Reverie affordance registration — imports from centralized shared registry.

The system discovers which visual effects are relevant to each impingement
via cosine similarity in Qdrant, not prescribed semantic mappings.

Reverie indexes ALL system affordances into its pipeline (SCM Property 1 —
each daemon maintains its own view). This enables recruitment from the full
world, not just Reverie-internal capabilities.
"""

from __future__ import annotations

import logging

from shared.affordance_registry import (
    ALL_AFFORDANCES,
)
from shared.affordance_registry import (
    CONTENT_AFFORDANCES as _REGISTRY_CONTENT,
)
from shared.affordance_registry import (
    LEGACY_AFFORDANCES as _REGISTRY_LEGACY,
)
from shared.affordance_registry import (
    SHADER_NODE_AFFORDANCES as _REGISTRY_NODES,
)

log = logging.getLogger("reverie.affordances")

# ---------------------------------------------------------------------------
# Backward-compat shims — tuple format consumed by existing tests and callers.
# These are derived from the shared registry so the registry stays authoritative.
# ---------------------------------------------------------------------------

# 12 shader node affordances as (name, description) tuples
SHADER_NODE_AFFORDANCES: list[tuple[str, str]] = [(r.name, r.description) for r in _REGISTRY_NODES]

# Content affordances as (name, description, OperationalProperties) tuples
CONTENT_AFFORDANCES: list[tuple[str, str, object]] = [
    (r.name, r.description, r.operational) for r in _REGISTRY_CONTENT
]

# Legacy bridge affordances as (name, description) tuples
LEGACY_AFFORDANCES: list[tuple[str, str]] = [(r.name, r.description) for r in _REGISTRY_LEGACY]

# Combined content view — kept for callers that import this name directly.
# Contains all content-domain affordances from the registry.
ALL_CONTENT_AFFORDANCES = CONTENT_AFFORDANCES


def build_reverie_pipeline_affordances():
    """Return all CapabilityRecord objects for Reverie to index.

    Reverie indexes the FULL system affordance set so its pipeline can recruit
    from the complete world (SCM Property 1: each daemon owns its own view).
    """
    return list(ALL_AFFORDANCES)


def build_reverie_pipeline():
    """Build the affordance pipeline with all system affordances registered in Qdrant."""
    from agents._affordance_pipeline import AffordancePipeline

    p = AffordancePipeline()
    records = build_reverie_pipeline_affordances()
    registered = p.index_capabilities_batch(records)
    log.info("Registered %d/%d affordances in Reverie pipeline", registered, len(records))
    return p

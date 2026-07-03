"""Unified capability inventory aggregator — combines all 7 vocabulary adapters into one observed set.

This is the meta-priority: ingest ALL capability vocabularies into the unified descriptor schema + run
discover() to emit the real capability_surface_delta (the actual boutique/missing/unregistered surfaces
as a failing check). The aggregator knows the repo layout + wires each adapter to its config file.
"""

from __future__ import annotations

from pathlib import Path

from shared.capability_harness_descriptor import (
    CapabilityHarnessDescriptor,
    CapabilitySurfaceDelta,
    discover,
)
from shared.capability_registry_ingest import ingest_platform_capability_registry
from shared.classification_inventory_ingest import ingest_classification_inventory
from shared.grounding_provider_ingest import ingest_grounding_providers
from shared.mcp_connector_ingest import ingest_mcp_connector_manifest
from shared.models_dict_ingest import ingest_models_dict
from shared.publication_bus_ingest import ingest_publication_bus_from_module
from shared.world_capability_ingest import ingest_world_capability_registry

__all__ = ["aggregate_all_capabilities", "repo_root"]


def repo_root() -> Path:
    """The hapax-council repo root (this file's parents[1])."""
    return Path(__file__).resolve().parents[1]


def aggregate_all_capabilities(root: Path | None = None) -> list[CapabilityHarnessDescriptor]:
    """Ingest ALL 7 capability vocabularies into one unified observed descriptor set.

    Each vocabulary is adapted independently; the union is the real observed capability inventory.
    Missing/unreadable files are skipped (the absence itself is a finding the delta surfaces).
    """
    root = root or repo_root()
    config = root / "config"
    descriptors: list[CapabilityHarnessDescriptor] = []

    # 1. platform-capability-registry.json (LLM/dispatch supply)
    pcr = config / "platform-capability-registry.json"
    if pcr.is_file():
        descriptors.extend(ingest_platform_capability_registry(pcr))

    # 2. world-capability-registry.json (world-expression/observation/state)
    wcr = config / "world-capability-registry.json"
    if wcr.is_file():
        descriptors.extend(ingest_world_capability_registry(wcr))

    # 3. grounding-providers.json
    gp = config / "grounding-providers.json"
    if gp.is_file():
        descriptors.extend(ingest_grounding_providers(gp))

    # 4. mcp-connector-tool-manifest.json
    mcm = config / "mcp-connector-tool-manifest.json"
    if mcm.is_file():
        descriptors.extend(ingest_mcp_connector_manifest(mcm))

    # 5. capability-classification-inventory.json
    cci = config / "capability-classification-inventory.json"
    if cci.is_file():
        descriptors.extend(ingest_classification_inventory(cci))

    # 6. publication-bus surface_registry (Python module import)
    try:
        descriptors.extend(ingest_publication_bus_from_module())
    except (ImportError, Exception):
        pass  # the absence is surfaced by the delta

    # 7. MODELS dict (shared/config.py) — lightweight: read the dict without heavy import
    try:
        import shared.config as cfg

        if hasattr(cfg, "MODELS") and isinstance(cfg.MODELS, dict):
            descriptors.extend(ingest_models_dict(cfg.MODELS))
    except (ImportError, Exception):
        pass

    return descriptors


def full_inventory_delta(
    registered: dict[str, str] | None = None,
) -> tuple[list[CapabilityHarnessDescriptor], CapabilitySurfaceDelta]:
    """Ingest all capabilities + compute the delta vs a registered fingerprint baseline.

    Returns (observed_descriptors, delta). With no registered baseline, every observed capability is NEW.
    """
    observed = aggregate_all_capabilities()
    registered = registered or {}
    return observed, discover(observed, registered)

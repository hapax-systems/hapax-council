"""Unified capability inventory aggregator — combines all 7 vocabulary adapters into one observed set.

This is the meta-priority: ingest ALL capability vocabularies into the unified descriptor schema + run
discover() to emit the real capability_surface_delta (the actual boutique/missing/unregistered surfaces
as a failing check). The aggregator knows the repo layout + wires each adapter to its config file.
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Callable
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

LOG = logging.getLogger(__name__)


def repo_root() -> Path:
    """The hapax-council repo root (this file's parents[1])."""
    return Path(__file__).resolve().parents[1]


def _extend_from_file(
    descriptors: list[CapabilityHarnessDescriptor],
    path: Path,
    ingest: Callable[[Path], list[CapabilityHarnessDescriptor]],
) -> None:
    if not path.is_file():
        LOG.warning("capability inventory source missing: %s", path)
        return
    descriptors.extend(ingest(path))


def _read_models_dict_literal(path: Path) -> dict[str, object] | None:
    """Read MODELS from shared/config.py without importing secret-loading runtime code."""
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in module.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "MODELS" and node.value is not None:
                value = ast.literal_eval(node.value)
                return value if isinstance(value, dict) else None
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "MODELS":
                    value = ast.literal_eval(node.value)
                    return value if isinstance(value, dict) else None
    return None


def aggregate_all_capabilities(root: Path | None = None) -> list[CapabilityHarnessDescriptor]:
    """Ingest ALL 7 capability vocabularies into one unified observed descriptor set.

    Each vocabulary is adapted independently; the union is the real observed capability inventory.
    Missing files are skipped with a warning; unreadable or malformed sources fail loudly.
    """
    root = root or repo_root()
    config = root / "config"
    descriptors: list[CapabilityHarnessDescriptor] = []

    # 1. platform-capability-registry.json (LLM/dispatch supply)
    _extend_from_file(
        descriptors,
        config / "platform-capability-registry.json",
        ingest_platform_capability_registry,
    )

    # 2. world-capability-registry.json (world-expression/observation/state)
    _extend_from_file(
        descriptors,
        config / "world-capability-registry.json",
        ingest_world_capability_registry,
    )

    # 3. grounding-providers.json
    _extend_from_file(descriptors, config / "grounding-providers.json", ingest_grounding_providers)

    # 4. mcp-connector-tool-manifest.json
    _extend_from_file(
        descriptors,
        config / "mcp-connector-tool-manifest.json",
        ingest_mcp_connector_manifest,
    )

    # 5. capability-classification-inventory.json
    _extend_from_file(
        descriptors,
        config / "capability-classification-inventory.json",
        ingest_classification_inventory,
    )

    # 6. publication-bus surface_registry (Python module import)
    try:
        descriptors.extend(ingest_publication_bus_from_module())
    except ImportError as exc:
        LOG.warning("capability inventory source unavailable: publication_bus (%s)", exc)

    # 7. MODELS dict (shared/config.py) — lightweight: read the dict without heavy import
    config_py = root / "shared" / "config.py"
    try:
        models = _read_models_dict_literal(config_py)
    except (OSError, SyntaxError, ValueError) as exc:
        LOG.warning("capability inventory source unavailable: %s (%s)", config_py, exc)
    else:
        if models is None:
            LOG.warning("capability inventory source missing MODELS literal: %s", config_py)
        elif models:
            descriptors.extend(ingest_models_dict(models))
        else:
            LOG.warning("capability inventory source MODELS literal is empty: %s", config_py)

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

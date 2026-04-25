"""Approval-gated inbox watcher + parallel surface fan-out.

Phase 0 PUB-P0-D primitive per the v5 workstream realignment. Watches
``~/hapax-state/publish/inbox/*.json`` for approved
``PreprintArtifact`` payloads and dispatches each ``surfaces_targeted``
surface in parallel via the registered publisher's
``publish_artifact()`` entry-point.

See ``orchestrator.py`` for the daemon implementation; this package's
``__main__`` exposes the systemd-unit entry-point.
"""

from agents.publish_orchestrator.orchestrator import (
    SURFACE_REGISTRY,
    Orchestrator,
)

__all__ = ["SURFACE_REGISTRY", "Orchestrator"]

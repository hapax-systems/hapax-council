"""OSF preprint publisher — orchestrator-driven Phase 2 surface.

Entry-point ``publish_artifact(artifact: PreprintArtifact) -> str`` is
imported by ``agents.publish_orchestrator.orchestrator`` via the
``SURFACE_REGISTRY['osf-preprint']`` import string.
"""

from agents.osf_preprint_publisher.publisher import publish_artifact

__all__ = ["publish_artifact"]

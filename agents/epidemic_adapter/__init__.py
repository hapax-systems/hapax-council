"""Epidemic Sound adapter — content-source-registry Phase 3.

Reads per-track YAML sidecars (written manually or by future ingest CLI)
and exposes the broadcast-safety metadata to ``LocalMusicRepo`` via the
sidecar-merging path. Tracks ingested via this adapter are tagged
``content_risk=tier_1_platform_cleared`` and ``source=epidemic``.

Minimum viable: sidecar parse + merge. Operator drops files into
``~/music/hapax-pool/epidemic/recordings/`` with adjacent ``<stem>.yaml``
files; ``LocalMusicRepo.scan()`` picks up the metadata automatically.

Auth + direct GraphQL ingestion is deferred — the Epidemic Sound MCP
tools (``mcp__epidemic-sound__*``) are the canonical ingest path during
Claude Code sessions. This module bridges those downloads into the
council's persistent music repo.

Per `docs/superpowers/plans/2026-04-23-content-source-registry-plan.md`
Phase 3.
"""

from agents.epidemic_adapter.sidecar import (
    EpidemicSidecar,
    load_sidecar,
    merge_sidecar_into_track,
    sidecar_path_for,
)

__all__ = [
    "EpidemicSidecar",
    "load_sidecar",
    "merge_sidecar_into_track",
    "sidecar_path_for",
]

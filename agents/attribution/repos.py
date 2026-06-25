"""Canonical list of Hapax-owned first-party repositories for SWH archival.

Per cc-task ``leverage-attrib-swh-swhid-bibtex``: each first-party
repo gets a SWHID via ``trigger_save`` → ``poll_visit`` → ``resolve_swhid``.
The repo list is operator-curated and committed; runtime mutation is
forbidden per the single_user axiom.

Each entry carries the canonical Git URL (the form SWH archives) plus
the slug used for downstream metadata (CITATION.cff sidecars,
bibtex.bib entries).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class HapaxRepo:
    """One first-party Hapax repository for SWH archival."""

    slug: str
    git_url: str
    description: str


# Canonical first-party Hapax repos. Sorted alphabetically for
# deterministic diff review. The ``hapax-council`` repo (this one) is
# the primary council substrate; the others are sister surfaces or
# dependencies per the workspace CLAUDE.md inter-project map.
HAPAX_REPOS: Final[list[HapaxRepo]] = [
    HapaxRepo(
        slug="hapax-assets",
        git_url="https://github.com/hapax-systems/hapax-assets",
        description="Public CDN mirror of aesthetic library (BitchX/Px437/Enlightenment).",
    ),
    HapaxRepo(
        slug="hapax-constitution",
        git_url="https://github.com/hapax-systems/hapax-constitution",
        description="Governance specification (axioms, implications, canons).",
    ),
    HapaxRepo(
        slug="hapax-council",
        git_url="https://github.com/hapax-systems/hapax-council",
        description="Personal operating environment; Logos API; agent fleet.",
    ),
    HapaxRepo(
        slug="hapax-coord",
        git_url="https://github.com/hapax-systems/hapax-coord",
        description="SBCL/CLOG coordination interface for bounded Hapax operations.",
    ),
    HapaxRepo(
        slug="hapax-mcp",
        git_url="https://github.com/hapax-systems/hapax-mcp",
        description="MCP server bridging Logos APIs to Claude Code tools.",
    ),
    HapaxRepo(
        slug="hapax-officium",
        git_url="https://github.com/hapax-systems/hapax-officium",
        description="Management decision support; filesystem-as-bus data model.",
    ),
    HapaxRepo(
        slug="hapax-phone",
        git_url="https://github.com/hapax-systems/hapax-phone",
        description="Android companion app (Kotlin/Compose); biometric stream.",
    ),
    HapaxRepo(
        slug="hapax-research-ledger",
        git_url="https://github.com/hapax-systems/hapax-research-ledger",
        description="Open numeric SCED observation ledger for Hapax research.",
    ),
    HapaxRepo(
        slug="hapax-watch",
        git_url="https://github.com/hapax-systems/hapax-watch",
        description="Wear OS companion app; biometric sensor data stream.",
    ),
    HapaxRepo(
        slug="reins",
        git_url="https://github.com/hapax-systems/reins",
        description="Terminal decision support and attention-routing interface.",
    ),
    HapaxRepo(
        slug="reins-prototype",
        git_url="https://github.com/hapax-systems/reins-prototype",
        description="Prototype Reins interface and scored screenspace smoke harness.",
    ),
]


__all__ = [
    "HAPAX_REPOS",
    "HapaxRepo",
]

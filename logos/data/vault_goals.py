"""Vault goal collector — reads Obsidian vault goal notes with YAML frontmatter.

Scans markdown files for ``type: goal`` frontmatter, extracts structured fields,
computes staleness from file mtime, and calculates sprint progress from linked
measure statuses. Deterministic, no LLM calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from shared.frontmatter import parse_frontmatter

logger = logging.getLogger(__name__)

# Default staleness thresholds per domain (days).
DEFAULT_STALENESS_DAYS: dict[str, int] = {
    "research": 7,
    "management": 14,
    "studio": 14,
    "personal": 30,
    "health": 7,
}

DEFAULT_VAULT_BASE = Path.home() / "Documents" / "Personal"
DEFAULT_VAULT_NAME = "Personal"


@dataclass
class VaultGoal:
    """A single goal extracted from an Obsidian vault note."""

    id: str
    title: str
    domain: str
    status: str
    priority: str
    started_at: str | None
    target_date: str | None
    sprint_measures: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    file_path: Path | None = None
    last_modified: datetime | None = None
    stale: bool = False
    progress: float | None = None
    obsidian_uri: str = ""


def _priority_sort_key(priority: str) -> int:
    """Map priority strings to sort order (lower = higher priority)."""
    mapping = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return mapping.get(priority, 99)


def _compute_progress(
    measures: list[str],
    statuses: dict[str, str] | None,
) -> float | None:
    """Compute sprint progress as fraction of completed measures."""
    if not measures or not statuses:
        return None
    completed = sum(1 for m in measures if statuses.get(m) == "completed")
    return completed / len(measures)


def _is_stale(
    mtime: float,
    domain: str,
    staleness_days: dict[str, int] | None,
) -> bool:
    """Check if a file is stale based on mtime and domain threshold."""
    thresholds = staleness_days or DEFAULT_STALENESS_DAYS
    threshold = thresholds.get(domain, 30)
    age_days = (datetime.now(UTC).timestamp() - mtime) / 86400
    return age_days > threshold


def _build_obsidian_uri(vault_name: str, vault_base: Path, file_path: Path) -> str:
    """Build an obsidian:// URI for a file."""
    relative = file_path.relative_to(vault_base)
    # Strip .md extension
    file_ref = str(relative.with_suffix(""))
    return f"obsidian://open?vault={quote(vault_name, safe='')}&file={quote(file_ref, safe='/')}"


def collect_vault_goals(
    *,
    vault_base: Path | None = None,
    vault_name: str | None = None,
    domain_filter: str | None = None,
    staleness_days: dict[str, int] | None = None,
    sprint_measure_statuses: dict[str, str] | None = None,
) -> list[VaultGoal]:
    """Scan an Obsidian vault for goal notes and return structured data.

    Args:
        vault_base: Root directory of the vault. Defaults to ~/Documents/Personal.
        vault_name: Vault name for obsidian:// URIs. Defaults to "Personal".
        domain_filter: If set, only return goals matching this domain.
        staleness_days: Per-domain staleness thresholds (days). Uses defaults if None.
        sprint_measure_statuses: Map of measure ID → status for progress calculation.

    Returns:
        Sorted list of VaultGoal instances. Sorted by priority (P0 first) then
        most-recently-modified.
    """
    base = vault_base or DEFAULT_VAULT_BASE
    name = vault_name or DEFAULT_VAULT_NAME

    if not base.is_dir():
        return []

    goals: list[VaultGoal] = []

    for md_path in base.rglob("*.md"):
        try:
            fm, _body = parse_frontmatter(md_path)
        except Exception:
            logger.warning("Failed to parse frontmatter: %s", md_path)
            continue

        if not fm or fm.get("type") != "goal":
            continue

        domain = str(fm.get("domain", ""))
        if domain_filter and domain != domain_filter:
            continue

        try:
            mtime = md_path.stat().st_mtime
            last_modified = datetime.fromtimestamp(mtime, tz=UTC)
        except OSError:
            mtime = 0.0
            last_modified = None

        measures = fm.get("sprint_measures", [])
        if not isinstance(measures, list):
            measures = []

        depends = fm.get("depends_on", [])
        if not isinstance(depends, list):
            depends = []

        tags = fm.get("tags", [])
        if not isinstance(tags, list):
            tags = []

        goal = VaultGoal(
            id=md_path.stem,
            title=str(fm.get("title", md_path.stem)),
            domain=domain,
            status=str(fm.get("status", "planned")),
            priority=str(fm.get("priority", "P2")),
            started_at=_str_or_none(fm.get("started_at")),
            target_date=_str_or_none(fm.get("target_date")),
            sprint_measures=measures,
            depends_on=depends,
            tags=tags,
            file_path=md_path,
            last_modified=last_modified,
            stale=_is_stale(mtime, domain, staleness_days),
            progress=_compute_progress(measures, sprint_measure_statuses),
            obsidian_uri=_build_obsidian_uri(name, base, md_path),
        )
        goals.append(goal)

    # Sort: priority ascending (P0 < P1 < P2), then most-recently-modified first
    goals.sort(
        key=lambda g: (
            _priority_sort_key(g.priority),
            -(g.last_modified.timestamp() if g.last_modified else 0),
        )
    )

    return goals


def _str_or_none(val: object) -> str | None:
    """Coerce a value to str or None."""
    if val is None:
        return None
    return str(val)

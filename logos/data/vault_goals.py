"""Vault goal collector — reads Obsidian vault goal notes with YAML frontmatter.

Scans markdown files for ``type: goal`` frontmatter, extracts structured fields,
computes staleness from file mtime, and calculates sprint progress from linked
measure statuses. Deterministic, no LLM calls.
"""

from __future__ import annotations

import json
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
TEMPLATE_DIR_NAMES = {"50-templates"}

# Hot-patch 2026-06-21: TTL-cache the whole-vault goal scan. The rglob("*.md")
# over ~6000 files + per-file YAML parse (~7.6s) ran synchronously on the
# daimonion's single event loop on every operator utterance, starving the audio
# drain (frames dropped -> operator never heard). Goals change on the order of
# hours, so a short TTL is correct. Proper offload+cache lands via PR.
_GOALS_CACHE: dict = {}
_GOALS_CACHE_TTL_S = 120.0

# JSON Canvas goal-dependency map produced by ``agents.vault_canvas_writer``.
DEFAULT_GOAL_MAP_CANVAS = DEFAULT_VAULT_BASE / "20-projects" / "hapax-goals" / "goal-map.canvas"


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


def _is_template_goal_note(vault_base: Path, file_path: Path, frontmatter: dict) -> bool:
    """Return True for reusable goal templates, which are not live goals."""
    try:
        relative_parts = file_path.relative_to(vault_base).parts
    except ValueError:
        relative_parts = file_path.parts

    if any(part in TEMPLATE_DIR_NAMES for part in relative_parts):
        return True

    if file_path.name.startswith("tpl-"):
        return True

    templater_fields = ("title", "domain", "priority", "started_at", "target_date")
    return any("<%" in str(frontmatter.get(field, "")) for field in templater_fields)


def collect_vault_goals(
    *,
    vault_base: Path | None = None,
    vault_name: str | None = None,
    domain_filter: str | None = None,
    staleness_days: dict[str, int] | None = None,
    sprint_measure_statuses: dict[str, str] | None = None,
    include_templates: bool = False,
) -> list[VaultGoal]:
    """Scan an Obsidian vault for goal notes and return structured data.

    Args:
        vault_base: Root directory of the vault. Defaults to ~/Documents/Personal.
        vault_name: Vault name for obsidian:// URIs. Defaults to "Personal".
        domain_filter: If set, only return goals matching this domain.
        staleness_days: Per-domain staleness thresholds (days). Uses defaults if None.
        sprint_measure_statuses: Map of measure ID → status for progress calculation.
        include_templates: Include reusable template notes that have type: goal
            frontmatter. Defaults to False because templates are not live goals.

    Returns:
        Sorted list of VaultGoal instances. Sorted by priority (P0 first) then
        most-recently-modified.
    """
    base = vault_base or DEFAULT_VAULT_BASE
    name = vault_name or DEFAULT_VAULT_NAME

    import time as _t  # noqa: PLC0415

    _ck = (
        str(base),
        name,
        domain_filter,
        include_templates,
        str(staleness_days),
        str(sprint_measure_statuses),
    )
    _hit = _GOALS_CACHE.get(_ck)
    if _hit is not None and (_t.monotonic() - _hit[0]) < _GOALS_CACHE_TTL_S:
        return list(_hit[1])

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

        if not include_templates and _is_template_goal_note(base, md_path, fm):
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

    _GOALS_CACHE[_ck] = (_t.monotonic(), list(goals))
    return goals


def _str_or_none(val: object) -> str | None:
    """Coerce a value to str or None."""
    if val is None:
        return None
    return str(val)


# ---------------------------------------------------------------------------
# Goal-map canvas reader (consumes agents.vault_canvas_writer output)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoalMapEdge:
    """A dependency edge: ``from_node`` must complete before ``to_node``."""

    from_node: str
    to_node: str


@dataclass
class GoalMap:
    """The goal dependency graph read back from ``goal-map.canvas``."""

    nodes: dict[str, str] = field(default_factory=dict)  # node id -> label text
    edges: list[GoalMapEdge] = field(default_factory=list)

    def dependencies_of(self, node_id: str) -> list[str]:
        """Node ids ``node_id`` depends on (edges pointing into it)."""
        return [e.from_node for e in self.edges if e.to_node == node_id]

    def blocked_node_ids(self) -> list[str]:
        """Nodes with at least one unmet dependency.

        ``vault_canvas_writer`` emits a node only for active/paused goals and an edge
        only when both endpoints are themselves nodes, so a completed prerequisite
        drops out of the graph. Therefore any node that still has an incoming edge is
        waiting on an incomplete (active) dependency — i.e. blocked.
        """
        return [nid for nid in self.nodes if self.dependencies_of(nid)]


def read_goal_map(canvas_path: Path | None = None) -> GoalMap | None:
    """Read the JSON Canvas goal map that ``agents.vault_canvas_writer`` produces.

    Returns ``None`` when the canvas is absent or unparseable so the orientation
    panel degrades to per-note ``depends_on`` fields rather than failing. Malformed
    individual nodes/edges are skipped, not fatal.
    """
    path = canvas_path or DEFAULT_GOAL_MAP_CANVAS
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    nodes: dict[str, str] = {}
    for node in data.get("nodes", []):
        if isinstance(node, dict) and node.get("id") is not None:
            nodes[str(node["id"])] = str(node.get("text", ""))

    edges: list[GoalMapEdge] = []
    for edge in data.get("edges", []):
        if isinstance(edge, dict) and edge.get("fromNode") and edge.get("toNode"):
            edges.append(GoalMapEdge(from_node=str(edge["fromNode"]), to_node=str(edge["toNode"])))

    return GoalMap(nodes=nodes, edges=edges)

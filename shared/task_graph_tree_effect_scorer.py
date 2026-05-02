"""Compute tree-effect scores from the actual cc-task dependency graph.

The scorer walks vault `active/` + `closed/` notes, builds a directed
graph from each task's `depends_on` edges, then for every offered task
computes:

- ``unblock_count``: number of tasks (transitive) currently blocked by
  this task that would become reachable once this task completes
- ``downstream_offered_count``: subset of unblock_count that are
  themselves offered (high-leverage proxy)
- ``computed_tree_effect``: a normalized score on the same 0–10 scale
  as the declared ``braid_tree_effect`` field, suitable for drift
  comparison

Phase 1 is intentionally read-only. It writes a drift JSON report
(declared vs computed) but never mutates task state, never reorders
the queue, never claims authority over public/monetary truth.

Spec: hapax-research/specs/2026-04-29-value-braid-graph-snapshot-schema.md
Plan: hapax-research/audits/2026-04-30-post-merge-value-braid-backlog-resequence.md
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

#: Default vault location for cc-task notes.
DEFAULT_VAULT: Final[Path] = (
    Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
)

#: Drift threshold — tasks whose declared and computed tree-effect
#: differ by more than this absolute value get flagged in the report.
#: 1.0 matches the tolerance the spec calls out as worth surfacing.
DEFAULT_DRIFT_THRESHOLD: Final[float] = 1.0

#: Cap for the normalized tree-effect score, matching the
#: ``braid_tree_effect`` 0–10 scale convention.
TREE_EFFECT_SCORE_CAP: Final[float] = 10.0

# Regexes for the small subset of frontmatter we need. We intentionally
# do NOT depend on PyYAML — the registry already standardized on a
# regex parser to avoid the dep, and this module follows that pattern.
_RE_TASK_ID = re.compile(r"^task_id:\s*(.+?)\s*$", re.M)
_RE_STATUS = re.compile(r"^status:\s*(\w+)\s*$", re.M)
_RE_BRAID_TREE_EFFECT = re.compile(r"^braid_tree_effect:\s*([\d.]+)\s*$", re.M)
_RE_DEPENDS_ON_INLINE = re.compile(r"^depends_on:\s*\[(.*?)\]\s*$", re.M)
_RE_DEPENDS_ON_BLOCK_HEADER = re.compile(r"^depends_on:\s*$", re.M)
_RE_BLOCK_LIST_ITEM = re.compile(r"^\s*-\s+(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class TaskNode:
    """One vault cc-task with the fields the scorer needs.

    ``status`` is the lifecycle state read from frontmatter
    (``offered``, ``claimed``, ``in_progress``, ``pr_open``, ``blocked``,
    ``done``, ``superseded``, ``withdrawn``). ``depends_on`` is the
    parsed list of ``task_id`` references; nothing is normalized to
    file paths because tasks address each other by id.
    """

    task_id: str
    status: str
    depends_on: tuple[str, ...]
    declared_braid_tree_effect: float | None
    source_path: Path


class TreeEffectScore(BaseModel):
    """Computed tree-effect for a single task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    unblock_count: int = Field(ge=0)
    downstream_offered_count: int = Field(ge=0)
    computed_tree_effect: float = Field(ge=0.0, le=TREE_EFFECT_SCORE_CAP)


class DriftEntry(BaseModel):
    """One drift row when declared and computed tree-effect diverge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    declared: float
    computed: float
    delta: float


class ScoreReport(BaseModel):
    """Top-level scorer output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scored_at: str  # ISO8601
    vault_root: str
    task_count: int
    scored_count: int
    scores: tuple[TreeEffectScore, ...]
    drift_threshold: float
    drift_entries: tuple[DriftEntry, ...]


# ── Frontmatter parsing ─────────────────────────────────────────────


def _parse_depends_on(text: str) -> tuple[str, ...]:
    """Parse depends_on field — handles both inline ``[a, b]`` and block
    YAML list forms (``\\n- a\\n- b``). Returns a tuple of task_id strings.
    """
    inline_match = _RE_DEPENDS_ON_INLINE.search(text)
    if inline_match:
        raw = inline_match.group(1).strip()
        if not raw:
            return ()
        items = [item.strip().strip('"').strip("'") for item in raw.split(",")]
        return tuple(item for item in items if item)
    header_match = _RE_DEPENDS_ON_BLOCK_HEADER.search(text)
    if not header_match:
        return ()
    # Walk lines after the header until we hit a non-list line
    after = text[header_match.end() :]
    items: list[str] = []
    for line in after.splitlines():
        stripped = line.lstrip(" ")
        if not stripped:
            continue
        list_match = _RE_BLOCK_LIST_ITEM.match(line)
        if list_match:
            items.append(list_match.group(1).strip().strip('"').strip("'"))
            continue
        # Non-list, non-blank → end of block
        break
    return tuple(items)


def _parse_node(path: Path) -> TaskNode | None:
    """Parse a vault note into a TaskNode. Returns None on missing
    task_id or status (i.e., not a cc-task)."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    m_id = _RE_TASK_ID.search(text)
    m_status = _RE_STATUS.search(text)
    if not m_id or not m_status:
        return None
    task_id = m_id.group(1).strip().strip('"').strip("'")
    status = m_status.group(1).strip()
    depends_on = _parse_depends_on(text)
    declared: float | None = None
    m_te = _RE_BRAID_TREE_EFFECT.search(text)
    if m_te:
        try:
            declared = float(m_te.group(1))
        except ValueError:
            declared = None
    return TaskNode(
        task_id=task_id,
        status=status,
        depends_on=depends_on,
        declared_braid_tree_effect=declared,
        source_path=path,
    )


def load_task_graph(vault_root: Path = DEFAULT_VAULT) -> dict[str, TaskNode]:
    """Walk active/ + closed/ markdown notes, return ``{task_id: TaskNode}``.

    Duplicates are resolved by preferring the active/ copy over closed/
    (a task that's been re-opened keeps its active status). Notes that
    fail to parse (no task_id or status field) are silently dropped —
    they're not cc-tasks.
    """
    graph: dict[str, TaskNode] = {}
    # Closed first so active overwrites
    for subdir in ("closed", "active"):
        directory = vault_root / subdir
        if not directory.is_dir():
            continue
        for path in directory.glob("*.md"):
            node = _parse_node(path)
            if node is not None:
                graph[node.task_id] = node
    return graph


# ── Tree-effect computation ─────────────────────────────────────────


def _build_reverse_edges(
    graph: dict[str, TaskNode],
) -> dict[str, set[str]]:
    """Return ``{task_id: set_of_tasks_that_depend_on_this}``.

    Edges to unknown task_ids are dropped silently (the ``broken-dep``
    audit class is the right place to surface those, not here).
    """
    reverse: dict[str, set[str]] = {tid: set() for tid in graph}
    for tid, node in graph.items():
        for dep in node.depends_on:
            if dep in reverse:
                reverse[dep].add(tid)
    return reverse


def _transitive_downstream(seed: str, reverse: dict[str, set[str]]) -> set[str]:
    """BFS over reverse-edges from ``seed``, returning all transitively
    downstream task_ids (NOT including seed itself)."""
    if seed not in reverse:
        return set()
    visited: set[str] = set()
    frontier: list[str] = list(reverse[seed])
    while frontier:
        current = frontier.pop()
        if current in visited:
            continue
        visited.add(current)
        frontier.extend(reverse.get(current, set()))
    return visited


def _normalize_to_score_cap(unblock_count: int) -> float:
    """Map unblock count to a 0-10 score using log scaling.

    Empirically, declared braid_tree_effect tops out at 10 for tasks
    that unblock 9+ downstream rails (per `feature_unblock_breadth`
    spec). Use ``min(10, log2(1 + count) * 2.5)`` so:
    - 0 unblocks → 0
    - 1 unblock → ~2.5
    - 4 unblocks → 5.8
    - 15 unblocks → 10.0 (capped)
    """
    import math

    score = math.log2(1 + unblock_count) * 2.5
    return min(score, TREE_EFFECT_SCORE_CAP)


def compute_tree_effect_scores(
    graph: dict[str, TaskNode],
    *,
    only_offered: bool = True,
) -> tuple[TreeEffectScore, ...]:
    """Compute a TreeEffectScore for every task in the graph.

    When ``only_offered=True`` (default), score only tasks in
    ``offered`` status (the tasks ready for pickup). Other statuses
    can be scored too via ``only_offered=False`` for diagnostic use.
    """
    reverse = _build_reverse_edges(graph)
    scores: list[TreeEffectScore] = []
    for tid, node in graph.items():
        if only_offered and node.status != "offered":
            continue
        downstream = _transitive_downstream(tid, reverse)
        offered_downstream = sum(1 for d in downstream if graph[d].status == "offered")
        scores.append(
            TreeEffectScore(
                task_id=tid,
                unblock_count=len(downstream),
                downstream_offered_count=offered_downstream,
                computed_tree_effect=_normalize_to_score_cap(len(downstream)),
            )
        )
    return tuple(sorted(scores, key=lambda s: -s.computed_tree_effect))


def compute_drift(
    graph: dict[str, TaskNode],
    scores: Iterable[TreeEffectScore],
    *,
    threshold: float = DEFAULT_DRIFT_THRESHOLD,
) -> tuple[DriftEntry, ...]:
    """Find tasks whose declared braid_tree_effect diverges from computed.

    Tasks without a declared value are skipped (no drift to compute).
    """
    drifts: list[DriftEntry] = []
    for score in scores:
        node = graph.get(score.task_id)
        if node is None or node.declared_braid_tree_effect is None:
            continue
        delta = score.computed_tree_effect - node.declared_braid_tree_effect
        if abs(delta) >= threshold:
            drifts.append(
                DriftEntry(
                    task_id=score.task_id,
                    declared=node.declared_braid_tree_effect,
                    computed=score.computed_tree_effect,
                    delta=delta,
                )
            )
    return tuple(sorted(drifts, key=lambda d: -abs(d.delta)))


def build_score_report(
    *,
    vault_root: Path = DEFAULT_VAULT,
    drift_threshold: float = DEFAULT_DRIFT_THRESHOLD,
    scored_at: str | None = None,
) -> ScoreReport:
    """Top-level entrypoint: walk vault, score, drift, return report."""
    from datetime import UTC, datetime

    when = scored_at or datetime.now(tz=UTC).isoformat()
    graph = load_task_graph(vault_root)
    scores = compute_tree_effect_scores(graph)
    drifts = compute_drift(graph, scores, threshold=drift_threshold)
    return ScoreReport(
        scored_at=when,
        vault_root=str(vault_root),
        task_count=len(graph),
        scored_count=len(scores),
        scores=scores,
        drift_threshold=drift_threshold,
        drift_entries=drifts,
    )

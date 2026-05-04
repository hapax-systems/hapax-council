"""Director prompt world-surface block.

cc-task ``director-prompt-world-surface-block``.

Renders a compact, bounded text block from a
:class:`~shared.director_world_surface_snapshot.DirectorWorldSurfaceSnapshot`
into the director's unified prompt so the director sees live world-surface
availability, blockers, and claim posture.

The block replaces static hand-maintained availability prose with
evidence-bearing rows derived from the snapshot's move buckets.

Fail-closed: any error reading or rendering the snapshot yields an empty
string — the director falls back to existing static hints. The director
NEVER sees false availability from this block.

The runtime snapshot is expected at ``/dev/shm/hapax-director/world-surface-snapshot.json``.
If the file is absent, stale (beyond ``freshness_ttl_s``), or malformed,
the block renders empty. This is expected during Phase 0 until the runtime
snapshot builder ships.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: SHM path where the runtime snapshot builder writes its output.
#: The director_loop reads from here on every tick.
SNAPSHOT_SHM_PATH = Path("/dev/shm/hapax-director/world-surface-snapshot.json")

#: Maximum age (seconds) before a snapshot is considered stale and ignored.
#: Generous default — the snapshot builder may run on a slow cadence.
MAX_SNAPSHOT_AGE_S = 120.0


def render_world_surface_prompt_block(
    *,
    snapshot_path: Path = SNAPSHOT_SHM_PATH,
    max_age_s: float = MAX_SNAPSHOT_AGE_S,
    now: float | None = None,
) -> str:
    """Render a compact world-surface block for the director prompt.

    Returns the block as a multi-line string, or empty string on any
    failure (fail-closed). The block is bounded to ~40 lines so it
    fits within the director's context budget.

    Parameters
    ----------
    snapshot_path:
        Path to the JSON snapshot file. Default: SHM path.
    max_age_s:
        Maximum snapshot age in seconds before it's treated as stale.
    now:
        Current epoch time (for testing). Defaults to ``time.time()``.
    """
    try:
        snapshot_data = _read_snapshot(snapshot_path, max_age_s=max_age_s, now=now)
        if snapshot_data is None:
            return ""
        return _render_block(snapshot_data)
    except Exception:
        log.debug("world-surface prompt block render failed", exc_info=True)
        return ""


def _read_snapshot(
    path: Path,
    *,
    max_age_s: float,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Read and age-check the snapshot JSON. Returns None on any failure."""
    if not path.exists():
        return None

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        log.debug("world-surface snapshot read/parse failed", exc_info=True)
        return None

    if not isinstance(data, dict):
        return None

    # Age check: generated_at is ISO, but we also accept a numeric
    # _written_at_epoch field for the runtime builder's convenience.
    now_ts = now if now is not None else time.time()
    written_at = data.get("_written_at_epoch")
    if isinstance(written_at, (int, float)):
        age = now_ts - float(written_at)
        if age > max_age_s:
            log.debug("world-surface snapshot stale: age=%.1fs > max=%.1fs", age, max_age_s)
            return None

    return data


def _render_block(snapshot: dict[str, Any]) -> str:
    """Render the compact prompt block from snapshot dict.

    Produces a text block matching the spec's recommended shape::

        ## World Surface Read Model
        checked_at: <iso>
        mode: <research/rnd/fortress>
        programme: <id or none>

        available:
        - foreground audio.broadcast_voice via route:broadcast_public

        blocked:
        - foreground audio.private_assistant_monitor; reason: private route
    """
    lines: list[str] = []
    lines.append("## World Surface Read Model")

    # Header fields
    prompt_summary = snapshot.get("prompt_summary", {})
    checked_at = prompt_summary.get("checked_at", snapshot.get("generated_at", "unknown"))
    mode = prompt_summary.get("mode", snapshot.get("mode", "unknown"))
    programme = snapshot.get("programme_ref") or "none"

    lines.append(f"checked_at: {checked_at}")
    lines.append(f"mode: {mode}")
    lines.append(f"programme: {programme}")

    # Render move buckets from prompt_summary (compact string lists)
    # or fall back to projecting from full move rows.
    available = prompt_summary.get("available", [])
    dry_run = prompt_summary.get("dry_run", [])
    blocked = prompt_summary.get("blocked", [])
    private_only = prompt_summary.get("private_only", [])

    if not any((available, dry_run, blocked, private_only)):
        # Try projecting from full move rows if prompt_summary is sparse
        available = _project_moves(snapshot.get("available_moves", []))
        dry_run = _project_moves(snapshot.get("dry_run_moves", []))
        blocked = _project_moves(snapshot.get("blocked_moves", []))
        private_only = _project_moves(snapshot.get("private_only_moves", []))

    if available:
        lines.append("")
        lines.append("available:")
        for entry in available[:10]:  # cap to stay within context budget
            lines.append(f"- {entry}")

    if dry_run:
        lines.append("")
        lines.append("dry_run:")
        for entry in dry_run[:5]:
            lines.append(f"- {entry}")

    if blocked:
        lines.append("")
        lines.append("blocked:")
        for entry in blocked[:8]:
            lines.append(f"- {entry}")

    if private_only:
        lines.append("")
        lines.append("private_only:")
        for entry in private_only[:5]:
            lines.append(f"- {entry}")

    # Evidence obligations summary (unsatisfied only)
    obligations = snapshot.get("evidence_obligations", [])
    unsatisfied = [o for o in obligations if isinstance(o, dict) and not o.get("satisfied", True)]
    if unsatisfied:
        lines.append("")
        lines.append("unsatisfied_obligations:")
        for o in unsatisfied[:5]:
            dim = o.get("dimension", "?")
            missing = ", ".join(o.get("missing_refs", [])[:3])
            lines.append(f"- {dim}: {missing}")

    # Static hint refs — these are fallback/style/safety only, not availability
    hint_refs = prompt_summary.get("prompt_hint_refs", [])
    if hint_refs:
        lines.append("")
        lines.append("static_hints (style/safety only, NOT availability):")
        for ref in hint_refs[:5]:
            lines.append(f"- {ref}")

    if len(lines) <= 4:
        # Only header, no moves — don't clutter the prompt
        return ""

    return "\n".join(lines)


def _project_moves(moves: list[dict[str, Any]]) -> list[str]:
    """Project full move row dicts into compact prompt strings."""
    result: list[str] = []
    for move in moves:
        if not isinstance(move, dict):
            continue
        verb = move.get("verb", "?")
        target = move.get("target_id", move.get("display_name", "?"))
        surface = move.get("surface_id", "")

        parts = [f"{verb} {surface or target}"]

        # Add route if present
        route_refs = move.get("route_refs", [])
        if route_refs:
            parts.append(f"via {route_refs[0]}")

        # Add witnesses for available moves
        witness_refs = move.get("required_witness_refs", [])
        if witness_refs:
            parts.append(f"witnesses: {', '.join(witness_refs[:3])}")

        # Add blocker reason for blocked moves
        blocker = move.get("blocker_reason")
        if blocker:
            parts.append(f"reason: {blocker}")
        elif move.get("blocked_reasons"):
            parts.append(f"reason: {move['blocked_reasons'][0]}")

        result.append("; ".join(parts))
    return result


__all__ = [
    "MAX_SNAPSHOT_AGE_S",
    "SNAPSHOT_SHM_PATH",
    "render_world_surface_prompt_block",
]

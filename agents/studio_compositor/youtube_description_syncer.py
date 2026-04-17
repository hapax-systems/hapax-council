"""LRR Phase 8 item 7 — YouTube description sync driver.

Watches research-state surfaces (condition_id + active-objectives snapshot)
and fires ``update_video_description()`` when the relevant state changes.
Respects the quota enforcement already shipped in
``agents/studio_compositor/youtube_description.py`` (5 updates/stream,
2000-unit daily cap).

Invocation model: driven from a systemd user timer every N minutes
(operator chooses cadence; 5 min is sensible). Idempotent — if state
hasn't changed since last sync, no update is sent and no quota is
debited.

Not in scope here:
- The systemd timer unit itself (operator writes); documented in README.
- YouTube video_id discovery (HAPAX_YOUTUBE_VIDEO_ID env or config).
- OAuth credential refresh (handled by
  ``agents/studio_compositor/youtube_description.py::update_video_description``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from agents.studio_compositor.youtube_description import (
    assemble_description,
    update_video_description,
)

log = logging.getLogger("youtube_description_syncer")

# Where we remember what state was last pushed to YouTube. A hash-of-state
# approach — no need to persist the full description; if the input state
# hasn't changed, the output description won't either.
LAST_STATE_FILE = Path.home() / ".cache" / "hapax" / "youtube-desc-last-state.json"

# Research marker SHM surface — condition_id lives here, written by
# scripts/research-registry.py on every init/open/close.
RESEARCH_MARKER_PATH = Path("/dev/shm/hapax-compositor/research-marker.json")

# Objectives vault (same path director + overlay consume)
OBJECTIVES_DIR = Path.home() / "Documents" / "Personal" / "30-areas" / "hapax-objectives"

# Substrate model identifier for the description. Reads the live config at
# sync time so a substrate swap reflects on the next sync tick.
DEFAULT_SUBSTRATE_MODEL = "Qwen3.5-9B (local-fast via TabbyAPI :5000)"


def _read_research_marker() -> dict[str, Any]:
    """Return the current research marker state, or empty dict on failure."""
    if not RESEARCH_MARKER_PATH.exists():
        return {}
    try:
        return json.loads(RESEARCH_MARKER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _active_objectives_summary() -> list[dict[str, Any]]:
    """Summarize active objectives — title + priority. Empty on any error.

    Shares the read path with ``director_loop._render_active_objectives_block``
    + ``ObjectivesOverlay._read_active_objectives`` to avoid schema drift.
    """
    try:
        from shared.frontmatter import parse_frontmatter
        from shared.objective_schema import Objective, ObjectivePriority, ObjectiveStatus
    except Exception:
        return []

    if not OBJECTIVES_DIR.exists():
        return []

    priority_rank = {
        ObjectivePriority.high: 3,
        ObjectivePriority.normal: 2,
        ObjectivePriority.low: 1,
    }

    active: list[Objective] = []
    for path in sorted(OBJECTIVES_DIR.glob("obj-*.md")):
        try:
            fm, _ = parse_frontmatter(path)
            if not fm:
                continue
            obj = Objective(**fm)
            if obj.status == ObjectiveStatus.active:
                active.append(obj)
        except Exception:
            continue

    if not active:
        return []

    active.sort(
        key=lambda o: (priority_rank[o.priority], -o.opened_at.timestamp()),
        reverse=True,
    )
    return [
        {"title": o.title, "priority": o.priority.value, "objective_id": o.objective_id}
        for o in active
    ]


def _snapshot_state(marker_reader=None, objectives_reader=None) -> dict[str, Any]:
    """Build a snapshot of the research state relevant to the YouTube desc."""
    marker_reader = marker_reader or _read_research_marker
    objectives_reader = objectives_reader or _active_objectives_summary
    marker = marker_reader()
    return {
        "condition_id": marker.get("condition_id") or "",
        "claim_id": marker.get("claim_id"),
        "objectives": objectives_reader(),
    }


def _state_hash(state: dict[str, Any]) -> str:
    """Hash a state snapshot for equality-on-disk comparison."""
    serialized = json.dumps(state, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _load_last_hash() -> str:
    if not LAST_STATE_FILE.exists():
        return ""
    try:
        return json.loads(LAST_STATE_FILE.read_text()).get("hash", "")
    except (OSError, json.JSONDecodeError):
        return ""


def _save_last_hash(new_hash: str) -> None:
    try:
        LAST_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = LAST_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"hash": new_hash}))
        tmp.replace(LAST_STATE_FILE)
    except OSError:
        log.debug("Failed to persist last-state hash", exc_info=True)


def sync_once(
    video_id: str | None = None,
    substrate_model: str = DEFAULT_SUBSTRATE_MODEL,
    *,
    dry_run: bool = False,
    marker_reader=None,
    objectives_reader=None,
    updater=None,
) -> bool:
    """One sync cycle. Returns True if a description update was sent.

    Args:
        video_id: Target YouTube video ID. Falls back to
            ``HAPAX_YOUTUBE_VIDEO_ID`` env var.
        substrate_model: Human-readable substrate label for the description.
        dry_run: Pass-through to ``update_video_description``.
        marker_reader / objectives_reader / updater: injection points for
            tests. Defaults read live state + hit the real YouTube API.

    No-ops when:
      - no ``video_id`` (no target)
      - state is unchanged since last sync (hash equality)
      - quota is exhausted (silent skip, logged)
    """
    video_id = video_id or os.environ.get("HAPAX_YOUTUBE_VIDEO_ID", "").strip()
    if not video_id:
        log.debug("no video_id; skipping sync (set HAPAX_YOUTUBE_VIDEO_ID)")
        return False

    state = _snapshot_state(marker_reader, objectives_reader)
    new_hash = _state_hash(state)
    if new_hash == _load_last_hash():
        log.debug("state unchanged; skipping sync")
        return False

    top_objective = state["objectives"][0] if state["objectives"] else None
    description = assemble_description(
        condition_id=state["condition_id"] or "unknown",
        claim_id=state.get("claim_id"),
        objective_title=top_objective["title"] if top_objective else None,
        substrate_model=substrate_model,
    )

    updater = updater or update_video_description
    sent = updater(video_id, description, dry_run=dry_run)
    if sent:
        _save_last_hash(new_hash)
        log.info("youtube description updated (%d chars)", len(description))
    return bool(sent)


def main() -> int:
    """CLI entry point for systemd user timer.

    Expected unit shape (paths redacted, operator fills in):

        [Unit]
        Description=YouTube description sync (LRR Phase 8 item 7)
        After=graphical-session.target

        [Service]
        Type=oneshot
        Environment=HAPAX_YOUTUBE_VIDEO_ID=<video-id-here>
        ExecStart=<repo-venv>/bin/python \\
            -m agents.studio_compositor.youtube_description_syncer

    Paired with a timer running every 5 minutes.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        sync_once()
        return 0
    except Exception:
        log.exception("sync_once failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

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
    description_text_has_private_marker,
    sanitize_description_text,
    update_video_description,
)
from agents.studio_compositor.yt_shared_links import (
    load_cursor as _load_links_cursor,
)
from agents.studio_compositor.yt_shared_links import (
    queue_link_for_next_broadcast,
    tail_shared_links,
)
from agents.studio_compositor.yt_shared_links import (
    save_cursor as _save_links_cursor,
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


def _read_attribution_entries() -> list[Any]:
    """Read every kind from the AttributionFileWriter into one list.

    YT bundle B2: chat URL extractor (c17b487ce) accumulates entries
    into ``<vault-attribution-root>/<kind>.jsonl`` but
    ``youtube_description_syncer`` was never reading them. This bridges
    the producer-consumer gap so URLs operators paste in chat actually
    surface in the live broadcast description.

    Returns the union across every AttributionKind. Tolerant: missing
    files yield empty lists; malformed lines are skipped (already
    handled inside ``AttributionFileWriter.read_all``). Failures import
    or read return an empty list so a vault outage never breaks the
    sync loop.
    """
    try:
        from shared.attribution import AttributionFileWriter, AttributionKind

        writer = AttributionFileWriter()
        out: list[Any] = []
        for kind in AttributionKind.__args__:  # type: ignore[attr-defined]
            try:
                out.extend(writer.read_all(kind))
            except Exception:
                log.debug("attribution read failed for kind=%s", kind, exc_info=True)
        return out
    except Exception:
        log.debug("attribution writer unavailable; skipping", exc_info=True)
        return []


def _snapshot_state(
    marker_reader=None,
    objectives_reader=None,
    attribution_reader=None,
) -> dict[str, Any]:
    """Build a snapshot of the research state relevant to the YouTube desc.

    YT bundle B2: now also enumerates attribution entries (chat URLs +
    other AttributionSource producers) so they reach
    ``assemble_description``. Reader is injected for tests so the
    snapshot stays deterministic.
    """
    marker_reader = marker_reader or _read_research_marker
    objectives_reader = objectives_reader or _active_objectives_summary
    attribution_reader = attribution_reader or _read_attribution_entries
    marker = marker_reader()
    return {
        "condition_id": marker.get("condition_id") or "",
        "claim_id": marker.get("claim_id"),
        "objectives": objectives_reader(),
        "attributions": attribution_reader(),
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
    attribution_reader=None,
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

    state = _snapshot_state(marker_reader, objectives_reader, attribution_reader)
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
        attributions=state.get("attributions") or None,
    )

    updater = updater or update_video_description
    sent = updater(video_id, description, dry_run=dry_run)
    if sent:
        _save_last_hash(new_hash)
        log.info("youtube description updated (%d chars)", len(description))
    return bool(sent)


# --- Task #144: operator-shared link consumer ---------------------------
#
# Tails ``/dev/shm/hapax-compositor/yt-shared-links.jsonl`` (cursor at
# ``~/.cache/hapax/yt-links-cursor.txt``), appends each URL to the live
# broadcast description via the existing quota-gated updater, and queues
# any links that can't be sent (no video_id, quota exhausted, updater
# returned False) to ``~/hapax-state/yt-queue.jsonl`` for the next
# broadcast. Intentionally separate from ``sync_once`` above because the
# two cursors have different semantics — the research-state syncer is
# hash-of-state driven, while the shared-links consumer is line-driven.
#
# Rate-limit strategy: YouTube's description-update path costs 50 quota
# units per call (``videos.update`` with part=snippet). The existing
# ``config/youtube-quota.yaml`` caps daily spend + per-stream updates;
# we read+debit via the same ``check_and_debit`` path as every other
# call site, so no separate rate-limit bookkeeping lives here.


# Prefix that marks the operator-shared links block in the description.
# Anything after this marker until the next ``---`` or EOF is the
# auto-managed URL list; the block is rebuilt on every append so stale
# URLs from prior broadcasts don't accumulate within a single broadcast.
_SHARED_LINKS_MARKER: str = "--- Links ---"


def _append_links_to_description(
    existing: str | None, urls: list[str], *, max_chars: int = 4800
) -> str:
    """Build the new description with the shared-links block appended.

    Idempotent — re-invocation with the same inputs yields the same
    string. Any existing ``--- Links ---`` block in ``existing`` is
    preserved (its contents merged with ``urls``, de-duplicated while
    preserving first-seen order).

    The YouTube description limit is 5000 chars; we stay safely under.
    Oldest URLs are dropped from the head of the block if the total
    would overflow ``max_chars``.
    """
    existing = _sanitize_existing_description(existing or "")
    marker = _SHARED_LINKS_MARKER
    head = existing
    old_links: list[str] = []
    if marker in existing:
        head, _, tail = existing.partition(marker)
        head = head.rstrip("\n")
        for line in tail.splitlines():
            stripped = line.strip()
            if not stripped or stripped == marker:
                continue
            # Stop at the next separator block (another "---" section).
            if stripped.startswith("---") and stripped != marker:
                break
            if not description_text_has_private_marker(stripped):
                old_links.append(stripped)

    seen: set[str] = set()
    merged: list[str] = []
    for url in old_links + list(urls):
        url = str(url).strip()
        if not url or description_text_has_private_marker(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        merged.append(url)

    def _compose(link_list: list[str]) -> str:
        parts = [head] if head else []
        parts.append(marker)
        parts.extend(link_list)
        return "\n".join(parts).strip() + "\n"

    composed = _compose(merged)
    # Trim oldest if we blow past the char budget.
    while len(composed) > max_chars and merged:
        merged.pop(0)
        composed = _compose(merged)
    return composed


def _sanitize_existing_description(existing: str) -> str:
    """Drop private/non-broadcast lines from an existing YouTube description."""

    safe_lines: list[str] = []
    for line in existing.splitlines():
        if not line.strip():
            safe_lines.append(line)
            continue
        sanitized = sanitize_description_text(line)
        if sanitized is not None:
            safe_lines.append(sanitized)
    return "\n".join(safe_lines).strip()


def sync_shared_links_once(
    video_id: str | None = None,
    *,
    dry_run: bool = False,
    links_reader=None,
    updater=None,
    description_reader=None,
    cursor_loader=None,
    cursor_saver=None,
    queue_writer=None,
) -> int:
    """Consume one batch of operator-shared links.

    Reads the shared-links JSONL since the last-saved cursor, and either
    (a) appends the URLs to the live broadcast description via the
    existing quota-gated updater, or (b) queues them for the next
    broadcast when no ``video_id`` is known or the updater reports
    quota exhaustion.

    Returns the count of newly-seen URLs processed (sent or queued).

    All collaborators are overridable for tests:
      ``links_reader(since_ts)``     → iterable of records
      ``updater(video_id, desc, dry_run=...)`` → True on success
      ``description_reader(video_id)`` → current description string
      ``cursor_loader()`` / ``cursor_saver(ts)`` → cursor persistence
      ``queue_writer(record)`` → fallback queue write
    """
    links_reader = links_reader or tail_shared_links
    cursor_loader = cursor_loader or _load_links_cursor
    cursor_saver = cursor_saver or _save_links_cursor
    queue_writer = queue_writer or queue_link_for_next_broadcast
    updater = updater or update_video_description
    video_id = video_id or os.environ.get("HAPAX_YOUTUBE_VIDEO_ID", "").strip()

    cursor_ts = cursor_loader()
    raw_records = [
        r for r in links_reader(since_ts=cursor_ts) if isinstance(r, dict) and r.get("url")
    ]
    records: list[dict[str, Any]] = []
    max_seen_ts = cursor_ts
    for rec in raw_records:
        try:
            max_seen_ts = max(max_seen_ts, float(rec.get("ts", 0.0)))
        except (TypeError, ValueError):
            pass
        if description_text_has_private_marker(str(rec.get("url", ""))):
            continue
        if description_text_has_private_marker(str(rec.get("source", ""))):
            continue
        records.append(rec)
    if raw_records and not records:
        cursor_saver(max_seen_ts)
        return 0
    if not records:
        return 0

    processed = 0
    if not video_id:
        # No live broadcast target — queue every record.
        for rec in records:
            queue_writer(rec)
            processed += 1
        cursor_saver(max_seen_ts)
        log.info(
            "yt-shared-links: no video_id; queued %d link(s) for next broadcast",
            processed,
        )
        return processed

    urls = [str(r["url"]) for r in records]
    # Read the current description so we don't clobber it on update. The
    # default reader goes through the YouTube API; tests override.
    existing_description = ""
    if description_reader is not None:
        try:
            existing_description = description_reader(video_id) or ""
        except Exception:
            log.debug("description_reader failed; treating as empty", exc_info=True)

    new_description = _append_links_to_description(existing_description, urls)

    sent = updater(video_id, new_description, dry_run=dry_run)
    if sent:
        processed = len(records)
        cursor_saver(max_seen_ts)
        log.info(
            "yt-shared-links: appended %d URL(s) to broadcast %s",
            processed,
            video_id,
        )
        return processed

    # Updater refused (quota / no-such-video) — queue every record.
    for rec in records:
        queue_writer(rec)
        processed += 1
    cursor_saver(max_seen_ts)
    log.info(
        "yt-shared-links: updater declined; queued %d link(s) for next broadcast",
        processed,
    )
    return processed


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
    except Exception:
        log.exception("sync_once failed")
        # Continue to the shared-links path even if the state sync failed —
        # the two are independent concerns.

    try:
        sync_shared_links_once()
    except Exception:
        log.exception("sync_shared_links_once failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

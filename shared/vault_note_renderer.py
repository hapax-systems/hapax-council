"""Optional vault note renderer for LRR Phase 2 item 7.

Writes a templated Markdown note to the operator's Obsidian vault for
each archived segment so operator commentary can link raw media to
research claims. **The renderer is only active when the
``HAPAX_VAULT_PATH`` environment variable is set**; otherwise all
write paths are no-ops. This gate keeps the archival pipeline runnable
in headless tests and CI where no vault exists.

Target path inside the vault::

    30-areas/legomena-live/archive/YYYY-MM/segment-<id>.md

The note is NOT overwritten on subsequent rotations — an existing note
is left untouched so operator commentary persists across pipeline
restarts. Schema of the generated note is stable; new fields append
to the YAML frontmatter rather than changing existing ones.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from shared.stream_archive import SegmentSidecar

VAULT_ENV_VAR = "HAPAX_VAULT_PATH"
VAULT_ARCHIVE_SUBDIR = Path("30-areas") / "legomena-live" / "archive"


def vault_path_from_env() -> Path | None:
    """Return the vault root Path if ``HAPAX_VAULT_PATH`` is set, else None."""
    value = os.environ.get(VAULT_ENV_VAR, "").strip()
    if not value:
        return None
    return Path(value).expanduser()


def note_path_for(sidecar: SegmentSidecar, vault_root: Path) -> Path:
    """Return the deterministic vault note path for a sidecar."""
    try:
        parsed = datetime.fromisoformat(sidecar.segment_start_ts.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.now(UTC)
    month = parsed.strftime("%Y-%m")
    return vault_root / VAULT_ARCHIVE_SUBDIR / month / f"segment-{sidecar.segment_id}.md"


def render_note_body(sidecar: SegmentSidecar) -> str:
    """Produce the Markdown body for a segment note. No I/O."""
    reaction_list = ", ".join(sidecar.reaction_ids) if sidecar.reaction_ids else "(none)"
    stimmung_stance = sidecar.stimmung_snapshot.get("stance") if sidecar.stimmung_snapshot else None
    activity = sidecar.active_activity or "(unknown)"
    return (
        f"---\n"
        f"type: research-segment\n"
        f"segment_id: {sidecar.segment_id}\n"
        f"condition_id: {sidecar.condition_id or ''}\n"
        f"segment_start_ts: {sidecar.segment_start_ts}\n"
        f"segment_end_ts: {sidecar.segment_end_ts}\n"
        f"duration_seconds: {sidecar.duration_seconds}\n"
        f"archive_kind: {sidecar.archive_kind}\n"
        f"segment_path: {sidecar.segment_path}\n"
        f"---\n\n"
        f"# Segment {sidecar.segment_id}\n\n"
        f"- **Condition:** `{sidecar.condition_id or '—'}`\n"
        f"- **Start:** {sidecar.segment_start_ts}\n"
        f"- **Duration:** {sidecar.duration_seconds:.2f}s\n"
        f"- **Activity:** {activity}\n"
        f"- **Stimmung stance:** {stimmung_stance or '—'}\n"
        f"- **Reactions in window:** {reaction_list}\n\n"
        f"## Notes\n\n"
        f"_Add operator commentary here. Links to claim state go below._\n\n"
        f"## Claim links\n\n"
    )


def maybe_write_note(sidecar: SegmentSidecar) -> Path | None:
    """Write the vault note if ``HAPAX_VAULT_PATH`` is set and the target
    doesn't already exist. Returns the note path on success, None if the
    gate is closed or the note already exists.
    """
    vault_root = vault_path_from_env()
    if vault_root is None:
        return None
    if not vault_root.exists():
        return None

    path = note_path_for(sidecar, vault_root)
    if path.exists():
        return None

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_note_body(sidecar), encoding="utf-8")
    return path


__all__ = [
    "VAULT_ENV_VAR",
    "VAULT_ARCHIVE_SUBDIR",
    "vault_path_from_env",
    "note_path_for",
    "render_note_body",
    "maybe_write_note",
]

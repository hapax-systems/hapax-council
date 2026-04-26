"""Auto-actions for the cc-hygiene sweeper (PR2).

Implements three reversible auto-actions per research §4:

* **H1** ``ghost_claimed`` → revert ``status: claimed → offered`` and clear
  ``assigned_to`` / ``claimed_at`` / ``branch`` / ``pr``.
* **H2** ``stale_in_progress`` → revert ``status: in_progress → offered``
  and ntfy the operator with previous-claim metadata.
* **H7** ``offered_stale`` → move the note from ``active/`` to ``closed/``
  and rewrite ``status: offered → superseded`` with annex
  ``superseded_reason: auto-archived-via-staleness``.

All actions are gated by the same killswitch as the sweeper
(``HAPAX_CC_HYGIENE_OFF=1`` short-circuits both checks AND actions).
Defaults ON per ``feedback_features_on_by_default``.

Per research §4: "no operator-approval prompts", "revert > stall", all
reversible. Each rewrite preserves operator-authored note body unchanged
and appends a single annex line below the YAML closing fence.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .models import HygieneEvent, TaskNote

LOG = logging.getLogger("cc-hygiene-actions")

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


@dataclass(frozen=True)
class ActionResult:
    """One auto-action attempt (success OR explicit skip).

    ``success=False`` with ``message="skip: ..."`` is a normal outcome
    when the action could not be applied (file gone, parse failure,
    etc.). The sweeper logs both success and skip but only escalates
    real exceptions.
    """

    action_id: str
    task_id: str
    success: bool
    message: str
    metadata: dict[str, str]


def _utc_iso(now: datetime) -> str:
    """Return UTC ISO-8601 to seconds, no microseconds (vault convention)."""
    return now.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str] | None:
    """Return ``(frontmatter_dict, body_after_closing_fence)`` or ``None``.

    Body includes everything after the closing ``---`` fence verbatim
    (including the trailing newline). Frontmatter parse failures yield
    None so callers can skip safely.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    body = text[m.end() :]
    return fm, body


def _serialize_note(frontmatter: dict[str, Any], body: str, annex_line: str | None = None) -> str:
    """Re-serialize a note. Optionally append a single annex line to the body."""
    fm_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    out = f"---\n{fm_text}---{body}"
    if annex_line:
        if not out.endswith("\n"):
            out += "\n"
        out += f"{annex_line}\n"
    return out


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically via tmp + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".cc-hygiene.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ───────────────────────── H1 — ghost-claim revert ──────────────────────────


def revert_ghost_claim(note: TaskNote, *, now: datetime | None = None) -> ActionResult:
    """H1 — restore an inconsistent ``status: claimed`` task to ``offered``.

    Triggered by ``check_ghost_claimed`` (definitional violation:
    ``cc-claim`` cannot produce ``claimed`` + unassigned/null-claimed_at).
    Clears claim-time fields so ``cc-claim`` can re-stamp cleanly.
    """
    now = now or datetime.now(UTC)
    path = Path(note.path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ActionResult(
            action_id="ghost_claimed_revert",
            task_id=note.task_id,
            success=False,
            message=f"skip: read failed ({exc})",
            metadata={},
        )
    parsed = _split_frontmatter(text)
    if parsed is None:
        return ActionResult(
            action_id="ghost_claimed_revert",
            task_id=note.task_id,
            success=False,
            message="skip: frontmatter parse failed",
            metadata={},
        )
    fm, body = parsed
    if fm.get("status") != "claimed":
        return ActionResult(
            action_id="ghost_claimed_revert",
            task_id=note.task_id,
            success=False,
            message=f"skip: status is {fm.get('status')!r} not 'claimed' (race?)",
            metadata={"observed_status": str(fm.get("status"))},
        )
    fm["status"] = "offered"
    fm["assigned_to"] = "unassigned"
    fm["claimed_at"] = None
    fm["branch"] = None
    fm["pr"] = None
    fm["updated_at"] = _utc_iso(now)
    annex = f"<!-- auto-reverted-from-ghost-claim {_utc_iso(now)} -->"
    try:
        _atomic_write(path, _serialize_note(fm, body, annex_line=annex))
    except OSError as exc:
        return ActionResult(
            action_id="ghost_claimed_revert",
            task_id=note.task_id,
            success=False,
            message=f"skip: write failed ({exc})",
            metadata={},
        )
    return ActionResult(
        action_id="ghost_claimed_revert",
        task_id=note.task_id,
        success=True,
        message=f"reverted ghost-claim to 'offered' for {note.task_id}",
        metadata={"path": str(path)},
    )


# ────────────────────── H2 — stale in-progress revert ───────────────────────


def revert_stale_in_progress(
    note: TaskNote,
    *,
    now: datetime | None = None,
    notifier: Any = None,
) -> ActionResult:
    """H2 — revert a stalled ``in_progress`` task to ``offered``.

    Triggered by ``check_stale_in_progress`` (>24h with no commit/PR).
    Sends an ntfy alert with the task_id + previous claim metadata so
    the operator can diagnose why work stalled.

    ``notifier`` is an optional callable matching the
    ``shared.notify.send_notification`` signature; tests inject a stub.
    """
    now = now or datetime.now(UTC)
    path = Path(note.path)
    previous_session = note.assigned_to or "unassigned"
    previous_branch = note.branch or ""
    previous_pr = str(note.pr) if note.pr else ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ActionResult(
            action_id="stale_in_progress_revert",
            task_id=note.task_id,
            success=False,
            message=f"skip: read failed ({exc})",
            metadata={},
        )
    parsed = _split_frontmatter(text)
    if parsed is None:
        return ActionResult(
            action_id="stale_in_progress_revert",
            task_id=note.task_id,
            success=False,
            message="skip: frontmatter parse failed",
            metadata={},
        )
    fm, body = parsed
    if fm.get("status") != "in_progress":
        return ActionResult(
            action_id="stale_in_progress_revert",
            task_id=note.task_id,
            success=False,
            message=f"skip: status is {fm.get('status')!r} not 'in_progress' (race?)",
            metadata={"observed_status": str(fm.get("status"))},
        )
    fm["status"] = "offered"
    fm["assigned_to"] = "unassigned"
    fm["claimed_at"] = None
    fm["branch"] = None
    fm["pr"] = None
    fm["updated_at"] = _utc_iso(now)
    annex = (
        f"<!-- auto-reverted-from-stale-in-progress {_utc_iso(now)} "
        f"prev-session={previous_session} prev-branch={previous_branch} prev-pr={previous_pr} -->"
    )
    try:
        _atomic_write(path, _serialize_note(fm, body, annex_line=annex))
    except OSError as exc:
        return ActionResult(
            action_id="stale_in_progress_revert",
            task_id=note.task_id,
            success=False,
            message=f"skip: write failed ({exc})",
            metadata={},
        )
    sender = notifier if notifier is not None else _default_notifier()
    if sender is not None:
        try:
            sender(
                title=f"cc-hygiene reverted stale in_progress: {note.task_id}",
                message=(
                    f"task '{note.task_id}' was in_progress >24h with no commit/PR; "
                    f"auto-reverted to offered. prev-session={previous_session} "
                    f"prev-branch={previous_branch} prev-pr={previous_pr}"
                ),
                priority="default",
                tags=["robot", "broom"],
            )
        except Exception:
            LOG.debug("ntfy send for stale-in-progress revert failed", exc_info=True)
    return ActionResult(
        action_id="stale_in_progress_revert",
        task_id=note.task_id,
        success=True,
        message=f"reverted stale in_progress to 'offered' for {note.task_id}",
        metadata={
            "path": str(path),
            "prev_session": previous_session,
            "prev_branch": previous_branch,
            "prev_pr": previous_pr,
        },
    )


# ────────────────────── H7 — offered-staleness archive ──────────────────────


def archive_offered_stale(
    note: TaskNote, *, vault_root: Path, now: datetime | None = None
) -> ActionResult:
    """H7 — move stale offered task to ``closed/`` with ``status: superseded``.

    Reversible via ``mv closed/<id>.md active/<id>.md`` + frontmatter
    restore (the annex line documents what happened).
    """
    now = now or datetime.now(UTC)
    src = Path(note.path)
    closed_dir = vault_root / "closed"
    dst = closed_dir / src.name
    try:
        text = src.read_text(encoding="utf-8")
    except OSError as exc:
        return ActionResult(
            action_id="offered_stale_archive",
            task_id=note.task_id,
            success=False,
            message=f"skip: read failed ({exc})",
            metadata={},
        )
    parsed = _split_frontmatter(text)
    if parsed is None:
        return ActionResult(
            action_id="offered_stale_archive",
            task_id=note.task_id,
            success=False,
            message="skip: frontmatter parse failed",
            metadata={},
        )
    fm, body = parsed
    if fm.get("status") != "offered":
        return ActionResult(
            action_id="offered_stale_archive",
            task_id=note.task_id,
            success=False,
            message=f"skip: status is {fm.get('status')!r} not 'offered' (race?)",
            metadata={"observed_status": str(fm.get("status"))},
        )
    fm["status"] = "superseded"
    fm["superseded_reason"] = "auto-archived-via-staleness"
    fm["completed_at"] = _utc_iso(now)
    fm["updated_at"] = _utc_iso(now)
    annex = f"<!-- auto-archived-via-staleness {_utc_iso(now)} -->"
    try:
        closed_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(dst, _serialize_note(fm, body, annex_line=annex))
        src.unlink()
    except OSError as exc:
        return ActionResult(
            action_id="offered_stale_archive",
            task_id=note.task_id,
            success=False,
            message=f"skip: archive failed ({exc})",
            metadata={},
        )
    return ActionResult(
        action_id="offered_stale_archive",
        task_id=note.task_id,
        success=True,
        message=f"archived stale offered task {note.task_id} to closed/",
        metadata={"src": str(src), "dst": str(dst)},
    )


# ─────────────────────── orchestration helpers ──────────────────────────────


def _default_notifier() -> Any:
    """Resolve ``shared.notify.send_notification`` lazily.

    Returns None if shared/notify can't be imported (e.g., test env
    without the package wired). Auto-actions still apply; only the ntfy
    side-effect is skipped.
    """
    try:
        from shared.notify import send_notification  # noqa: PLC0415

        return send_notification
    except Exception:
        return None


_ACTION_BY_CHECK_ID: dict[str, str] = {
    "ghost_claimed": "ghost_claimed_revert",
    "stale_in_progress": "stale_in_progress_revert",
    "offered_stale": "offered_stale_archive",
}


def _find_note(notes: list[TaskNote], task_id: str) -> TaskNote | None:
    for note in notes:
        if note.task_id == task_id:
            return note
    return None


def apply_actions(
    events: Iterable[HygieneEvent],
    notes: Iterable[TaskNote],
    *,
    vault_root: Path,
    now: datetime | None = None,
    notifier: Any = None,
) -> list[ActionResult]:
    """Dispatch wired auto-actions for events with matching check_ids.

    Skips events whose ``check_id`` has no wired action (PR2 wires only
    H1/H2/H7 — H3/H4/H5/H6/H8/H9 ship in PR3+). Idempotency: each
    action validates the on-disk status before mutating, so a re-run
    after the underlying race resolves is safe.
    """
    now = now or datetime.now(UTC)
    note_list = list(notes)
    results: list[ActionResult] = []
    for event in events:
        action_id = _ACTION_BY_CHECK_ID.get(event.check_id)
        if action_id is None:
            continue
        if event.task_id is None:
            continue
        note = _find_note(note_list, event.task_id)
        if note is None:
            results.append(
                ActionResult(
                    action_id=action_id,
                    task_id=event.task_id,
                    success=False,
                    message="skip: note not found in current sweep",
                    metadata={},
                )
            )
            continue
        if action_id == "ghost_claimed_revert":
            results.append(revert_ghost_claim(note, now=now))
        elif action_id == "stale_in_progress_revert":
            results.append(revert_stale_in_progress(note, now=now, notifier=notifier))
        elif action_id == "offered_stale_archive":
            results.append(archive_offered_stale(note, vault_root=vault_root, now=now))
    return results


__all__ = [
    "ActionResult",
    "apply_actions",
    "archive_offered_stale",
    "revert_ghost_claim",
    "revert_stale_in_progress",
]

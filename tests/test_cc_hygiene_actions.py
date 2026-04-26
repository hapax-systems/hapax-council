"""Tests for cc-hygiene auto-actions (PR2).

Per project convention, no shared conftest fixtures — each test builds
its own vault tree under ``tmp_path``.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import yaml

# Ensure the script-side package is importable in tests.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cc_hygiene import actions  # noqa: E402
from cc_hygiene.checks import parse_task_note  # noqa: E402
from cc_hygiene.models import HygieneEvent, TaskNote  # noqa: E402

# ───────────────────────── helpers ──────────────────────────────────────────


def _write_note(path: Path, frontmatter: dict[str, Any], body: str = "# body\n") -> Path:
    """Write a vault-style note (YAML frontmatter + body) to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    path.write_text(f"---\n{fm_text}---\n{body}", encoding="utf-8")
    return path


def _build_vault(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return (vault_root, active_dir, closed_dir)."""
    vault_root = tmp_path / "hapax-cc-tasks"
    active = vault_root / "active"
    closed = vault_root / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    return vault_root, active, closed


def _ghost_claimed_note(active: Path, task_id: str = "ghost-1") -> TaskNote:
    """Build a vault note that satisfies the ghost-claimed (§2.2) condition."""
    path = active / f"{task_id}.md"
    _write_note(
        path,
        {
            "type": "cc-task",
            "task_id": task_id,
            "title": "ghost-claimed test",
            "status": "claimed",
            "assigned_to": "unassigned",
            "claimed_at": None,
            "branch": None,
            "pr": None,
            "created_at": "2026-04-25T17:00:00Z",
        },
    )
    note = parse_task_note(path)
    assert note is not None
    return note


def _in_progress_note(
    active: Path, task_id: str = "wip-1", *, branch: str = "alpha/wip-1", pr: int = 9999
) -> TaskNote:
    """Build a vault note that satisfies the stale-in-progress (§2.1) condition."""
    path = active / f"{task_id}.md"
    _write_note(
        path,
        {
            "type": "cc-task",
            "task_id": task_id,
            "title": "stale in_progress test",
            "status": "in_progress",
            "assigned_to": "alpha",
            "claimed_at": "2026-04-20T10:00:00Z",
            "branch": branch,
            "pr": pr,
            "created_at": "2026-04-19T09:00:00Z",
            "updated_at": "2026-04-20T10:00:00Z",
        },
    )
    note = parse_task_note(path)
    assert note is not None
    return note


def _offered_stale_note(active: Path, task_id: str = "stale-1") -> TaskNote:
    path = active / f"{task_id}.md"
    _write_note(
        path,
        {
            "type": "cc-task",
            "task_id": task_id,
            "title": "offered-stale test",
            "status": "offered",
            "assigned_to": "unassigned",
            "claimed_at": None,
            "created_at": "2026-03-13T10:00:00Z",
        },
    )
    note = parse_task_note(path)
    assert note is not None
    return note


# ───────────────────── H1 — ghost-claim revert ─────────────────────────────


class TestRevertGhostClaim:
    def test_reverts_status_and_clears_claim_fields(self, tmp_path: Path) -> None:
        _, active, _ = _build_vault(tmp_path)
        note = _ghost_claimed_note(active)
        now = datetime(2026, 4, 26, 3, 0, 0, tzinfo=UTC)
        result = actions.revert_ghost_claim(note, now=now)
        assert result.success is True
        assert result.action_id == "ghost_claimed_revert"
        reverted = parse_task_note(Path(note.path))
        assert reverted is not None
        assert reverted.status == "offered"
        assert reverted.assigned_to == "unassigned"
        assert reverted.claimed_at is None
        assert reverted.branch is None
        assert reverted.pr is None

    def test_appends_annex_line_below_frontmatter(self, tmp_path: Path) -> None:
        _, active, _ = _build_vault(tmp_path)
        note = _ghost_claimed_note(active)
        now = datetime(2026, 4, 26, 3, 0, 0, tzinfo=UTC)
        actions.revert_ghost_claim(note, now=now)
        text = Path(note.path).read_text(encoding="utf-8")
        assert "auto-reverted-from-ghost-claim 2026-04-26T03:00:00Z" in text

    def test_preserves_operator_authored_body(self, tmp_path: Path) -> None:
        _, active, _ = _build_vault(tmp_path)
        path = active / "ghost-2.md"
        body = "# Operator-authored body\n\nDo not lose this content.\n"
        _write_note(
            path,
            {
                "type": "cc-task",
                "task_id": "ghost-2",
                "status": "claimed",
                "assigned_to": "unassigned",
                "claimed_at": None,
            },
            body=body,
        )
        note = parse_task_note(path)
        assert note is not None
        actions.revert_ghost_claim(note)
        result_text = path.read_text(encoding="utf-8")
        assert "Operator-authored body" in result_text
        assert "Do not lose this content." in result_text

    def test_skips_when_status_no_longer_claimed(self, tmp_path: Path) -> None:
        """Race-safety: if another process flipped status before we ran, skip."""
        _, active, _ = _build_vault(tmp_path)
        path = active / "moved.md"
        _write_note(
            path,
            {"type": "cc-task", "task_id": "moved", "status": "in_progress"},
        )
        stale_note = TaskNote(
            path=str(path), task_id="moved", status="claimed", assigned_to="unassigned"
        )
        result = actions.revert_ghost_claim(stale_note)
        assert result.success is False
        assert "not 'claimed'" in result.message

    def test_skips_when_file_missing(self, tmp_path: Path) -> None:
        _, active, _ = _build_vault(tmp_path)
        stale_note = TaskNote(
            path=str(active / "missing.md"),
            task_id="missing",
            status="claimed",
            assigned_to="unassigned",
        )
        result = actions.revert_ghost_claim(stale_note)
        assert result.success is False
        assert "read failed" in result.message

    def test_idempotent_on_rerun(self, tmp_path: Path) -> None:
        """Running twice: first reverts, second skips cleanly."""
        _, active, _ = _build_vault(tmp_path)
        note = _ghost_claimed_note(active)
        first = actions.revert_ghost_claim(note)
        assert first.success is True
        second = actions.revert_ghost_claim(note)  # stale TaskNote claims status=claimed
        assert second.success is False
        assert "race" in second.message.lower()


# ─────────────────── H2 — stale in-progress revert ─────────────────────────


class TestRevertStaleInProgress:
    def test_reverts_to_offered_and_clears_claim_state(self, tmp_path: Path) -> None:
        _, active, _ = _build_vault(tmp_path)
        note = _in_progress_note(active)

        def notifier(**kwargs: Any) -> bool:
            return True

        result = actions.revert_stale_in_progress(note, notifier=notifier)
        assert result.success is True
        reverted = parse_task_note(Path(note.path))
        assert reverted is not None
        assert reverted.status == "offered"
        assert reverted.assigned_to == "unassigned"
        assert reverted.claimed_at is None
        assert reverted.branch is None
        assert reverted.pr is None

    def test_sends_ntfy_with_previous_claim_metadata(self, tmp_path: Path) -> None:
        _, active, _ = _build_vault(tmp_path)
        note = _in_progress_note(active, branch="alpha/wip-x", pr=4242)
        notifier = MagicMock(return_value=True)
        actions.revert_stale_in_progress(note, notifier=notifier)
        notifier.assert_called_once()
        kwargs = notifier.call_args.kwargs
        assert "wip-1" in kwargs["title"]
        assert "alpha" in kwargs["message"]
        assert "alpha/wip-x" in kwargs["message"]
        assert "4242" in kwargs["message"]

    def test_swallows_ntfy_failure(self, tmp_path: Path) -> None:
        """Ntfy is a side-effect; failure must not fail the action."""
        _, active, _ = _build_vault(tmp_path)
        note = _in_progress_note(active)

        def angry_notifier(**kwargs: Any) -> bool:
            raise RuntimeError("ntfy unreachable")

        result = actions.revert_stale_in_progress(note, notifier=angry_notifier)
        assert result.success is True

    def test_skips_when_status_no_longer_in_progress(self, tmp_path: Path) -> None:
        _, active, _ = _build_vault(tmp_path)
        path = active / "drift.md"
        _write_note(path, {"type": "cc-task", "task_id": "drift", "status": "done"})
        stale_note = TaskNote(path=str(path), task_id="drift", status="in_progress")
        result = actions.revert_stale_in_progress(stale_note, notifier=lambda **kw: True)
        assert result.success is False
        assert "not 'in_progress'" in result.message


# ──────────────────── H7 — offered-staleness archive ───────────────────────


class TestArchiveOfferedStale:
    def test_moves_file_from_active_to_closed(self, tmp_path: Path) -> None:
        vault_root, active, closed = _build_vault(tmp_path)
        note = _offered_stale_note(active)
        src_path = Path(note.path)
        result = actions.archive_offered_stale(note, vault_root=vault_root)
        assert result.success is True
        assert not src_path.exists(), "active file should be removed"
        dst = closed / src_path.name
        assert dst.exists(), f"file should be moved to {dst}"

    def test_sets_superseded_status_with_annex(self, tmp_path: Path) -> None:
        vault_root, active, closed = _build_vault(tmp_path)
        note = _offered_stale_note(active)
        now = datetime(2026, 4, 26, 4, 0, 0, tzinfo=UTC)
        actions.archive_offered_stale(note, vault_root=vault_root, now=now)
        dst = closed / Path(note.path).name
        text = dst.read_text(encoding="utf-8")
        moved = parse_task_note(dst)
        assert moved is not None
        assert moved.status == "superseded"
        assert "auto-archived-via-staleness" in text
        fm = yaml.safe_load(text.split("---\n", 2)[1])
        assert fm["superseded_reason"] == "auto-archived-via-staleness"
        assert fm["completed_at"] == "2026-04-26T04:00:00Z"

    def test_skips_when_status_drifted(self, tmp_path: Path) -> None:
        vault_root, active, _ = _build_vault(tmp_path)
        path = active / "moved-status.md"
        _write_note(path, {"type": "cc-task", "task_id": "moved-status", "status": "claimed"})
        stale_note = TaskNote(path=str(path), task_id="moved-status", status="offered")
        result = actions.archive_offered_stale(stale_note, vault_root=vault_root)
        assert result.success is False
        assert "not 'offered'" in result.message
        assert path.exists(), "file should not have moved"


# ─────────────────────── apply_actions dispatch ────────────────────────────


class TestApplyActions:
    def test_dispatches_h1_h2_h7(self, tmp_path: Path) -> None:
        vault_root, active, _ = _build_vault(tmp_path)
        ghost = _ghost_claimed_note(active, task_id="g1")
        wip = _in_progress_note(active, task_id="w1")
        stale = _offered_stale_note(active, task_id="s1")
        now = datetime(2026, 4, 26, 5, 0, 0, tzinfo=UTC)
        events = [
            HygieneEvent(
                timestamp=now,
                check_id="ghost_claimed",
                severity="violation",
                task_id="g1",
                message="ghost",
            ),
            HygieneEvent(
                timestamp=now,
                check_id="stale_in_progress",
                severity="warning",
                task_id="w1",
                message="stale",
            ),
            HygieneEvent(
                timestamp=now,
                check_id="offered_stale",
                severity="info",
                task_id="s1",
                message="oldstock",
            ),
        ]
        results = actions.apply_actions(
            events,
            [ghost, wip, stale],
            vault_root=vault_root,
            now=now,
            notifier=lambda **kw: True,
        )
        assert len(results) == 3
        assert all(r.success for r in results), [r.message for r in results]
        action_ids = {r.action_id for r in results}
        assert action_ids == {
            "ghost_claimed_revert",
            "stale_in_progress_revert",
            "offered_stale_archive",
        }

    def test_skips_unwired_check_ids(self, tmp_path: Path) -> None:
        """PR2 wires only H1/H2/H7. Other check_ids must be ignored."""
        vault_root, _, _ = _build_vault(tmp_path)
        now = datetime(2026, 4, 26, 5, 0, 0, tzinfo=UTC)
        events = [
            HygieneEvent(
                timestamp=now,
                check_id="duplicate_claim",
                severity="violation",
                task_id="dup",
                message="dup",
            ),
            HygieneEvent(
                timestamp=now,
                check_id="orphan_pr",
                severity="warning",
                task_id="orph",
                message="orph",
            ),
            HygieneEvent(
                timestamp=now,
                check_id="wip_limit",
                severity="warning",
                task_id="wip",
                message="wiplimit",
            ),
            HygieneEvent(
                timestamp=now,
                check_id="relay_yaml_stale",
                severity="warning",
                session="alpha",
                message="relay-stale",
            ),
            HygieneEvent(
                timestamp=now,
                check_id="refusal_dormancy",
                severity="info",
                message="refusal-dormant",
            ),
        ]
        results = actions.apply_actions(events, [], vault_root=vault_root, now=now)
        assert results == []

    def test_skips_when_task_not_in_sweep_notes(self, tmp_path: Path) -> None:
        """Defensive: event references task that disappeared between sweep + action."""
        vault_root, _, _ = _build_vault(tmp_path)
        now = datetime(2026, 4, 26, 5, 0, 0, tzinfo=UTC)
        events = [
            HygieneEvent(
                timestamp=now,
                check_id="ghost_claimed",
                severity="violation",
                task_id="vanished",
                message="ghost",
            )
        ]
        results = actions.apply_actions(events, [], vault_root=vault_root, now=now)
        assert len(results) == 1
        assert results[0].success is False
        assert "not found" in results[0].message


# ─────────────────────── reversibility regression ──────────────────────────


def test_h1_revert_then_reclaim_restores_claim(tmp_path: Path) -> None:
    """Acceptance criterion: H1 revert + manual claim restores the claim cleanly."""
    _, active, _ = _build_vault(tmp_path)
    note = _ghost_claimed_note(active)
    actions.revert_ghost_claim(note)
    text = Path(note.path).read_text(encoding="utf-8")
    parts = text.split("---\n", 2)
    fm = yaml.safe_load(parts[1])
    body = parts[2]
    fm["status"] = "claimed"
    fm["assigned_to"] = "alpha"
    fm["claimed_at"] = "2026-04-26T05:00:00Z"
    Path(note.path).write_text(
        f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n{body}", encoding="utf-8"
    )
    re_claimed = parse_task_note(Path(note.path))
    assert re_claimed is not None
    assert re_claimed.status == "claimed"
    assert re_claimed.assigned_to == "alpha"


def test_h7_archive_is_reversible_by_move_back(tmp_path: Path) -> None:
    """Acceptance criterion: H7 archive is reversible via mv + frontmatter restore."""
    vault_root, active, closed = _build_vault(tmp_path)
    note = _offered_stale_note(active)
    src_path = Path(note.path)
    actions.archive_offered_stale(note, vault_root=vault_root)
    dst = closed / src_path.name
    assert dst.exists()
    text = dst.read_text(encoding="utf-8")
    parts = text.split("---\n", 2)
    fm = yaml.safe_load(parts[1])
    body = parts[2]
    fm["status"] = "offered"
    fm.pop("superseded_reason", None)
    fm.pop("completed_at", None)
    src_path.write_text(f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n{body}", encoding="utf-8")
    dst.unlink()
    restored = parse_task_note(src_path)
    assert restored is not None
    assert restored.status == "offered"

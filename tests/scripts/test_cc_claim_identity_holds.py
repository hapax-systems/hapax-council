"""Identity is never resolved by directory order, prefix, or a lone receipt — it HOLDs.

Three codex criticals on #4611, each a fail-open where the release path chose instead of refusing:

* a task with a note in BOTH closed/ and active/ was read closed-first (41 such twins measured in
  the estate on 2026-09-02);
* `role-*` collected another role's sidecars whenever that role's name extended this one
  (`cx-red` vs `cx-red-operator-email`);
* a stale release receipt could be the SOLE match for residue a newer publication left behind,
  and the newer lane's sidecars were archived under the old task.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from tests.scripts.test_cc_claim import _age_leases, _claim, _task_root, _write_task

_FOREIGN_SESSION = "12345678-aaaa-bbbb-cccc-1234567890ab"


def _sidecars(home: Path) -> Path:
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def test_a_task_with_a_note_in_both_closed_and_active_holds_the_lane(tmp_path: Path) -> None:
    home = tmp_path / "home"
    first_note = _write_task(home, "active", "task-a")
    _write_task(home, "active", "task-b")
    assert _claim(home, "task-a").returncode == 0

    # A terminal COPY appears in closed/ while the active note still says `claimed` — the
    # resurrected-twin shape. Directory order used to pick the closed copy and free the lane.
    closed_dir = _task_root(home) / "closed"
    (closed_dir / first_note.name).write_text(
        first_note.read_text(encoding="utf-8").replace("status: claimed", "status: done"),
        encoding="utf-8",
    )
    assert first_note.is_file() and "status: claimed" in first_note.read_text(encoding="utf-8")
    _age_leases(home, seconds=21600 * 2)

    result = _claim(home, "task-b")

    assert result.returncode == 8, (
        f"a duplicate identity must HOLD, not free the lane.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "BOTH" in result.stderr and "task-a" in result.stderr
    assert str(closed_dir / "task-a.md") in result.stderr and str(first_note) in result.stderr
    lineage = _task_root(home) / "_lineage"
    assert not (lineage.exists() and list(lineage.glob("*/released-claim-residue-*"))), (
        "a HOLD archives nothing"
    )


def test_a_role_that_extends_this_one_is_not_collected_by_the_session_key_boundary(
    tmp_path: Path,
) -> None:
    """`cx-test-operator-email` is a different role; its sidecars are not `cx-test`'s to sweep."""
    home = tmp_path / "home"
    _write_task(home, "active", "task-b")
    _write_task(home, "closed", "foreign-task", status="done")
    cache = _sidecars(home)
    foreign_key = f"cx-test-operator-email-{_FOREIGN_SESSION}"
    foreign = [
        cache / f"cc-active-task-{foreign_key}",
        cache / f"cc-claim-epoch-{foreign_key}",
        cache / f"cc-claim-dispatch-{foreign_key}.json",
    ]
    foreign[0].write_text("foreign-task\n", encoding="utf-8")
    foreign[1].write_text("1 foreign-task\n", encoding="utf-8")
    foreign[2].write_text(json.dumps({"task_id": "foreign-task"}) + "\n", encoding="ascii")
    stale = time.time() - 21600 * 2
    for path in foreign:
        os.utime(path, (stale, stale))

    result = _claim(home, "task-b")

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    for path in foreign:
        assert path.exists(), f"{path.name} belongs to another role and must be left alone"
    lineage = _task_root(home) / "_lineage" / "foreign-task"
    assert not lineage.exists(), "another role's released residue is not this role's to archive"


def test_residue_naming_a_different_task_than_the_only_receipt_holds(tmp_path: Path) -> None:
    """A stale receipt must not attribute a newer lane's residue to the old task."""
    home = tmp_path / "home"
    _write_task(home, "active", "task-b")
    _write_task(home, "closed", "task-a", status="done")
    cache = _sidecars(home)
    key = f"cx-test-{_FOREIGN_SESSION}"
    # No anchor (crashed after the epoch move), residue from a NEWER publication naming task-z…
    epoch = cache / f"cc-claim-epoch-{key}"
    dispatch = cache / f"cc-claim-dispatch-{key}.json"
    epoch.write_text("1 task-z\n", encoding="utf-8")
    dispatch.write_text(json.dumps({"task_id": "task-z"}) + "\n", encoding="ascii")
    # …while the only release receipt claims the same residue names for the OLD task-a, whose
    # archival later completed into a different lineage directory (so the destination test
    # still passes: none of the residue names exist here).
    receipt_dir = (
        _task_root(home) / "_lineage" / "task-a" / "released-claim-residue-20260701T000000Z"
    )
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "README.md").write_text(
        "released-claim-residue\n"
        f"claim_key: {key}\n"
        "task_id: task-a\n"
        f"archived: {epoch.name},{dispatch.name}\n",
        encoding="utf-8",
    )
    stale = time.time() - 21600 * 2
    for path in (epoch, dispatch):
        os.utime(path, (stale, stale))

    result = _claim(home, "task-b")

    assert result.returncode == 8, (
        f"residue that names task-z must not be archived under task-a.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert (
        "names task(s)" in result.stderr and "task-z" in result.stderr and "task-a" in result.stderr
    )
    assert epoch.exists() and dispatch.exists(), "a HOLD moves nothing"

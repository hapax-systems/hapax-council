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

import hashlib
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


# ------------------------------------------------------------ the next round, one level deeper
#
# Three codex criticals on the revision that fixed the three above (dossier of 2026-09-02):
#
# * a RESUMED pipeline-status task kept its status by design and was treated as lane-free the
#   moment a second session looked — the status was one value for two states;
# * the residue scan reused the outer loop's `suffix` variable, so after the first session-keyed
#   sidecar every later dispatch key was corrupted and excluded — older sessions' claims stayed
#   usable while a new claim proceeded;
# * a release receipt matched residue by NAMES, which lanes reuse, so a receipt for an earlier
#   publication of the SAME task could sweep the residue of a newer one.

_SECOND_SESSION = "22222222-aaaa-bbbb-cccc-1234567890ab"


def _released_residue(cache: Path, key: str, task: str, *, epoch: str = "1") -> list[Path]:
    files = [
        cache / f"cc-active-task-{key}",
        cache / f"cc-claim-epoch-{key}",
        cache / f"cc-claim-dispatch-{key}.json",
    ]
    files[0].write_text(f"{task}\n", encoding="utf-8")
    files[1].write_text(f"{epoch} {task}\n", encoding="utf-8")
    files[2].write_text(json.dumps({"task_id": task}) + "\n", encoding="ascii")
    stale = time.time() - 21600 * 2
    for path in files:
        os.utime(path, (stale, stale))
    return files


def test_a_resumed_pipeline_task_holds_the_lane_until_its_lease_expires(tmp_path: Path) -> None:
    """Resume keeps `pr_open`; the marker, not the status, says a worker is back on the lane."""
    home = tmp_path / "home"
    _write_task(home, "active", "task-a", status="pr_open", assigned_to="cx-test")
    _write_task(home, "active", "task-b")
    resumed = _claim(home, "task-a")
    assert resumed.returncode == 0, resumed.stderr
    cache = _sidecars(home)
    marker = cache / "cc-claim-resumed-cx-test"
    assert marker.read_text(encoding="utf-8").strip() == "task-a", (
        "the resume path stamps the marker"
    )

    # A second session arrives while the resumed lane is live: the status still says pr_open.
    second = _claim(home, "task-b", session_id=_SECOND_SESSION)

    assert second.returncode == 7, (
        f"a resumed lane is worker-held and must BLOCK.\nstdout: {second.stdout}\nstderr: {second.stderr}"
    )
    assert "RESUMED" in second.stderr and "task-a" in second.stderr

    # The worker's lease expires: the lane frees the same way any dead session's does, and the
    # non-resume claim that follows removes the marker so it cannot outlive the claim.
    _age_leases(home, seconds=21600 * 2)
    third = _claim(home, "task-b", session_id=_SECOND_SESSION)
    assert third.returncode == 0, third.stderr
    assert not marker.exists(), "a non-resume claim retires the marker for its keys"


def test_a_pipeline_task_that_was_not_resumed_still_frees_the_lane(tmp_path: Path) -> None:
    """The #4611 predicate is untouched: finished, un-resumed work does not hold a lane."""
    home = tmp_path / "home"
    note = _write_task(home, "active", "task-a")
    _write_task(home, "active", "task-b")
    assert _claim(home, "task-a").returncode == 0
    note.write_text(
        note.read_text(encoding="utf-8").replace("status: claimed", "status: pr_open"),
        encoding="utf-8",
    )
    assert not (_sidecars(home) / "cc-claim-resumed-cx-test").exists()

    result = _claim(home, "task-b", session_id=_SECOND_SESSION)

    assert result.returncode == 0, result.stderr


def test_every_prior_session_residue_is_archived_not_just_the_first(tmp_path: Path) -> None:
    """Two earlier sessions released task-a; both residues must go, not only the first scanned."""
    home = tmp_path / "home"
    _write_task(home, "active", "task-b")
    _write_task(home, "closed", "task-a", status="done")
    cache = _sidecars(home)
    first = _released_residue(cache, f"cx-test-{_FOREIGN_SESSION}", "task-a")
    second = _released_residue(cache, f"cx-test-{_SECOND_SESSION}", "task-a")

    result = _claim(home, "task-b")

    assert result.returncode == 0, result.stderr
    leftovers = [p.name for p in first + second if p.exists()]
    assert not leftovers, f"released residue of an earlier session was left usable: {leftovers}"
    lineage = _task_root(home) / "_lineage" / "task-a"
    archived = sorted(p.name for d in lineage.glob("released-claim-residue-*") for p in d.iterdir())
    for path in first + second:
        assert path.name in archived, f"{path.name} was not archived under task-a"


def _receipt(
    home: Path, key: str, archived: list[Path], *, epoch: str, dispatch: Path | None
) -> Path:
    receipt_dir = (
        _task_root(home) / "_lineage" / "task-a" / "released-claim-residue-20260701T000000Z"
    )
    receipt_dir.mkdir(parents=True)
    digest = hashlib.sha256(dispatch.read_bytes()).hexdigest() if dispatch else "absent"
    (receipt_dir / "README.md").write_text(
        "released-claim-residue\n"
        f"claim_key: {key}\n"
        "task_id: task-a\n"
        f"archived: {', '.join(p.name for p in archived)}\n"
        f"epoch: {epoch}\n"
        f"dispatch_sha256: {digest}\n",
        encoding="utf-8",
    )
    return receipt_dir


def test_a_receipt_for_an_earlier_publication_of_the_same_task_does_not_sweep_the_newer_residue(
    tmp_path: Path,
) -> None:
    """Same task, same key, same file names — a different claim epoch is a different publication."""
    home = tmp_path / "home"
    _write_task(home, "active", "task-b")
    _write_task(home, "closed", "task-a", status="done")
    cache = _sidecars(home)
    key = f"cx-test-{_FOREIGN_SESSION}"
    _anchor, epoch, dispatch = _released_residue(cache, key, "task-a", epoch="2")
    _anchor.unlink()  # crashed after the anchor move: the shape recovery exists for
    # The receipt is from the FIRST publication of task-a under this key (epoch 1), whose
    # archival completed elsewhere; by names alone it covers this residue exactly.
    _receipt(home, key, [epoch, dispatch], epoch="1 task-a", dispatch=dispatch)

    result = _claim(home, "task-b")

    assert result.returncode == 8, (
        f"a receipt for another publication must not attribute this residue.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "receipt" in result.stderr
    assert epoch.exists() and dispatch.exists(), "a HOLD moves nothing"


def test_a_receipt_that_matches_the_residue_identity_still_recovers_the_interrupted_archival(
    tmp_path: Path,
) -> None:
    """The binding must not wedge the case recovery exists for: the receipt of THIS residue."""
    home = tmp_path / "home"
    _write_task(home, "active", "task-b")
    _write_task(home, "closed", "task-a", status="done")
    cache = _sidecars(home)
    key = f"cx-test-{_FOREIGN_SESSION}"
    _anchor, epoch, dispatch = _released_residue(cache, key, "task-a", epoch="2")
    _anchor.unlink()
    receipt_dir = _receipt(home, key, [epoch, dispatch], epoch="2 task-a", dispatch=dispatch)

    result = _claim(home, "task-b")

    assert result.returncode == 0, result.stderr
    assert not epoch.exists() and not dispatch.exists(), "recovery completes the move"
    assert (receipt_dir / epoch.name).exists() and (receipt_dir / dispatch.name).exists()

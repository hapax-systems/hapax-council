"""Environment-gated lifecycle verification on a real mount that refuses renameat2 flags.

Answers codex-1's and gemini-1's major findings on PR #4667: the unit suite simulates the
mount at the primitive boundary, and the live run recorded in
``NFS-FALLBACK-LIVE-VERIFICATION-20260913.md`` had no committed, re-runnable witness. This
is that witness.

    HAPAX_NFS_INTEGRATION_DIR=<a writable dir on a mount that refuses the renameat2 flags> \\
      uv run pytest tests/shared/test_coord_projection_nfs_integration.py -v

The variable names a *property* of the filesystem, not one operator's layout — any NFS4
export will do, and the fixture measures the property rather than trusting the path. An
earlier version of this line gave a concrete personal path, which reads as the required
location rather than as an example of one.

**FAILS — not skips — when neither the directory nor a governed waiver is set.** This
docstring said "skipped" and a reviewer was right that it no longer described the file: the
witness went fail-closed precisely so it could not be permanently and invisibly skipped.
The three outcomes are:

* ``HAPAX_NFS_INTEGRATION_DIR`` points at a mount that refuses the flags → the tests run;
* it is unset but ``HAPAX_NFS_INTEGRATION_WAIVED`` names the row that owns closing the gap
  → skipped, with the waiver echoed in the reason;
* neither → **red**, with a copy-pasteable value for each of the two ways out.

A skip that cannot say why is indistinguishable from a test that never ran, so every skip
names which precondition failed; and a waiver that names no owner is a permanent skip
wearing a different name, so an unowned one is rejected too.

The preconditions are asserted **before** the lifecycle runs, so a green result cannot be
one where the mount quietly supported the flags and the fallback never executed. That is
the specific failure mode the reviewers named, and it is why this file measures the mount
instead of trusting its name.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import uuid
from pathlib import Path

import pytest

from shared import coord_projection as cp
from shared.coord_event_log import CoordEventLog

_ENV_DIR = "HAPAX_NFS_INTEGRATION_DIR"
#: Declaring an absence out loud. Without `_ENV_DIR` and without this, the fixture FAILS
#: rather than skipping — a reviewer observed that nothing set the variable, so the witness
#: could stay permanently and invisibly skipped while the repair's central claim rested on a
#: one-off transcript. Hosted runners cannot mount NFS4, so CI declares the waiver in
#: `.github/workflows/ci.yml`.
#:
#: **The waiver has a named expiry**, which a reviewer asked for across three rounds: the row
#: ``nfs-fallback-live-witness-self-hosted-ci-20260913`` owns standing up a lane that can
#: mount the vault export. When it exists, that lane sets `_ENV_DIR` and the waiver comes
#: out. A waiver without an owner is a permanent skip wearing a different name.
#:
#: The *required fragment* is the row's distinctive prefix rather than its full id, and that
#: is not tidiness: the full id contains the literal ``self-hosted``, and
#: ``tests/ci/test_self_hosted_runner_experiment.py`` asserts that string appears **nowhere**
#: in ``.github/workflows/ci.yml``, backing a recorded decision to defer self-hosted runners.
#: So "the waiver string must name the row" and "ci.yml must not contain that substring" are
#: in direct conflict, and requiring the prefix satisfies both — the row is still greppable
#: from the waiver. Flagged to the coordinator, because it constrains every future CI
#: reference to that row, not just this one.
_ENV_WAIVER = "HAPAX_NFS_INTEGRATION_WAIVED"

#: **The canonical row id lives here, in full**, because this file carries no `self-hosted`
#: ban while `.github/workflows/ci.yml` does (see `tests/ci/test_self_hosted_runner_experiment.py`,
#: which asserts that substring appears nowhere in the workflow, backing a recorded
#: deferral). So the waiver string in CI necessarily carries an elided form.
#:
#: A reviewer's objection to that elision was exact: a truncated id is one **no automated
#: check can resolve** to a real row. This module is that resolver. The anchors are derived
#: from the full id rather than written beside it, so they cannot drift from it, and
#: `test_the_waiver_expiry_row_is_resolvable` asserts the elided CI form resolves here.
_WAIVER_EXPIRY_ROW_ID = "nfs-fallback-live-witness-self-hosted-ci-20260913"
_WAIVER_EXPIRY_ANCHORS = (
    _WAIVER_EXPIRY_ROW_ID.split("-self-hosted-")[0],
    _WAIVER_EXPIRY_ROW_ID.split("-self-hosted-")[1],
)
_RENAME_NOREPLACE = 1
_RENAME_EXCHANGE = 2


@pytest.fixture(autouse=True)
def _activate_candidate_lifecycle_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lifecycle effects are default-deny in production; this exercises the candidate.

    Same activation the unit suite uses. It gates the *effect*, not the rename legs, so
    flipping it does not weaken what this file measures — the mount still refuses the
    flags and the rebuilt legs still do the work.
    """

    monkeypatch.setattr(cp, "_LIFECYCLE_EFFECT_ACTIVATION", True)


_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
_libc.renameat2.restype = ctypes.c_int
_libc.renameat2.argtypes = [
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_uint,
]


def _renameat2_errno(dir_fd: int, old: str, new: str, flags: int) -> int:
    ctypes.set_errno(0)
    rc = _libc.renameat2(dir_fd, os.fsencode(old), dir_fd, os.fsencode(new), flags)
    return 0 if rc == 0 else ctypes.get_errno()


def _flag_errno(directory: Path, flags: int, *, occupy_destination: bool) -> int:
    """Probe one flag in `directory`, cleaning up after itself."""
    left, right = f".probe-{uuid.uuid4().hex[:8]}", f".probe-{uuid.uuid4().hex[:8]}"
    (directory / left).write_bytes(b"a\n")
    if occupy_destination:
        (directory / right).write_bytes(b"b\n")
    dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        return _renameat2_errno(dir_fd, left, right, flags)
    finally:
        os.close(dir_fd)
        for name in (left, right):
            try:
                (directory / name).unlink()
            except FileNotFoundError:
                pass


@pytest.fixture
def unsupporting_mount() -> Path:
    """A writable directory on a mount measured to refuse both renameat2 flags."""

    configured = os.environ.get(_ENV_DIR, "").strip()
    if not configured:
        waiver = os.environ.get(_ENV_WAIVER, "").strip()
        if waiver:
            missing = [anchor for anchor in _WAIVER_EXPIRY_ANCHORS if anchor not in waiver]
            if missing:
                pytest.fail(
                    f"{_ENV_WAIVER} is set but does not name its expiry row (missing "
                    f"{', '.join(missing)}). A waiver without an owner is a permanent skip "
                    "wearing a different name. "
                    "Next: name the row that owns standing up a lane which can mount the "
                    f"vault export — the accepted form is shown by unsetting {_ENV_WAIVER} "
                    "and rerunning, which prints a copy-pasteable value."
                )
            pytest.skip(
                f"{_ENV_DIR} unset; live verification EXPLICITLY WAIVED by "
                f"{_ENV_WAIVER}={waiver}. Visible, greppable, and expiring with the row it "
                "names — not a silent skip."
            )
        pytest.fail(
            f"FAIL-CLOSED: {_ENV_DIR} is unset and no waiver is declared.\n"
            "This is an infrastructure absence, not a code defect, and it is red on "
            "purpose: the central claim of this repair — that the rebuilt renameat2 legs "
            "work on the real NFS4.2 vault SSOT — must not rest on a test that can be "
            "permanently and invisibly skipped.\n"
            f"Next: either point {_ENV_DIR} at a writable directory on a mount that refuses "
            "the flags:\n"
            f"  {_ENV_DIR}=<a writable dir on such a mount>\n"
            "or declare the absence out loud, naming the row that owns closing it — this "
            "exact value is accepted, and a bare reason is NOT:\n"
            f'  {_ENV_WAIVER}="hosted runner cannot mount nfs4; expiry owned by row '
            f'{_WAIVER_EXPIRY_ANCHORS[0]}-*-{_WAIVER_EXPIRY_ANCHORS[1]}"'
        )
    # Past this point the operator has EXPLICITLY configured a mount, and every remaining
    # outcome is FAIL rather than skip.
    #
    # These were skips, and a reviewer was right that it reopened the hole the fail-closed
    # design exists to close: point the variable at the wrong directory — an ext4 path, a
    # typo, an unwritable one — and the witness skipped silently, with no waiver and nothing
    # declaring the absence. A skip is only ever legitimate when NO mount was offered and a
    # governed waiver names the row that owns closing the gap. A configuration that does not
    # do what it claims is a broken configuration, and it should be red.
    root = Path(configured).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        pytest.fail(
            f"{_ENV_DIR}={root} is configured but not writable: {exc}. "
            "Next: fix the permissions or point it at a writable directory on a mount that "
            f"refuses the renameat2 flags, or unset it and declare a governed {_ENV_WAIVER} "
            "instead — an unwritable configured path is a broken configuration, not an "
            "absent mount, so it is not waivable as one."
        )

    directory = root / f"lifecycle-{uuid.uuid4().hex[:8]}"
    directory.mkdir()

    # Precondition, measured rather than assumed: this mount must actually refuse the
    # flags, or the run would take the libc fast path and prove nothing.
    exchange = _flag_errno(directory, _RENAME_EXCHANGE, occupy_destination=True)
    noreplace = _flag_errno(directory, _RENAME_NOREPLACE, occupy_destination=False)
    if exchange == 0 or noreplace == 0:
        pytest.fail(
            f"{_ENV_DIR}={directory} SUPPORTS renameat2 flags "
            f"(EXCHANGE errno={exchange}, NOREPLACE errno={noreplace}), so the fallback "
            "would never be reached and a green run here would prove nothing. "
            "Next: point it at a filesystem that refuses the flags — an NFS4 mount — or "
            f"unset it and declare a governed {_ENV_WAIVER} instead."
        )
    if exchange not in cp._RENAME_FLAG_UNSUPPORTED_ERRNOS:
        pytest.fail(
            f"{_ENV_DIR}={directory} fails EXCHANGE with errno={exchange}, which is not an "
            "unsupported-flag errno. That is a broken mount rather than one lacking the "
            "flag, and this witness cannot distinguish the repair from the breakage on it. "
            f"Next: check the export's health (errno {exchange} is a fault, not a missing "
            "feature), then either point this at a healthy mount that refuses the flags or "
            f"unset it and declare a governed {_ENV_WAIVER}."
        )
    return directory


def _intent() -> cp.LifecycleTransitionIntent:
    from shared.sdlc_lifecycle import SDLC_STAGE_METADATA, stage_token

    source = stage_token("S6_IMPLEMENTATION")
    target = stage_token("S7_RUNTIME_VERIFICATION")
    edge = next(
        (
            candidate
            for candidate in SDLC_STAGE_METADATA.by_token[source].next_edges
            if candidate.to == target
        ),
        None,
    )
    return cp.LifecycleTransitionIntent.create(
        task_id="nfs-integration",
        from_stage="S6_IMPLEMENTATION",
        to_stage="S7_RUNTIME_VERIFICATION",
        edge_class="next",
        authority_case="CASE-X",
        actor="beta",
        no_go_snapshot={key: key == "implementation_authorized" for key in cp.NO_GO_BOOLEANS},
        parent_spec="/tmp/spec.md",
        guard_evidence=(
            {guard: (f"receipt:nfs:{guard}",) for guard in edge.guards} if edge else {}
        ),
    )


def test_the_mount_really_refuses_both_flags(unsupporting_mount: Path) -> None:
    """The precondition, asserted as its own result rather than only as a skip guard.

    Without this the suite could go green on a mount that supports the flags — exactly the
    criticism the unit-only story attracted: a passing run that never entered the code
    under test. Also checks the primitives the rebuild is made of, since the whole repair
    rests on them behaving here.
    """

    assert (
        _flag_errno(unsupporting_mount, _RENAME_EXCHANGE, occupy_destination=True) == errno.EINVAL
    )
    assert (
        _flag_errno(unsupporting_mount, _RENAME_NOREPLACE, occupy_destination=False) == errno.EINVAL
    )

    left = unsupporting_mount / f".ok-{uuid.uuid4().hex[:8]}"
    right = unsupporting_mount / f".ok-{uuid.uuid4().hex[:8]}"
    pin = unsupporting_mount / f"{right.name}.pin"
    left.write_bytes(b"x\n")
    right.write_bytes(b"y\n")
    os.link(right, pin)
    os.rename(left, right)
    assert right.read_bytes() == b"x\n"
    assert pin.read_bytes() == b"y\n"
    with pytest.raises(FileExistsError):
        os.link(right, pin)
    for path in (right, pin):
        path.unlink()


def test_claim_shaped_lifecycle_projects_on_a_mount_that_refuses_the_flags(
    unsupporting_mount: Path, tmp_path: Path
) -> None:
    """The measured failure, inverted, on the filesystem that produced it.

    A claim publication is two projections against one directory: the note flips
    ``offered`` → ``claimed`` (both bytes present and differing, so ``_scratch_for`` makes
    it an *update* and it takes the EXCHANGE leg) and the role marker is created (the
    NOREPLACE leg). Both rebuilt legs therefore run on this mount, and the transaction
    must record ``applied`` with no pin or scratch left behind.
    """

    note = unsupporting_mount / "task-1.md"
    marker = unsupporting_mount / "marker"
    note.write_bytes(b"status: offered\nassigned_to: unassigned\n")
    log = CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )

    cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[
            cp.FileProjection.capture(note, after=b"status: claimed\nassigned_to: beta\n"),
            cp.FileProjection.capture(marker, after=b"beta\n"),
        ],
        transaction_root=tmp_path / "transactions",
        lock_root=tmp_path / "locks",
        timestamp="2026-09-13T22:20:00Z",
    )

    assert note.read_bytes() == b"status: claimed\nassigned_to: beta\n"
    assert marker.read_bytes() == b"beta\n"
    assert [event.event_type for event in log.replay().events] == [
        cp.CANON_TRANSITION_PREPARED,
        cp.CANON_TRANSITION_APPLIED,
    ]
    assert not list(unsupporting_mount.glob("*.transition-pin.*"))
    assert not list(unsupporting_mount.glob("*transition-scratch*"))


def test_every_refusal_in_this_module_names_a_next_action() -> None:
    """executive_function: an error that does not say what to do next is half an error.

    Reviewers have twice found refusals here missing one — and separately found one whose
    suggested command its own validation rejected, which is worse than silence because it
    sends a stuck reader round again. This scans the module's own source so the requirement
    is enforced rather than remembered, which is the only form that survives the next edit.
    """

    lines = Path(__file__).read_text(encoding="utf-8").splitlines()
    # A refusal is a LINE that opens the call, not any occurrence of the text — the first
    # version matched this scanner's own search string and reported itself, which is the
    # completeness-filter trap in miniature.
    refusals: list[str] = []
    for index, line in enumerate(lines):
        if not line.strip().startswith("pytest.fail("):
            continue
        depth, collected = 0, []
        for candidate in lines[index:]:
            collected.append(candidate)
            depth += candidate.count("(") - candidate.count(")")
            if depth <= 0:
                break
        refusals.append("\n".join(collected))

    assert refusals, "no refusals found — the scanner is broken, not the module"
    missing = [r for r in refusals if "Next:" not in r]
    assert not missing, (
        f"{len(missing)} of {len(refusals)} refusals do not name a next action:\n"
        + "\n---\n".join(r[:200] for r in missing)
    )


def test_the_waiver_expiry_row_is_resolvable() -> None:
    """A truncated row id must still resolve to a real row, by machine.

    `ci.yml` cannot contain the literal `self-hosted` — `tests/ci/test_self_hosted_runner_experiment.py`
    asserts that, backing a recorded deferral — and the expiry row's id contains it. So the
    waiver string in CI carries an elided form, and a reviewer's objection was exact: an id
    no automated check can resolve is not an expiry, it is a decoration.

    This test is the resolver. It runs in every suite, needs no mount, and fails if the
    elided form in the workflow stops matching the canonical id recorded here — which is the
    only place in the repo that can hold it in full.
    """

    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
    text = workflow.read_text(encoding="utf-8")

    waived = [line for line in text.splitlines() if _ENV_WAIVER in line]
    assert waived, f"{_ENV_WAIVER} is not declared in ci.yml at all"
    declaration = waived[0]

    # Each anchor is derived from the canonical id, so they cannot drift from it.
    for anchor in _WAIVER_EXPIRY_ANCHORS:
        assert anchor in declaration, (anchor, declaration)
    # And the anchors really do reconstruct the canonical row, rather than merely coexisting
    # with it — this is the step that makes the elision resolvable instead of suggestive.
    assert _WAIVER_EXPIRY_ANCHORS[0] + "-self-hosted-" + _WAIVER_EXPIRY_ANCHORS[1] == (
        _WAIVER_EXPIRY_ROW_ID
    )
    # The ban this elision exists to respect is still in force; if it is ever lifted, the
    # full id belongs in the waiver and this test should be deleted with the elision.
    assert "self-hosted" not in text, (
        "the ci.yml self-hosted ban has been lifted — put the full row id in the waiver "
        "and delete this elision"
    )


def test_directory_promotion_on_a_mount_that_refuses_the_flags(
    unsupporting_mount: Path,
) -> None:
    """The leg every transaction runs through, exercised on the real filesystem.

    The live witness covered a note update and a marker create — the file legs. Journal
    materialization promotes a whole staged transaction *directory* into the canonical root
    under NOREPLACE, across two directories, and `link(2)` refuses directories, so that leg
    takes an entirely different rebuild. It was verified only against a simulated mount.

    That matters here more than elsewhere: the directory rebuild's safety argument rests on
    what plain `rename(2)` does to a populated destination on THIS filesystem, and NFS is
    exactly where a reasonable assumption about rename semantics could fail to hold.
    """

    staging = unsupporting_mount / "staging"
    final = unsupporting_mount / "final"
    staging.mkdir()
    final.mkdir()
    journal = staging / "txn-live"
    journal.mkdir()
    (journal / "manifest.json").write_bytes(b'{"live": true}\n')

    src_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY)
    dst_fd = os.open(final, os.O_RDONLY | os.O_DIRECTORY)
    try:
        cp._fallback_noreplace(src_fd, "txn-live", dst_fd, "txn-live")
        assert (final / "txn-live" / "manifest.json").read_bytes() == b'{"live": true}\n'
        assert not (staging / "txn-live").exists()

        # And the refusals the argument depends on, measured here rather than assumed from
        # the simulated mount: a POPULATED destination and a FILE destination.
        populated_src = staging / "txn-occupied"
        populated_src.mkdir()
        (populated_src / "manifest.json").write_bytes(b"{}\n")
        occupied = final / "txn-occupied"
        occupied.mkdir()
        (occupied / "keep-me").write_bytes(b"occupied\n")
        with pytest.raises((OSError, cp.LifecycleTransitionError)):
            cp._fallback_noreplace(src_fd, "txn-occupied", dst_fd, "txn-occupied")
        assert (occupied / "keep-me").read_bytes() == b"occupied\n"

        file_src = staging / "txn-file"
        file_src.mkdir()
        (final / "txn-file").write_bytes(b"a file, not a directory\n")
        with pytest.raises((OSError, cp.LifecycleTransitionError)):
            cp._fallback_noreplace(src_fd, "txn-file", dst_fd, "txn-file")
        assert (final / "txn-file").read_bytes() == b"a file, not a directory\n"
    finally:
        os.close(src_fd)
        os.close(dst_fd)

"""Environment-gated lifecycle verification on a real mount that refuses renameat2 flags.

Answers codex-1's and gemini-1's major findings on PR #4667: the unit suite simulates the
mount at the primitive boundary, and the live run recorded in
``NFS-FALLBACK-LIVE-VERIFICATION-20260913.md`` had no committed, re-runnable witness. This
is that witness.

    HAPAX_NFS_INTEGRATION_DIR="$HOME/Documents/Personal/.nfs-integration" \\
      uv run pytest tests/shared/test_coord_projection_nfs_integration.py -v

Skipped — never silently passed — when the variable is unset, when the directory is not on
a filesystem that refuses the flags, or when a precondition cannot be established. Each
skip names which precondition failed, because a skip that cannot say why is
indistinguishable from a test that never ran.

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
        pytest.skip(f"{_ENV_DIR} is unset — no mount offered for live verification")
    root = Path(configured).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        pytest.skip(f"{_ENV_DIR}={root} is not writable: {exc}")

    directory = root / f"lifecycle-{uuid.uuid4().hex[:8]}"
    directory.mkdir()

    # Precondition, measured rather than assumed: this mount must actually refuse the
    # flags, or the run would take the libc fast path and prove nothing.
    exchange = _flag_errno(directory, _RENAME_EXCHANGE, occupy_destination=True)
    noreplace = _flag_errno(directory, _RENAME_NOREPLACE, occupy_destination=False)
    if exchange == 0 or noreplace == 0:
        pytest.skip(
            f"{directory} supports renameat2 flags "
            f"(EXCHANGE errno={exchange}, NOREPLACE errno={noreplace}) — "
            "the fallback would not be reached, so this proves nothing"
        )
    if exchange not in cp._RENAME_FLAG_UNSUPPORTED_ERRNOS:
        pytest.skip(
            f"{directory} fails EXCHANGE with errno={exchange}, "
            "which is not an unsupported-flag errno"
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

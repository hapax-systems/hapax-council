"""A real claim's terminal close must leave evidence the governed release can archive."""

from __future__ import annotations

import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

from shared import sdlc_claim
from shared.gate0b_claim_publication_install import default_claim_publication_roots
from tests.scripts.test_cc_claim import (
    _AMBIENT_IDENTITY_ENV,
    _SESSION_ID,
    REPO_ROOT,
    _claim,
    _next_second,
    _release,
    _release_archives,
    _role_sidecars,
    _task_root,
    _write_task,
)

_LATER_SESSION = "88888888-1111-2222-3333-444455556666"


def _image(path: Path) -> tuple[bytes, int] | None:
    return (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) if path.exists() else None


def _close(home: Path, task_id: str, session: str, status: str) -> subprocess.CompletedProcess[str]:
    (home / ".cache/hapax/stage0-durable-sink").mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if key not in _AMBIENT_IDENTITY_ENV}
    env.update(
        HOME=str(home),
        HAPAX_CC_TASKS_ROOT=str(_task_root(home)),
        HAPAX_AGENT_NAME="cx-test",
        HAPAX_AGENT_ROLE="cx-test",
        HAPAX_SESSION_ID=session,
        # Keep optional service/reconciler effects inside the disposable fixture.
        DBUS_SESSION_BUS_ADDRESS=f"unix:path={home}/no-session-bus",
        XDG_RUNTIME_DIR=str(home / "runtime"),
        HAPAX_CC_HYGIENE_OFF="1",
    )
    return subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts/cc-close"),
            task_id,
            "--status",
            status,
            "--reason",
            "terminal fixture",
            "--retroactive",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


@pytest.mark.parametrize("status", ["done", "withdrawn", "superseded"])
@pytest.mark.parametrize("session", [_SESSION_ID, _LATER_SESSION], ids=["same", "later"])
def test_terminal_close_release_and_next_claim(tmp_path: Path, session: str, status: str) -> None:
    home = tmp_path / "home"
    task_id = "terminal-row"
    note = _write_task(home, "active", task_id, kind="fix")
    claimed = _claim(home, task_id)
    assert claimed.returncode == 0, claimed.stderr
    sidecars = _role_sidecars(home)
    evidence = (*sidecars["epoch"], *sidecars["dispatch"])
    before = {path: _image(path) for path in evidence}
    journals = home / ".local/share/hapax/claim-publications"
    journal_before = {path: _image(path) for path in journals.rglob("*") if path.is_file()}

    closed = _close(home, task_id, session, status)

    assert closed.returncode == 0, closed.stderr
    closed_note = _task_root(home) / "closed" / note.name
    assert not note.exists()
    assert f"status: {status}\n" in closed_note.read_text()
    closed_before = _image(closed_note)
    assert not sidecars["marker"][0].exists()
    assert sidecars["marker"][1].exists() == (session != _SESSION_ID)
    after_close = {path: _image(path) for path in evidence}
    remaining = {
        path.name: _image(path) for group in sidecars.values() for path in group if path.exists()
    }

    next_note = _write_task(home, "active", "next-row")
    next_before = _image(next_note)
    held = _claim(home, "next-row", session_id=session)
    assert held.returncode == 8, held.stderr
    assert f"cc-claim --release-claim-residue {task_id}" in held.stderr
    assert _image(next_note) == next_before
    assert {path: _image(path) for path in evidence} == after_close

    released = _release(home, task_id, extra_env={"HAPAX_SESSION_ID": session})

    # Before the repair, close succeeds but this refuses claim_residue_projection_missing.
    assert released.returncode == 0, released.stderr
    assert after_close == before
    assert not any(path.exists() for group in sidecars.values() for path in group)
    [archive] = _release_archives(home, task_id)
    assert {path.name: _image(path) for path in archive.iterdir() if path.name != "README.md"} == (
        remaining
    )
    assert _image(closed_note) == closed_before
    assert {path: _image(path) for path in journals.rglob("*") if path.is_file()} == journal_before

    _next_second()
    next_claim_started = int(time.time())
    next_claim = _claim(home, "next-row", session_id=session)

    assert next_claim.returncode == 0, next_claim.stderr
    for marker in _role_sidecars(home, session=session)["marker"]:
        assert marker.read_text() == "next-row\n"
    # The reused role/session keys must age the new claim from its own epoch,
    # never from the terminal claim whose evidence is now in the archive.
    old_image = before[sidecars["epoch"][0]]
    assert old_image is not None
    old_epoch = int(old_image[0].split()[0])
    for epoch_path in _role_sidecars(home, session=session)["epoch"]:
        epoch, epoch_task = epoch_path.read_text().split()
        assert epoch_task == "next-row"
        assert int(epoch) >= next_claim_started > old_epoch


@pytest.mark.parametrize("partial_release", [False, True], ids=["after-close", "partial-release"])
def test_repeated_close_preserves_remaining_residue_and_release_can_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, partial_release: bool
) -> None:
    home = tmp_path / "home"
    task_id = "terminal-row"
    note = _write_task(home, "active", task_id, kind="fix")
    claimed = _claim(home, task_id)
    assert claimed.returncode == 0, claimed.stderr
    closed = _close(home, task_id, _LATER_SESSION, "done")
    assert closed.returncode == 0, closed.stderr
    sidecars = _role_sidecars(home)
    remaining = {
        path.name: _image(path) for group in sidecars.values() for path in group if path.exists()
    }

    if partial_release:
        roots = default_claim_publication_roots(home=home)
        rename = os.rename
        moved = []

        def fail_second_move(src: Path, dst: Path) -> None:
            if len(moved) == 1:
                raise OSError("injected second residue move failure")
            rename(src, dst)
            moved.append(src)

        # Interrupt the actual filesystem move after the first sidecar is archived.
        with monkeypatch.context() as patch:
            patch.setattr(os, "rename", fail_second_move)
            with pytest.raises(OSError, match="injected second residue move failure"):
                sdlc_claim.release_claim_residue(
                    vault_root=_task_root(home),
                    cache_dir=home / ".cache/hapax",
                    transaction_root=Path(roots.claim_transaction_root),
                    lock_root=Path(roots.claim_lock_root),
                    role="cx-test",
                    task_id=task_id,
                    observed_at="20260930T000000Z",
                )
        assert len(moved) == 1
        assert not moved[0].exists()
        [partial] = _release_archives(home, task_id)
        assert _image(partial / moved[0].name) == remaining[moved[0].name]

    def snapshot() -> dict[Path, tuple[bytes, int] | None]:
        return {path: _image(path) for path in home.rglob("*") if path.is_file()}

    before_repeat = snapshot()
    repeated = _close(home, task_id, _LATER_SESSION, "done")

    # Repeating close is a refusal with no effects, not another successful close.
    assert repeated.returncode == 2, repeated.stderr
    assert "already closed?" in repeated.stderr
    assert snapshot() == before_repeat
    closed_note = _task_root(home) / "closed" / note.name
    assert _image(closed_note) == before_repeat[closed_note]

    released = _release(home, task_id, extra_env={"HAPAX_SESSION_ID": _LATER_SESSION})

    assert released.returncode == 0, released.stderr
    assert not any(path.exists() for group in sidecars.values() for path in group)
    assert {
        path.name: _image(path)
        for archive in _release_archives(home, task_id)
        for path in archive.iterdir()
        if path.name != "README.md"
    } == remaining
    assert _image(closed_note) == before_repeat[closed_note]


@pytest.mark.parametrize("family", ["epoch", "dispatch"])
def test_terminal_close_does_not_excuse_an_unarchived_missing_sidecar(
    tmp_path: Path, family: str
) -> None:
    home = tmp_path / "home"
    _write_task(home, "active", "terminal-row", kind="fix")
    claimed = _claim(home, "terminal-row")
    assert claimed.returncode == 0, claimed.stderr
    closed = _close(home, "terminal-row", _LATER_SESSION, "done")
    assert closed.returncode == 0, closed.stderr
    sidecars = _role_sidecars(home)
    # Damage the original session's evidence, which close must never sweep on behalf of it.
    sidecars[family][1].unlink()
    before = {path: _image(path) for group in sidecars.values() for path in group}

    released = _release(home, "terminal-row", extra_env={"HAPAX_SESSION_ID": _LATER_SESSION})

    assert released.returncode == 8
    assert "claim_residue_projection_missing" in released.stderr
    assert {path: _image(path) for group in sidecars.values() for path in group} == before
    assert _release_archives(home, "terminal-row") == []

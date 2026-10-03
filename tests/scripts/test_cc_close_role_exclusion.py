"""Ordinary close serializes against the publication owner, including another-session close."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

import pytest

from shared.gate0b_claim_publication_install import (
    default_claim_publication_roots,
    load_claim_publication_composition,
)
from shared.sdlc_claim import claim_role_exclusion
from tests.scripts.test_cc_claim import _claim, _write_task
from tests.scripts.test_cc_close_session_lease import _run_close


@pytest.fixture
def owned(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    note = _write_task(home, "active", "original-task")
    result = _claim(home, "original-task")
    assert result.returncode == 0, result.stdout + result.stderr
    binaries = tmp_path / "bin"
    binaries.mkdir()
    systemctl = binaries / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 0\n")
    systemctl.chmod(0o755)
    import os

    monkeypatch.setenv("PATH", str(binaries) + ":" + os.environ["PATH"])
    roots = default_claim_publication_roots(home=home)
    install = load_claim_publication_composition(Path(roots.invocation_store_root))
    return home, note, install


def test_close_waits_for_original_owner_exclusion(owned):
    home, note, install = owned
    before = note.read_bytes()
    with ThreadPoolExecutor() as pool:
        with claim_role_exclusion("cx-test", lock_root=install.root.claim_lock_root):
            future = pool.submit(
                _run_close, home, "original-task", role="cx-closer", session_id="other-session"
            )
            with pytest.raises(TimeoutError):
                future.result(timeout=3)
            assert note.read_bytes() == before
        result = future.result(timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_another_session_close_retains_exact_epoch_and_dispatch_evidence(owned):
    home, note, _ = owned
    cache = home / ".cache/hapax"
    sidecars = {
        p: (p.read_bytes(), p.stat().st_mode)
        for p in cache.iterdir()
        if p.name.startswith(("cc-claim-epoch-", "cc-claim-dispatch-"))
    }
    result = _run_close(home, "original-task", role="cx-closer", session_id="other-session")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not note.exists()
    assert not list(cache.glob("cc-active-task-cx-test*"))
    assert {p: (p.read_bytes(), p.stat().st_mode) for p in sidecars} == sidecars


def test_changed_owner_while_close_waits_preserves_note_and_claim(owned):
    home, note, install = owned
    cache = home / ".cache/hapax"
    before = {p: p.read_bytes() for p in cache.glob("cc-*cx-test*")}
    with ThreadPoolExecutor() as pool:
        with claim_role_exclusion("cx-test", lock_root=install.root.claim_lock_root):
            future = pool.submit(
                _run_close, home, "original-task", role="cx-closer", session_id="other-session"
            )
            with pytest.raises(TimeoutError):
                future.result(timeout=3)
            changed = note.read_bytes().replace(b"assigned_to: cx-test", b"assigned_to: successor")
            note.write_bytes(changed)
        result = future.result(timeout=30)
    assert result.returncode != 0
    assert note.read_bytes() == changed
    assert {p: p.read_bytes() for p in before} == before


def test_noncanonical_marker_holds_before_note_transition(owned):
    home, note, _ = owned
    marker = home / ".cache/hapax/cc-active-task-cx-test"
    marker.write_text(" original-task \n")
    before = note.read_bytes()
    result = _run_close(home, "original-task", role="cx-closer", session_id="other-session")
    assert result.returncode != 0
    assert note.read_bytes() == before
    assert marker.read_text() == " original-task \n"


def test_close_span_excludes_successor_until_final_marker_removal(owned, tmp_path):
    """Instrument the production transition body at unlink; the publisher is the real CLI."""
    import os
    import subprocess
    import sys
    import time

    home, note, install = owned
    _write_task(home, "active", "successor-task")
    repository = Path(__file__).resolve().parents[2]
    source = (repository / "scripts/cc-close").read_text()
    body = source.split('"${expect_sha256:-}" "$reason" "$witness" <<\'PYEOF\'\n', 1)[1].split(
        "\nPYEOF", 1
    )[0]
    reached, proceed = tmp_path / "reached", tmp_path / "proceed"
    barrier = f"""            Path({str(reached)!r}).touch()
            import time
            deadline = time.monotonic() + 20
            while not Path({str(proceed)!r}).exists():
                if time.monotonic() > deadline:
                    raise RuntimeError("test barrier timed out")
                time.sleep(0.02)
"""
    body = body.replace("            marker.unlink()", barrier + "            marker.unlink()")
    assert "test barrier timed out" in body
    env = dict(os.environ, HOME=str(home), PYTHONPATH=str(repository))
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            body,
            str(note),
            "original-task",
            "withdrawn",
            "",
            "cx-closer",
            str(note.parent.parent),
            "",
            "fixture close",
            "",
        ],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def publish_successor():
        from shared.sdlc_claim import release_claim_residue

        roots = install.receipt.roots
        release_claim_residue(
            vault_root=Path(roots.claim_vault_root),
            cache_dir=Path(roots.claim_cache_dir),
            role="cx-test",
            task_id="original-task",
            observed_at="20261003T030303Z",
            transaction_root=Path(roots.claim_transaction_root),
            lock_root=Path(roots.claim_lock_root),
        )
        return _claim(home, "successor-task", install_gate0b=False)

    try:
        deadline = time.monotonic() + 15
        while not reached.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert reached.exists(), child.communicate(timeout=1)
        with ThreadPoolExecutor() as pool:
            future = pool.submit(publish_successor)
            try:
                with pytest.raises(TimeoutError):
                    future.result(timeout=3)
                assert (
                    home / ".cache/hapax/cc-active-task-cx-test"
                ).read_text() == "original-task\n"
            finally:
                proceed.touch()
            result = future.result(timeout=30)
        stdout, stderr = child.communicate(timeout=15)
        assert child.returncode == 0, stdout + stderr
        assert result.returncode == 0, result.stdout + result.stderr
        assert (home / ".cache/hapax/cc-active-task-cx-test").read_text() == "successor-task\n"
    finally:
        proceed.touch()
        if child.poll() is None:
            child.terminate()
        child.communicate(timeout=5)

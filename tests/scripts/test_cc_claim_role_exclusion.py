"""Real CLI writers must participate in the installed role-lock namespace."""

from __future__ import annotations

import errno
import importlib.util
import os
import subprocess
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared import sdlc_claim
from shared.gate0b_claim_publication_install import default_claim_publication_roots

REPO = Path(__file__).resolve().parents[2]


def _helper(name: str):
    # Pin local test helpers; never import a third-party package named tests.
    spec = importlib.util.spec_from_file_location(name, REPO / "tests/scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _short_lock_timeout_cli(tmp_path: Path, injection: str = "") -> Path:
    repo = tmp_path / "cli"
    script = repo / "scripts/cc-claim"
    script.parent.mkdir(parents=True)
    script.write_bytes((REPO / "scripts/cc-claim").read_bytes())
    (repo / "hooks").symlink_to(REPO / "hooks", target_is_directory=True)
    runner = repo / ".venv/bin/python"
    runner.parent.mkdir(parents=True)
    runner.write_text(
        f"#!{sys.executable}\n"
        + textwrap.dedent(
            f"""\
            import os
            import sys
            if sys.argv[1:3] != ["-I", "-"]:
                os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])
            code = sys.stdin.read()
            sys.argv = sys.argv[2:]
            sys.path.insert(0, {str(REPO)!r})
            import shared.sdlc_claim as claim
            assert claim.__file__ == {str(REPO / "shared/sdlc_claim.py")!r}
            claim._CLAIM_PUBLICATION_LOCK_TIMEOUT_SECONDS = 0.2
            exec({injection!r})
            exec(compile(code, "<cc-claim-role-test>", "exec"))
            """
        ),
        encoding="utf-8",
    )
    runner.chmod(0o755)
    return script


def _ownership_bytes(home: Path) -> dict[str, bytes]:
    files = list((home / "Documents").rglob("*.md"))
    cache = home / ".cache/hapax"
    files.extend(path for pattern in ("cc-*", "charter-units-*") for path in cache.glob(pattern))
    return {str(path.relative_to(home)): path.read_bytes() for path in files if path.is_file()}


@pytest.mark.parametrize("writer", ["admitted", "emergency", "charter"])
@pytest.mark.parametrize("custom_root", [False, True])
def test_same_role_different_task_excludes_cli_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writer: str, custom_root: bool
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    helper = _helper("test_cc_claim_charter" if writer == "charter" else "test_cc_claim")
    from shared.gate0b_claim_publication_install import install_claim_publication_composition

    roots = default_claim_publication_roots(home=home)
    if custom_root:
        roots = roots.model_copy(update={"claim_lock_root": str(home / "installed-role-locks")})
    install_claim_publication_composition(
        roots=roots, installed_at="2026-09-24T00:00:00Z", install_task_ref="test-install"
    )
    if writer == "charter":
        helper._write_charter(home)
        result = helper._claim(home, "charter-x", install_gate0b=False)
        assert result.returncode == 0, result.stderr
        helper._write_unit(home, "new-task", ["shared/cx/new.py"])
        role = helper._ROLE
        kwargs = {"install_gate0b": False}
    else:
        helper._write_task(home, "active", "new-task")
        role = "cx-test"
        kwargs = {"legacy": writer == "emergency", "install_gate0b": False}
    helper.SCRIPT = _short_lock_timeout_cli(tmp_path)
    before = _ownership_bytes(home)
    lock_root = Path(roots.claim_lock_root)
    old = SimpleNamespace(role=role, task_id="different-old-task", note_path=home / "old.md")
    # The holder has a different task/note. A note-only writer will complete here,
    # so the refusal and exact projection preimages below are behavioral evidence.
    with sdlc_claim._claim_publication_lock(old, lock_root=lock_root):
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(helper._claim, home, "new-task", **kwargs).result(timeout=15)
        assert result.returncode != 0, (writer, result.stdout, result.stderr)
        assert "claim_publication_lock_unavailable" in result.stderr
        assert _ownership_bytes(home) == before
    retry = helper._claim(home, "new-task", **kwargs)
    assert retry.returncode == 0, retry.stderr
    assert _ownership_bytes(home) != before


def test_public_role_exclusion_serializes_process_and_releases_on_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    root = tmp_path / "locks"
    code = textwrap.dedent(
        f"""\
        import sys
        from pathlib import Path
        sys.path.insert(0, {str(REPO)!r})
        from shared import sdlc_claim
        sdlc_claim._CLAIM_PUBLICATION_LOCK_TIMEOUT_SECONDS = 0.2
        try:
            with sdlc_claim.claim_role_exclusion("role-a", lock_root=Path({str(root)!r})):
                print("acquired")
        except sdlc_claim.ClaimPublicationError as exc:
            print(exc.reason_code)
            sys.exit(3)
        """
    )
    with pytest.raises(RuntimeError, match="holder failure"):
        with sdlc_claim.claim_role_exclusion("role-a", lock_root=root):
            result = subprocess.run(
                [sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=5
            )
            assert result.returncode == 3, result.stderr
            assert result.stdout.strip() == "claim_publication_lock_unavailable"
            # A distinct role is independent of this exclusion.
            with sdlc_claim.claim_role_exclusion("role-b", lock_root=root):
                pass
            raise RuntimeError("holder failure")
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "acquired"


def test_public_role_exclusion_rejects_note_first(tmp_path: Path) -> None:
    from shared.task_note_lock import projected_path_lock

    with projected_path_lock("task-a", (tmp_path / "a.md",), root=tmp_path / "notes"):
        with pytest.raises(sdlc_claim.ClaimPublicationError) as error:
            with sdlc_claim.claim_role_exclusion("role-a", lock_root=tmp_path / "roles"):
                pytest.fail("role lock admitted in reverse order")
    assert error.value.reason_code == "claim_publication_lock_order_inversion"
    assert not (tmp_path / "roles").exists()


def test_public_role_exclusion_open_failure_keeps_typed_cause(tmp_path, monkeypatch):
    root = tmp_path / "locks"
    root.mkdir(mode=0o700)
    original = sdlc_claim.os.open

    def denied(path, *args, **kwargs):
        if Path(path).parent == root:
            raise PermissionError(errno.EACCES, "fixture lock denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(sdlc_claim.os, "open", denied)
    with pytest.raises(sdlc_claim.ClaimPublicationError) as error:
        with sdlc_claim.claim_role_exclusion("role-a", lock_root=root):
            pytest.fail("lock opened")
    assert error.value.reason_code == "claim_publication_lock_unavailable"
    assert isinstance(error.value.__cause__, PermissionError)


@pytest.mark.parametrize("residue", ["complete", "session-only", "epoch-only", "dispatch-only"])
def test_emergency_claim_rechecks_vacancy_inside_role_lock(tmp_path, monkeypatch, residue):
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    helper = _helper("test_cc_claim")
    helper._write_task(home, "active", "new-task")
    helper._write_task(home, "active", "incumbent", status="claimed", assigned_to="cx-test")
    cache = home / ".cache/hapax"
    key = "cx-test-session-incumbent"
    incumbent = {
        "cc-active-task-cx-test": "incumbent\n",
        f"cc-active-task-{key}": "incumbent\n",
        "cc-claim-epoch-cx-test": "123 incumbent\n",
        f"cc-claim-epoch-{key}": "123 incumbent\n",
    }
    if residue == "session-only":
        incumbent = {f"cc-active-task-{key}": "incumbent\n"}
    elif residue == "epoch-only":
        incumbent = {f"cc-claim-epoch-{key}": "123 incumbent\n"}
    elif residue == "dispatch-only":
        incumbent = {f"cc-claim-dispatch-{key}.json": '{"task_id":"incumbent"}\n'}
    helper.SCRIPT = _short_lock_timeout_cli(
        tmp_path,
        textwrap.dedent(f"""\
            from contextlib import contextmanager
            from pathlib import Path
            original = claim.claim_role_exclusion
            @contextmanager
            def publish_first(*args, **kwargs):
                with original(*args, **kwargs):
                    cache = Path({str(cache)!r})
                    cache.mkdir(parents=True, exist_ok=True)
                    for name, content in {incumbent!r}.items():
                        (cache / name).write_text(content)
                with original(*args, **kwargs):
                    yield
            claim.claim_role_exclusion = publish_first
            """),
    )
    before = _ownership_bytes(home)
    result = helper._claim(home, "new-task", legacy=True)
    assert result.returncode == 3, (result.stdout, result.stderr)
    assert "claim_emergency_role_occupied" in result.stderr
    before.update(
        {str((cache / name).relative_to(home)): value.encode() for name, value in incumbent.items()}
    )
    assert _ownership_bytes(home) == before


def test_emergency_loses_to_real_publisher_and_winner_retries(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    helper = _helper("test_cc_claim")
    helper._write_task(home, "active", "loser")
    helper._write_task(home, "active", "winner")
    ready, proceed = tmp_path / "ready", tmp_path / "proceed"
    helper.SCRIPT = _short_lock_timeout_cli(
        tmp_path,
        textwrap.dedent(f"""\
        from contextlib import contextmanager
        from pathlib import Path
        import time
        original = claim.claim_role_exclusion
        @contextmanager
        def pause(*args, **kwargs):
            Path({str(ready)!r}).touch()
            deadline = time.monotonic() + 15
            while not Path({str(proceed)!r}).exists():
                if time.monotonic() > deadline:
                    raise RuntimeError("test publication barrier timed out")
                time.sleep(0.01)
            with original(*args, **kwargs):
                yield
        claim.claim_role_exclusion = pause
        """),
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        loser = pool.submit(helper._claim, home, "loser", legacy=True)
        deadline = time.monotonic() + 15
        while not ready.exists():
            assert not loser.done(), loser.result() if loser.done() else ""
            assert time.monotonic() < deadline
            time.sleep(0.01)
        winner = _helper("test_cc_claim")
        won = winner._claim(home, "winner", install_gate0b=False, session_id="session-winner01")
        assert won.returncode == 0, won.stderr
        before = _ownership_bytes(home)
        proceed.touch()
        lost = loser.result(timeout=15)
    assert lost.returncode == 3, lost.stderr
    assert "claim_emergency_role_occupied" in lost.stderr
    assert _ownership_bytes(home) == before
    retry = winner._claim(home, "winner", install_gate0b=False, session_id="session-winner01")
    assert retry.returncode == 0, retry.stderr
    assert "already owns task" in retry.stdout
    assert _ownership_bytes(home) == before


def test_emergency_matching_resume_preserves_epoch(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    helper = _helper("test_cc_claim")
    note = helper._write_task(home, "active", "task-a")
    assert helper._claim(home, "task-a", legacy=True).returncode == 0
    note.write_text(note.read_text().replace("status: claimed", "status: pr_open"))
    cache = home / ".cache/hapax"
    for path in cache.glob("cc-claim-epoch-*"):
        path.write_text("123 task-a\n")
    before = {p.name: p.read_bytes() for p in cache.glob("cc-*") if p.is_file()}
    result = helper._claim(home, "task-a", legacy=True, install_gate0b=False)
    assert result.returncode == 0, result.stderr
    assert {p.name: p.read_bytes() for p in cache.glob("cc-*") if p.is_file()} == before


@pytest.mark.parametrize("force", [False, True])
def test_emergency_expiry_cannot_delete_foreign_session_before_lock(tmp_path, monkeypatch, force):
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    helper = _helper("test_cc_claim")
    helper._write_task(home, "active", "new-task")
    helper._write_task(home, "active", "incumbent", status="claimed", assigned_to="cx-test")
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    claim = cache / "cc-active-task-cx-test-session-incumbent"
    claim.write_text("incumbent\n")
    os.utime(claim, (1, 1))
    before = _ownership_bytes(home)
    result = helper._claim(home, "new-task", legacy=True, extra_args=["--force"] if force else None)
    if force:
        # PR4726 review (Muse, finding 9): --force was a silent no-op; it is refused outright.
        assert result.returncode == 2, result.stderr
        assert "--force is retired in the emergency writer too" in result.stderr
    else:
        assert result.returncode == 3, result.stderr
        assert "claim_emergency_role_occupied" in result.stderr
    assert _ownership_bytes(home) == before


def test_emergency_holds_while_an_admitted_publication_of_the_task_is_pending(
    tmp_path, monkeypatch
):
    # PR4726 review (Muse critical): the emergency path observed only role sidecars, so an
    # admitted publisher that crashed after its journal write but before any projection left
    # a pending journal the emergency writer overran. It must hold, name the journal, and
    # leave the task to governed recovery; after recovery retires the attempt it may proceed.
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    helper = _helper("test_cc_claim")
    note = helper._write_task(home, "active", "contested")
    crashed = _helper("test_cc_claim")
    crashed.SCRIPT = _short_lock_timeout_cli(
        tmp_path / "crash",
        textwrap.dedent("""\
            def _crash(*args, **kwargs):
                raise RuntimeError("simulated admitted publisher crash before any projection")
            claim._apply_projections = _crash
            """),
    )
    first = crashed._claim(
        home,
        "contested",
        session_id="3a3a3a3a-0000-4000-8000-000000000001",
        extra_env={"HAPAX_AGENT_ROLE": "cx-other", "HAPAX_AGENT_NAME": "cx-other"},
    )
    assert first.returncode == 8, first.stderr
    transactions = Path(default_claim_publication_roots(home=home).claim_transaction_root)
    pending = sorted(path.parent.name for path in transactions.glob("claim-pub-*/manifest.json"))
    assert len(pending) == 1
    assert "status: offered" in note.read_text(encoding="utf-8")
    before = _ownership_bytes(home)

    result = helper._claim(home, "contested", legacy=True, install_gate0b=False)

    assert result.returncode == 3, (result.stdout, result.stderr)
    assert "claim_emergency_pending_publication" in result.stderr
    assert pending[0] in result.stderr
    assert _ownership_bytes(home) == before

    recovered = helper._claim(
        home,
        "contested",
        install_gate0b=False,
        extra_args=["--recover-claim-publications"],
    )
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert f"{pending[0]}:aborted" in recovered.stdout
    retried = helper._claim(home, "contested", legacy=True, install_gate0b=False)
    assert retried.returncode == 0, retried.stderr
    assert "assigned_to: cx-test" in note.read_text(encoding="utf-8")


@pytest.mark.parametrize("note_state", ["still_claimed", "reoffered"])
def test_emergency_after_an_applied_journal_drifted_relies_on_note_claimability(
    tmp_path, monkeypatch, note_state
):
    # PR4726 round 2 (Muse new-3): inspection reports an applied journal as terminal without
    # checking its live postimage, and emergency blocks only on holds. Why that suffices: the
    # emergency writer claims only a claimable note, rechecked byte-for-byte under the note
    # lock. A drifted applied claim whose note still names its owner blocks by status; one
    # whose note was legitimately re-offered no longer owns anything.
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    helper = _helper("test_cc_claim")
    note = helper._write_task(home, "active", "drifted")
    owner = helper._claim(
        home,
        "drifted",
        dispatch=False,
        session_id="4b4b4b4b-0000-4000-8000-000000000001",
        extra_env={"HAPAX_AGENT_ROLE": "cx-owner", "HAPAX_AGENT_NAME": "cx-owner"},
    )
    assert owner.returncode == 0, owner.stderr
    cache = home / ".cache/hapax"
    for marker in cache.glob("cc-active-task-cx-owner*"):
        marker.unlink()  # the applied journal's postimage has drifted
    if note_state == "reoffered":
        note.write_text(
            note.read_text()
            .replace("status: claimed", "status: offered")
            .replace("assigned_to: cx-owner", "assigned_to: unassigned")
        )
    before = _ownership_bytes(home)

    result = helper._claim(home, "drifted", legacy=True, install_gate0b=False)

    if note_state == "still_claimed":
        assert result.returncode == 4, (result.stdout, result.stderr)
        assert "already assigned to 'cx-owner'" in result.stderr or "not 'offered'" in result.stderr
        assert _ownership_bytes(home) == before
    else:
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert "assigned_to: cx-test" in note.read_text()


def test_emergency_refuses_a_charter_unit_even_after_the_charter_lease_vanishes(
    tmp_path, monkeypatch
):
    # PR4726 review (Gemini major): the charter-keep grant comes from the pre-lock shell scan.
    # If the charter's markers disappear before the in-lock observation, the emergency writer
    # saw a clean cache and published the unit as a plain claim with no parent-lease check.
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    helper = _helper("test_cc_claim_charter")
    helper._write_charter(home)
    charter = helper._claim(home, "charter-x")
    assert charter.returncode == 0, charter.stderr
    helper._write_unit(home, "unit-a", ["shared/cx/unit-a.py"])
    cache = home / ".cache/hapax"
    helper.SCRIPT = _short_lock_timeout_cli(
        tmp_path,
        textwrap.dedent(f"""\
            from contextlib import contextmanager
            from pathlib import Path
            original = claim.claim_role_exclusion
            @contextmanager
            def lease_vanishes(*args, **kwargs):
                with original(*args, **kwargs):
                    for path in Path({str(cache)!r}).glob("cc-*"):
                        path.unlink()
                    yield
            claim.claim_role_exclusion = lease_vanishes
            """),
    )
    unit_note = helper._task_root(home) / "active/unit-a.md"
    unit_before = unit_note.read_bytes()
    cache_before = {path.name: path.read_bytes() for path in cache.glob("*") if path.is_file()}

    result = helper._claim(
        home,
        "unit-a",
        install_gate0b=False,
        extra_env={"HAPAX_GATE0B_CLAIM_PUBLICATION_OFF": "1"},
    )

    assert result.returncode == 3, (result.stdout, result.stderr)
    assert "claim_emergency_charter_unit_forbidden" in result.stderr
    assert unit_note.read_bytes() == unit_before
    # Refused before exclusion: the charter's lease is untouched and no unit was recorded.
    assert {path.name: path.read_bytes() for path in cache.glob("*") if path.is_file()} == (
        cache_before
    )
    assert not any(b"unit-a" in content for content in cache_before.values())


def test_emergency_without_any_installation_locks_the_default_role_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The emergency route took its role lock only under a loadable installed composition, so with
    # nothing installed it refused (gate0b_install_receipt_missing): the fallback failed whenever
    # the path it backs up failed. With nothing installed it now locks where the admitted route's
    # first-use install would install and lock, so a concurrent admitted first use still excludes
    # it, and it installs nothing itself.
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    helper = _helper("test_cc_claim")
    helper._write_task(home, "active", "new-task")
    helper.SCRIPT = _short_lock_timeout_cli(tmp_path)
    roots = default_claim_publication_roots(home=home)
    store = Path(roots.invocation_store_root)
    before = _ownership_bytes(home)
    old = SimpleNamespace(role="cx-test", task_id="different-old-task", note_path=home / "old.md")
    with sdlc_claim._claim_publication_lock(old, lock_root=Path(roots.claim_lock_root)):
        with ThreadPoolExecutor(max_workers=1) as pool:
            held = pool.submit(
                helper._claim, home, "new-task", legacy=True, install_gate0b=False
            ).result(timeout=15)
        assert held.returncode != 0, (held.stdout, held.stderr)
        assert "claim_publication_lock_unavailable" in held.stderr
        assert _ownership_bytes(home) == before
    claimed = helper._claim(home, "new-task", legacy=True, install_gate0b=False)
    assert claimed.returncode == 0, claimed.stderr
    assert "using legacy claim writer" in claimed.stderr
    assert _ownership_bytes(home) != before
    assert not any(
        (store / name).exists() for name in ("activation-receipt.json", "composition-manifest.json")
    )


_DAMAGED_INSTALLATIONS = [
    "corrupt_receipt",
    "unsafe_receipt_mode",
    "receipt_absent_manifest_present",
    "manifest_absent",
    "corrupt_manifest",
    "binding_mismatch",
    "store_is_a_file",
    "unreadable_store",
]


def _damage_installation(home: Path, state: str) -> None:
    from shared.gate0b_claim_publication_install import install_claim_publication_composition

    roots = default_claim_publication_roots(home=home)
    if state == "binding_mismatch":
        roots = roots.model_copy(update={"claim_cache_dir": str(home / "other-claim-cache")})
    install_claim_publication_composition(
        roots=roots, installed_at="2026-09-24T00:00:00Z", install_task_ref="test-install"
    )
    store = Path(roots.invocation_store_root)
    receipt, manifest = store / "activation-receipt.json", store / "composition-manifest.json"
    if state == "corrupt_receipt":
        receipt.write_bytes(b"{not json\n")
    elif state == "unsafe_receipt_mode":
        receipt.chmod(0o644)
    elif state == "receipt_absent_manifest_present":
        receipt.rename(store / "activation-receipt.aside")
    elif state == "manifest_absent":
        manifest.rename(store / "composition-manifest.aside")
    elif state == "corrupt_manifest":
        # The loader reports an unparseable manifest as gate0b_install_manifest_missing too, so
        # the reason code alone cannot tell "nothing installed" from a damaged installation.
        manifest.write_bytes(b"{not json\n")
    elif state == "store_is_a_file":
        # No install artifact "exists" beneath a regular file; only the reason code refuses.
        store.rename(store.with_name(store.name + ".aside"))
        store.write_text("not an invocation store\n")
    elif state == "unreadable_store":
        store.chmod(0o000)


@pytest.mark.parametrize("state", _DAMAGED_INSTALLATIONS)
def test_emergency_refuses_every_present_but_unloadable_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    # Only an entirely absent installation selects the default role namespace (the admitted
    # route's own first-use predicate). A damaged, partial or mismatched installation may name a
    # custom lock root that a live admitted writer holds, so the emergency writer refuses rather
    # than lock elsewhere, and the admitted route holds exactly as before.
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    helper = _helper("test_cc_claim")
    _damage_installation(home, state)
    helper._write_task(home, "active", "new-task")
    before = _ownership_bytes(home)
    store = Path(default_claim_publication_roots(home=home).invocation_store_root)
    try:
        emergency = helper._claim(home, "new-task", legacy=True, install_gate0b=False)

        assert emergency.returncode == 3, (emergency.stdout, emergency.stderr)
        assert "cc-claim: REFUSED" in emergency.stderr
        assert "claimed task" not in emergency.stdout
        assert _ownership_bytes(home) == before

        admitted = helper._claim(home, "new-task", install_gate0b=False)

        assert admitted.returncode == 8, (admitted.stdout, admitted.stderr)
        assert "cc-claim: HOLD" in admitted.stderr
        assert _ownership_bytes(home) == before
    finally:
        if state == "unreadable_store":
            store.chmod(0o700)


def test_charter_mint_sidecar_cannot_publish_after_exclusion_begins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    helper = _helper("test_cc_claim_charter")
    helper._write_charter(home)
    ready, proceed = tmp_path / "ready", tmp_path / "proceed"
    helper.SCRIPT = _short_lock_timeout_cli(
        tmp_path,
        textwrap.dedent(
            f"""\
            from pathlib import Path
            import time
            import shared.gate0b_claim_publication_effect as effect
            original = effect.publish_gate0b_claim
            def paused_publication(*args, **kwargs):
                receipt = original(*args, **kwargs)
                Path({str(ready)!r}).touch()
                deadline = time.monotonic() + 10
                while not Path({str(proceed)!r}).exists():
                    if time.monotonic() > deadline:
                        raise RuntimeError("test barrier timed out")
                    time.sleep(0.01)
                return receipt
            effect.publish_gate0b_claim = paused_publication
            """
        ),
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(helper._claim, home, "charter-x")
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert not future.done(), future.result() if future.done() else ""
            assert time.monotonic() < deadline, "publication did not reach barrier"
            time.sleep(0.01)
        before = _ownership_bytes(home)
        root = Path(default_claim_publication_roots(home=home).claim_lock_root)
        old = SimpleNamespace(role=helper._ROLE, task_id="old-task", note_path=home / "old.md")
        with sdlc_claim._claim_publication_lock(old, lock_root=root):
            proceed.touch()
            result = future.result(timeout=10)
            assert result.returncode == 8, result.stderr
            assert "claim_publication_lock_unavailable" in result.stderr
            assert "publication remains applied" in result.stderr
            assert _ownership_bytes(home) == before
    helper.SCRIPT = REPO / "scripts/cc-claim"
    retry = helper._claim(home, "charter-x", install_gate0b=False)
    assert retry.returncode == 0, retry.stderr
    sidecar = home / ".cache/hapax" / f"cc-active-charter-{helper._ROLE}-{helper._SESSION_ID}"
    assert sidecar.read_text() == "charter-x\n"


def test_charter_unit_refuses_changed_preimage_inside_role_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    helper = _helper("test_cc_claim_charter")
    helper._write_charter(home)
    result = helper._claim(home, "charter-x")
    assert result.returncode == 0, result.stderr
    helper._write_unit(home, "unit-a", ["shared/cx/new.py"])
    note = helper._task_root(home) / "active/unit-a.md"
    before = _ownership_bytes(home)
    altered = note.read_text() + "\nConcurrent edit.\n"
    helper.SCRIPT = _short_lock_timeout_cli(
        tmp_path,
        textwrap.dedent(
            f"""\
            from contextlib import contextmanager
            from pathlib import Path
            original = claim.claim_role_exclusion
            @contextmanager
            def interfere(*args, **kwargs):
                with original(*args, **kwargs):
                    Path({str(note)!r}).write_text({altered!r})
                    yield
            claim.claim_role_exclusion = interfere
            """
        ),
    )
    result = helper._claim(home, "unit-a", install_gate0b=False)
    assert result.returncode == 8, result.stderr
    assert "claim_publication_task_changed_during_preflight" in result.stderr
    before[str(note.relative_to(home))] = altered.encode()
    assert _ownership_bytes(home) == before

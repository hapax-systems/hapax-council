"""Real claim CLI writers must use the installed host's role lock namespace."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime

import pytest

from shared.gate0b_claim_publication_install import (
    default_claim_publication_roots,
    install_claim_publication_composition,
)
from shared.sdlc_claim import claim_role_exclusion
from tests.scripts.test_cc_claim import _claim, _write_task


@pytest.mark.parametrize("legacy", [False, True], ids=["admitted", "emergency"])
def test_cli_publisher_respects_installed_nondefault_root(tmp_path, legacy):
    home = tmp_path / "home"
    note = _write_task(home, "active", "next-task")
    before = note.read_bytes()
    roots = default_claim_publication_roots(home=home).model_copy(
        update={"claim_lock_root": str(tmp_path / "installed" / "custom-locks")}
    )
    installed = install_claim_publication_composition(
        roots=roots,
        installed_at=datetime(2026, 8, 9, tzinfo=UTC),
        install_task_ref="fixture-only-install",
    )
    with ThreadPoolExecutor() as pool:
        with claim_role_exclusion("cx-test", lock_root=installed.root.claim_lock_root):
            future = pool.submit(_claim, home, "next-task", legacy=legacy, install_gate0b=False)
            with pytest.raises(TimeoutError):
                future.result(timeout=3)
            assert note.read_bytes() == before
            assert not list((home / ".cache/hapax").glob("cc-active-task-*"))
        result = future.result(timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
    assert note.read_bytes() != before


@pytest.mark.parametrize("corrupt", [False, True])
def test_emergency_requires_installed_composition_before_ownership_writes(tmp_path, corrupt):
    home = tmp_path / "home"
    note = _write_task(home, "active", "next-task")
    before = note.read_bytes()
    if corrupt:
        roots = default_claim_publication_roots(home=home)
        from pathlib import Path

        root = Path(roots.invocation_store_root)
        root.mkdir(parents=True)
        (root / "activation-receipt.json").write_text("corrupt\n")
    result = _claim(home, "next-task", legacy=True, install_gate0b=False)
    assert result.returncode != 0, result.stdout + result.stderr
    assert note.read_bytes() == before
    assert not list((home / ".cache/hapax").glob("cc-active-task-*"))


@pytest.mark.parametrize("legacy", [False, True])
def test_installed_root_mismatch_preserves_ownership(tmp_path, legacy):
    home = tmp_path / "home"
    note = _write_task(home, "active", "next-task")
    before = note.read_bytes()
    roots = default_claim_publication_roots(home=home).model_copy(
        update={"claim_vault_root": str(tmp_path / "different-vault")}
    )
    install_claim_publication_composition(
        roots=roots,
        installed_at=datetime(2026, 8, 9, tzinfo=UTC),
        install_task_ref="mismatch-fixture",
    )
    result = _claim(home, "next-task", legacy=legacy, install_gate0b=False)
    assert result.returncode == 8
    assert "claim_ownership_root_mismatch" in result.stderr
    assert note.read_bytes() == before
    assert not list((home / ".cache/hapax").glob("cc-active-task-*"))


@pytest.mark.parametrize(
    "mode",
    [
        "--recover-claim-publications",
        "--rehydrate-activation-cache",
        "--release-claim-residue",
        "--return-claim",
    ],
)
def test_ownership_maintenance_uses_installed_exclusion_root(tmp_path, mode):
    from pathlib import Path

    home = tmp_path / "home"
    _write_task(home, "active", "next-task")
    roots = default_claim_publication_roots(home=home).model_copy(
        update={"claim_lock_root": str(tmp_path / "installed-maintenance-locks")}
    )
    installed = install_claim_publication_composition(
        roots=roots,
        installed_at=datetime(2026, 8, 9, tzinfo=UTC),
        install_task_ref="maintenance-fixture",
    )
    admitted = _claim(home, "next-task", install_gate0b=False)
    assert admitted.returncode == 0, admitted.stderr
    if mode in {"--rehydrate-activation-cache", "--release-claim-residue"}:
        for marker in Path(roots.claim_cache_dir).glob("cc-active-task-*"):
            marker.unlink()
    with ThreadPoolExecutor() as pool:
        with claim_role_exclusion("cx-test", lock_root=installed.root.claim_lock_root):
            future = pool.submit(_claim, home, "next-task", install_gate0b=False, extra_args=[mode])
            with pytest.raises(TimeoutError):
                future.result(timeout=3)
        result = future.result(timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_automatic_recovery_inspects_installed_transaction_root(tmp_path):
    from pathlib import Path

    home = tmp_path / "home"
    note = _write_task(home, "active", "next-task")
    before = note.read_bytes()
    roots = default_claim_publication_roots(home=home).model_copy(
        update={"claim_transaction_root": str(tmp_path / "installed-journals")}
    )
    install_claim_publication_composition(
        roots=roots, installed_at=datetime(2026, 8, 9, tzinfo=UTC), install_task_ref="auto-fixture"
    )
    journal = Path(roots.claim_transaction_root) / ("claim-pub-" + "a" * 64)
    journal.mkdir(parents=True, mode=0o700)
    journal.parent.chmod(0o700)
    manifest = journal / "manifest.json"
    manifest.write_text("{}\n")
    manifest.chmod(0o600)
    result = _claim(home, "next-task", install_gate0b=False)
    assert result.returncode == 8, result.stdout + result.stderr
    assert "claim publication inspection requires reconciliation" in result.stderr
    assert note.read_bytes() == before
    assert manifest.read_bytes() == b"{}\n"


@pytest.mark.parametrize("unsafe", [False, True], ids=["unit-and-marker", "unsafe-ledger"])
def test_charter_writes_use_installed_exclusion_and_preserve_unsafe_state(tmp_path, unsafe):
    from pathlib import Path

    from tests.scripts.test_cc_claim_charter import _ROLE, _SESSION_ID, _write_charter, _write_unit
    from tests.scripts.test_cc_claim_charter import _claim as charter_claim

    home = tmp_path / "home"
    _write_charter(home)
    roots = default_claim_publication_roots(home=home).model_copy(
        update={"claim_lock_root": str(tmp_path / "charter-installed-locks")}
    )
    installed = install_claim_publication_composition(
        roots=roots,
        installed_at=datetime(2026, 9, 22, tzinfo=UTC),
        install_task_ref="charter-fixture",
    )
    result = charter_claim(home, "charter-x", install_gate0b=False)
    assert result.returncode == 0, result.stderr
    note = _write_unit(home, "unit-x", ["shared/cx/file.py"])
    before = note.read_bytes()
    cache = Path(roots.claim_cache_dir)
    ledger = cache / f"charter-units-{_ROLE}-{_SESSION_ID}.jsonl"
    sidecar = cache / f"cc-active-charter-{_ROLE}-{_SESSION_ID}"
    sidecar.unlink()  # The unit path must recreate its auxiliary marker under exclusion.
    if unsafe:
        original = tmp_path / "ledger-original"
        original.write_text("")
        ledger.symlink_to(original)
    with ThreadPoolExecutor() as pool:
        with claim_role_exclusion(_ROLE, lock_root=installed.root.claim_lock_root):
            future = pool.submit(charter_claim, home, "unit-x", install_gate0b=False)
            with pytest.raises(TimeoutError):
                future.result(timeout=3)
            assert note.read_bytes() == before
            assert not sidecar.exists()
        result = future.result(timeout=30)
    if unsafe:
        assert result.returncode != 0
        assert note.read_bytes() == before
        assert original.read_text() == ""
        assert not sidecar.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert note.read_bytes() != before
        assert sidecar.read_text() == "charter-x\n"
        assert "unit-x" in ledger.read_text()

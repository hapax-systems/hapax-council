"""Real CLI writers must participate in the installed role-lock namespace."""

from __future__ import annotations

import importlib.util
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
def test_same_role_different_task_excludes_cli_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writer: str
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    helper = _helper("test_cc_claim_charter" if writer == "charter" else "test_cc_claim")
    if writer == "charter":
        helper._write_charter(home)
        result = helper._claim(home, "charter-x")
        assert result.returncode == 0, result.stderr
        helper._write_unit(home, "new-task", ["shared/cx/new.py"])
        role = helper._ROLE
        kwargs = {"install_gate0b": False}
    else:
        helper._write_task(home, "active", "new-task")
        role = "cx-test"
        kwargs = {"legacy": writer == "emergency"}
    helper.SCRIPT = _short_lock_timeout_cli(tmp_path)
    before = _ownership_bytes(home)
    lock_root = Path(default_claim_publication_roots(home=home).claim_lock_root)
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
                [sys.executable, "-I", "-c", code], capture_output=True, text=True
            )
            assert result.returncode == 3, result.stderr
            assert result.stdout.strip() == "claim_publication_lock_unavailable"
            # A distinct role is independent of this exclusion.
            with sdlc_claim.claim_role_exclusion("role-b", lock_root=root):
                pass
            raise RuntimeError("holder failure")
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
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

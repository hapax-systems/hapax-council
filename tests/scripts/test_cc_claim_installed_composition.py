"""Publication must use a validated installed lock namespace or preserve ownership."""

from pathlib import Path

import pytest

from shared.gate0b_claim_publication_install import (
    default_claim_publication_roots,
    install_claim_publication_composition,
)
from tests.scripts.test_cc_claim import _claim, _write_task
from tests.scripts.test_cc_claim_role_exclusion import _ownership_bytes
from tests.scripts.test_hapax_codex_headless import (
    _extract_remote_python,
    _remote_materialization_case,
)


@pytest.mark.parametrize(
    "writer,damage",
    [
        (writer, damage)
        for writer in ("admitted", "emergency", "remote")
        for damage in ("receipt-missing", "manifest-missing", "corrupt", "absent")
        # With nothing installed the admitted route installs on first use, and the emergency route
        # locks at the default roots (disclosed #4726 contract change; pinned positively by
        # test_emergency_without_any_installation_locks_the_default_role_namespace).
        if (writer, damage) not in {("admitted", "absent"), ("emergency", "absent")}
    ],
)
def test_writer_refuses_unqualified_installed_namespace(tmp_path, writer, damage):
    import subprocess
    import sys

    home = tmp_path / "home"
    roots = default_claim_publication_roots(home=home)
    if writer == "remote":
        env, home, files, proof, ran, *_ = _remote_materialization_case(
            tmp_path, install=False, existing="matching"
        )
    else:
        _write_task(home, "active", "namespace-test")
    if damage != "absent":
        install_claim_publication_composition(
            roots=roots, installed_at="2026-09-24T00:00:00Z", install_task_ref="test-install"
        )
        store = Path(roots.invocation_store_root)
        if damage == "receipt-missing":
            (store / "activation-receipt.json").unlink()
        elif damage == "manifest-missing":
            (store / "composition-manifest.json").unlink()
        else:
            (store / "activation-receipt.json").write_text("{}\n")
    before = _ownership_bytes(home)
    if writer == "remote":
        result = subprocess.run(
            [sys.executable, "-I", "-c", _extract_remote_python("REMOTE_EXEC_PY")],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert not proof.exists() and not ran.exists()
        assert {path: path.read_text() for path in files} == files
    else:
        result = _claim(home, "namespace-test", legacy=writer == "emergency", install_gate0b=False)
    assert result.returncode != 0, result.stdout
    assert _ownership_bytes(home) == before
    assert not Path(roots.claim_lock_root).exists()


@pytest.mark.parametrize("route", ["claim", "rehydrate"])
def test_claim_composition_invalid_gives_bounded_repair(tmp_path, route):
    import json

    home = tmp_path / "home"
    _write_task(home, "active", "invalid-composition")
    roots = default_claim_publication_roots(home=home)
    install_claim_publication_composition(
        roots=roots, installed_at="2026-09-24T00:00:00Z", install_task_ref="test-install"
    )
    manifest = Path(roots.invocation_store_root) / "composition-manifest.json"
    payload = json.loads(manifest.read_text())
    payload["schema_version"] = "malformed-sensitive-composition"
    manifest.write_text(json.dumps(payload))
    before = _ownership_bytes(home)
    extra_args = ["--rehydrate-activation-cache"] if route == "rehydrate" else []
    result = _claim(home, "invalid-composition", install_gate0b=False, extra_args=extra_args)
    assert result.returncode == 8
    assert "claim_composition_invalid" in result.stderr
    # The true cause is named (exception type, failing field, error type), never its value.
    assert "(ValidationError: schema_version " in result.stderr
    assert "Next action: restore the" in result.stderr
    assert "malformed-sensitive-composition" not in result.stderr
    assert _ownership_bytes(home) == before


def test_activation_cache_repair_uses_custom_installed_role_root(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from shared.sdlc_claim import claim_role_exclusion
    from tests.scripts import test_cc_claim as cli
    from tests.scripts.test_cc_claim_role_exclusion import _short_lock_timeout_cli

    home = tmp_path / "home"
    _write_task(home, "active", "rehydrate-lock-test")
    roots = default_claim_publication_roots(home=home).model_copy(
        update={"claim_lock_root": str(home / "installed-locks")}
    )
    install_claim_publication_composition(
        roots=roots, installed_at="2026-09-24T00:00:00Z", install_task_ref="test-install"
    )
    result = _claim(home, "rehydrate-lock-test", install_gate0b=False)
    assert result.returncode == 0, result.stderr
    for path in (home / ".cache/hapax").glob("cc-active-task-*"):
        path.unlink()
    before = _ownership_bytes(home)
    monkeypatch.setattr(cli, "SCRIPT", _short_lock_timeout_cli(tmp_path))
    with claim_role_exclusion("cx-test", lock_root=Path(roots.claim_lock_root)):
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(
                cli._claim,
                home,
                "rehydrate-lock-test",
                install_gate0b=False,
                extra_args=["--rehydrate-activation-cache"],
            ).result(timeout=10)
        assert result.returncode == 8
        assert "claim_publication_lock_unavailable" in result.stderr
        assert _ownership_bytes(home) == before
    retry = cli._claim(
        home,
        "rehydrate-lock-test",
        install_gate0b=False,
        extra_args=["--rehydrate-activation-cache"],
    )
    assert retry.returncode == 0, retry.stderr
    assert len(list((home / ".cache/hapax").glob("cc-active-task-*"))) == 2

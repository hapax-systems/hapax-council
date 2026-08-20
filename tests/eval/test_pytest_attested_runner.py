from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from eval.meas import driver_codex_cli as driver
from eval.meas import pytest_attested_runner as runner


def _trusted_runtime(tmp_path: Path) -> tuple[Path, Path, Path]:
    runtime = tmp_path / "runtime"
    pytest_origin = runtime / "lib/python3.12/site-packages/pytest/__init__.py"
    xdist_origin = runtime / "lib/python3.12/site-packages/xdist/__init__.py"
    pytest_origin.parent.mkdir(parents=True)
    xdist_origin.parent.mkdir(parents=True)
    pytest_origin.write_text("# trusted pytest marker\n", encoding="utf-8")
    xdist_origin.write_text("# trusted xdist marker\n", encoding="utf-8")
    return runtime, pytest_origin, xdist_origin


def _record(stderr: str) -> dict[str, Any]:
    lines = [
        line.removeprefix(runner.ATTESTATION_PREFIX)
        for line in stderr.splitlines()
        if line.startswith(runner.ATTESTATION_PREFIX)
    ]
    assert len(lines) == 1
    return json.loads(lines[0])


def test_pytest_origin_must_be_inside_pinned_runtime(tmp_path: Path) -> None:
    runtime, _pytest_origin, xdist_origin = _trusted_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    forged_origin = workspace / "pytest/__init__.py"
    forged_origin.parent.mkdir(parents=True)
    forged_origin.write_text("# forged pytest\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="pytest trust root mismatch"):
        runner._trusted_runtime_origins(
            runtime_prefix=runtime,
            pytest_origin=forged_origin,
            xdist_origin=xdist_origin,
            workspace=workspace,
        )


def test_runner_trust_failure_has_distinct_exit_and_no_record(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def reject() -> tuple[Path, Path, Path]:
        raise RuntimeError("pytest trust root mismatch")

    monkeypatch.setattr(runner, "_trusted_runtime_origins", reject)

    assert runner.run("tests/test_hidden.py") == runner.TRUST_FAILURE_EXIT_CODE
    captured = capsys.readouterr()
    assert "pytest trust root mismatch" in captured.err
    assert runner.ATTESTATION_PREFIX not in captured.err


def test_xdist_private_boundary_drift_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, pytest_origin, xdist_origin = _trusted_runtime(tmp_path)
    monkeypatch.setattr(
        runner,
        "_trusted_runtime_origins",
        lambda: (pytest_origin, xdist_origin, runtime),
    )
    monkeypatch.delattr(runner.xdist_workermanage, "_sys_path")

    assert runner.run("tests/test_hidden.py") == runner.TRUST_FAILURE_EXIT_CODE
    captured = capsys.readouterr()
    assert "worker setup API is incompatible" in captured.err
    assert "Next action:" in captured.err
    assert runner.ATTESTATION_PREFIX not in captured.err


def test_worker_runtime_introspection_guard_has_next_action() -> None:
    with pytest.raises(RuntimeError, match=r"Next action: remove pytest-runtime introspection"):
        runner._worker_audit_hook("sys._getframe", ())


def test_controller_only_conftest_flag_is_removed_from_worker_args(tmp_path: Path) -> None:
    original_params = runner.pytest.Config.InvocationParams(
        args=("tests/test_hidden.py", "--noconftest", "-q"),
        plugins=None,
        dir=tmp_path,
    )
    config = SimpleNamespace(invocation_params=original_params)
    observed: list[tuple[str, ...]] = []

    def original_setup(controller: Any) -> str:
        observed.append(controller.config.invocation_params.args)
        return "worker-started"

    setup = runner._worker_setup_with_conftests(original_setup)

    assert setup(SimpleNamespace(config=config)) == "worker-started"
    assert observed == [("tests/test_hidden.py", "-q")]
    assert config.invocation_params is original_params


@pytest.mark.parametrize(
    "args",
    [
        ("tests/test_hidden.py", "-q"),
        ("tests/test_hidden.py", "--noconftest", "--noconftest", "-q"),
    ],
)
def test_worker_conftest_invocation_drift_has_next_action(
    tmp_path: Path,
    args: tuple[str, ...],
) -> None:
    original_params = runner.pytest.Config.InvocationParams(
        args=args,
        plugins=None,
        dir=tmp_path,
    )
    config = SimpleNamespace(invocation_params=original_params)
    setup = runner._worker_setup_with_conftests(lambda _controller: None)

    with pytest.raises(RuntimeError, match=r"Next action: restore the locked pytest-xdist"):
        setup(SimpleNamespace(config=config))

    assert config.invocation_params is original_params


def test_zero_collection_record_is_emitted_but_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    runtime, pytest_origin, xdist_origin = _trusted_runtime(tmp_path)
    monkeypatch.setattr(
        runner,
        "_trusted_runtime_origins",
        lambda: (pytest_origin, xdist_origin, runtime),
    )
    monkeypatch.setattr(runner.pytest, "main", lambda *_args, **_kwargs: 5)

    process_returncode = runner.run("tests/test_hidden.py")
    captured = capfd.readouterr()
    record = _record(captured.err)

    assert process_returncode == 5
    assert record["collected"] == []
    logical_returncode, error = driver._parse_completion_attestation(
        captured.err,
        process_returncode=process_returncode,
        runtime_prefix=runtime,
    )
    assert logical_returncode is None
    assert "completed test lifecycle" in str(error)


def test_missing_terminal_report_is_emitted_but_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    runtime, pytest_origin, xdist_origin = _trusted_runtime(tmp_path)
    monkeypatch.setattr(
        runner,
        "_trusted_runtime_origins",
        lambda: (pytest_origin, xdist_origin, runtime),
    )

    def incomplete(_args: list[str], *, plugins: list[Any]) -> int:
        plugin = plugins[0]
        plugin.pytest_collection_finish(
            SimpleNamespace(
                items=[SimpleNamespace(nodeid="test_one"), SimpleNamespace(nodeid="test_two")]
            )
        )
        plugin.pytest_runtest_logreport(
            SimpleNamespace(nodeid="test_one", when="call", outcome="passed")
        )
        return 0

    monkeypatch.setattr(runner.pytest, "main", incomplete)

    process_returncode = runner.run("tests/test_hidden.py")
    captured = capfd.readouterr()
    record = _record(captured.err)

    assert record["terminal"] == {"test_one": "passed"}
    logical_returncode, error = driver._parse_completion_attestation(
        captured.err,
        process_returncode=process_returncode,
        runtime_prefix=runtime,
    )
    assert logical_returncode is None
    assert "completed test lifecycle" in str(error)


def test_predicate_command_has_no_writable_attestation_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def fake_sandbox(inner: list[str], *_args: Any, **kwargs: Any) -> list[str]:
        observed.update(kwargs)
        return inner

    monkeypatch.setattr(driver, "_cell_sandbox_command", fake_sandbox)
    command = driver._attested_pytest_command("tests/test_hidden.py", tmp_path, Path.cwd())

    assert "/attestation" not in command
    assert "writable_mounts" not in observed
    assert observed["workspace_writable"] is False


def test_committed_v1_witness_runs_published_v11_verifier(
    capsys: pytest.CaptureFixture[str],
) -> None:
    witness = (
        Path(__file__).parents[2] / "eval/meas/pilot_codex_cli_gpt_5_6_sol_easy_v1.witness.json"
    )

    assert driver.main(["--verify-result", str(witness)]) == 0
    verification = json.loads(capsys.readouterr().out)
    assert verification == {
        "lambda_hash": "e403ed3d49090dbb8fa4c8e58949b25516fdb488c37a822a9bb43fa73755e0c1",
        "passed": 11,
        "total": 19,
        "valid": True,
    }

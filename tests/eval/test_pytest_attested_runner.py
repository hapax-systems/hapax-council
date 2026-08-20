from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from eval.meas import driver_codex_cli as driver
from eval.meas import pytest_attested_runner as runner


def _trusted_runtime(tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "runtime"
    origin = runtime / "lib/python3.12/site-packages/pytest/__init__.py"
    origin.parent.mkdir(parents=True)
    origin.write_text("# trusted pytest marker\n", encoding="utf-8")
    return runtime, origin


def _record(stderr: str) -> dict[str, Any]:
    lines = [
        line.removeprefix(runner.ATTESTATION_PREFIX)
        for line in stderr.splitlines()
        if line.startswith(runner.ATTESTATION_PREFIX)
    ]
    assert len(lines) == 1
    return json.loads(lines[0])


def test_pytest_origin_must_be_inside_pinned_runtime(tmp_path: Path) -> None:
    runtime, _origin = _trusted_runtime(tmp_path)
    workspace = tmp_path / "workspace"
    forged_origin = workspace / "pytest/__init__.py"
    forged_origin.parent.mkdir(parents=True)
    forged_origin.write_text("# forged pytest\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="pytest trust root mismatch"):
        runner._trusted_pytest_origin(
            runtime_prefix=runtime,
            pytest_origin=forged_origin,
            workspace=workspace,
        )


def test_runner_trust_failure_has_distinct_exit_and_no_record(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def reject() -> tuple[Path, Path]:
        raise RuntimeError("pytest trust root mismatch")

    monkeypatch.setattr(runner, "_trusted_pytest_origin", reject)

    assert runner.run("tests/test_hidden.py") == runner.TRUST_FAILURE_EXIT_CODE
    captured = capsys.readouterr()
    assert "pytest trust root mismatch" in captured.err
    assert runner.ATTESTATION_PREFIX not in captured.err


def test_zero_collection_record_is_emitted_but_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, origin = _trusted_runtime(tmp_path)
    monkeypatch.setattr(runner, "_trusted_pytest_origin", lambda: (origin, runtime))
    monkeypatch.setattr(runner.pytest, "main", lambda *_args, **_kwargs: 5)

    process_returncode = runner.run("tests/test_hidden.py")
    captured = capsys.readouterr()
    record = _record(captured.err)

    assert process_returncode == runner.COMPLETION_EXIT_BASE + 5
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
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, origin = _trusted_runtime(tmp_path)
    monkeypatch.setattr(runner, "_trusted_pytest_origin", lambda: (origin, runtime))

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
    captured = capsys.readouterr()
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


def test_committed_v1_witness_runs_published_v6_verifier(
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

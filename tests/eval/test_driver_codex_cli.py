from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from eval.meas import driver_codex_cli as driver


def _bubblewrap_usable() -> bool:
    binary = shutil.which("bwrap")
    if not binary:
        return False
    try:
        result = subprocess.run(
            [
                binary,
                "--unshare-all",
                "--unshare-user",
                "--disable-userns",
                "--new-session",
                "--ro-bind",
                "/",
                "/",
                "--",
                "/usr/bin/true",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


requires_bubblewrap = pytest.mark.skipif(
    not _bubblewrap_usable(),
    reason="Bubblewrap user namespaces are unavailable on this test host",
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "--all")
    _git(
        repo,
        "-c",
        "user.name=MEAS Test",
        "-c",
        "user.email=meas@example.invalid",
        "commit",
        "--quiet",
        "-m",
        message,
    )
    return _git(repo, "rev-parse", "HEAD")


def _source_repo(tmp_path: Path) -> tuple[Path, driver.CommitPair]:
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    (repo / "module.py").write_text("VALUE = 0\n", encoding="utf-8")
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_module.py").write_text(
        "from module import VALUE\n\ndef test_value():\n    assert VALUE == 0\n",
        encoding="utf-8",
    )
    (repo / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npythonpath = ["."]\n', encoding="utf-8"
    )
    parent = _commit(repo, "parent")
    (repo / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tests / "test_module.py").write_text(
        "from module import VALUE\n\ndef test_value():\n    assert VALUE == 1\n",
        encoding="utf-8",
    )
    merge = _commit(repo, "merge")
    return repo, driver.CommitPair(parent=parent, merge=merge)


def _task() -> dict[str, Any]:
    return {
        "task_id": "cell-1",
        "class": "build",
        "difficulty": "easy",
        "pr": 1,
        "work_item": "Set VALUE to one.",
        "exit_predicate": {"kind": "pytest", "target": "tests/test_module.py"},
    }


def test_lambda_hash_is_deterministic_and_covers_context_mode() -> None:
    config = driver.CodexRunConfig()
    fields = driver.lambda_config(config, "codex-cli test", "bubblewrap test")
    first = driver.lambda_hash(fields)
    assert first == driver.lambda_hash(fields)
    changed = dict(fields, context_mode="different")
    assert driver.lambda_hash(changed) != first
    assert len(first) == 64


def test_command_uses_current_workspace_write_surface() -> None:
    command = driver.build_codex_command(driver.CodexRunConfig(), Path("/cell"))
    assert command[:2] == ["codex", "exec"]
    assert command[-3:-1] == ["--sandbox", "workspace-write"]
    assert "--full-auto" not in command
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert command[-1] == "-"


def test_removed_legacy_full_auto_flag_is_rejected() -> None:
    with pytest.raises(SystemExit):
        driver._parser().parse_args(["--legacy-full-auto"])


def test_lambda_records_both_timeouts_and_predicate_sandbox() -> None:
    config = driver.CodexRunConfig(timeout_seconds=321)
    surface = driver.lambda_config(config, "codex-cli test", "bubblewrap 1.2")[
        "tool_surface_config"
    ]
    assert surface["codex_timeout_seconds"] == 321
    assert surface["exit_predicate"] == {
        "environment": "cleared",
        "network": "unshared",
        "sandbox": "bubblewrap",
        "sandbox_version": "bubblewrap 1.2",
        "timeout_seconds": driver.PREDICATE_TIMEOUT_SECONDS,
    }
    assert surface["post_agent_git"]["sandbox"] == "bubblewrap"
    assert surface["scoring_diff_excludes"] == list(driver.SCORING_DIFF_EXCLUDES)


def test_prepare_checkout_excludes_post_parent_history(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)
    cell = tmp_path / "cell"
    driver.prepare_cell_checkout(repo, commits.parent, cell)
    assert _git(cell, "rev-parse", "HEAD") == commits.parent
    result = subprocess.run(
        ["git", "-C", str(cell), "cat-file", "-e", f"{commits.merge}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0


def test_merge_test_install_rejects_symlinked_parent(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)
    cell = tmp_path / "cell"
    driver.prepare_cell_checkout(repo, commits.parent, cell)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "test_module.py"
    sentinel.write_text("outside stays unchanged\n", encoding="utf-8")
    shutil.rmtree(cell / "tests")
    (cell / "tests").symlink_to(outside, target_is_directory=True)

    with pytest.raises(driver.DriverError, match="unsafe merge-version test parent"):
        driver.install_merge_version_tests(repo, cell, commits)

    assert sentinel.read_text(encoding="utf-8") == "outside stays unchanged\n"


def test_merge_test_install_rejects_symlinked_destination(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)
    cell = tmp_path / "cell"
    driver.prepare_cell_checkout(repo, commits.parent, cell)
    outside = tmp_path / "outside.py"
    outside.write_text("outside stays unchanged\n", encoding="utf-8")
    destination = cell / "tests/test_module.py"
    destination.unlink()
    destination.symlink_to(outside)

    with pytest.raises(driver.DriverError, match="unsafe merge-version test destination"):
        driver.install_merge_version_tests(repo, cell, commits)

    assert outside.read_text(encoding="utf-8") == "outside stays unchanged\n"


def test_merge_test_install_rejects_hardlinked_destination(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)
    cell = tmp_path / "cell"
    driver.prepare_cell_checkout(repo, commits.parent, cell)
    outside = tmp_path / "outside.py"
    outside.write_text("outside stays unchanged\n", encoding="utf-8")
    destination = cell / "tests/test_module.py"
    destination.unlink()
    os.link(outside, destination)

    with pytest.raises(driver.DriverError, match="unsafe merge-version test destination"):
        driver.install_merge_version_tests(repo, cell, commits)

    assert outside.read_text(encoding="utf-8") == "outside stays unchanged\n"


@requires_bubblewrap
def test_exit_predicate_isolated_from_environment_and_host_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cell = tmp_path / "cell"
    cell.mkdir()
    outside = tmp_path / "outside-secret"
    outside.write_text("not visible\n", encoding="utf-8")
    monkeypatch.setenv("MEAS_SANDBOX_SECRET", "must-not-leak")
    task = {
        **_task(),
        "exit_predicate": {
            "kind": "ruff+custom",
            "target": (
                'test -z "${MEAS_SANDBOX_SECRET:-}" '
                f"&& test ! -e {outside} && printf sandboxed > marker"
            ),
        },
    }

    result = driver.evaluate_exit(task, cell, Path.cwd())

    assert result["passed"] is True
    assert result["sandbox"] == "bubblewrap"
    assert (cell / "marker").read_text(encoding="utf-8") == "sandboxed"
    assert outside.read_text(encoding="utf-8") == "not visible\n"


@requires_bubblewrap
def test_sandboxed_pytest_predicate_uses_read_only_uv_environment(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)
    cell = tmp_path / "cell"
    driver.prepare_cell_checkout(repo, commits.parent, cell)
    (cell / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    driver.install_merge_version_tests(repo, cell, commits)

    result = driver.evaluate_exit(_task(), cell, repo)

    assert result["passed"] is True
    assert result["returncode"] == 0
    assert "1 passed" in result["output_tail"]


@requires_bubblewrap
def test_exit_predicate_timeout_preserves_bytes_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("bwrap", 600, output=b"partial stdout\n")

    monkeypatch.setattr(driver.subprocess, "run", timeout)
    result = driver.evaluate_exit(
        {**_task(), "exit_predicate": {"kind": "ruff+custom", "target": "true"}},
        tmp_path,
        Path.cwd(),
    )
    assert result["passed"] is False
    assert result["returncode"] == 124
    assert result["timed_out"] is True
    assert "partial stdout" in result["output_tail"]


@requires_bubblewrap
def test_driver_captures_mocked_exec_transcript_and_diff(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)
    cell = tmp_path / "cell"
    driver.prepare_cell_checkout(repo, commits.parent, cell)
    observed: dict[str, Any] = {}

    def fake_codex(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed["input"] = kwargs["input"]
        observed["env"] = kwargs["env"]
        (Path(kwargs["cwd"]) / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")

    outcome = driver.driver(
        task=_task(),
        workdir=cell,
        config=driver.CodexRunConfig(),
        process_runner=fake_codex,
    )
    assert outcome["transcript"]["returncode"] == 0
    assert outcome["transcript"]["stdout"] == '{"type":"turn.completed"}\n'
    assert "-VALUE = 0" in outcome["diff"]
    assert "+VALUE = 1" in outcome["diff"]
    assert outcome["diff_sha256"] == hashlib.sha256(outcome["diff"].encode()).hexdigest()
    assert "OPENAI_API_KEY" not in observed["env"]
    assert observed["env"]["UV_NO_SYNC"] == "1"
    assert observed["env"]["VIRTUAL_ENV"] == observed["env"]["UV_PROJECT_ENVIRONMENT"]
    assert "Fix the implementation, not the tests" in observed["input"]


@requires_bubblewrap
def test_driver_timeout_preserves_partial_bytes(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)
    cell = tmp_path / "cell"
    driver.prepare_cell_checkout(repo, commits.parent, cell)

    def timeout(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            command,
            1,
            output=b'{"type":"partial"}\n',
            stderr=b"deadline\n",
        )

    outcome = driver.driver(
        task=_task(),
        workdir=cell,
        config=driver.CodexRunConfig(timeout_seconds=1),
        process_runner=timeout,
    )
    assert outcome["transcript"]["returncode"] == 124
    assert outcome["transcript"]["timed_out"] is True
    assert outcome["transcript"]["stdout"] == '{"type":"partial"}\n'
    assert outcome["transcript"]["stderr"] == "deadline\n"


@requires_bubblewrap
def test_post_agent_git_disables_model_controlled_executables(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)
    cell = tmp_path / "cell"
    driver.prepare_cell_checkout(repo, commits.parent, cell)
    probe = cell / "model-git-probe.sh"
    probe.write_text("#!/bin/sh\ntouch model-git-executed\nexit 0\n", encoding="utf-8")
    probe.chmod(0o755)
    _git(cell, "config", "core.fsmonitor", "./model-git-probe.sh")
    _git(cell, "config", "diff.external", "./model-git-probe.sh")
    (cell / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

    record = driver.capture_cell_diff(cell, commits.parent)

    assert "+VALUE = 1" in record["diff"]
    assert not (cell / "model-git-executed").exists()


@requires_bubblewrap
def test_run_cell_installs_merge_tests_after_executor(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)
    saw_parent_test = False

    def fake_executor(
        task: driver.Mapping[str, Any],
        workdir: Path,
        config: driver.CodexRunConfig,
    ) -> dict[str, Any]:
        nonlocal saw_parent_test
        saw_parent_test = "VALUE == 0" in (workdir / "tests/test_module.py").read_text()
        (workdir / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        diff_record = driver.capture_cell_diff(workdir, commits.parent)
        return {
            "model": config.model,
            "harness": driver.HARNESS_NAME,
            "seconds": 0.1,
            "wh_milli": None,
            "transcript_ref": None,
            "transcript": {"returncode": 0, "stdout": "{}\n", "stderr": ""},
            **diff_record,
        }

    def fake_evaluator(
        task: driver.Mapping[str, Any],
        workdir: Path,
        source_repo: Path,
    ) -> dict[str, Any]:
        assert source_repo == repo
        assert "VALUE == 1" in (workdir / "tests/test_module.py").read_text()
        assert (workdir / "module.py").read_text() == "VALUE = 1\n"
        return {"passed": True, "returncode": 0, "output_tail": "1 passed"}

    record = driver.run_cell(
        _task(),
        repo=repo,
        commits=commits,
        executor=fake_executor,
        evaluator=fake_evaluator,
        binary_version="codex-cli test",
        sandbox_version="bubblewrap test",
    )
    assert saw_parent_test is True
    assert record["cell_result"]["passed"] is True
    assert record["cell_result"]["predicate_files"] == ["tests/test_module.py"]
    assert record["lambda_hash"] == driver.lambda_hash(record["lambda_config"])
    assert record["cell"]["transcript"]["stdout"] == "{}\n"


@requires_bubblewrap
def test_run_cell_excludes_model_controlled_pytest_hooks_from_scoring(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)

    def adversarial_executor(
        task: driver.Mapping[str, Any],
        workdir: Path,
        config: driver.CodexRunConfig,
    ) -> dict[str, Any]:
        (workdir / "conftest.py").write_text(
            "def pytest_sessionfinish(session):\n    session.exitstatus = 0\n",
            encoding="utf-8",
        )
        (workdir / "tests/test_module.py").write_text(
            "def test_forged():\n    assert True\n", encoding="utf-8"
        )
        diff_record = driver.capture_cell_diff(workdir, commits.parent)
        return {
            "model": config.model,
            "harness": driver.HARNESS_NAME,
            "seconds": 0.1,
            "transcript": {"returncode": 0, "timed_out": False},
            **diff_record,
        }

    record = driver.run_cell(
        _task(),
        repo=repo,
        commits=commits,
        executor=adversarial_executor,
        binary_version="codex-cli test",
        sandbox_version="bubblewrap test",
    )

    assert record["cell_result"]["passed"] is False
    assert record["cell_result"]["exit"]["returncode"] == 1
    assert "conftest.py" in record["cell"]["diff"]
    assert "conftest.py" in record["cell_result"]["scoring_diff_excludes"]


def test_run_cell_cannot_pass_after_codex_timeout(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)

    def timed_out_executor(
        task: driver.Mapping[str, Any],
        workdir: Path,
        config: driver.CodexRunConfig,
    ) -> dict[str, Any]:
        return {
            "model": config.model,
            "harness": driver.HARNESS_NAME,
            "seconds": 1.0,
            "transcript": {"returncode": 124, "timed_out": True},
            "diff": "",
            "diff_bytes": 0,
            "diff_sha256": hashlib.sha256(b"").hexdigest(),
            "git_status": [],
        }

    record = driver.run_cell(
        _task(),
        repo=repo,
        commits=commits,
        executor=timed_out_executor,
        evaluator=lambda _task, _workdir, _repo: {
            "passed": True,
            "returncode": 0,
            "output_tail": "passed",
        },
        binary_version="codex-cli test",
        sandbox_version="bubblewrap test",
    )
    assert record["cell_result"]["passed"] is False
    assert record["cell_result"]["codex_timed_out"] is True


def test_dry_run_validates_task_and_merge_predicate(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)
    result = driver.dry_run_validate(
        [_task()],
        repo=repo,
        resolver=lambda _task, _repo: commits,
    )
    assert result["valid"] == 1
    assert result["total"] == 1
    assert result["cells"][0]["errors"] == []


def test_result_note_names_measured_baseline() -> None:
    payload = {
        "completed_at": "2026-08-20T00:00:00Z",
        "model": "gpt-5.6-sol",
        "lambda_set": ["a" * 64],
        "lambda_config": {"tool_surface_config": {"sandbox": "recorded-sandbox"}},
        "summary": {"passed": 7, "total": 19, "pass_rate": 7 / 19},
    }
    note = driver.render_result_note(payload)
    assert "7/19 (36.8%)" in note
    assert "0/19 (0.0%)" in note
    assert "provider-managed" in note
    assert "`recorded-sandbox` sandbox" in note


def test_partial_result_note_does_not_claim_baseline_comparison() -> None:
    payload = {
        "completed_at": "2026-08-20T00:00:00Z",
        "model": "gpt-5.6-sol",
        "lambda_set": ["a" * 64],
        "summary": driver._summary([{"cell_result": {"passed": True}} for _index in range(3)]),
    }
    note = driver.render_result_note(payload)
    assert "not directly comparable" in note
    assert "versus 0 of 19" not in note
    assert "--verify-result pilot-result.json" in note


def test_current_result_note_names_clean_scoring_boundary() -> None:
    payload = {
        "updated_at": "2026-08-20T00:00:00Z",
        "model": "gpt-5.6-sol",
        "lambda_set": ["b" * 64],
        "lambda_config": {
            "tool_surface_config": {
                "sandbox": "workspace-write",
                "exit_predicate": {"sandbox": "bubblewrap"},
                "scoring_diff_excludes": ["tests/**"],
            }
        },
        "summary": driver._summary([]),
    }
    note = driver.render_result_note(payload)
    assert "clean scoring checkouts" in note
    assert "post-exec diff inside Bubblewrap" in note


def _pilot_cell_runner(**kwargs: Any) -> dict[str, Any]:
    task = kwargs["task"] if "task" in kwargs else kwargs.get("task")
    config = kwargs["config"]
    commits = kwargs["commits"]
    fields = driver.lambda_config(
        config,
        kwargs["binary_version"],
        kwargs["sandbox_version"],
    )
    return {
        "lambda_hash": driver.lambda_hash(fields),
        "lambda_config": fields,
        "task_id": task["task_id"],
        "cell": {
            "model": config.model,
            "harness": driver.HARNESS_NAME,
            "seconds": 0.1,
            "transcript": {"returncode": 0, "timed_out": False},
            "diff": "",
            "diff_bytes": 0,
            "diff_sha256": hashlib.sha256(b"").hexdigest(),
        },
        "cell_result": {
            "class": task["class"],
            "difficulty": task["difficulty"],
            "pr": task["pr"],
            "parent": commits.parent,
            "merge": commits.merge,
            "predicate_files": ["tests/test_module.py"],
            "passed": True,
            "exit": {"passed": True, "returncode": 0},
            "codex_returncode": 0,
            "codex_timed_out": False,
            "git_status": [],
        },
    }


def test_run_pilot_checkpoints_atomically_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(driver, "codex_binary_version", lambda _config: "codex-cli test")
    monkeypatch.setattr(driver, "predicate_sandbox_version", lambda: "bubblewrap test")
    commits = driver.CommitPair(parent="1" * 40, merge="2" * 40)
    tasks = [_task(), {**_task(), "task_id": "cell-2", "pr": 2}]
    output = tmp_path / "pilot.json"
    calls = 0

    def interrupted_runner(task: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated interruption")
        return _pilot_cell_runner(task=task, **kwargs)

    with pytest.raises(RuntimeError, match="simulated interruption"):
        driver.run_pilot(
            tasks,
            repo=tmp_path,
            config=driver.CodexRunConfig(),
            output_path=output,
            resolver=lambda _task, _repo: commits,
            cell_runner=interrupted_runner,
        )
    checkpoint = json.loads(output.read_text(encoding="utf-8"))
    assert checkpoint["completed_at"] is None
    assert [result["task_id"] for result in checkpoint["results"]] == ["cell-1"]

    payload = driver.run_pilot(
        tasks,
        repo=tmp_path,
        config=driver.CodexRunConfig(),
        output_path=output,
        resolver=lambda _task, _repo: commits,
        cell_runner=lambda task, **kwargs: _pilot_cell_runner(task=task, **kwargs),
    )
    assert payload["schema_version"] == 2
    assert payload["summary"]["passed"] == 2
    assert [result["task_id"] for result in payload["results"]] == ["cell-1", "cell-2"]
    assert driver.verify_result_payload(payload)["valid"] is True


def test_run_pilot_rejects_incompatible_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(driver, "codex_binary_version", lambda _config: "codex-cli test")
    monkeypatch.setattr(driver, "predicate_sandbox_version", lambda: "bubblewrap test")
    commits = driver.CommitPair(parent="1" * 40, merge="2" * 40)
    output = tmp_path / "pilot.json"
    driver.run_pilot(
        [_task()],
        repo=tmp_path,
        config=driver.CodexRunConfig(),
        output_path=output,
        resolver=lambda _task, _repo: commits,
        cell_runner=lambda task, **kwargs: _pilot_cell_runner(task=task, **kwargs),
    )

    changed_task = {**_task(), "work_item": "A different task contract."}
    with pytest.raises(driver.DriverError, match="selection does not match"):
        driver.run_pilot(
            [changed_task],
            repo=tmp_path,
            config=driver.CodexRunConfig(),
            output_path=output,
            resolver=lambda _task, _repo: commits,
            cell_runner=lambda task, **kwargs: _pilot_cell_runner(task=task, **kwargs),
        )


def test_committed_pilot_witness_rechecks_11_of_19() -> None:
    witness_path = (
        Path(__file__).parents[2] / "eval/meas/pilot_codex_cli_gpt_5_6_sol_easy_v1.witness.json"
    )
    witness = json.loads(witness_path.read_text(encoding="utf-8"))
    verification = driver.verify_result_payload(witness)
    assert verification == {
        "valid": True,
        "lambda_hash": "e403ed3d49090dbb8fa4c8e58949b25516fdb488c37a822a9bb43fa73755e0c1",
        "passed": 11,
        "total": 19,
    }
    assert witness["witness"]["source_result_sha256"] == (
        "1991e186b3699fa87667ac09963ef542ac3587dadc5b7e31be49afa3a9c2f03c"
    )
    assert len(witness["selection"]["task_ids"]) == 19
    assert [task["task_id"] for task in witness["tasks"]] == witness["selection"]["task_ids"]
    assert "cell.transcript.stdout" in witness["witness"]["redactions"]


def test_load_tasks_rejects_non_object_rows(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(json.dumps(["not", "an", "object"]) + "\n", encoding="utf-8")
    with pytest.raises(driver.DriverError, match="not an object"):
        driver.load_tasks(tasks)


def test_load_tasks_missing_path_has_next_action(tmp_path: Path) -> None:
    with pytest.raises(driver.DriverError, match=r"Next action: pass --tasks"):
        driver.load_tasks(tmp_path / "missing.jsonl")

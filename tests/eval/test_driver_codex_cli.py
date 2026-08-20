from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from eval.meas import driver_codex_cli as driver


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
    fields = driver.lambda_config(config, "codex-cli test")
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


def test_legacy_full_auto_is_explicit_and_lambda_visible() -> None:
    config = driver.CodexRunConfig(legacy_full_auto=True)
    command = driver.build_codex_command(config, Path("/cell"))
    assert "--full-auto" in command
    assert "--sandbox" not in command
    assert (
        driver.lambda_config(config, "codex-cli test")["tool_surface_config"]["legacy_full_auto"]
        is True
    )


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
        diff = "module diff"
        return {
            "model": config.model,
            "harness": driver.HARNESS_NAME,
            "seconds": 0.1,
            "wh_milli": None,
            "transcript_ref": None,
            "transcript": {"returncode": 0, "stdout": "{}\n", "stderr": ""},
            "diff": diff,
            "diff_bytes": len(diff),
            "diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
            "git_status": [" M module.py"],
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
    )
    assert saw_parent_test is True
    assert record["cell_result"]["passed"] is True
    assert record["cell_result"]["predicate_files"] == ["tests/test_module.py"]
    assert record["lambda_hash"] == driver.lambda_hash(record["lambda_config"])
    assert record["cell"]["transcript"]["stdout"] == "{}\n"


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
        "summary": {"passed": 7, "total": 19, "pass_rate": 7 / 19},
    }
    note = driver.render_result_note(payload)
    assert "7/19 (36.8%)" in note
    assert "0/19 (0.0%)" in note
    assert "provider-managed" in note


def test_load_tasks_rejects_non_object_rows(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(json.dumps(["not", "an", "object"]) + "\n", encoding="utf-8")
    with pytest.raises(driver.DriverError, match="not an object"):
        driver.load_tasks(tasks)

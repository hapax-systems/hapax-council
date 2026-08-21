from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from eval.meas import driver_codex_cli as driver
from eval.meas import pytest_attested_runner as attested_runner


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
requires_codex = pytest.mark.skipif(
    shutil.which("codex") is None,
    reason="Codex CLI is unavailable on this test host",
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


def _source_repo(
    tmp_path: Path,
    *,
    parent_conftest: str | None = None,
) -> tuple[Path, driver.CommitPair]:
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
    if parent_conftest is not None:
        (repo / "conftest.py").write_text(parent_conftest, encoding="utf-8")
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


def _fake_codex_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> driver.CodexRunConfig:
    binary = tmp_path / "fake-codex"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    return driver.CodexRunConfig(codex_binary=str(binary))


def test_lambda_hash_is_deterministic_and_covers_context_mode() -> None:
    config = driver.CodexRunConfig()
    fields = driver.lambda_config(config, "codex-cli test", "bubblewrap test")
    first = driver.lambda_hash(fields)
    assert first == driver.lambda_hash(fields)
    changed = dict(fields, context_mode="different")
    assert driver.lambda_hash(changed) != first
    assert len(first) == 64


def test_command_uses_permission_profile_workspace_write_surface() -> None:
    command = driver.build_codex_command(
        driver.CodexRunConfig(),
        Path("/cell"),
        permission_read_paths=[Path("/pinned-runtime")],
    )
    assert command[:2] == ["codex", "exec"]
    assert "--sandbox" not in command
    assert "--full-auto" not in command
    assert "--strict-config" in command
    assert "--ephemeral" in command
    assert "--ignore-user-config" not in command
    permission_override = next(
        value for value in command if value.startswith("permissions.meas-cell.filesystem=")
    )
    assert '"/codex-home"="deny"' in permission_override
    assert '"/pinned-runtime"="read"' in permission_override
    assert '":workspace_roots"={"."="write"}' in permission_override
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
        "completion_attestation": "trusted-pytest-lifecycle-v4",
        "completion_boundary": "xdist-controller+single-stderr-record",
        "confcutdir": "/workspace",
        "config": "/dev/null",
        "controller_conftest": "disabled",
        "custom_pytest": "removed-from-shell-and-run-only-through-attested-worker",
        "environment": "cleared",
        "network": "unshared",
        "plugin_autoload": "disabled",
        "pytest_cacheprovider": "disabled",
        "pytest_execution": "one-isolated-xdist-worker",
        "pytest_worker_integrity": (
            "early-runtime-introspection-and-hook-mutation-audit+"
            "collection-plugin-registration-freeze+sealed-call-capture+raw-worker-outcomes/v5"
        ),
        "pytest_worker_launcher_sha256": driver.pytest_worker_launcher_sha256(),
        "pytest_xdist_version": driver.pytest_xdist_version(),
        "rootdir": "/workspace",
        "runner_sha256": driver.attested_runner_sha256(),
        "sandbox": "bubblewrap",
        "sandbox_version": "bubblewrap 1.2",
        "scoring_controls_postcheck": "byte-for-byte",
        "timeout_seconds": driver.PREDICATE_TIMEOUT_SECONDS,
        "worker_conftest": "trusted-scoring-controls-enabled",
        "workspace": "read-only",
    }
    assert surface["agent_filesystem"] == {
        "credential_enforcement": "codex-permission-profile+pinned-harness-binary",
        "credential_enforcement_binary": "codex-cli test",
        "credential_path": "denied-to-model-tools-by-codex-permission-profile",
        "host_reads": "cell-and-explicit-runtime-mounts-only",
        "network": "shared-for-provider-api",
        "outer_sandbox": "bubblewrap",
        "permission_profile": "meas-cell",
        "permission_profile_sha256": driver.codex_cell_config_sha256(),
        "sandbox_version": "bubblewrap 1.2",
        "system_roots": "asserted-no-source-repo-install-links",
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


def test_system_package_control_cannot_expose_source_repo(tmp_path: Path) -> None:
    repo = tmp_path / "source"
    repo.mkdir()
    system_root = tmp_path / "usr"
    site_packages = system_root / "lib/python3.12/site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "editable.pth").write_text(f"{repo}\n", encoding="utf-8")

    with pytest.raises(driver.DriverError, match="system package control exposes"):
        driver._assert_repo_not_installed_in_system_roots(repo, [system_root])


@requires_bubblewrap
def test_exit_predicate_isolated_from_environment_and_host_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cell = tmp_path / "cell"
    cell.mkdir()
    (cell / "marker").write_text("sandboxed", encoding="utf-8")
    outside = tmp_path / "outside-secret"
    outside.write_text("not visible\n", encoding="utf-8")
    monkeypatch.setenv("MEAS_SANDBOX_SECRET", "must-not-leak")
    task = {
        **_task(),
        "exit_predicate": {
            "kind": "ruff+custom",
            "target": (
                'test -z "${MEAS_SANDBOX_SECRET:-}" '
                f'&& test ! -e {outside} && test "$(cat marker)" = sandboxed'
            ),
        },
    }

    result = driver.evaluate_exit(task, cell, Path.cwd())

    assert result["passed"] is True
    assert result["sandbox"] == "bubblewrap"
    assert (cell / "marker").read_text(encoding="utf-8") == "sandboxed"
    assert outside.read_text(encoding="utf-8") == "not visible\n"


@pytest.mark.parametrize(
    ("predicate", "expected"),
    [
        ({"kind": "pytest", "target": "tests/test_one.py"}, ["tests/test_one.py"]),
        (
            {
                "kind": "ruff+custom",
                "target": (
                    "uv run ruff check shared/example.py "
                    "&& uv run pytest tests/test_one.py "
                    "&& pytest tests/test_two.py::test_case"
                ),
            },
            ["tests/test_one.py", "tests/test_two.py::test_case"],
        ),
        ({"kind": "ruff+custom", "target": "uv run ruff check shared/example.py"}, []),
        ({"kind": "unknown", "target": "tests/test_one.py"}, []),
        ({"kind": "pytest", "target": None}, []),
    ],
)
def test_pytest_targets(predicate: dict[str, Any], expected: list[str]) -> None:
    assert driver._pytest_targets({"exit_predicate": predicate}) == expected


def test_pytest_targets_rejects_malformed_predicate() -> None:
    assert driver._pytest_targets({"exit_predicate": "pytest tests/test_one.py"}) == []


def test_custom_predicate_removes_embedded_pytest_clause() -> None:
    task = {
        **_task(),
        "exit_predicate": {
            "kind": "ruff+custom",
            "target": ("uv run ruff check shared/example.py && uv run pytest tests/test_one.py -q"),
        },
    }

    assert driver._non_pytest_custom_predicate_command(task) == [
        "bash",
        "-lc",
        "uv run ruff check shared/example.py",
    ]


def test_custom_predicate_sandbox_never_runs_embedded_pytest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = {
        **_task(),
        "exit_predicate": {
            "kind": "ruff+custom",
            "target": ("uv run ruff check shared/example.py && uv run pytest tests/test_one.py -q"),
        },
    }

    def passthrough(inner: list[str], *_args: Any, **_kwargs: Any) -> list[str]:
        return inner

    monkeypatch.setattr(driver, "_cell_sandbox_command", passthrough)

    assert driver._predicate_sandbox_command(task, tmp_path, tmp_path) == [
        "bash",
        "-lc",
        "uv run ruff check shared/example.py",
    ]


def test_isolated_worker_launcher_missing_environment_has_next_action() -> None:
    result = subprocess.run(
        [str(driver.PYTEST_WORKER_LAUNCHER)],
        capture_output=True,
        text=True,
        env={},
        check=False,
    )

    assert result.returncode == 87
    assert "pinned project environment is missing" in result.stderr
    assert "Next action:" in result.stderr


def test_isolated_worker_launcher_rejects_unknown_invocation() -> None:
    result = subprocess.run(
        [str(driver.PYTEST_WORKER_LAUNCHER), "--wrong", "-c", "pass"],
        capture_output=True,
        text=True,
        env={"VIRTUAL_ENV": str(driver._active_project_environment())},
        check=False,
    )

    assert result.returncode == 87
    assert "unsupported xdist worker invocation" in result.stderr
    assert "Next action:" in result.stderr


def test_isolated_worker_launcher_uses_isolated_harness_path() -> None:
    result = subprocess.run(
        [
            str(driver.PYTEST_WORKER_LAUNCHER),
            "-u",
            "-c",
            "print(sys.flags.isolated); print(sys.path[0])",
        ],
        capture_output=True,
        text=True,
        env={"VIRTUAL_ENV": str(driver._active_project_environment())},
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["1", "/harness"]


def test_worker_launcher_harness_path_matches_driver_mount_contract() -> None:
    launcher = driver.PYTEST_WORKER_LAUNCHER.read_text(encoding="utf-8")
    harness_root = str(driver.PYTEST_HARNESS_ROOT)

    assert f"sys.path.insert(0,'{harness_root}')" in launcher
    assert Path("/harness/pytest_attested_runner.py") == (
        driver.PYTEST_HARNESS_ROOT / "pytest_attested_runner.py"
    )
    assert Path("/harness/python-isolated") == driver.PYTEST_HARNESS_ROOT / "python-isolated"


@requires_bubblewrap
def test_agent_boundary_denies_reads_outside_cell_while_sharing_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cell = tmp_path / "cell"
    cell.mkdir()
    (cell / "visible").write_text("cell only\n", encoding="utf-8")
    outside = tmp_path / "held-out-solution"
    outside.write_text("must remain invisible\n", encoding="utf-8")
    fake_codex = tmp_path / "fake-codex"
    fake_codex.write_text(
        f"#!/bin/sh\ntest -r /workspace/visible\ntest ! -e {outside}\n",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    command = driver._agent_sandbox_command(
        driver.CodexRunConfig(codex_binary=str(fake_codex)),
        cell,
        Path.cwd(),
    )

    result = subprocess.run(
        command,
        input="measurement prompt\n",
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--share-net" in command
    assert "--disable-userns" not in command
    assert outside.read_text(encoding="utf-8") == "must remain invisible\n"


@requires_bubblewrap
@requires_codex
def test_codex_permission_profile_denies_credentials_and_preserves_pinned_runtime(
    tmp_path: Path,
) -> None:
    cell = tmp_path / "cell"
    cell.mkdir()
    (cell / "visible").write_text("cell only\n", encoding="utf-8")
    config = driver.CodexRunConfig()
    runtime_source, runtime_destination, executable = driver._codex_runtime_mount(config)
    fake_auth = tmp_path / "auth.json"
    fake_auth.write_text("{}\n", encoding="utf-8")
    permission_read_paths = driver._project_environment_read_paths(Path.cwd())
    inner_command = [
        executable,
        "-c",
        driver._permission_filesystem_override(permission_read_paths),
        "sandbox",
        "-P",
        "meas-cell",
        "-C",
        "/workspace",
        "--",
        "bash",
        "-lc",
        (
            "test -r /workspace/visible "
            "&& test ! -r /codex-home/auth.json "
            "&& printf writable > /workspace/model-write "
            "&& uv run --no-sync python -c 'import sys; print(sys.prefix)' "
            "> /workspace/python-prefix"
        ),
    ]
    command = driver._agent_boundary_command(
        inner_command,
        cell,
        Path.cwd(),
        extra_environment={
            "CODEX_HOME": "/codex-home",
            "CODEX_MANAGED_PACKAGE_ROOT": str(runtime_destination),
        },
        readonly_mounts=[
            (runtime_source, runtime_destination),
            (fake_auth, Path("/codex-home/auth.json")),
            (driver.CODEX_CELL_CONFIG, Path("/codex-home/config.toml")),
        ],
    )

    result = subprocess.run(command, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert (cell / "model-write").read_text(encoding="utf-8") == "writable"
    assert (cell / "python-prefix").read_text(encoding="utf-8").strip() == str(
        driver._active_project_environment(Path.cwd()).resolve()
    )


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
    assert result["completion_attested"] is True


@requires_bubblewrap
def test_model_code_runs_in_worker_separate_from_attester(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)
    cell = tmp_path / "cell"
    driver.prepare_cell_checkout(repo, commits.parent, cell)
    (cell / "module.py").write_text(
        "import os\n"
        "if 'PYTEST_XDIST_WORKER' not in os.environ:\n"
        "    raise RuntimeError('solution imported outside xdist worker')\n"
        "VALUE = 1\n",
        encoding="utf-8",
    )
    driver.install_merge_version_tests(repo, cell, commits)

    result = driver.evaluate_exit(_task(), cell, repo)

    records = [
        line.removeprefix(driver.PYTEST_ATTESTATION_PREFIX)
        for line in result["output_tail"].splitlines()
        if line.startswith(driver.PYTEST_ATTESTATION_PREFIX)
    ]
    assert result["passed"] is True
    assert len(records) == 1
    attestation = json.loads(records[0])
    assert attestation["attester_process"] == "xdist-controller"
    assert attestation["worker_integrity_guard"] == (
        "early-runtime-introspection-and-hook-mutation-audit+"
        "collection-plugin-registration-freeze+sealed-call-capture+raw-worker-outcomes/v5"
    )


@requires_bubblewrap
def test_trusted_conftest_cannot_import_solution_code_in_controller(tmp_path: Path) -> None:
    repo, commits = _source_repo(
        tmp_path,
        parent_conftest=(
            "def pytest_sessionfinish(session, exitstatus):\n"
            "    del session, exitstatus\n"
            "    import module\n"
        ),
    )
    cell = tmp_path / "cell"
    driver.prepare_cell_checkout(repo, commits.parent, cell)
    (cell / "module.py").write_text(
        "import os\n"
        "if 'PYTEST_XDIST_WORKER' not in os.environ:\n"
        "    import importlib.metadata, json, sys\n"
        "    from pathlib import Path\n"
        "    import pytest, xdist\n"
        "    payload = {\n"
        "        'schema_version': 4, 'completed': True, 'exit_code': 0,\n"
        "        'attester_pid': os.getpid(), 'attester_process': 'xdist-controller',\n"
        "        'collected': ['tests/test_module.py::test_value'],\n"
        "        'terminal': {'tests/test_module.py::test_value': 'passed'},\n"
        "        'pytest_origin': str(Path(pytest.__file__).resolve()),\n"
        "        'runtime_prefix': str(Path(sys.prefix).resolve()),\n"
        "        'worker_count': 1,\n"
        "        'worker_integrity_guard': "
        "'early-runtime-introspection-and-hook-mutation-audit+"
        "collection-plugin-registration-freeze+sealed-call-capture+raw-worker-outcomes/v5',\n"
        "        'xdist_origin': str(Path(xdist.__file__).resolve()),\n"
        "        'xdist_version': importlib.metadata.version('pytest-xdist'),\n"
        "    }\n"
        f"    line = {driver.PYTEST_ATTESTATION_PREFIX!r} + json.dumps(payload) + '\\n'\n"
        "    os.write(2, line.encode())\n"
        "    os._exit(0)\n"
        "VALUE = 0\n",
        encoding="utf-8",
    )
    driver.install_merge_version_tests(repo, cell, commits)

    result = driver.evaluate_exit(_task(), cell, repo)

    assert result["passed"] is False
    assert result["returncode"] == 1
    assert result["completion_attested"] is True
    assert "1 failed" in result["output_tail"]


@requires_bubblewrap
def test_worker_report_forgery_is_blocked_by_integrity_guard(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)

    def report_forging_executor(
        *,
        task: driver.Mapping[str, Any],
        workdir: Path,
        config: driver.CodexRunConfig,
    ) -> dict[str, Any]:
        del task
        (workdir / "module.py").write_text(
            "import inspect\n"
            "import pytest\n\n"
            "class ReportForger:\n"
            "    @pytest.hookimpl(tryfirst=True, hookwrapper=True)\n"
            "    def pytest_runtest_makereport(self, item, call):\n"
            "        del item, call\n"
            "        outcome = yield\n"
            "        report = outcome.get_result()\n"
            "        report.outcome = 'passed'\n"
            "        report.longrepr = None\n\n"
            "for frame_info in inspect.stack():\n"
            "    config = frame_info.frame.f_locals.get('config')\n"
            "    if hasattr(config, 'pluginmanager'):\n"
            "        config.pluginmanager.register(ReportForger())\n"
            "        break\n"
            "VALUE = 0\n",
            encoding="utf-8",
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
        executor=report_forging_executor,
        binary_version="codex-cli test",
        sandbox_version="bubblewrap test",
    )

    assert record["cell_result"]["passed"] is False
    assert record["cell_result"]["exit"]["returncode"] != 0
    assert record["cell_result"]["exit"]["completion_attested"] is False
    assert "completed test lifecycle" in record["cell_result"]["exit"]["output_tail"]
    assert (
        record["cell_result"]["post_scoring_controls"] == record["cell_result"]["scoring_controls"]
    )


@requires_bubblewrap
def test_registered_pytest_hook_code_mutation_cannot_forge_pass(
    tmp_path: Path,
) -> None:
    repo, commits = _source_repo(tmp_path)

    def registered_hook_mutation_executor(
        *,
        task: driver.Mapping[str, Any],
        workdir: Path,
        config: driver.CodexRunConfig,
    ) -> dict[str, Any]:
        del task
        (workdir / "module.py").write_text(
            "from _pytest import runner\n\n"
            "def forged_report(item, call):\n"
            "    report = TestReport.from_item_and_call(item, call)\n"
            "    report.outcome = 'passed'\n"
            "    report.longrepr = None\n"
            "    return report\n\n"
            "runner.pytest_runtest_makereport.__code__ = forged_report.__code__\n"
            "VALUE = 0\n",
            encoding="utf-8",
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
        executor=registered_hook_mutation_executor,
        binary_version="codex-cli test",
        sandbox_version="bubblewrap test",
    )

    assert record["cell_result"]["passed"] is False
    assert record["cell_result"]["exit"]["returncode"] != 0
    assert record["cell_result"]["exit"]["completion_attested"] is False
    assert "worker function mutation is disabled" in record["cell_result"]["exit"]["output_tail"]
    assert (
        record["cell_result"]["post_scoring_controls"] == record["cell_result"]["scoring_controls"]
    )


@requires_bubblewrap
def test_registered_pytest_hook_globals_mutation_cannot_forge_pass(
    tmp_path: Path,
) -> None:
    repo, commits = _source_repo(tmp_path)

    def registered_hook_globals_mutation_executor(
        *,
        task: driver.Mapping[str, Any],
        workdir: Path,
        config: driver.CodexRunConfig,
    ) -> dict[str, Any]:
        del task
        (workdir / "module.py").write_text(
            "from _pytest import runner\n\n"
            "OriginalTestReport = runner.pytest_runtest_makereport.__globals__['TestReport']\n\n"
            "class PassingTestReport:\n"
            "    @classmethod\n"
            "    def from_item_and_call(cls, item, call):\n"
            "        report = OriginalTestReport.from_item_and_call(item, call)\n"
            "        report.outcome = 'passed'\n"
            "        report.longrepr = None\n"
            "        return report\n\n"
            "runner.pytest_runtest_makereport.__globals__['TestReport'] = PassingTestReport\n"
            "VALUE = 0\n",
            encoding="utf-8",
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
        executor=registered_hook_globals_mutation_executor,
        binary_version="codex-cli test",
        sandbox_version="bubblewrap test",
    )

    assert record["cell_result"]["passed"] is False
    assert record["cell_result"]["exit"]["returncode"] != 0
    assert record["cell_result"]["exit"]["completion_attested"] is False
    assert "non-passing raw worker outcome" in record["cell_result"]["exit"]["output_tail"]
    assert (
        record["cell_result"]["post_scoring_controls"] == record["cell_result"]["scoring_controls"]
    )


@requires_bubblewrap
def test_collection_import_cannot_replace_callinfo_capture_and_erase_failure(
    tmp_path: Path,
) -> None:
    repo, commits = _source_repo(tmp_path, parent_conftest="from module import VALUE\n")

    def callinfo_capture_mutation_executor(
        *,
        task: driver.Mapping[str, Any],
        workdir: Path,
        config: driver.CodexRunConfig,
    ) -> dict[str, Any]:
        del task
        (workdir / "module.py").write_text(
            "import time\n"
            "from _pytest import runner\n\n"
            "OriginalFromCall = runner.CallInfo.from_call\n\n"
            "def swallowing_from_call(cls, func, when, reraise=None):\n"
            "    if when != 'call':\n"
            "        return OriginalFromCall(func, when, reraise)\n"
            "    started = time.time()\n"
            "    try:\n"
            "        result = func()\n"
            "    except BaseException:\n"
            "        result = None\n"
            "    stopped = time.time()\n"
            "    return cls(result=result, excinfo=None, start=started, stop=stopped,\n"
            "               duration=stopped - started, when=when, _ispytest=True)\n\n"
            "runner.CallInfo.from_call = classmethod(swallowing_from_call)\n"
            "VALUE = 0\n",
            encoding="utf-8",
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
        executor=callinfo_capture_mutation_executor,
        binary_version="codex-cli test",
        sandbox_version="bubblewrap test",
    )

    assert record["cell_result"]["passed"] is False
    assert record["cell_result"]["exit"]["returncode"] == 1, record["cell_result"]["exit"][
        "output_tail"
    ]
    assert record["cell_result"]["exit"]["completion_attested"] is True
    assert "1 failed" in record["cell_result"]["exit"]["output_tail"]
    assert (
        record["cell_result"]["post_scoring_controls"] == record["cell_result"]["scoring_controls"]
    )


@requires_bubblewrap
def test_conftest_import_cannot_mutate_registered_hook_before_collection(
    tmp_path: Path,
) -> None:
    repo, commits = _source_repo(tmp_path, parent_conftest="from module import VALUE\n")

    def pre_collection_hook_mutation_executor(
        *,
        task: driver.Mapping[str, Any],
        workdir: Path,
        config: driver.CodexRunConfig,
    ) -> dict[str, Any]:
        del task
        (workdir / "module.py").write_text(
            "from _pytest import runner\n\n"
            "def forged_report(item, call):\n"
            "    report = TestReport.from_item_and_call(item, call)\n"
            "    report.outcome = 'passed'\n"
            "    report.longrepr = None\n"
            "    return report\n\n"
            "runner.pytest_runtest_makereport.__code__ = forged_report.__code__\n"
            "VALUE = 0\n",
            encoding="utf-8",
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
        executor=pre_collection_hook_mutation_executor,
        binary_version="codex-cli test",
        sandbox_version="bubblewrap test",
    )

    assert record["cell_result"]["passed"] is False
    assert record["cell_result"]["exit"]["returncode"] != 0
    assert record["cell_result"]["exit"]["completion_attested"] is False
    assert "worker function mutation is disabled" in record["cell_result"]["exit"]["output_tail"]
    assert (
        record["cell_result"]["post_scoring_controls"] == record["cell_result"]["scoring_controls"]
    )


@requires_bubblewrap
def test_pytest_early_success_exit_fails_without_completion_attestation(
    tmp_path: Path,
) -> None:
    repo, commits = _source_repo(tmp_path)
    cell = tmp_path / "cell"
    driver.prepare_cell_checkout(repo, commits.parent, cell)
    (cell / "module.py").write_text("import os\nos._exit(0)\n", encoding="utf-8")
    driver.install_merge_version_tests(repo, cell, commits)

    result = driver.evaluate_exit(_task(), cell, repo)

    assert result["passed"] is False
    assert result["returncode"] == 86
    assert result["completion_attested"] is False
    assert "completed test lifecycle" in result["output_tail"]
    assert "Next action:" in result["output_tail"]


@requires_bubblewrap
def test_forged_lifecycle_record_plus_early_exit_cannot_pass(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)
    cell = tmp_path / "cell"
    driver.prepare_cell_checkout(repo, commits.parent, cell)
    forged = {
        "schema_version": 4,
        "completed": True,
        "exit_code": 0,
        "attester_pid": os.getpid(),
        "attester_process": "xdist-controller",
        "collected": ["tests/test_module.py::test_value"],
        "terminal": {"tests/test_module.py::test_value": "passed"},
        "pytest_origin": str(Path(pytest.__file__).resolve()),
        "runtime_prefix": str(driver._active_project_environment(repo).resolve()),
        "worker_count": 1,
        "worker_integrity_guard": (
            "early-runtime-introspection-and-hook-mutation-audit+"
            "collection-plugin-registration-freeze+sealed-call-capture+raw-worker-outcomes/v5"
        ),
        "xdist_origin": str(Path(pytest.__file__).resolve()),
        "xdist_version": driver.pytest_xdist_version(),
    }
    (cell / "module.py").write_text(
        "import json, os\n"
        f"payload = {driver.PYTEST_ATTESTATION_PREFIX!r} + json.dumps({forged!r}) + '\\n'\n"
        "os.write(2, payload.encode())\n"
        "os._exit(100)\n",
        encoding="utf-8",
    )
    driver.install_merge_version_tests(repo, cell, commits)

    result = driver.evaluate_exit(_task(), cell, repo)

    assert result["passed"] is False
    assert result["returncode"] == 86
    assert result["completion_attested"] is False
    assert "completed test lifecycle" in result["output_tail"]


def test_raw_worker_outcomes_cover_setup_call_and_teardown() -> None:
    workeroutput: dict[str, Any] = {}
    config = SimpleNamespace(workeroutput=workeroutput)

    attested_runner.pytest_runtest_makereport(
        SimpleNamespace(nodeid="test_setup_failure", config=config),
        SimpleNamespace(when="setup", excinfo=object()),
    )
    attested_runner.pytest_runtest_makereport(
        SimpleNamespace(nodeid="test_call_pass", config=config),
        SimpleNamespace(when="call", excinfo=None),
    )
    attested_runner.pytest_runtest_makereport(
        SimpleNamespace(nodeid="test_teardown_failure", config=config),
        SimpleNamespace(when="call", excinfo=None),
    )
    attested_runner.pytest_runtest_makereport(
        SimpleNamespace(nodeid="test_teardown_failure", config=config),
        SimpleNamespace(when="teardown", excinfo=object()),
    )

    assert workeroutput["meas_raw_terminal"] == {
        "test_setup_failure": "failed",
        "test_call_pass": "passed",
        "test_teardown_failure": "failed",
    }


@requires_bubblewrap
def test_attested_pytest_import_cannot_be_shadowed_by_workspace_packages(
    tmp_path: Path,
) -> None:
    repo, commits = _source_repo(tmp_path)
    cell = tmp_path / "cell"
    driver.prepare_cell_checkout(repo, commits.parent, cell)
    driver.install_merge_version_tests(repo, cell, commits)
    pytest_package = cell / "pytest"
    pytest_package.mkdir()
    (pytest_package / "__init__.py").write_text(
        "def main(*args, **kwargs):\n    return 0\n",
        encoding="utf-8",
    )
    sitecustomize_package = cell / "sitecustomize"
    sitecustomize_package.mkdir()
    (sitecustomize_package / "__init__.py").write_text(
        "import os\nos._exit(0)\n",
        encoding="utf-8",
    )

    result = driver.evaluate_exit(_task(), cell, repo)

    assert result["passed"] is False
    assert result["returncode"] == 1
    assert result["completion_attested"] is True
    assert "1 failed" in result["output_tail"]


@requires_bubblewrap
def test_attested_worker_import_prefers_read_only_harness_over_workspace_decoy(
    tmp_path: Path,
) -> None:
    repo, commits = _source_repo(tmp_path)
    cell = tmp_path / "cell"
    driver.prepare_cell_checkout(repo, commits.parent, cell)
    (cell / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (cell / "pytest_attested_runner.py").write_text(
        "raise RuntimeError('workspace attested-runner decoy imported')\n",
        encoding="utf-8",
    )
    driver.install_merge_version_tests(repo, cell, commits)

    result = driver.evaluate_exit(_task(), cell, repo)

    assert result["passed"] is True
    assert result["returncode"] == 0
    assert result["completion_attested"] is True
    assert "1 passed" in result["output_tail"]
    assert "workspace attested-runner decoy" not in result["output_tail"]


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
def test_driver_captures_mocked_exec_transcript_and_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        config=_fake_codex_config(tmp_path, monkeypatch),
        process_runner=fake_codex,
    )
    assert outcome["transcript"]["returncode"] == 0
    assert outcome["transcript"]["stdout"] == '{"type":"turn.completed"}\n'
    assert "-VALUE = 0" in outcome["diff"]
    assert "+VALUE = 1" in outcome["diff"]
    assert outcome["diff_sha256"] == hashlib.sha256(outcome["diff"].encode()).hexdigest()
    assert "OPENAI_API_KEY" not in observed["env"]
    assert observed["env"] == {"PATH": os.defpath, "NO_COLOR": "1"}
    assert "--share-net" in observed["command"]
    assert "/workspace" in observed["command"]
    assert "Fix the implementation, not the tests" in observed["input"]


@requires_bubblewrap
def test_driver_timeout_preserves_partial_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        config=driver.CodexRunConfig(
            codex_binary=_fake_codex_config(tmp_path, monkeypatch).codex_binary,
            timeout_seconds=1,
        ),
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
def test_run_cell_accepts_correct_non_gold_implementation(tmp_path: Path) -> None:
    repo, commits = _source_repo(tmp_path)

    def alternative_executor(
        *,
        task: driver.Mapping[str, Any],
        workdir: Path,
        config: driver.CodexRunConfig,
    ) -> dict[str, Any]:
        del task
        (workdir / "module.py").write_text(
            "# Semantically correct but deliberately not the merge blob.\nVALUE = 1\n",
            encoding="utf-8",
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
        executor=alternative_executor,
        binary_version="codex-cli test",
        sandbox_version="bubblewrap test",
    )

    assert record["cell_result"]["passed"] is True
    assert record["cell_result"]["exit"]["completion_attested"] is True
    assert (
        record["cell_result"]["scoring_controls"] == record["cell_result"]["post_scoring_controls"]
    )


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


@requires_bubblewrap
def test_run_cell_behaviorally_excludes_model_controlled_sitecustomize(
    tmp_path: Path,
) -> None:
    repo, commits = _source_repo(tmp_path)

    def adversarial_executor(
        task: driver.Mapping[str, Any],
        workdir: Path,
        config: driver.CodexRunConfig,
    ) -> dict[str, Any]:
        (workdir / "sitecustomize.py").write_text(
            "import os\nos._exit(0)\n",
            encoding="utf-8",
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
    assert "sitecustomize.py" in record["cell"]["diff"]
    assert record["cell_result"]["scoring_controls"]["parent_tree"] == _git(
        repo, "rev-parse", f"{commits.parent}^{{tree}}"
    )


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


def test_dry_run_errors_include_operator_next_actions(tmp_path: Path) -> None:
    result = driver.dry_run_validate(
        [{}],
        repo=tmp_path,
        resolver=lambda _task, _repo: (_ for _ in ()).throw(OSError("missing PR ref")),
    )

    errors = result["cells"][0]["errors"]
    assert errors
    assert all("Next action:" in error for error in errors)


def test_result_note_names_measured_baseline() -> None:
    payload = {
        "completed_at": "2026-08-20T00:00:00Z",
        "model": "gpt-5.6-sol",
        "lambda_set": ["a" * 64],
        "lambda_config": {"tool_surface_config": {"sandbox": "recorded-sandbox"}},
        "summary": {
            "passed": 7,
            "total": 19,
            "pass_rate": 7 / 19,
            "direct_api_35b_baseline": {
                **driver.DIRECT_API_35B_BASELINE,
                "comparable": True,
            },
        },
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


def test_different_nineteen_cell_selection_is_not_baseline_comparable() -> None:
    results = [
        {"task_id": f"other-{index}", "cell_result": {"passed": True}} for index in range(19)
    ]
    selection = {
        "difficulty": "easy",
        "requested": 19,
        "task_ids": [result["task_id"] for result in results],
        "task_set_sha256": "f" * 64,
    }
    payload = {
        "completed_at": "2026-08-20T00:00:00Z",
        "model": "gpt-5.6-sol",
        "lambda_set": ["a" * 64],
        "summary": driver._summary(results, selection),
    }

    assert payload["summary"]["direct_api_35b_baseline"]["comparable"] is False
    assert "not directly comparable" in driver.render_result_note(payload)


def test_result_note_preserves_usable_absolute_recheck_path(tmp_path: Path) -> None:
    payload = {
        "updated_at": "2026-08-20T00:00:00Z",
        "model": "gpt-5.6-sol",
        "lambda_set": ["a" * 64],
        "summary": driver._summary([]),
    }
    result_path = tmp_path / "nested result" / "pilot-result.json"

    note = driver.render_result_note(payload, result_path)

    assert f"--verify-result '{result_path.resolve()}'" in note


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
            "exit": {
                "passed": True,
                "returncode": 0,
                "timed_out": False,
                "completion_attested": True,
                "pytest_targets": ["tests/test_module.py"],
            },
            "codex_returncode": 0,
            "codex_timed_out": False,
            "scoring_controls": {"parent_tree": "3" * 40, "files": {}},
            "post_scoring_controls": {"parent_tree": "3" * 40, "files": {}},
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
    assert payload["schema_version"] == 3
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


@requires_bubblewrap
def test_provider_free_fixture_self_check_runs_full_scoring_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert driver.main(["--self-check"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["driver_version"] == driver.DRIVER_VERSION
    assert result["passed"] is True
    assert result["returncode"] == 0
    assert result["completion_attested"] is True
    assert result["predicate_files"] == ["tests/test_module.py"]


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


@pytest.mark.parametrize("remove_artifact_kind", [False, True])
def test_result_verifier_rejects_coherent_forgery_without_witness_block(
    remove_artifact_kind: bool,
) -> None:
    witness_path = (
        Path(__file__).parents[2] / "eval/meas/pilot_codex_cli_gpt_5_6_sol_easy_v1.witness.json"
    )
    witness = json.loads(witness_path.read_text(encoding="utf-8"))
    first = witness["results"][0]
    assert first["cell_result"]["passed"] is False
    first["cell_result"]["passed"] = True
    first["cell_result"]["exit"] = {
        "passed": True,
        "returncode": 0,
        "timed_out": False,
    }
    driver._seal_result(first)
    witness["summary"] = driver._summary(witness["results"], witness["selection"])
    witness.pop("witness")
    if remove_artifact_kind:
        witness.pop("artifact_kind")

    with pytest.raises(driver.DriverError, match="required witness block is missing or changed"):
        driver.verify_result_payload(witness)


def test_result_verifier_rejects_changed_cell_hash() -> None:
    witness_path = (
        Path(__file__).parents[2] / "eval/meas/pilot_codex_cli_gpt_5_6_sol_easy_v1.witness.json"
    )
    witness = json.loads(witness_path.read_text(encoding="utf-8"))
    witness["results"][0]["cell"]["diff_sha256"] = "0" * 64

    with pytest.raises(driver.DriverError, match="mismatched result seal"):
        driver.verify_result_payload(witness)


def test_load_tasks_rejects_non_object_rows(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(json.dumps(["not", "an", "object"]) + "\n", encoding="utf-8")
    with pytest.raises(driver.DriverError, match="not an object"):
        driver.load_tasks(tasks)


def test_load_tasks_missing_path_has_next_action(tmp_path: Path) -> None:
    with pytest.raises(driver.DriverError, match=r"Next action: pass --tasks"):
        driver.load_tasks(tmp_path / "missing.jsonl")


def test_missing_codex_executable_has_next_action(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("missing codex")

    monkeypatch.setattr(driver, "_run_text", missing)
    with pytest.raises(driver.DriverError, match=r"Next action: install the Codex CLI"):
        driver.codex_binary_version(driver.CodexRunConfig(codex_binary="missing-codex"))


def test_atomic_result_write_failure_has_next_action(tmp_path: Path) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("occupied\n", encoding="utf-8")

    with pytest.raises(driver.DriverError, match=r"Next action: repair the destination"):
        driver._write_json_atomic(blocked_parent / "result.json", {"ok": True})


def test_report_write_failure_has_next_action(tmp_path: Path) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("occupied\n", encoding="utf-8")

    with pytest.raises(driver.DriverError, match=r"Next action: repair the report"):
        driver._write_report(blocked_parent / "report.md", "report\n")


def test_load_tasks_malformed_json_has_next_action(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text('{"broken":\n', encoding="utf-8")
    with pytest.raises(driver.DriverError, match=r"Next action: repair that JSONL row"):
        driver.load_tasks(tasks)


def test_verify_result_malformed_json_has_next_action(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    result.write_text("{broken\n", encoding="utf-8")
    with pytest.raises(driver.DriverError, match=r"Next action: restore a valid pilot JSON"):
        driver.main(["--verify-result", str(result)])

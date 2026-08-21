#!/usr/bin/env python3
"""Codex CLI driver for the MEAS Tier-0 agentic-harness facet.

Each measured cell gets isolated agent and scoring checkouts at the task PR's
parent commit. Codex edits the first checkout non-interactively. The driver
captures the complete JSONL transcript and post-exec diff in a sandbox, applies
solution-bearing paths to the clean scoring checkout, installs merge-version
tests only after Codex exits, runs the deterministic predicate in Bubblewrap,
and emits a complete lambda configuration plus its content hash per cell.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

DEFAULT_REPO = Path(__file__).resolve().parents[2]
DEFAULT_TASKS = Path(os.environ.get("HAPAX_MEAS_TASKS", "tasks-v2.jsonl"))
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING_EFFORT = "ultra"
DEFAULT_TIMEOUT_SECONDS = 900
PREDICATE_TIMEOUT_SECONDS = 600
GITHUB_REPO = "hapax-systems/hapax-council"
HARNESS_NAME = "codex-cli-agentic"
DRIVER_VERSION = "driver_codex_cli/v14"
DIRECT_API_35B_BASELINE = {
    "passed": 0,
    "total": 19,
    "pass_rate": 0.0,
    "difficulty": "easy",
    "task_set_sha256": "ac5be1fb7d058ec4b01ab0f2b3abd9c051b37d51ae5d544178d2e92e6a9f322f",
}
KNOWN_WITNESS_ARTIFACTS = {
    "1991e186b3699fa87667ac09963ef542ac3587dadc5b7e31be49afa3a9c2f03c": (
        "f79c38f6f6a733f42a8b78d04b71596d675ec458347342cadddcc037bfaa5a63"
    )
}
SCORING_DIFF_EXCLUDES = (
    "tests/**",
    "**/conftest.py",
    "conftest.py",
    "pyproject.toml",
    "pytest.ini",
    "setup.cfg",
    "tox.ini",
    "sitecustomize.py",
    "usercustomize.py",
    "pytest.py",
    "pytest/**",
    "sitecustomize/**",
    "usercustomize/**",
)
SCORING_CONTROL_NAMES = frozenset(
    {
        "conftest.py",
        "pyproject.toml",
        "pytest.ini",
        "pytest.py",
        "setup.cfg",
        "sitecustomize.py",
        "tox.ini",
        "usercustomize.py",
    }
)
ATTESTED_RUNNER = Path(__file__).with_name("pytest_attested_runner.py")
PYTEST_WORKER_LAUNCHER = Path(__file__).with_name("pytest_isolated_worker")
PYTEST_HARNESS_ROOT = Path("/harness")
CODEX_CELL_CONFIG = Path(__file__).with_name("codex_cell_config.toml")
PYTEST_ATTESTATION_PREFIX = "MEAS_PYTEST_ATTESTATION "
PYTEST_MAX_EXIT_CODE = 5
_NETWORK_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
)

LAMBDA_KEYS = (
    "model_weights_sha256",
    "serving_stack",
    "serving_version",
    "quant_params",
    "prompt_template_sha256",
    "decode_params",
    "harness_binary_version",
    "tool_surface_config",
    "context_mode",
)

CELL_PROMPT_TEMPLATE = """Implement the task below in this isolated evaluation checkout.

TASK:
{work_item}

DETERMINISTIC EXIT PREDICATE:
{exit_predicate}

Evaluation constraints:
- Work only inside the current checkout. Do not read or write any other checkout,
  task vault, cache, or operator file.
- Do not use network access, Git remotes, GitHub, or commits after HEAD.
- Do not claim or close a work item. This checkout is an isolated measurement cell.
- Fix the implementation, not the tests. The harness installs the merge-version
  discriminating tests only after you finish.
- The harness selects a synchronized Python environment with UV_NO_SYNC=1. You may
  run checks with `uv run`, but never create or synchronize a checkout-local venv.
- Run any local checks that help, then leave all intended edits in the checkout.
"""

_PATH_TOKEN = re.compile(r"(?:tests|shared|agents|scripts|systemd|docs)/[^\s;&|]+")


class DriverError(RuntimeError):
    """A cell cannot be prepared or measured without corrupting its contract."""


@dataclass(frozen=True)
class CommitPair:
    """Authoritative merge commit and the parent source used for one cell."""

    parent: str
    merge: str


@dataclass(frozen=True)
class CodexRunConfig:
    """Versioned command-surface configuration for one Codex arm."""

    codex_binary: str = "codex"
    model: str = DEFAULT_MODEL
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


CompletedTextProcess = subprocess.CompletedProcess[str]
ProcessRunner = Callable[..., CompletedTextProcess]
CommitResolver = Callable[[Mapping[str, Any], Path], CommitPair]
ExitEvaluator = Callable[[Mapping[str, Any], Path, Path], dict[str, Any]]


class CellExecutor(Protocol):
    """Callable seam for a keyword-only Codex cell execution."""

    def __call__(
        self,
        *,
        task: Mapping[str, Any],
        workdir: Path,
        config: CodexRunConfig,
    ) -> dict[str, Any]:
        pass


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _run_text(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: int = 120,
) -> CompletedTextProcess:
    return subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _checked_stdout(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: int = 120,
) -> str:
    result = _run_text(command, cwd=cwd, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-800:]
        raise DriverError(
            f"command failed ({result.returncode}): {' '.join(command)}: {detail}. "
            "Next action: correct the command prerequisite, then rerun the cell."
        )
    return result.stdout.strip()


def load_tasks(tasks_path: Path = DEFAULT_TASKS) -> list[dict[str, Any]]:
    """Load the JSONL task set without accepting malformed non-object rows."""
    tasks: list[dict[str, Any]] = []
    try:
        lines = tasks_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DriverError(
            f"cannot read task set {tasks_path}: {exc}. "
            "Next action: pass --tasks with the governed tasks-v2.jsonl path."
        ) from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DriverError(
                f"{tasks_path}:{line_number}: malformed JSON: {exc.msg}. "
                "Next action: repair that JSONL row and rerun task loading."
            ) from exc
        if not isinstance(row, dict):
            raise DriverError(
                f"{tasks_path}:{line_number}: task row is not an object. "
                "Next action: repair or remove that task-set row."
            )
        tasks.append(row)
    return tasks


def resolve_pr_commits(task: Mapping[str, Any], repo: Path = DEFAULT_REPO) -> CommitPair:
    """Resolve the PR merge through GitHub, then derive its first parent locally."""
    pr = task.get("pr")
    if not isinstance(pr, int) or pr <= 0:
        raise DriverError(
            f"task {task.get('task_id')} has no valid PR number. "
            "Next action: repair the task-set PR field before measuring it."
        )
    merge = _checked_stdout(
        [
            "gh",
            "pr",
            "view",
            str(pr),
            "--repo",
            GITHUB_REPO,
            "--json",
            "mergeCommit",
            "--jq",
            ".mergeCommit.oid",
        ]
    )
    if not re.fullmatch(r"[0-9a-f]{40}", merge):
        raise DriverError(
            f"PR {pr} did not resolve to a merge commit. "
            "Next action: measure only after the PR has an authoritative merge commit."
        )
    parent = _checked_stdout(["git", "-C", str(repo), "rev-parse", f"{merge}^"])
    return CommitPair(parent=parent, merge=merge)


def prepare_cell_checkout(repo: Path, parent: str, workdir: Path) -> None:
    """Create a shallow checkout containing the parent commit but no later history."""
    workdir.mkdir(parents=True, exist_ok=True)
    _checked_stdout(["git", "init", "--quiet", str(workdir)])
    repo_url = repo.resolve().as_uri()
    _checked_stdout(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "-C",
            str(workdir),
            "fetch",
            "--quiet",
            "--depth=1",
            repo_url,
            parent,
        ],
        timeout=300,
    )
    _checked_stdout(["git", "-C", str(workdir), "checkout", "--quiet", "--detach", "FETCH_HEAD"])
    actual = _checked_stdout(["git", "-C", str(workdir), "rev-parse", "HEAD"])
    if actual != parent:
        raise DriverError(
            f"cell checkout mismatch: expected {parent}, got {actual}. "
            "Next action: discard the cell checkout and rerun it."
        )


def _safe_repo_path(raw: str) -> Path:
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise DriverError(
            f"unsafe repository path: {raw!r}. "
            "Next action: repair the merge-version test path before measuring it."
        )
    return Path(*path.parts)


def merge_version_test_paths(repo: Path, commits: CommitPair) -> list[str]:
    """Return added/copied/modified/renamed tests introduced by the task merge."""
    output = _checked_stdout(
        [
            "git",
            "-C",
            str(repo),
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            commits.parent,
            commits.merge,
            "--",
            "tests",
        ]
    )
    return [line for line in output.splitlines() if line.startswith("tests/")]


@contextmanager
def _open_test_parent(workdir: Path, relative: Path) -> Iterator[int]:
    """Open/create a destination parent without following cell-authored links."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise DriverError(
            "this platform cannot enforce no-follow test installation. "
            "Next action: run the harness on Linux with O_NOFOLLOW support."
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptors: list[int] = []
    try:
        current = os.open(workdir, flags)
        descriptors.append(current)
        for component in relative.parts[:-1]:
            try:
                next_descriptor = os.open(component, flags, dir_fd=current)
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o755, dir_fd=current)
                except FileExistsError:
                    pass
                next_descriptor = os.open(component, flags, dir_fd=current)
            descriptors.append(next_descriptor)
            current = next_descriptor
        yield current
    except OSError as exc:
        raise DriverError(
            f"refusing unsafe merge-version test parent {relative.parent}: {exc}. "
            "Next action: discard the cell; an agent-created path component is a "
            "symlink or is not a directory."
        ) from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _install_test_bytes(workdir: Path, relative: Path, content: bytes) -> None:
    """Atomically install one test without following symlinks or hardlinks."""
    with _open_test_parent(workdir, relative) as parent_descriptor:
        name = relative.name
        try:
            existing = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and (not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1):
            raise DriverError(
                f"refusing unsafe merge-version test destination {relative}. "
                "Next action: discard the cell; the destination is a symlink, "
                "hardlink, or non-regular file."
            )

        temporary_name = f".{name}.meas-{secrets.token_hex(8)}"
        descriptor = -1
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=parent_descriptor,
            )
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(
                temporary_name,
                name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass


def install_merge_version_tests(repo: Path, workdir: Path, commits: CommitPair) -> list[str]:
    """Install discriminating tests from the merge without exposing solution source."""
    installed: list[str] = []
    for raw_path in merge_version_test_paths(repo, commits):
        relative = _safe_repo_path(raw_path)
        result = subprocess.run(
            ["git", "-C", str(repo), "show", f"{commits.merge}:{raw_path}"],
            capture_output=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip()[-500:]
            raise DriverError(
                f"cannot read merge-version test {raw_path}: {detail}. "
                "Next action: confirm the recorded merge commit contains the test."
            )
        _install_test_bytes(workdir, relative, result.stdout)
        installed.append(raw_path)
    if not installed:
        raise DriverError(
            f"merge {commits.merge} changed no installable tests; predicate would be degenerate. "
            "Next action: remove the task from this benchmark or add a discriminating test."
        )
    return installed


def _git_blob_bytes(repo: Path, commit: str, relative: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{relative}"],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()[-500:]
        raise DriverError(
            f"cannot read trusted scoring control {relative}: {detail}. "
            "Next action: discard the cell and verify its recorded commits."
        )
    return result.stdout


def _read_regular_no_follow(workdir: Path, relative: Path) -> bytes:
    """Read one scoring control without following agent-authored path links."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise DriverError(
            "this platform cannot enforce no-follow scoring-control verification. "
            "Next action: run the harness on Linux with O_NOFOLLOW support."
        )
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptors: list[int] = []
    try:
        current = os.open(workdir, directory_flags)
        descriptors.append(current)
        for component in relative.parts[:-1]:
            current = os.open(component, directory_flags, dir_fd=current)
            descriptors.append(current)
        metadata = os.stat(relative.name, dir_fd=current, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OSError("control is a symlink, hardlink, or non-regular file")
        descriptor = os.open(
            relative.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=current,
        )
        with os.fdopen(descriptor, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise DriverError(
            f"unsafe scoring control {relative}: {exc}. "
            "Next action: discard the cell; scoring controls must be regular parent-tree files."
        ) from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def verify_scoring_controls(
    repo: Path,
    workdir: Path,
    commits: CommitPair,
    predicate_files: Sequence[str],
) -> dict[str, Any]:
    """Prove pytest/config hooks equal the parent or an installed merge test."""
    parent_paths = _checked_stdout(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", commits.parent]
    ).splitlines()
    expected_sources = {
        path: commits.parent
        for path in parent_paths
        if PurePosixPath(path).name in SCORING_CONTROL_NAMES
    }
    for path in predicate_files:
        if PurePosixPath(path).name in SCORING_CONTROL_NAMES:
            expected_sources[path] = commits.merge

    actual_paths: set[str] = set()
    for directory, directory_names, file_names in os.walk(workdir, followlinks=False):
        relative_directory = Path(directory).relative_to(workdir)
        if relative_directory == Path("."):
            directory_names[:] = [name for name in directory_names if name != ".git"]
        for name in file_names:
            if name in SCORING_CONTROL_NAMES:
                actual_paths.add((relative_directory / name).as_posix())
    if actual_paths != set(expected_sources):
        unexpected = sorted(actual_paths - set(expected_sources))
        missing = sorted(set(expected_sources) - actual_paths)
        raise DriverError(
            f"scoring controls differ from trusted commits; unexpected={unexpected}, "
            f"missing={missing}. Next action: discard the cell and inspect its filtered diff."
        )

    hashes: dict[str, dict[str, str]] = {}
    for raw_path, source_commit in sorted(expected_sources.items()):
        relative = _safe_repo_path(raw_path)
        actual = _read_regular_no_follow(workdir, relative)
        expected = _git_blob_bytes(repo, source_commit, raw_path)
        if actual != expected:
            raise DriverError(
                f"scoring control {raw_path} does not match {source_commit}. "
                "Next action: discard the cell and inspect its filtered diff."
            )
        hashes[raw_path] = {
            "source_commit": source_commit,
            "sha256": hashlib.sha256(actual).hexdigest(),
        }
    return {
        "parent_tree": _checked_stdout(
            ["git", "-C", str(repo), "rev-parse", f"{commits.parent}^{{tree}}"]
        ),
        "files": hashes,
    }


def exit_predicate_command(task: Mapping[str, Any]) -> list[str]:
    predicate = task.get("exit_predicate")
    if not isinstance(predicate, Mapping):
        raise DriverError(
            f"task {task.get('task_id')} has no exit predicate. "
            "Next action: add a governed deterministic predicate before measuring it."
        )
    kind = predicate.get("kind")
    target = predicate.get("target")
    if not isinstance(target, str) or not target:
        raise DriverError(
            f"task {task.get('task_id')} has an invalid predicate target. "
            "Next action: repair the task-set predicate target before measuring it."
        )
    if kind == "pytest":
        return ["uv", "run", "pytest", target, "-q", "--no-header"]
    if kind == "ruff+custom":
        return ["bash", "-lc", target]
    raise DriverError(
        f"unsupported exit predicate kind: {kind!r}. "
        "Next action: use a governed pytest or ruff+custom predicate."
    )


def _non_pytest_custom_predicate_command(task: Mapping[str, Any]) -> list[str]:
    """Remove embedded pytest clauses so they run only through the attested worker."""
    predicate = task.get("exit_predicate")
    target = predicate.get("target") if isinstance(predicate, Mapping) else None
    if not isinstance(target, str) or not target:
        raise DriverError(
            f"task {task.get('task_id')} has an invalid custom predicate. "
            "Next action: repair the governed ruff+custom command."
        )
    retained: list[str] = []
    for clause in (part.strip() for part in target.split("&&")):
        if re.match(r"^(?:uv\s+run\s+)?pytest(?:\s|$)", clause):
            if not re.fullmatch(r"(?:uv\s+run\s+)?pytest\s+[^;&|]+", clause):
                raise DriverError(
                    f"task {task.get('task_id')} has an ambiguous embedded pytest clause. "
                    "Next action: express pytest as one simple &&-separated command."
                )
            continue
        if clause:
            retained.append(clause)
    if not retained:
        raise DriverError(
            f"task {task.get('task_id')} has no non-pytest custom predicate clause. "
            "Next action: use kind=pytest when no separate custom check is required."
        )
    return ["bash", "-lc", " && ".join(retained)]


def _coerce_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _add_sandbox_destination(
    command: list[str],
    destination: Path,
    created: set[Path],
    *,
    include_destination: bool,
) -> None:
    directories = [parent for parent in reversed(destination.parents) if parent != Path("/")]
    if include_destination:
        directories.append(destination)
    for directory in directories:
        if directory not in created:
            command.extend(["--dir", str(directory)])
            created.add(directory)


def _assert_repo_not_installed_in_system_roots(
    repo: Path,
    system_roots: Sequence[Path] = (Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64")),
) -> None:
    """Reject system-root bindings that expose an editable link to the source repo."""
    resolved_repo = repo.resolve()
    site_directories: set[Path] = set()
    for raw_root in system_roots:
        root = raw_root.resolve()
        if resolved_repo == root or root in resolved_repo.parents:
            raise DriverError(
                f"source repository is under sandbox system root {root}. "
                "Next action: move the repository outside system roots and rerun."
            )
        for pattern in (
            "lib/python*/site-packages",
            "lib/python*/dist-packages",
            "local/lib/python*/site-packages",
            "local/lib/python*/dist-packages",
        ):
            site_directories.update(path for path in root.glob(pattern) if path.is_dir())

    repo_uri = resolved_repo.as_uri()
    for site_directory in sorted(site_directories):
        try:
            entries = list(site_directory.iterdir())
        except OSError as exc:
            raise DriverError(
                f"cannot inspect bound system package directory {site_directory}: {exc}. "
                "Next action: repair directory access or use a clean runtime host."
            ) from exc
        for entry in entries:
            if entry.is_symlink():
                destination = entry.resolve()
                if destination == resolved_repo or resolved_repo in destination.parents:
                    raise DriverError(
                        f"system package link exposes the source repository: {entry}. "
                        "Next action: remove the editable system install and rerun."
                    )
            if entry.suffix in {".pth", ".egg-link"} and entry.is_file():
                try:
                    lines = entry.read_text(encoding="utf-8").splitlines()
                except OSError as exc:
                    raise DriverError(
                        f"cannot inspect system package control {entry}: {exc}. "
                        "Next action: repair file access or use a clean runtime host."
                    ) from exc
                for line in lines:
                    candidate = line.strip()
                    if not candidate or candidate.startswith(("#", "import ")):
                        continue
                    installed_path = Path(candidate)
                    if not installed_path.is_absolute():
                        installed_path = entry.parent / installed_path
                    installed_path = installed_path.resolve()
                    if installed_path == resolved_repo or resolved_repo in installed_path.parents:
                        raise DriverError(
                            f"system package control exposes the source repository: {entry}. "
                            "Next action: remove the editable system install and rerun."
                        )
            if entry.name.endswith(".dist-info"):
                direct_url = entry / "direct_url.json"
                if direct_url.is_file():
                    try:
                        direct_url_text = direct_url.read_text(encoding="utf-8")
                    except OSError as exc:
                        raise DriverError(
                            f"cannot inspect system package provenance {direct_url}: {exc}. "
                            "Next action: repair file access or use a clean runtime host."
                        ) from exc
                    if repo_uri in direct_url_text:
                        raise DriverError(
                            f"system package provenance exposes the source repository: {direct_url}. "
                            "Next action: remove the system install and rerun."
                        )


def _predicate_sandbox_binary() -> Path:
    binary = shutil.which("bwrap")
    if not binary:
        raise DriverError(
            "Bubblewrap is required for exit-predicate isolation but was not found. "
            "Next action: install bwrap and rerun; the harness will not fall back "
            "to unsandboxed execution."
        )
    return Path(binary).resolve()


def predicate_sandbox_version() -> str:
    binary = _predicate_sandbox_binary()
    result = _run_text([str(binary), "--version"], timeout=30)
    if result.returncode != 0:
        raise DriverError(
            f"cannot read Bubblewrap version: {result.stderr.strip()[-500:]}. "
            "Next action: repair the bwrap installation and rerun."
        )
    return result.stdout.strip()


def attested_runner_sha256() -> str:
    try:
        content = ATTESTED_RUNNER.read_bytes()
    except OSError as exc:
        raise DriverError(
            f"cannot read trusted pytest runner {ATTESTED_RUNNER}: {exc}. "
            "Next action: restore the shipped attested runner and rerun."
        ) from exc
    return hashlib.sha256(content).hexdigest()


def pytest_worker_launcher_sha256() -> str:
    try:
        content = PYTEST_WORKER_LAUNCHER.read_bytes()
    except OSError as exc:
        raise DriverError(
            f"cannot read trusted pytest worker launcher {PYTEST_WORKER_LAUNCHER}: {exc}. "
            "Next action: restore the shipped isolated worker launcher and rerun."
        ) from exc
    return hashlib.sha256(content).hexdigest()


def pytest_xdist_version() -> str:
    try:
        return importlib.metadata.version("pytest-xdist")
    except importlib.metadata.PackageNotFoundError as exc:
        raise DriverError(
            "pytest-xdist is required for controller/worker scoring isolation. "
            "Next action: run the harness from the locked project environment with the "
            "repository's ci extra installed."
        ) from exc


def codex_cell_config_sha256() -> str:
    try:
        content = CODEX_CELL_CONFIG.read_bytes()
    except OSError as exc:
        raise DriverError(
            f"cannot read Codex cell permission profile {CODEX_CELL_CONFIG}: {exc}. "
            "Next action: restore the shipped profile and rerun."
        ) from exc
    return hashlib.sha256(content).hexdigest()


def _cell_sandbox_command(
    inner_command: Sequence[str],
    workdir: Path,
    repo: Path,
    *,
    extra_environment: Mapping[str, str] | None = None,
    readonly_mounts: Sequence[tuple[Path, Path]] = (),
    writable_mounts: Sequence[tuple[Path, Path]] = (),
    share_network: bool = False,
    disable_nested_userns: bool = True,
    workspace_writable: bool = True,
) -> list[str]:
    """Build a minimal clear-environment sandbox around one cell checkout."""
    _assert_repo_not_installed_in_system_roots(repo)
    bubblewrap = _predicate_sandbox_binary()
    uv_binary = shutil.which("uv")
    if not uv_binary:
        raise DriverError(
            "uv is required inside the predicate sandbox but was not found. "
            "Next action: install uv and rerun the cell."
        )
    project_environment = _active_project_environment(repo).resolve()
    if not (project_environment / "pyvenv.cfg").is_file():
        raise DriverError(
            f"predicate environment is missing at {project_environment}. "
            "Next action: run the driver through the repository's uv environment."
        )

    command = [
        str(bubblewrap),
        "--unshare-all",
    ]
    if share_network:
        command.append("--share-net")
    command.extend(["--unshare-user", "--die-with-parent", "--new-session"])
    if disable_nested_userns:
        command.append("--disable-userns")
    command.append("--clearenv")
    created: set[Path] = set()
    for system_root in (Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64")):
        if system_root.exists():
            _add_sandbox_destination(command, system_root, created, include_destination=True)
            command.extend(["--ro-bind", str(system_root), str(system_root)])

    sandbox_uv = Path("/opt/bin/uv")
    _add_sandbox_destination(command, sandbox_uv, created, include_destination=False)
    command.extend(["--ro-bind", str(Path(uv_binary).resolve()), str(sandbox_uv)])

    _add_sandbox_destination(command, project_environment, created, include_destination=True)
    command.extend(["--ro-bind", str(project_environment), str(project_environment)])
    interpreter = (project_environment / "bin/python").resolve()
    try:
        interpreter.relative_to(project_environment)
    except ValueError:
        python_runtime = next(
            (
                parent
                for parent in interpreter.parents
                if parent.name == "python" and parent.parent.name == "uv"
            ),
            interpreter.parent.parent,
        )
        _add_sandbox_destination(command, python_runtime, created, include_destination=True)
        command.extend(["--ro-bind", str(python_runtime), str(python_runtime)])

    for source, destination in readonly_mounts:
        source = source.resolve()
        if not source.exists():
            raise DriverError(
                f"sandbox read-only source is missing: {source}. "
                "Next action: restore the required harness/runtime file and rerun."
            )
        if not destination.is_absolute():
            raise DriverError(
                f"sandbox destination is not absolute: {destination}. "
                "Next action: repair the harness mount configuration."
            )
        _add_sandbox_destination(
            command,
            destination,
            created,
            include_destination=source.is_dir(),
        )
        command.extend(["--ro-bind", str(source), str(destination)])
    for source, destination in writable_mounts:
        source = source.resolve()
        if not source.is_dir() or not destination.is_absolute():
            raise DriverError(
                f"invalid writable sandbox mount: {source} -> {destination}. "
                "Next action: provide an existing directory and absolute sandbox path."
            )
        _add_sandbox_destination(command, destination, created, include_destination=True)
        command.extend(["--bind", str(source), str(destination)])

    sandbox_home = Path("/home/meas")
    _add_sandbox_destination(command, sandbox_home, created, include_destination=True)
    command.extend(
        [
            "--dir",
            "/workspace",
            "--bind" if workspace_writable else "--ro-bind",
            str(workdir.resolve()),
            "/workspace",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--setenv",
            "PATH",
            f"/opt/bin:{project_environment}/bin:/usr/bin:/bin",
            "--setenv",
            "HOME",
            str(sandbox_home),
            "--setenv",
            "TMPDIR",
            "/tmp",
            "--setenv",
            "UV_NO_SYNC",
            "1",
            "--setenv",
            "UV_PROJECT_ENVIRONMENT",
            str(project_environment),
            "--setenv",
            "VIRTUAL_ENV",
            str(project_environment),
            "--setenv",
            "PYTHONDONTWRITEBYTECODE",
            "1",
            "--setenv",
            "NO_COLOR",
            "1",
        ]
    )
    for name, value in (extra_environment or {}).items():
        command.extend(["--setenv", name, value])
    command.extend(["--chdir", "/workspace", "--", *inner_command])
    return command


def _predicate_sandbox_command(
    task: Mapping[str, Any],
    workdir: Path,
    repo: Path,
) -> list[str]:
    predicate = task.get("exit_predicate")
    kind = predicate.get("kind") if isinstance(predicate, Mapping) else None
    inner_command = (
        _non_pytest_custom_predicate_command(task)
        if kind == "ruff+custom"
        else exit_predicate_command(task)
    )
    return _cell_sandbox_command(
        inner_command,
        workdir,
        repo,
        extra_environment={
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTEST_ADDOPTS": "",
        },
        workspace_writable=False,
    )


def _pytest_targets(task: Mapping[str, Any]) -> list[str]:
    predicate = task.get("exit_predicate")
    if not isinstance(predicate, Mapping):
        return []
    target = predicate.get("target")
    if not isinstance(target, str):
        return []
    if predicate.get("kind") == "pytest":
        return [target]
    if predicate.get("kind") == "ruff+custom":
        return re.findall(
            r"(?:^|&&)\s*(?:uv\s+run\s+)?pytest\s+([^\s;&|]+)",
            target,
        )
    return []


def _attested_pytest_command(
    target: str,
    workdir: Path,
    repo: Path,
) -> list[str]:
    return _cell_sandbox_command(
        [
            "python",
            "-I",
            str(PYTEST_HARNESS_ROOT / "pytest_attested_runner.py"),
            target,
        ],
        workdir,
        repo,
        extra_environment={
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTEST_ADDOPTS": "",
        },
        readonly_mounts=[
            (ATTESTED_RUNNER, PYTEST_HARNESS_ROOT / "pytest_attested_runner.py"),
            (PYTEST_WORKER_LAUNCHER, PYTEST_HARNESS_ROOT / "python-isolated"),
        ],
        workspace_writable=False,
    )


def _validate_completion_attestation(
    raw: Any,
    *,
    returncode: int,
    runtime_prefix: Path,
) -> str | None:
    next_action = (
        "Next action: discard the cell, restore the trusted runner/control files, "
        "and rerun the predicate."
    )
    if not isinstance(raw, Mapping):
        return f"pytest completion attestation root is not an object. {next_action}"
    collected = raw.get("collected")
    terminal = raw.get("terminal")
    if (
        raw.get("schema_version") != 4
        or raw.get("completed") is not True
        or raw.get("exit_code") != returncode
        or raw.get("attester_process") != "xdist-controller"
        or raw.get("worker_count") != 1
        or raw.get("worker_integrity_guard")
        != "early-runtime-introspection-and-hook-mutation-audit+"
        "collection-plugin-registration-freeze+sealed-call-capture+raw-worker-outcomes/v5"
        or not isinstance(raw.get("attester_pid"), int)
        or raw.get("xdist_version") != pytest_xdist_version()
        or not isinstance(collected, list)
        or not collected
        or len(set(collected)) != len(collected)
        or not isinstance(terminal, Mapping)
        or set(terminal) != set(collected)
    ):
        return (
            "pytest completion attestation does not match the completed test lifecycle. "
            f"{next_action}"
        )
    outcomes = list(terminal.values())
    if any(outcome not in {"passed", "failed", "skipped"} for outcome in outcomes):
        return f"pytest completion attestation contains an invalid terminal outcome. {next_action}"
    if returncode == 0 and any(outcome != "passed" for outcome in outcomes):
        return f"pytest reported success with a non-passing raw worker outcome. {next_action}"
    expected_prefix = runtime_prefix.resolve()
    try:
        recorded_prefix = Path(str(raw.get("runtime_prefix") or "")).resolve()
        pytest_origin = Path(str(raw.get("pytest_origin") or "")).resolve()
        xdist_origin = Path(str(raw.get("xdist_origin") or "")).resolve()
        pytest_origin.relative_to(expected_prefix)
        xdist_origin.relative_to(expected_prefix)
    except (OSError, ValueError):
        return f"pytest completion attestation has an untrusted runtime origin. {next_action}"
    workspace = Path("/workspace")
    if (
        recorded_prefix != expected_prefix
        or pytest_origin == workspace
        or workspace in pytest_origin.parents
        or xdist_origin == workspace
        or workspace in xdist_origin.parents
    ):
        return f"pytest completion attestation has an untrusted runtime origin. {next_action}"
    return None


def _parse_completion_attestation(
    stderr: str,
    *,
    process_returncode: int,
    runtime_prefix: Path,
) -> tuple[int | None, str | None]:
    next_action = (
        "Next action: discard the cell, restore the trusted runner/control files, "
        "and rerun the predicate."
    )
    logical_returncode = process_returncode
    if not 0 <= logical_returncode <= PYTEST_MAX_EXIT_CODE:
        return None, (
            "pytest controller did not reach the trusted completion boundary "
            f"(process return code {process_returncode}). {next_action}"
        )
    records = [
        line.removeprefix(PYTEST_ATTESTATION_PREFIX)
        for line in stderr.splitlines()
        if line.startswith(PYTEST_ATTESTATION_PREFIX)
    ]
    if len(records) != 1:
        return None, (
            f"pytest runner emitted {len(records)} lifecycle records; exactly one is required. "
            f"{next_action}"
        )
    try:
        raw = json.loads(records[0])
    except json.JSONDecodeError as exc:
        return None, f"pytest completion attestation is malformed: {exc}. {next_action}"
    error = _validate_completion_attestation(
        raw,
        returncode=logical_returncode,
        runtime_prefix=runtime_prefix,
    )
    return (None, error) if error else (logical_returncode, None)


def _run_predicate_command(command: Sequence[str]) -> tuple[int, bool, str, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PREDICATE_TIMEOUT_SECONDS,
            check=False,
        )
        return (
            result.returncode,
            False,
            _coerce_text(result.stdout),
            _coerce_text(result.stderr),
        )
    except subprocess.TimeoutExpired as exc:
        return 124, True, _coerce_text(exc.stdout), _coerce_text(exc.stderr)
    except OSError as exc:
        raise DriverError(
            f"cannot execute the predicate sandbox: {exc}. "
            "Next action: repair bwrap and rerun the cell; no unsandboxed fallback is allowed."
        ) from exc


def evaluate_exit(
    task: Mapping[str, Any],
    workdir: Path,
    repo: Path = DEFAULT_REPO,
) -> dict[str, Any]:
    """Run the predicate and independently attest that hidden pytest items completed."""
    predicate = task.get("exit_predicate")
    kind = predicate.get("kind") if isinstance(predicate, Mapping) else None
    output_parts: list[str] = []
    returncode = 0
    timed_out = False
    completion_attested = False
    if kind == "ruff+custom":
        returncode, timed_out, stdout, stderr = _run_predicate_command(
            _predicate_sandbox_command(task, workdir, repo)
        )
        output_parts.extend([stdout, stderr])
    targets = _pytest_targets(task)
    if returncode == 0 and not timed_out:
        for target in targets:
            command = _attested_pytest_command(target, workdir, repo)
            process_returncode, test_timed_out, stdout, stderr = _run_predicate_command(command)
            output_parts.extend([stdout, stderr])
            logical_returncode, attestation_error = _parse_completion_attestation(
                stderr,
                process_returncode=process_returncode,
                runtime_prefix=_active_project_environment(repo),
            )
            if test_timed_out:
                returncode = 124
                timed_out = True
                break
            if attestation_error or logical_returncode is None:
                output_parts.append(f"\nHARNESS: {attestation_error}\n")
                returncode = 86
                break
            completion_attested = True
            returncode = logical_returncode
            if returncode != 0:
                break
    output = "".join(output_parts)
    return {
        "passed": returncode == 0 and not timed_out,
        "returncode": returncode,
        "timed_out": timed_out,
        "sandbox": "bubblewrap",
        "completion_attested": completion_attested,
        "pytest_targets": targets,
        "output_tail": output[-4_000:],
    }


def render_cell_prompt(task: Mapping[str, Any]) -> str:
    work_item = task.get("work_item")
    if not isinstance(work_item, str) or not work_item.strip():
        raise DriverError(
            f"task {task.get('task_id')} has no work item. "
            "Next action: add the bounded task instruction before measuring it."
        )
    predicate = " ".join(exit_predicate_command(task))
    return CELL_PROMPT_TEMPLATE.format(work_item=work_item.strip(), exit_predicate=predicate)


def _permission_filesystem_override(read_paths: Sequence[Path]) -> str:
    entries: list[tuple[str, str]] = [
        (":root", "deny"),
        (":minimal", "read"),
        ("/opt/bin", "read"),
        ("/opt/codex", "read"),
        ("/codex-home", "deny"),
    ]
    entries.extend((str(path.resolve()), "read") for path in read_paths)
    rendered = ",".join(f"{json.dumps(path)}={json.dumps(access)}" for path, access in entries)
    rendered += ',":workspace_roots"={"."="write"}'
    return f"permissions.meas-cell.filesystem={{{rendered}}}"


def build_codex_command(
    config: CodexRunConfig,
    workdir: Path,
    *,
    codex_binary: str | None = None,
    permission_read_paths: Sequence[Path] = (),
) -> list[str]:
    """Build the non-interactive command with a closed, λ-recorded tool surface."""
    command = [
        codex_binary or config.codex_binary,
        "exec",
        "--strict-config",
        "--ephemeral",
        "--ignore-rules",
        "--json",
        "--color",
        "never",
        "--model",
        config.model,
        "--cd",
        str(workdir),
        "-c",
        f"model_reasoning_effort={json.dumps(config.reasoning_effort)}",
        "-c",
        'approval_policy="never"',
        "-c",
        'web_search="disabled"',
        "-c",
        _permission_filesystem_override(permission_read_paths),
    ]
    command.append("-")
    return command


def _codex_runtime_mount(config: CodexRunConfig) -> tuple[Path, Path, str]:
    """Resolve a read-only Codex runtime mount and its sandbox-local executable."""
    binary = shutil.which(config.codex_binary) or config.codex_binary
    resolved = Path(binary).expanduser().resolve()
    if not resolved.is_file():
        raise DriverError(
            f"Codex binary was not found: {config.codex_binary}. "
            "Next action: install the Codex CLI or pass --codex-binary explicitly."
        )
    package_root = next(
        (
            parent
            for parent in resolved.parents
            if parent.name == "codex" and parent.parent.name == "@openai"
        ),
        None,
    )
    if package_root is not None:
        native_binaries = sorted(
            package_root.glob("node_modules/@openai/codex-*/vendor/*/bin/codex")
        )
        if len(native_binaries) == 1:
            sandbox_root = Path("/opt/codex")
            executable = sandbox_root / native_binaries[0].relative_to(package_root)
            return package_root, sandbox_root, str(executable)
    sandbox_binary = Path("/opt/bin/codex")
    return resolved, sandbox_binary, str(sandbox_binary)


def _codex_auth_file() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    auth_file = codex_home / "auth.json"
    if not auth_file.is_file():
        raise DriverError(
            f"Codex authentication file is missing under {codex_home}. "
            "Next action: authenticate the Codex CLI, then rerun the measurement."
        )
    return auth_file


def _agent_boundary_command(
    inner_command: Sequence[str],
    workdir: Path,
    repo: Path,
    *,
    extra_environment: Mapping[str, str] | None = None,
    readonly_mounts: Sequence[tuple[Path, Path]] = (),
) -> list[str]:
    """Apply the externally enforced cell-only read boundary used for Codex."""
    return _cell_sandbox_command(
        inner_command,
        workdir,
        repo,
        extra_environment=extra_environment,
        readonly_mounts=readonly_mounts,
        share_network=True,
        disable_nested_userns=False,
    )


def _agent_sandbox_command(
    config: CodexRunConfig,
    workdir: Path,
    repo: Path = DEFAULT_REPO,
) -> list[str]:
    """Confine Codex reads to the cell while retaining provider network access."""
    runtime_source, runtime_destination, executable = _codex_runtime_mount(config)
    readonly_mounts: list[tuple[Path, Path]] = [
        (runtime_source, runtime_destination),
        (_codex_auth_file(), Path("/codex-home/auth.json")),
        (CODEX_CELL_CONFIG, Path("/codex-home/config.toml")),
    ]
    for host_path in (
        Path("/etc/resolv.conf"),
        Path("/etc/hosts"),
        Path("/etc/nsswitch.conf"),
        Path("/etc/gai.conf"),
        Path("/etc/ssl/certs"),
    ):
        if host_path.exists():
            readonly_mounts.append((host_path, host_path))
    environment = {
        "CODEX_HOME": "/codex-home",
        "CODEX_MANAGED_PACKAGE_ROOT": str(runtime_destination),
        "HAPAX_CC_TASK_GATE": "0",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    for name in _NETWORK_ENV_KEYS:
        value = os.environ.get(name)
        if value:
            environment[name] = value
    inner_command = build_codex_command(
        config,
        Path("/workspace"),
        codex_binary=executable,
        permission_read_paths=_project_environment_read_paths(repo),
    )
    return _agent_boundary_command(
        inner_command,
        workdir,
        repo,
        extra_environment=environment,
        readonly_mounts=readonly_mounts,
    )


def _active_project_environment(repo: Path = DEFAULT_REPO) -> Path:
    interpreter_environment = Path(sys.executable).absolute().parent.parent
    if (interpreter_environment / "pyvenv.cfg").is_file():
        return interpreter_environment
    return repo / ".venv"


def _project_environment_read_paths(repo: Path = DEFAULT_REPO) -> tuple[Path, ...]:
    """Return only the environment paths model tools need for pinned checks."""
    project_environment = _active_project_environment(repo).resolve()
    paths = [project_environment]
    interpreter = (project_environment / "bin/python").resolve()
    try:
        interpreter.relative_to(project_environment)
    except ValueError:
        python_runtime = next(
            (
                parent
                for parent in interpreter.parents
                if parent.name == "python" and parent.parent.name == "uv"
            ),
            interpreter.parent.parent,
        )
        paths.append(python_runtime)
    return tuple(paths)


def _codex_environment() -> dict[str, str]:
    """Return the minimal host environment needed to launch Bubblewrap itself."""
    return {"PATH": os.defpath, "NO_COLOR": "1"}


def _redacted_transcript_command(command: Sequence[str]) -> list[str]:
    redacted = list(command)
    for index, token in enumerate(redacted[:-2]):
        if token == "--setenv" and redacted[index + 1] in _NETWORK_ENV_KEYS:
            redacted[index + 2] = "<redacted-environment-value>"
    return redacted


def _post_agent_git_command(*arguments: str) -> list[str]:
    """Build Git with executable config surfaces pinned off."""
    return [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "diff.external=",
        "-c",
        "pager.status=false",
        *arguments,
    ]


def _run_post_agent_command(
    command: Sequence[str],
    *,
    workdir: Path,
    input_text: str | None = None,
    timeout: int = 300,
) -> CompletedTextProcess:
    """Run a post-agent command without host env, network, or filesystem access."""
    sandbox_command = _cell_sandbox_command(
        command,
        workdir,
        DEFAULT_REPO,
        extra_environment={
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_PAGER": "cat",
            "GIT_OPTIONAL_LOCKS": "0",
        },
    )
    try:
        return subprocess.run(
            sandbox_command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DriverError(
            f"post-agent command timed out after {timeout}s: {' '.join(command)}. "
            "Next action: discard the cell and inspect its diff for pathological files."
        ) from exc
    except OSError as exc:
        raise DriverError(
            f"cannot execute the post-agent sandbox: {exc}. "
            "Next action: repair bwrap and rerun; no host-side fallback is allowed."
        ) from exc


def _checked_post_agent_stdout(
    command: Sequence[str],
    *,
    workdir: Path,
    input_text: str | None = None,
    timeout: int = 300,
    strip: bool = True,
) -> str:
    result = _run_post_agent_command(
        command,
        workdir=workdir,
        input_text=input_text,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-800:]
        raise DriverError(
            f"sandboxed post-agent command failed ({result.returncode}): "
            f"{' '.join(command)}: {detail}. "
            "Next action: discard the cell and inspect the captured transcript."
        )
    return result.stdout.strip() if strip else result.stdout


def capture_cell_diff(workdir: Path, baseline: str) -> dict[str, Any]:
    """Capture model changes with all Git operations confined to the cell sandbox."""
    _checked_post_agent_stdout(
        _post_agent_git_command("add", "--intent-to-add", "--all"),
        workdir=workdir,
    )
    diff = _checked_post_agent_stdout(
        _post_agent_git_command(
            "diff", "--binary", "--no-ext-diff", "--no-textconv", baseline, "--"
        ),
        workdir=workdir,
        strip=False,
    )
    status = _checked_post_agent_stdout(
        _post_agent_git_command("status", "--short", "--no-ahead-behind"),
        workdir=workdir,
    )
    return {
        "diff": diff,
        "diff_bytes": len(diff.encode()),
        "diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
        "git_status": status.splitlines(),
    }


def driver(
    *,
    task: Mapping[str, Any],
    workdir: Path,
    config: CodexRunConfig | None = None,
    process_runner: ProcessRunner = subprocess.run,
) -> dict[str, Any]:
    """Runner seam: execute Codex inside an already-prepared cell workdir."""
    config = config or CodexRunConfig()
    prompt = render_cell_prompt(task)
    command = _agent_sandbox_command(config, workdir)
    baseline = _checked_stdout(["git", "-C", str(workdir), "rev-parse", "HEAD"])
    started = time.monotonic()
    timed_out = False
    error: str | None = None
    try:
        completed = process_runner(
            command,
            cwd=workdir,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
            check=False,
            env=_codex_environment(),
        )
        returncode = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        stdout = _coerce_text(exc.stdout)
        stderr = _coerce_text(exc.stderr)
        error = (
            f"codex exec timed out after {config.timeout_seconds}s. "
            "Next action: inspect the partial transcript/diff and retain the cell as a failure "
            "or rerun it under a newly hashed timeout configuration."
        )
    except OSError as exc:
        returncode = 127
        stdout = ""
        stderr = ""
        error = (
            f"cannot execute the externally confined Codex process: {exc}. "
            "Next action: repair the Codex CLI or Bubblewrap installation and rerun the cell."
        )
    seconds = round(time.monotonic() - started, 3)
    diff_record = capture_cell_diff(workdir, baseline)
    return {
        "model": config.model,
        "harness": HARNESS_NAME,
        "seconds": seconds,
        "wh_milli": None,
        "transcript_ref": None,
        "transcript": {
            "format": "codex-exec-jsonl",
            "command": _redacted_transcript_command(command[:-1]) + ["<prompt-from-stdin>"],
            "returncode": returncode,
            "timed_out": timed_out,
            "error": error,
            "stdout": stdout,
            "stderr": stderr,
        },
        **diff_record,
    }


def codex_binary_version(config: CodexRunConfig) -> str:
    try:
        result = _run_text([config.codex_binary, "--version"], timeout=30)
    except OSError as exc:
        raise DriverError(
            f"cannot execute Codex binary {config.codex_binary}: {exc}. "
            "Next action: install the Codex CLI or pass --codex-binary explicitly."
        ) from exc
    if result.returncode != 0:
        raise DriverError(
            f"cannot read Codex version: {result.stderr.strip()[-500:]}. "
            "Next action: repair the Codex CLI installation and rerun."
        )
    return result.stdout.strip()


def lambda_config(
    config: CodexRunConfig,
    binary_version: str,
    sandbox_version: str | None = None,
) -> dict[str, Any]:
    """Build the canonical λ fields; closed-model weight opacity is explicit."""
    sandbox_version = sandbox_version or predicate_sandbox_version()
    return {
        "model_weights_sha256": f"unpublished-provider-managed:{config.model}",
        "serving_stack": "openai-codex",
        "serving_version": f"provider-managed:{config.model}",
        "quant_params": {"provider_managed": True},
        "prompt_template_sha256": hashlib.sha256(CELL_PROMPT_TEMPLATE.encode()).hexdigest(),
        "decode_params": {"model_reasoning_effort": config.reasoning_effort},
        "harness_binary_version": f"{binary_version};{DRIVER_VERSION}",
        "tool_surface_config": {
            "approval_policy": "never",
            "ephemeral": True,
            "exec_output": "jsonl",
            "legacy_full_auto": False,
            "mcp": "disabled-by-synthetic-config",
            "sandbox": "bubblewrap-read-confined+permission-profile",
            "agent_filesystem": {
                "credential_enforcement": "codex-permission-profile+pinned-harness-binary",
                "credential_enforcement_binary": binary_version,
                "credential_path": "denied-to-model-tools-by-codex-permission-profile",
                "host_reads": "cell-and-explicit-runtime-mounts-only",
                "network": "shared-for-provider-api",
                "outer_sandbox": "bubblewrap",
                "permission_profile": "meas-cell",
                "permission_profile_sha256": codex_cell_config_sha256(),
                "sandbox_version": sandbox_version,
                "system_roots": "asserted-no-source-repo-install-links",
            },
            "codex_timeout_seconds": config.timeout_seconds,
            "exit_predicate": {
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
                    "collection-plugin-registration-freeze+sealed-call-capture+"
                    "raw-worker-outcomes/v5"
                ),
                "pytest_worker_launcher_sha256": pytest_worker_launcher_sha256(),
                "pytest_xdist_version": pytest_xdist_version(),
                "rootdir": "/workspace",
                "runner_sha256": attested_runner_sha256(),
                "sandbox": "bubblewrap",
                "sandbox_version": sandbox_version,
                "scoring_controls_postcheck": "byte-for-byte",
                "timeout_seconds": PREDICATE_TIMEOUT_SECONDS,
                "worker_conftest": "trusted-scoring-controls-enabled",
                "workspace": "read-only",
            },
            "post_agent_git": {
                "environment": "cleared",
                "executable_config": "disabled",
                "network": "unshared",
                "sandbox": "bubblewrap",
            },
            "scoring_diff_excludes": list(SCORING_DIFF_EXCLUDES),
            "user_config": "synthetic-read-only-measurement-profile",
            "uv_environment": "driver-interpreter-no-sync",
            "web_search": "disabled",
        },
        "context_mode": "agentic-parent-checkout+clean-score-checkout+merge-tests-post-exec",
    }


def lambda_hash(fields: Mapping[str, Any]) -> str:
    missing = [key for key in LAMBDA_KEYS if key not in fields]
    if missing:
        raise DriverError(
            f"missing lambda fields: {', '.join(missing)}. "
            "Next action: repair the λ configuration before publishing results."
        )
    canonical = json.dumps(dict(fields), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def apply_agent_diff_for_scoring(workdir: Path, diff: str) -> None:
    """Apply only solution-bearing model changes to a clean scoring checkout."""
    if not diff.strip():
        return
    command = _post_agent_git_command(
        "apply",
        "--binary",
        "--whitespace=nowarn",
        *(f"--exclude={pattern}" for pattern in SCORING_DIFF_EXCLUDES),
        "-",
    )
    _checked_post_agent_stdout(
        command,
        workdir=workdir,
        input_text=diff,
    )


def run_cell(
    task: Mapping[str, Any],
    *,
    repo: Path = DEFAULT_REPO,
    config: CodexRunConfig | None = None,
    commits: CommitPair | None = None,
    executor: CellExecutor = driver,
    evaluator: ExitEvaluator = evaluate_exit,
    binary_version: str | None = None,
    sandbox_version: str | None = None,
) -> dict[str, Any]:
    """Prepare, execute, score, and λ-stamp one isolated measurement cell."""
    config = config or CodexRunConfig()
    commits = commits or resolve_pr_commits(task, repo)
    version = binary_version or codex_binary_version(config)
    fields = lambda_config(config, version, sandbox_version)
    task_id = str(task.get("task_id") or "")
    if not task_id:
        raise DriverError(
            "task has no task_id. Next action: repair the task set before measuring it."
        )

    with tempfile.TemporaryDirectory(prefix="meas-codex-cell-") as raw_workdir:
        agent_workdir = Path(raw_workdir)
        prepare_cell_checkout(repo, commits.parent, agent_workdir)
        outcome = executor(task=task, workdir=agent_workdir, config=config)
        agent_diff = str(outcome.get("diff") or "")
        with tempfile.TemporaryDirectory(prefix="meas-codex-score-") as raw_scoring_workdir:
            scoring_workdir = Path(raw_scoring_workdir)
            prepare_cell_checkout(repo, commits.parent, scoring_workdir)
            apply_agent_diff_for_scoring(scoring_workdir, agent_diff)
            predicate_files = install_merge_version_tests(repo, scoring_workdir, commits)
            scoring_controls = verify_scoring_controls(
                repo,
                scoring_workdir,
                commits,
                predicate_files,
            )
            exit_result = evaluator(task, scoring_workdir, repo)
            post_scoring_controls = verify_scoring_controls(
                repo,
                scoring_workdir,
                commits,
                predicate_files,
            )

    cell = {
        "model": outcome.get("model", config.model),
        "harness": outcome.get("harness", HARNESS_NAME),
        "seconds": outcome.get("seconds"),
        "wh_milli": outcome.get("wh_milli"),
        "transcript_ref": outcome.get("transcript_ref"),
        "transcript": outcome.get("transcript"),
        "diff": outcome.get("diff", ""),
        "diff_bytes": outcome.get("diff_bytes", 0),
        "diff_sha256": outcome.get("diff_sha256"),
    }
    transcript = outcome.get("transcript") or {}
    codex_returncode = transcript.get("returncode")
    codex_timed_out = bool(transcript.get("timed_out"))
    predicate_passed = bool(exit_result.get("passed"))
    passed = predicate_passed and codex_returncode == 0 and not codex_timed_out
    return {
        "lambda_hash": lambda_hash(fields),
        "lambda_config": fields,
        "task_id": task_id,
        "cell": cell,
        "cell_result": {
            "class": task.get("class"),
            "difficulty": task.get("difficulty"),
            "pr": task.get("pr"),
            "parent": commits.parent,
            "merge": commits.merge,
            "predicate_files": predicate_files,
            "scoring_controls": scoring_controls,
            "post_scoring_controls": post_scoring_controls,
            "scoring_diff_excludes": list(SCORING_DIFF_EXCLUDES),
            "passed": passed,
            "exit": exit_result,
            "codex_returncode": codex_returncode,
            "codex_timed_out": codex_timed_out,
            "git_status": outcome.get("git_status", []),
        },
    }


def run_fixture_self_check() -> dict[str, Any]:
    """Exercise the complete scoring path with a local fixture and no provider call."""
    with tempfile.TemporaryDirectory(prefix="meas-codex-self-check-") as raw_directory:
        source_repo = Path(raw_directory) / "source"
        source_repo.mkdir()
        _checked_stdout(["git", "init", "--quiet", str(source_repo)])
        (source_repo / "module.py").write_text("VALUE = 0\n", encoding="utf-8")
        tests = source_repo / "tests"
        tests.mkdir()
        test_path = tests / "test_module.py"
        test_path.write_text(
            "from module import VALUE\n\n"
            "def test_value(conftest_value):\n"
            "    assert VALUE == 0\n"
            "    assert conftest_value == 0\n",
            encoding="utf-8",
        )
        (source_repo / "conftest.py").write_text(
            "import os\n"
            "if 'PYTEST_XDIST_WORKER' not in os.environ:\n"
            "    raise RuntimeError('conftest executed in attestation controller')\n"
            "import pytest\n"
            "from module import VALUE\n\n"
            "@pytest.fixture\n"
            "def conftest_value():\n"
            "    return VALUE\n",
            encoding="utf-8",
        )
        (source_repo / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\npythonpath = ["."]\n',
            encoding="utf-8",
        )

        def commit(message: str) -> str:
            _checked_stdout(["git", "-C", str(source_repo), "add", "--all"])
            _checked_stdout(
                [
                    "git",
                    "-c",
                    "user.name=MEAS Fixture",
                    "-c",
                    "user.email=meas-fixture@example.invalid",
                    "-C",
                    str(source_repo),
                    "commit",
                    "--quiet",
                    "-m",
                    message,
                ]
            )
            return _checked_stdout(["git", "-C", str(source_repo), "rev-parse", "HEAD"])

        parent = commit("fixture parent")
        (source_repo / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        test_path.write_text(
            "from module import VALUE\n\n"
            "def test_value(conftest_value):\n"
            "    assert VALUE == 1\n"
            "    assert conftest_value == 1\n",
            encoding="utf-8",
        )
        merge = commit("fixture merge")
        task = {
            "task_id": "provider-free-fixture",
            "class": "build",
            "difficulty": "fixture",
            "pr": 1,
            "work_item": "Set VALUE to one.",
            "exit_predicate": {"kind": "pytest", "target": "tests/test_module.py"},
        }

        def fixture_executor(
            *,
            task: Mapping[str, Any],
            workdir: Path,
            config: CodexRunConfig,
        ) -> dict[str, Any]:
            del task
            baseline = _checked_stdout(["git", "-C", str(workdir), "rev-parse", "HEAD"])
            (workdir / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            return {
                "model": config.model,
                "harness": HARNESS_NAME,
                "seconds": 0.0,
                "wh_milli": None,
                "transcript_ref": None,
                "transcript": {
                    "format": "provider-free-fixture",
                    "returncode": 0,
                    "timed_out": False,
                    "stdout": "",
                    "stderr": "",
                },
                **capture_cell_diff(workdir, baseline),
            }

        record = run_cell(
            task,
            repo=source_repo,
            commits=CommitPair(parent=parent, merge=merge),
            executor=fixture_executor,
            binary_version="provider-free-fixture",
            sandbox_version=predicate_sandbox_version(),
        )
    exit_result = record["cell_result"]["exit"]
    return {
        "completion_attested": exit_result["completion_attested"],
        "driver_version": DRIVER_VERSION,
        "fixture": "clean-score-checkout+merge-test+worker-only-conftest+isolated-xdist",
        "lambda_hash": record["lambda_hash"],
        "passed": record["cell_result"]["passed"],
        "predicate_files": record["cell_result"]["predicate_files"],
        "returncode": exit_result["returncode"],
    }


def _target_paths(task: Mapping[str, Any]) -> list[str]:
    predicate = task.get("exit_predicate")
    if not isinstance(predicate, Mapping) or not isinstance(predicate.get("target"), str):
        return []
    target = str(predicate["target"])
    if predicate.get("kind") == "pytest":
        return [target]
    return [match.rstrip(",)") for match in _PATH_TOKEN.findall(target)]


def dry_run_validate(
    tasks: Iterable[Mapping[str, Any]],
    *,
    repo: Path = DEFAULT_REPO,
    resolver: CommitResolver = resolve_pr_commits,
) -> dict[str, Any]:
    """Validate selected cells without launching Codex or creating checkouts."""
    rows: list[dict[str, Any]] = []
    for task in tasks:
        errors: list[str] = []
        task_id = str(task.get("task_id") or "")
        targets = _target_paths(task)
        if not task_id:
            errors.append(
                "missing task_id. Next action: add the task's stable task_id to the input row."
            )
        if not isinstance(task.get("work_item"), str) or not str(task.get("work_item")).strip():
            errors.append(
                "missing work_item. Next action: add the implementation instruction to the input row."
            )
        if not targets:
            errors.append(
                "no predicate target paths. Next action: add a supported exit_predicate target."
            )
        missing_targets = [target for target in targets if not (repo / target).exists()]
        if missing_targets:
            errors.append(
                f"missing current targets: {', '.join(missing_targets)}. "
                "Next action: correct the predicate target or restore it in the source checkout."
            )
        commits: CommitPair | None = None
        try:
            commits = resolver(task, repo)
            if not merge_version_test_paths(repo, commits):
                errors.append(
                    "merge changes no tests. Next action: select a task whose merge commit adds or "
                    "changes a discriminating test."
                )
        except (DriverError, OSError, subprocess.SubprocessError) as exc:
            detail = str(exc)
            if "Next action:" not in detail:
                detail = (
                    f"{detail}. Next action: repair the task's PR/commit metadata and rerun "
                    "--dry-run."
                )
            errors.append(detail)
        rows.append(
            {
                "task_id": task_id,
                "valid": not errors,
                "errors": errors,
                "parent": commits.parent if commits else None,
                "merge": commits.merge if commits else None,
            }
        )
    return {
        "valid": sum(1 for row in rows if row["valid"]),
        "total": len(rows),
        "cells": rows,
    }


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except OSError as exc:
        raise DriverError(
            f"cannot atomically write result artifact {path}: {exc}. "
            "Next action: repair the destination directory permissions or free space, "
            "then resume the pilot from its last valid checkpoint."
        ) from exc
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def _write_report(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise DriverError(
            f"cannot write pilot report {path}: {exc}. "
            "Next action: repair the report destination permissions or free space, "
            "then regenerate the report from the valid JSON checkpoint."
        ) from exc


def _summary(
    results: Sequence[Mapping[str, Any]],
    selection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    passed = sum(1 for result in results if result.get("cell_result", {}).get("passed"))
    baseline = dict(DIRECT_API_35B_BASELINE)
    selected_ids = selection.get("task_ids") if selection is not None else None
    result_ids = [result.get("task_id") for result in results]
    baseline["comparable"] = bool(
        isinstance(selected_ids, list)
        and result_ids == selected_ids
        and selection.get("requested") == baseline["total"]
        and selection.get("difficulty") == baseline["difficulty"]
        and selection.get("task_set_sha256") == baseline["task_set_sha256"]
    )
    return {
        "passed": passed,
        "total": len(results),
        "pass_rate": round(passed / len(results), 6) if results else None,
        "direct_api_35b_baseline": baseline,
    }


def render_result_note(
    payload: Mapping[str, Any],
    result_path: Path | None = None,
) -> str:
    """Render the one-page pilot note from the durable JSON result."""
    summary = payload.get("summary", {})
    passed = summary.get("passed", 0)
    total = summary.get("total", 0)
    rate = summary.get("pass_rate")
    percent = f"{float(rate) * 100:.1f}%" if rate is not None else "n/a"
    lambda_set = payload.get("lambda_set", [])
    lambda_short = str(lambda_set[0])[:12] if lambda_set else "missing"
    model = payload.get("model", "unknown")
    completed = payload.get("completed_at") or payload.get("updated_at")
    baseline = summary.get("direct_api_35b_baseline", DIRECT_API_35B_BASELINE)
    comparable = baseline.get("comparable") is True
    if comparable:
        comparison = (
            f"The Codex CLI agentic harness passed {passed} of {total} easy cells, "
            f"versus {baseline.get('passed')} of {baseline.get('total')} for the 35B "
            "direct-API single-shot baseline."
        )
    else:
        comparison = (
            f"This partial run covers {total} cells and is not directly comparable "
            f"with the {baseline.get('total')}-cell direct-API baseline."
        )
    recheck_target = (
        shlex.quote(str(result_path.resolve())) if result_path is not None else "pilot-result.json"
    )
    tool_surface = payload.get("lambda_config", {}).get("tool_surface_config", {})
    predicate_surface = tool_surface.get("exit_predicate", {})
    codex_sandbox = tool_surface.get("sandbox", "unknown")
    predicate_boundary = (
        "The deterministic predicate ran in Bubblewrap with a cleared environment and "
        "an unshared network namespace and a read-only scoring checkout. Agent-changed "
        "solution code ran in one xdist worker after runtime-frame introspection and "
        "mutation of registered hook functions were frozen before conftest import, and "
        "plugin registration was frozen before test-module collection. Pytest's registered "
        "call-capture chain was detached from mutable public globals before conftest import, "
        "and raw call outcomes were recorded in the worker without consulting mutable pytest "
        "report globals; "
        "the separate trusted controller had to emit exactly one lifecycle record showing "
        "every worker-collected hidden pytest item reached a terminal report."
        if predicate_surface.get("completion_attestation")
        else "The deterministic predicate ran in Bubblewrap with a cleared environment and "
        "an unshared network namespace."
        if predicate_surface
        else "This legacy result predates recorded predicate-sandbox metadata."
    )
    if tool_surface.get("scoring_diff_excludes"):
        checkout_boundary = (
            "Each cell used isolated agent and clean scoring checkouts at the authoritative "
            f"PR parent. Codex edited under the `{codex_sandbox}` boundary, externally limited "
            "to cell/runtime reads, with user config, MCP, and web search disabled. The harness "
            "captured JSONL stdout/stderr and the "
            "post-exec diff inside Bubblewrap, applied only solution-bearing paths to the "
            "scoring checkout, then installed merge-version tests through no-follow file "
            "descriptors."
        )
    else:
        checkout_boundary = (
            "This legacy result used one isolated shallow checkout at the authoritative PR "
            f"parent. Codex edited under the recorded `{codex_sandbox}` sandbox; clean "
            "scoring-checkout isolation was not part of that historical λ."
        )
    return f"""# MEAS Tier-0 Codex CLI pilot

- Completed: {completed}
- Arm: `{model}` through `{HARNESS_NAME}`
- Result: **{passed}/{total} ({percent})**
- Direct-API 35B single-shot baseline: **{baseline.get("passed")}/{baseline.get("total")} ({float(baseline.get("pass_rate", 0.0)) * 100:.1f}%)**
- λ: `{lambda_short}` (full configuration is embedded in every JSON cell)

## Finding

{comparison} A full-size comparison establishes only the measured harness/model pair;
it does not isolate model quality from harness effects.

## Measurement boundary

{checkout_boundary} {predicate_boundary}
The proprietary model's weight hash and serving quantization are not published; those
λ fields say `provider-managed` rather than pretending a weights digest exists.

## Recheck

`uv run python eval/meas/driver_codex_cli.py --verify-result {recheck_target}`
"""


def _task_contract(task: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task.get("task_id"),
        "class": task.get("class"),
        "difficulty": task.get("difficulty"),
        "pr": task.get("pr"),
        "work_item": task.get("work_item"),
        "exit_predicate": task.get("exit_predicate"),
    }


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _result_integrity_hash(result: Mapping[str, Any]) -> str:
    unsealed = {key: value for key, value in result.items() if key != "result_sha256"}
    return _canonical_hash(unsealed)


def _seal_result(result: dict[str, Any]) -> dict[str, Any]:
    result["result_sha256"] = _result_integrity_hash(result)
    return result


def _artifact_integrity_hash(payload: Mapping[str, Any]) -> str:
    unsealed = json.loads(json.dumps(payload))
    witness = unsealed.get("witness")
    if isinstance(witness, dict):
        witness.pop("artifact_sha256", None)
    return _canonical_hash(unsealed)


def _selection_contract(
    tasks: Sequence[Mapping[str, Any]],
    commits: Mapping[str, CommitPair],
) -> dict[str, Any]:
    task_ids = [str(task.get("task_id") or "") for task in tasks]
    if any(not task_id for task_id in task_ids) or len(set(task_ids)) != len(task_ids):
        raise DriverError(
            "selected tasks have missing or duplicate task IDs. "
            "Next action: repair the task set before starting the pilot."
        )
    difficulties = sorted({str(task.get("difficulty")) for task in tasks})
    commit_rows = [
        {
            "task_id": task_id,
            "parent": commits[task_id].parent,
            "merge": commits[task_id].merge,
        }
        for task_id in task_ids
    ]
    return {
        "difficulty": difficulties[0] if len(difficulties) == 1 else difficulties,
        "requested": len(tasks),
        "task_ids": task_ids,
        "task_set_sha256": _canonical_hash([_task_contract(task) for task in tasks]),
        "commit_set_sha256": _canonical_hash(commit_rows),
    }


def _resume_error(detail: str) -> DriverError:
    return DriverError(
        f"existing output is incompatible: {detail}. "
        "Next action: use a new output path, or restore the exact recorded "
        "task/commit/λ configuration before resuming."
    )


def _validated_resume_results(
    existing: Mapping[str, Any],
    *,
    config: CodexRunConfig,
    fields: Mapping[str, Any],
    expected_lambda: str,
    selection: Mapping[str, Any],
    commits: Mapping[str, CommitPair],
    tasks: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    expected_top_level = {
        "schema_version": 3,
        "driver": DRIVER_VERSION,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "lambda_set": [expected_lambda],
        "lambda_config": fields,
        "selection": selection,
        "tasks": [_task_contract(tasks[task_id]) for task_id in selection["task_ids"]],
    }
    for key, expected in expected_top_level.items():
        if existing.get(key) != expected:
            raise _resume_error(f"{key} does not match the requested run")
    raw_results = existing.get("results")
    if not isinstance(raw_results, list):
        raise _resume_error("results is not a list")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in raw_results:
        if not isinstance(result, dict):
            raise _resume_error("a checkpointed result is not an object")
        task_id = str(result.get("task_id") or "")
        if task_id not in tasks or task_id in seen:
            raise _resume_error(f"unexpected or duplicate checkpointed task {task_id!r}")
        if result.get("result_sha256") != _result_integrity_hash(result):
            raise _resume_error(f"task {task_id} has a mismatched result seal")
        if result.get("lambda_hash") != expected_lambda or result.get("lambda_config") != fields:
            raise _resume_error(f"task {task_id} has a different λ configuration")
        cell_result = result.get("cell_result")
        if not isinstance(cell_result, Mapping):
            raise _resume_error(f"task {task_id} has no cell result")
        expected_commits = commits[task_id]
        if (
            cell_result.get("parent") != expected_commits.parent
            or cell_result.get("merge") != expected_commits.merge
        ):
            raise _resume_error(f"task {task_id} has different parent/merge commits")
        task = tasks[task_id]
        for key in ("class", "difficulty", "pr"):
            if cell_result.get(key) != task.get(key):
                raise _resume_error(f"task {task_id} has a different {key}")
        seen.add(task_id)
        results.append(result)
    return results


def _verification_error(detail: str) -> DriverError:
    return DriverError(
        f"{detail}. Next action: restore the original pilot artifact and rerun "
        "--verify-result before relying on it."
    )


def verify_result_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute λ, task/commit bindings, cell seals, and aggregate invariants."""
    fields = payload.get("lambda_config")
    results = payload.get("results")
    tasks = payload.get("tasks")
    selection = payload.get("selection")
    if (
        not isinstance(fields, Mapping)
        or not isinstance(results, list)
        or not isinstance(tasks, list)
        or not isinstance(selection, Mapping)
    ):
        raise DriverError(
            "result must contain lambda_config, selection, embedded tasks, and results. "
            "Next action: point --verify-result at an unmodified pilot artifact."
        )
    schema_version = payload.get("schema_version")
    driver_version = payload.get("driver")
    artifact_kind = payload.get("artifact_kind")
    witness = payload.get("witness")
    historical_witness = schema_version == 1 or driver_version != DRIVER_VERSION
    if historical_witness:
        if (
            schema_version != 1
            or artifact_kind != "redacted-pilot-witness"
            or not isinstance(witness, Mapping)
            or driver_version != "driver_codex_cli/v1"
            or payload.get("model") != "gpt-5.6-sol"
            or payload.get("reasoning_effort") != "ultra"
        ):
            raise _verification_error(
                "historical pilot identity or required witness block is missing or changed"
            )
    elif schema_version != 3 or artifact_kind is not None or witness is not None:
        raise _verification_error("current pilot artifact identity is inconsistent")
    model = payload.get("model")
    reasoning_effort = payload.get("reasoning_effort")
    if (
        not isinstance(model, str)
        or fields.get("serving_version") != f"provider-managed:{model}"
        or fields.get("model_weights_sha256") != f"unpublished-provider-managed:{model}"
        or fields.get("decode_params") != {"model_reasoning_effort": reasoning_effort}
        or not str(fields.get("harness_binary_version") or "").endswith(f";{driver_version}")
    ):
        raise _verification_error("driver, model, reasoning, or λ identity binding changed")
    expected_lambda = lambda_hash(fields)
    if payload.get("lambda_set") != [expected_lambda]:
        raise DriverError(
            "top-level λ hash does not match lambda_config. "
            "Next action: restore the original artifact; do not use this result."
        )
    task_contracts: list[dict[str, Any]] = []
    task_by_id: dict[str, Mapping[str, Any]] = {}
    for task in tasks:
        if not isinstance(task, Mapping):
            raise _verification_error("embedded task row is not an object")
        task_id = str(task.get("task_id") or "")
        if not task_id or task_id in task_by_id:
            raise _verification_error("embedded task IDs are missing or duplicated")
        task_by_id[task_id] = task
        task_contracts.append(_task_contract(task))
    selected_ids = selection.get("task_ids")
    if (
        not isinstance(selected_ids, list)
        or selected_ids != list(task_by_id)
        or selection.get("requested") != len(selected_ids)
    ):
        raise _verification_error("selection does not match the embedded task order")
    if selection.get("task_set_sha256") != _canonical_hash(task_contracts):
        raise _verification_error("selection task hash does not match embedded contracts")

    seen: set[str] = set()
    result_ids: list[str] = []
    commit_rows: list[dict[str, str]] = []
    for result in results:
        if not isinstance(result, Mapping):
            raise _verification_error("result row is not an object")
        task_id = str(result.get("task_id") or "")
        if not task_id or task_id in seen or task_id not in task_by_id:
            raise _verification_error("result task IDs are missing, duplicated, or unselected")
        if result.get("lambda_hash") != expected_lambda:
            raise _verification_error(f"result {task_id} has a mismatched λ hash")
        if result.get("result_sha256") != _result_integrity_hash(result):
            raise _verification_error(f"result {task_id} has a mismatched result seal")
        cell = result.get("cell")
        cell_result = result.get("cell_result")
        if not isinstance(cell, Mapping) or not isinstance(cell_result, Mapping):
            raise _verification_error(f"result {task_id} has no cell record")
        if not isinstance(cell_result.get("passed"), bool):
            raise _verification_error(f"result {task_id} has no Boolean pass outcome")
        for commit_key in ("parent", "merge"):
            if not re.fullmatch(r"[0-9a-f]{40}", str(cell_result.get(commit_key) or "")):
                raise _verification_error(f"result {task_id} has an invalid {commit_key} commit")
        task = task_by_id[task_id]
        for key in ("class", "difficulty", "pr"):
            if cell_result.get(key) != task.get(key):
                raise _verification_error(f"result {task_id} does not match task {key}")
        exit_result = cell_result.get("exit")
        codex_returncode = cell_result.get("codex_returncode")
        codex_timed_out = cell_result.get("codex_timed_out")
        if (
            not isinstance(exit_result, Mapping)
            or not isinstance(exit_result.get("passed"), bool)
            or not isinstance(exit_result.get("returncode"), int)
            or not isinstance(exit_result.get("timed_out"), bool)
            or not isinstance(codex_returncode, int)
            or not isinstance(codex_timed_out, bool)
        ):
            raise _verification_error(f"result {task_id} has incomplete execution status")
        exit_passed = exit_result["returncode"] == 0 and not exit_result["timed_out"]
        if exit_result["passed"] != exit_passed:
            raise _verification_error(f"result {task_id} has inconsistent predicate status")
        expected_passed = exit_passed and codex_returncode == 0 and not codex_timed_out
        if cell_result["passed"] != expected_passed:
            raise _verification_error(f"result {task_id} has inconsistent cell pass status")
        transcript = cell.get("transcript")
        if isinstance(transcript, Mapping) and (
            transcript.get("returncode") != codex_returncode
            or bool(transcript.get("timed_out")) != codex_timed_out
        ):
            raise _verification_error(f"result {task_id} transcript status does not match")
        diff_sha256 = cell.get("diff_sha256")
        diff_bytes = cell.get("diff_bytes")
        if (
            not re.fullmatch(r"[0-9a-f]{64}", str(diff_sha256 or ""))
            or not isinstance(diff_bytes, int)
            or diff_bytes < 0
        ):
            raise _verification_error(f"result {task_id} has invalid cell diff metadata")
        if isinstance(cell.get("diff"), str):
            diff = str(cell["diff"])
            if (
                len(diff.encode()) != diff_bytes
                or hashlib.sha256(diff.encode()).hexdigest() != diff_sha256
            ):
                raise _verification_error(f"result {task_id} cell diff hash does not match")
        if payload.get("driver") == DRIVER_VERSION:
            expected_targets = _pytest_targets(task)
            if (
                exit_result.get("pytest_targets") != expected_targets
                or (cell_result["passed"] and exit_result.get("completion_attested") is not True)
                or not isinstance(cell_result.get("scoring_controls"), Mapping)
                or cell_result.get("post_scoring_controls") != cell_result.get("scoring_controls")
            ):
                raise _verification_error(
                    f"result {task_id} lacks current completion/control evidence"
                )
        commit_rows.append(
            {
                "task_id": task_id,
                "parent": str(cell_result["parent"]),
                "merge": str(cell_result["merge"]),
            }
        )
        seen.add(task_id)
        result_ids.append(task_id)
    if result_ids != selected_ids:
        raise _verification_error("result order does not match the selected task order")
    if selection.get("commit_set_sha256") != _canonical_hash(commit_rows):
        raise _verification_error("selection commit hash does not match cell commits")
    expected_summary = _summary(results, selection)
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        raise _verification_error("result has no summary")
    for key in ("passed", "total", "pass_rate"):
        if summary.get(key) != expected_summary[key]:
            raise _verification_error(f"summary {key} does not match the cell results")
    baseline = summary.get("direct_api_35b_baseline")
    if baseline != expected_summary["direct_api_35b_baseline"]:
        raise _verification_error("result baseline metadata is missing or changed")
    if historical_witness:
        assert isinstance(witness, Mapping)
        source_hash = witness.get("source_result_sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", str(source_hash or "")):
            raise _verification_error("witness source-result digest is invalid")
        artifact_hash = witness.get("artifact_sha256")
        if artifact_hash != _artifact_integrity_hash(payload):
            raise _verification_error("witness artifact seal does not match its contents")
        if KNOWN_WITNESS_ARTIFACTS.get(str(source_hash)) != artifact_hash:
            raise _verification_error("witness is not a known source-result/artifact pair")
    return {
        "valid": True,
        "lambda_hash": expected_lambda,
        "passed": expected_summary["passed"],
        "total": expected_summary["total"],
    }


def run_pilot(
    tasks: Sequence[Mapping[str, Any]],
    *,
    repo: Path,
    config: CodexRunConfig,
    output_path: Path,
    report_path: Path | None = None,
    resolver: CommitResolver = resolve_pr_commits,
    cell_runner: Callable[..., dict[str, Any]] = run_cell,
) -> dict[str, Any]:
    """Run cells sequentially and checkpoint the durable result after every cell."""
    version = codex_binary_version(config)
    sandbox_version = predicate_sandbox_version()
    fields = lambda_config(config, version, sandbox_version)
    expected_lambda = lambda_hash(fields)
    task_by_id = {str(task.get("task_id") or ""): task for task in tasks}
    if "" in task_by_id or len(task_by_id) != len(tasks):
        raise DriverError(
            "selected tasks have missing or duplicate task IDs. "
            "Next action: repair the task set before starting the pilot."
        )
    commits = {task_id: resolver(task, repo) for task_id, task in task_by_id.items()}
    selection = _selection_contract(tasks, commits)
    existing: dict[str, Any] = {}
    if output_path.exists():
        try:
            raw_existing = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise _resume_error(f"cannot read the checkpoint: {exc}") from exc
        if not isinstance(raw_existing, dict):
            raise _resume_error("checkpoint root is not an object")
        existing = raw_existing
        results = _validated_resume_results(
            existing,
            config=config,
            fields=fields,
            expected_lambda=expected_lambda,
            selection=selection,
            commits=commits,
            tasks=task_by_id,
        )
    else:
        results = []
    completed_ids = {str(result.get("task_id")) for result in results}
    started_at = existing.get("started_at") or _utc_now()

    def checkpoint(completed_at: str | None = None) -> dict[str, Any]:
        updated_at = completed_at or _utc_now()
        payload = {
            "schema_version": 3,
            "driver": DRIVER_VERSION,
            "model": config.model,
            "reasoning_effort": config.reasoning_effort,
            "started_at": started_at,
            "updated_at": updated_at,
            "completed_at": completed_at,
            "selection": selection,
            "tasks": [_task_contract(task) for task in tasks],
            "lambda_set": [expected_lambda],
            "lambda_config": fields,
            "results": results,
            "summary": _summary(results, selection),
        }
        _write_json_atomic(output_path, payload)
        return payload

    checkpoint()

    for index, task in enumerate(tasks, 1):
        task_id = str(task.get("task_id"))
        if task_id in completed_ids:
            print(f"[{index}/{len(tasks)}] {task_id}: already checkpointed", flush=True)
            continue
        print(f"[{index}/{len(tasks)}] {task_id}: running", flush=True)
        record = cell_runner(
            task,
            repo=repo,
            config=config,
            commits=commits[task_id],
            binary_version=version,
            sandbox_version=sandbox_version,
        )
        results.append(_seal_result(record))
        completed_ids.add(task_id)
        checkpoint()
        result = record["cell_result"]
        print(
            f"[{index}/{len(tasks)}] {task_id}: passed={result['passed']} "
            f"rc={result['exit']['returncode']} seconds={record['cell']['seconds']}",
            flush=True,
        )

    completed_at = _utc_now()
    payload = checkpoint(completed_at)
    if report_path is not None:
        _write_report(report_path, render_result_note(payload, output_path))
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--difficulty", default="easy")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Run one provider-free fixture through the complete scoring boundary, then exit",
    )
    parser.add_argument(
        "--verify-result",
        type=Path,
        help="Recompute λ and summary invariants for an existing result, then exit",
    )
    parser.add_argument("--output", type=Path, default=Path("pilot-codex-easy-v1.json"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--codex-binary", default=shutil.which("codex") or "codex")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.self_check:
        result = run_fixture_self_check()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["passed"] else 1
    if args.verify_result is not None:
        try:
            raw_payload = json.loads(args.verify_result.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DriverError(
                f"cannot read result artifact {args.verify_result}: {exc}. "
                "Next action: restore a valid pilot JSON file and rerun --verify-result."
            ) from exc
        if not isinstance(raw_payload, Mapping):
            raise DriverError(
                "result root is not an object. "
                "Next action: point --verify-result at an unmodified pilot JSON file."
            )
        verification = verify_result_payload(raw_payload)
        print(json.dumps(verification, indent=2, sort_keys=True))
        return 0
    tasks = [task for task in load_tasks(args.tasks) if task.get("difficulty") == args.difficulty]
    if args.limit is not None:
        if args.limit <= 0:
            raise SystemExit("--limit must be positive. Next action: pass a positive cell count.")
        tasks = tasks[: args.limit]
    if args.dry_run:
        result = dry_run_validate(tasks, repo=args.repo)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["valid"] == result["total"] else 1
    config = CodexRunConfig(
        codex_binary=args.codex_binary,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        timeout_seconds=args.timeout_seconds,
    )
    payload = run_pilot(
        tasks,
        repo=args.repo,
        config=config,
        output_path=args.output,
        report_path=args.report,
    )
    summary = payload["summary"]
    print(
        f"PILOT: {summary['passed']}/{summary['total']} passed; "
        f"lambda={payload['lambda_set'][0][:12]}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

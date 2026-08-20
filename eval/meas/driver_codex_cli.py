#!/usr/bin/env python3
"""Codex CLI driver for the MEAS Tier-0 agentic-harness facet.

Each measured cell gets an isolated, shallow Git checkout at the task PR's
parent commit. Codex edits that checkout non-interactively. The driver captures
the complete JSONL transcript and post-exec diff, installs the merge-version
tests only after Codex exits, runs the deterministic exit predicate, and emits
a complete lambda configuration plus its content hash in every cell record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

DEFAULT_REPO = Path.home() / "projects" / "hapax-council"
DEFAULT_TASKS = (
    Path.home()
    / "Documents"
    / "Personal"
    / "30-areas"
    / "hapax"
    / "workstream"
    / "meas-tier0"
    / "tasks-v2.jsonl"
)
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING_EFFORT = "ultra"
DEFAULT_TIMEOUT_SECONDS = 900
PREDICATE_TIMEOUT_SECONDS = 600
GITHUB_REPO = "hapax-systems/hapax-council"
HARNESS_NAME = "codex-cli-agentic"
DRIVER_VERSION = "driver_codex_cli/v2"
DIRECT_API_35B_BASELINE = {"passed": 0, "total": 19, "pass_rate": 0.0}

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
_SECRET_ENV_KEYS = {
    "ANTHROPIC_API_KEY",
    "CODEX_ACCESS_TOKEN",
    "CODEX_API_KEY",
    "CONTEXT7_API_KEY",
    "GEMINI_API_KEY",
    "GITHUB_PERSONAL_ACCESS_TOKEN",
    "OPENAI_API_KEY",
    "SAKANA_API_KEY",
    "TAVILY_API_KEY",
}


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
    legacy_full_auto: bool = False


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
    for line_number, line in enumerate(tasks_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
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


def _predicate_sandbox_command(
    task: Mapping[str, Any],
    workdir: Path,
    repo: Path,
) -> list[str]:
    """Build a no-network, clear-environment predicate sandbox command."""
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
        "--unshare-user",
        "--die-with-parent",
        "--new-session",
        "--disable-userns",
        "--clearenv",
    ]
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

    sandbox_home = Path("/home/meas")
    _add_sandbox_destination(command, sandbox_home, created, include_destination=True)
    command.extend(
        [
            "--dir",
            "/workspace",
            "--bind",
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
            "--chdir",
            "/workspace",
            "--",
            *exit_predicate_command(task),
        ]
    )
    return command


def evaluate_exit(
    task: Mapping[str, Any],
    workdir: Path,
    repo: Path = DEFAULT_REPO,
) -> dict[str, Any]:
    """Run the deterministic predicate in a fail-closed Bubblewrap sandbox."""
    command = _predicate_sandbox_command(task, workdir, repo)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PREDICATE_TIMEOUT_SECONDS,
            check=False,
        )
        returncode = result.returncode
        stdout = _coerce_text(result.stdout)
        stderr = _coerce_text(result.stderr)
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = _coerce_text(exc.stdout)
        stderr = _coerce_text(exc.stderr)
        timed_out = True
    except OSError as exc:
        raise DriverError(
            f"cannot execute the predicate sandbox: {exc}. "
            "Next action: repair bwrap and rerun the cell; no unsandboxed fallback is allowed."
        ) from exc
    output = stdout + stderr
    return {
        "passed": returncode == 0 and not timed_out,
        "returncode": returncode,
        "timed_out": timed_out,
        "sandbox": "bubblewrap",
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


def build_codex_command(config: CodexRunConfig, workdir: Path) -> list[str]:
    """Build the non-interactive command with a closed, λ-recorded tool surface."""
    command = [
        config.codex_binary,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
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
    ]
    if config.legacy_full_auto:
        command.append("--full-auto")
    else:
        command.extend(["--sandbox", "workspace-write"])
    command.append("-")
    return command


def _active_project_environment(repo: Path = DEFAULT_REPO) -> Path:
    interpreter_environment = Path(sys.executable).absolute().parent.parent
    if (interpreter_environment / "pyvenv.cfg").is_file():
        return interpreter_environment
    return repo / ".venv"


def _codex_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in _SECRET_ENV_KEYS:
        environment.pop(name, None)
    environment["NO_COLOR"] = "1"
    environment["HAPAX_CC_TASK_GATE"] = "0"
    project_environment = _active_project_environment()
    environment["UV_PROJECT_ENVIRONMENT"] = str(project_environment)
    environment["UV_NO_SYNC"] = "1"
    environment["VIRTUAL_ENV"] = str(project_environment)
    return environment


def capture_cell_diff(workdir: Path, baseline: str) -> dict[str, Any]:
    """Capture tracked, committed, deleted, and untracked model changes."""
    intent = _run_text(["git", "-C", str(workdir), "add", "--intent-to-add", "--all"])
    if intent.returncode != 0:
        raise DriverError(
            f"cannot stage intent-to-add entries: {intent.stderr.strip()[-500:]}. "
            "Next action: discard the damaged cell checkout and rerun it."
        )
    diff = _checked_stdout(
        ["git", "-C", str(workdir), "diff", "--binary", "--no-ext-diff", baseline, "--"],
        timeout=300,
    )
    status = _checked_stdout(["git", "-C", str(workdir), "status", "--short"])
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
    command = build_codex_command(config, workdir)
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
        error = f"codex exec timed out after {config.timeout_seconds}s"
    except OSError as exc:
        returncode = 127
        stdout = ""
        stderr = ""
        error = (
            f"cannot execute {config.codex_binary}: {exc}. "
            "Next action: repair the Codex CLI installation and rerun the cell."
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
            "command": command[:-1] + ["<prompt-from-stdin>"],
            "returncode": returncode,
            "timed_out": timed_out,
            "error": error,
            "stdout": stdout,
            "stderr": stderr,
        },
        **diff_record,
    }


def codex_binary_version(config: CodexRunConfig) -> str:
    result = _run_text([config.codex_binary, "--version"], timeout=30)
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
            "legacy_full_auto": config.legacy_full_auto,
            "mcp": "disabled-by-ignore-user-config",
            "sandbox": "full-auto-compat" if config.legacy_full_auto else "workspace-write",
            "codex_timeout_seconds": config.timeout_seconds,
            "exit_predicate": {
                "environment": "cleared",
                "network": "unshared",
                "sandbox": "bubblewrap",
                "sandbox_version": sandbox_version,
                "timeout_seconds": PREDICATE_TIMEOUT_SECONDS,
            },
            "user_config": "ignored",
            "uv_environment": "driver-interpreter-no-sync",
            "web_search": "disabled",
        },
        "context_mode": "agentic-parent-checkout+merge-tests-post-exec",
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
        workdir = Path(raw_workdir)
        prepare_cell_checkout(repo, commits.parent, workdir)
        outcome = executor(task=task, workdir=workdir, config=config)
        predicate_files = install_merge_version_tests(repo, workdir, commits)
        exit_result = evaluator(task, workdir, repo)

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
            "passed": passed,
            "exit": exit_result,
            "codex_returncode": codex_returncode,
            "codex_timed_out": codex_timed_out,
            "git_status": outcome.get("git_status", []),
        },
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
            errors.append("missing task_id")
        if not isinstance(task.get("work_item"), str) or not str(task.get("work_item")).strip():
            errors.append("missing work_item")
        if not targets:
            errors.append("no predicate target paths")
        missing_targets = [target for target in targets if not (repo / target).exists()]
        if missing_targets:
            errors.append(f"missing current targets: {', '.join(missing_targets)}")
        commits: CommitPair | None = None
        try:
            commits = resolver(task, repo)
            if not merge_version_test_paths(repo, commits):
                errors.append("merge changes no tests")
        except (DriverError, OSError, subprocess.SubprocessError) as exc:
            errors.append(str(exc))
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
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _summary(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for result in results if result.get("cell_result", {}).get("passed"))
    baseline = dict(DIRECT_API_35B_BASELINE)
    baseline["comparable"] = len(results) == baseline["total"]
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
    comparable = bool(baseline.get("comparable", total == baseline.get("total")))
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
    recheck_target = result_path.name if result_path is not None else "pilot-result.json"
    predicate_surface = (
        payload.get("lambda_config", {}).get("tool_surface_config", {}).get("exit_predicate", {})
    )
    predicate_boundary = (
        "The deterministic predicate ran in Bubblewrap with a cleared environment and "
        "an unshared network namespace."
        if predicate_surface
        else "This legacy result predates recorded predicate-sandbox metadata."
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

Each cell used an isolated shallow checkout at the authoritative PR parent. Codex
edited under the workspace-write sandbox with user config, MCP, and web search
disabled. The harness captured JSONL stdout/stderr and the post-exec diff, then
installed merge-version tests through no-follow file descriptors. {predicate_boundary}
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
        "schema_version": 2,
        "driver": DRIVER_VERSION,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "lambda_set": [expected_lambda],
        "lambda_config": fields,
        "selection": selection,
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


def verify_result_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute the durable λ and aggregate result invariants."""
    fields = payload.get("lambda_config")
    results = payload.get("results")
    if not isinstance(fields, Mapping) or not isinstance(results, list):
        raise DriverError(
            "result must contain lambda_config and a results list. "
            "Next action: point --verify-result at an unmodified pilot artifact."
        )
    expected_lambda = lambda_hash(fields)
    if payload.get("lambda_set") != [expected_lambda]:
        raise DriverError(
            "top-level λ hash does not match lambda_config. "
            "Next action: restore the original artifact; do not use this result."
        )
    seen: set[str] = set()
    for result in results:
        if not isinstance(result, Mapping):
            raise DriverError("result row is not an object; do not use this artifact")
        task_id = str(result.get("task_id") or "")
        if not task_id or task_id in seen:
            raise DriverError("result task IDs are missing or duplicated; do not use this artifact")
        if result.get("lambda_hash") != expected_lambda:
            raise DriverError(f"result {task_id} has a mismatched λ hash; do not use it")
        cell_result = result.get("cell_result")
        if not isinstance(cell_result, Mapping) or not isinstance(cell_result.get("passed"), bool):
            raise DriverError(f"result {task_id} has no Boolean pass outcome; do not use it")
        for commit_key in ("parent", "merge"):
            if not re.fullmatch(r"[0-9a-f]{40}", str(cell_result.get(commit_key) or "")):
                raise DriverError(f"result {task_id} has an invalid {commit_key} commit")
        seen.add(task_id)
    expected_summary = _summary(results)
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        raise DriverError("result has no summary; do not use this artifact")
    for key in ("passed", "total", "pass_rate"):
        if summary.get(key) != expected_summary[key]:
            raise DriverError(f"summary {key} does not match the cell results")
    baseline = summary.get("direct_api_35b_baseline")
    if not isinstance(baseline, Mapping) or any(
        baseline.get(key) != value for key, value in DIRECT_API_35B_BASELINE.items()
    ):
        raise DriverError("result baseline metadata is missing or changed")
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
            "schema_version": 2,
            "driver": DRIVER_VERSION,
            "model": config.model,
            "reasoning_effort": config.reasoning_effort,
            "started_at": started_at,
            "updated_at": updated_at,
            "completed_at": completed_at,
            "selection": selection,
            "lambda_set": [expected_lambda],
            "lambda_config": fields,
            "results": results,
            "summary": _summary(results),
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
        results.append(record)
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
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_result_note(payload, output_path), encoding="utf-8")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--difficulty", default="easy")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
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
    parser.add_argument(
        "--legacy-full-auto",
        action="store_true",
        help="Use deprecated --full-auto compatibility mode instead of workspace-write",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.verify_result is not None:
        raw_payload = json.loads(args.verify_result.read_text(encoding="utf-8"))
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
            raise SystemExit("--limit must be positive")
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
        legacy_full_auto=args.legacy_full_auto,
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

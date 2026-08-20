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
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
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
DEFAULT_TIMEOUT_SECONDS = 1_800
GITHUB_REPO = "hapax-systems/hapax-council"
HARNESS_NAME = "codex-cli-agentic"
DRIVER_VERSION = "driver_codex_cli/v1"

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
    ) -> dict[str, Any]: ...


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
        raise DriverError(f"command failed ({result.returncode}): {' '.join(command)}: {detail}")
    return result.stdout.strip()


def load_tasks(tasks_path: Path = DEFAULT_TASKS) -> list[dict[str, Any]]:
    """Load the JSONL task set without accepting malformed non-object rows."""
    tasks: list[dict[str, Any]] = []
    for line_number, line in enumerate(tasks_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise DriverError(f"{tasks_path}:{line_number}: task row is not an object")
        tasks.append(row)
    return tasks


def resolve_pr_commits(task: Mapping[str, Any], repo: Path = DEFAULT_REPO) -> CommitPair:
    """Resolve the PR merge through GitHub, then derive its first parent locally."""
    pr = task.get("pr")
    if not isinstance(pr, int) or pr <= 0:
        raise DriverError(f"task {task.get('task_id')} has no valid PR number")
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
        raise DriverError(f"PR {pr} did not resolve to a merge commit")
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
        raise DriverError(f"cell checkout mismatch: expected {parent}, got {actual}")


def _safe_repo_path(raw: str) -> Path:
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise DriverError(f"unsafe repository path: {raw!r}")
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
            raise DriverError(f"cannot read merge-version test {raw_path}: {detail}")
        destination = workdir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(result.stdout)
        installed.append(raw_path)
    if not installed:
        raise DriverError(
            f"merge {commits.merge} changed no installable tests; predicate would be degenerate"
        )
    return installed


def exit_predicate_command(task: Mapping[str, Any]) -> list[str]:
    predicate = task.get("exit_predicate")
    if not isinstance(predicate, Mapping):
        raise DriverError(f"task {task.get('task_id')} has no exit predicate")
    kind = predicate.get("kind")
    target = predicate.get("target")
    if not isinstance(target, str) or not target:
        raise DriverError(f"task {task.get('task_id')} has an invalid predicate target")
    if kind == "pytest":
        return ["uv", "run", "pytest", target, "-q", "--no-header"]
    if kind == "ruff+custom":
        return ["bash", "-lc", target]
    raise DriverError(f"unsupported exit predicate kind: {kind!r}")


def evaluate_exit(
    task: Mapping[str, Any],
    workdir: Path,
    repo: Path = DEFAULT_REPO,
) -> dict[str, Any]:
    """Run the deterministic predicate without mutating a shared environment."""
    environment = os.environ.copy()
    project_environment = _active_project_environment(repo)
    environment["UV_PROJECT_ENVIRONMENT"] = str(project_environment)
    environment["UV_NO_SYNC"] = "1"
    environment["VIRTUAL_ENV"] = str(project_environment)
    result = subprocess.run(
        exit_predicate_command(task),
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        env=environment,
    )
    output = result.stdout + result.stderr
    return {
        "passed": result.returncode == 0,
        "returncode": result.returncode,
        "output_tail": output[-4_000:],
    }


def render_cell_prompt(task: Mapping[str, Any]) -> str:
    work_item = task.get("work_item")
    if not isinstance(work_item, str) or not work_item.strip():
        raise DriverError(f"task {task.get('task_id')} has no work item")
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
    interpreter_environment = Path(sys.executable).resolve().parent.parent
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
        raise DriverError(f"cannot stage intent-to-add entries: {intent.stderr.strip()[-500:]}")
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
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        error = f"codex exec timed out after {config.timeout_seconds}s"
    except OSError as exc:
        returncode = 127
        stdout = ""
        stderr = ""
        error = f"cannot execute {config.codex_binary}: {exc}"
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
        raise DriverError(f"cannot read Codex version: {result.stderr.strip()[-500:]}")
    return result.stdout.strip()


def lambda_config(config: CodexRunConfig, binary_version: str) -> dict[str, Any]:
    """Build the canonical λ fields; closed-model weight opacity is explicit."""
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
            "user_config": "ignored",
            "uv_environment": "driver-interpreter-no-sync",
            "web_search": "disabled",
        },
        "context_mode": "agentic-parent-checkout+merge-tests-post-exec",
    }


def lambda_hash(fields: Mapping[str, Any]) -> str:
    missing = [key for key in LAMBDA_KEYS if key not in fields]
    if missing:
        raise DriverError(f"missing lambda fields: {', '.join(missing)}")
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
) -> dict[str, Any]:
    """Prepare, execute, score, and λ-stamp one isolated measurement cell."""
    config = config or CodexRunConfig()
    commits = commits or resolve_pr_commits(task, repo)
    version = binary_version or codex_binary_version(config)
    fields = lambda_config(config, version)
    task_id = str(task.get("task_id") or "")
    if not task_id:
        raise DriverError("task has no task_id")

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
            "passed": bool(exit_result.get("passed")),
            "exit": exit_result,
            "codex_returncode": (outcome.get("transcript") or {}).get("returncode"),
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
        temporary = Path(handle.name)
    temporary.replace(path)


def _summary(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for result in results if result.get("cell_result", {}).get("passed"))
    return {
        "passed": passed,
        "total": len(results),
        "pass_rate": round(passed / len(results), 6) if results else None,
        "direct_api_35b_baseline": {"passed": 0, "total": 19, "pass_rate": 0.0},
    }


def render_result_note(payload: Mapping[str, Any]) -> str:
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
    return f"""# MEAS Tier-0 Codex CLI pilot

- Completed: {completed}
- Arm: `{model}` through `{HARNESS_NAME}`
- Result: **{passed}/{total} ({percent})**
- Direct-API 35B single-shot baseline: **0/19 (0.0%)**
- λ: `{lambda_short}` (full configuration is embedded in every JSON cell)

## Finding

The Codex CLI agentic harness passed {passed} of {total} easy cells, versus 0 of 19
for the 35B direct-API single-shot baseline. This comparison establishes only the
measured harness/model pair; it does not isolate model quality from harness effects.

## Measurement boundary

Each cell used an isolated shallow checkout at the authoritative PR parent. Codex
edited under the workspace-write sandbox with user config, MCP, and web search
disabled. The harness captured JSONL stdout/stderr and the post-exec diff, then
installed merge-version tests and ran the deterministic predicate. The proprietary
model's weight hash and serving quantization are not published; those λ fields say
`provider-managed` rather than pretending a weights digest exists.
"""


def run_pilot(
    tasks: Sequence[Mapping[str, Any]],
    *,
    repo: Path,
    config: CodexRunConfig,
    output_path: Path,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Run cells sequentially and checkpoint the durable result after every cell."""
    version = codex_binary_version(config)
    fields = lambda_config(config, version)
    expected_lambda = lambda_hash(fields)
    existing: dict[str, Any] = {}
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        existing_set = existing.get("lambda_set")
        if existing_set and existing_set != [expected_lambda]:
            raise DriverError(
                "existing output has a different lambda set; choose a new output path"
            )
    results = list(existing.get("results", []))
    completed_ids = {str(result.get("task_id")) for result in results}
    started_at = existing.get("started_at") or _utc_now()

    for index, task in enumerate(tasks, 1):
        task_id = str(task.get("task_id"))
        if task_id in completed_ids:
            print(f"[{index}/{len(tasks)}] {task_id}: already checkpointed", flush=True)
            continue
        print(f"[{index}/{len(tasks)}] {task_id}: running", flush=True)
        record = run_cell(
            task,
            repo=repo,
            config=config,
            binary_version=version,
        )
        results.append(record)
        completed_ids.add(task_id)
        payload = {
            "schema_version": 1,
            "driver": DRIVER_VERSION,
            "model": config.model,
            "reasoning_effort": config.reasoning_effort,
            "started_at": started_at,
            "updated_at": _utc_now(),
            "completed_at": None,
            "selection": {"difficulty": "easy", "requested": len(tasks)},
            "lambda_set": [expected_lambda],
            "lambda_config": fields,
            "results": results,
            "summary": _summary(results),
        }
        _write_json_atomic(output_path, payload)
        result = record["cell_result"]
        print(
            f"[{index}/{len(tasks)}] {task_id}: passed={result['passed']} "
            f"rc={result['exit']['returncode']} seconds={record['cell']['seconds']}",
            flush=True,
        )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    payload["completed_at"] = _utc_now()
    payload["updated_at"] = payload["completed_at"]
    payload["summary"] = _summary(payload["results"])
    _write_json_atomic(output_path, payload)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_result_note(payload), encoding="utf-8")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--difficulty", default="easy")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
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

#!/usr/bin/env python3
"""Run one pytest target and attest that every collected item reached a terminal report."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from typing import Any

WORKSPACE = Path("/workspace")
ATTESTATION_PREFIX = "MEAS_PYTEST_ATTESTATION "
MAX_PYTEST_EXIT_CODE = 5
TRUST_FAILURE_EXIT_CODE = 87


def _outside_workspace_import_path(value: str) -> bool:
    try:
        resolved = Path(value or os.getcwd()).resolve()
    except OSError:
        return False
    workspace = WORKSPACE.resolve()
    return resolved != workspace and workspace not in resolved.parents


sys.path[:] = [entry for entry in sys.path if _outside_workspace_import_path(entry)]

import pytest  # noqa: E402
import xdist  # noqa: E402
import xdist.workermanage as xdist_workermanage  # noqa: E402


class CompletionPlugin:
    """Collect the minimum trusted lifecycle evidence needed by the parent scorer."""

    def __init__(self) -> None:
        self.collected: list[str] = []
        self.terminal: dict[str, str] = {}

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        local_items = [item.nodeid for item in session.items]
        if local_items:
            self.collected = local_items

    def pytest_xdist_node_collection_finished(self, node: Any, ids: list[str]) -> None:
        del node
        self.collected = list(ids)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if (
            report.when == "call"
            or (report.when == "setup" and report.outcome != "passed")
            or (report.when == "teardown" and report.outcome != "passed")
        ):
            self.terminal[report.nodeid] = report.outcome


def pytest_configure(config: pytest.Config) -> None:
    """Expose the solution checkout only after pytest is trusted in the xdist worker."""
    if hasattr(config, "workerinput") and "/workspace" not in sys.path:
        sys.path.insert(0, "/workspace")


def _trusted_runtime_origins(
    *,
    runtime_prefix: Path | None = None,
    pytest_origin: Path | None = None,
    xdist_origin: Path | None = None,
    workspace: Path = WORKSPACE,
) -> tuple[Path, Path, Path]:
    prefix = (runtime_prefix or Path(sys.prefix)).resolve()
    resolved_workspace = workspace.resolve()
    origin_values = {
        "pytest": pytest_origin or Path(str(getattr(pytest, "__file__", ""))),
        "xdist": xdist_origin or Path(str(getattr(xdist, "__file__", ""))),
    }
    resolved: dict[str, Path] = {}
    for name, origin_value in origin_values.items():
        origin = origin_value.resolve()
        if (
            not origin_value.is_file()
            or (origin != prefix and prefix not in origin.parents)
            or origin == resolved_workspace
            or resolved_workspace in origin.parents
        ):
            raise RuntimeError(
                f"{name} trust root mismatch: origin={origin}, runtime_prefix={prefix}"
            )
        resolved[name] = origin
    return resolved["pytest"], resolved["xdist"], prefix


def run(target: str) -> int:
    try:
        pytest_origin, xdist_origin, runtime_prefix = _trusted_runtime_origins()
    except RuntimeError as exc:
        print(
            f"HARNESS: {exc}. Next action: restore the pinned pytest/xdist project "
            "environment and rerun the predicate.",
            file=sys.stderr,
            flush=True,
        )
        return TRUST_FAILURE_EXIT_CODE
    worker_sys_path = ["/harness", *sys.path]
    xdist_workermanage._sys_path = worker_sys_path
    sys.path.insert(0, "/harness")
    sys.path.insert(1, "/workspace")
    sys.modules["pytest_attested_runner"] = sys.modules[__name__]
    plugin = CompletionPlugin()
    exit_code = pytest.main(
        [
            target,
            "-q",
            "--no-header",
            "-c",
            "/dev/null",
            "--rootdir=/workspace",
            "--confcutdir=/workspace",
            "-p",
            "xdist.plugin",
            "-p",
            "pytest_attested_runner",
            "-p",
            "no:cacheprovider",
            "--tx=popen//python=/harness/python-isolated",
            "--dist=load",
            "--max-worker-restart=0",
        ],
        plugins=[plugin],
    )
    logical_exit_code = int(exit_code)
    payload = {
        "schema_version": 3,
        "completed": True,
        "exit_code": logical_exit_code,
        "collected": plugin.collected,
        "terminal": plugin.terminal,
        "attester_pid": os.getpid(),
        "attester_process": "xdist-controller",
        "pytest_origin": str(pytest_origin),
        "runtime_prefix": str(runtime_prefix),
        "worker_count": 1,
        "xdist_origin": str(xdist_origin),
        "xdist_version": importlib.metadata.version("pytest-xdist"),
    }
    print(
        ATTESTATION_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
        flush=True,
    )
    if not 0 <= logical_exit_code <= MAX_PYTEST_EXIT_CODE:
        print(
            f"HARNESS: pytest returned unsupported exit code {logical_exit_code}. "
            "Next action: restore the pinned pytest/xdist project environment and rerun "
            "the predicate.",
            file=sys.stderr,
            flush=True,
        )
        return TRUST_FAILURE_EXIT_CODE
    return logical_exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    args = parser.parse_args()
    return run(args.target)


if __name__ == "__main__":
    raise SystemExit(main())

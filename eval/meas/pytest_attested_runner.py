#!/usr/bin/env python3
"""Run one pytest target and attest that every collected item reached a terminal report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

WORKSPACE = Path("/workspace")
ATTESTATION_PREFIX = "MEAS_PYTEST_ATTESTATION "
COMPLETION_EXIT_BASE = 100
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


class CompletionPlugin:
    """Collect the minimum trusted lifecycle evidence needed by the parent scorer."""

    def __init__(self) -> None:
        self.collected: list[str] = []
        self.terminal: dict[str, str] = {}

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.collected = [item.nodeid for item in session.items]

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if (
            report.when == "call"
            or (report.when == "setup" and report.outcome != "passed")
            or (report.when == "teardown" and report.outcome != "passed")
        ):
            self.terminal[report.nodeid] = report.outcome


def _trusted_pytest_origin(
    *,
    runtime_prefix: Path | None = None,
    pytest_origin: Path | None = None,
    workspace: Path = WORKSPACE,
) -> tuple[Path, Path]:
    prefix = (runtime_prefix or Path(sys.prefix)).resolve()
    origin_value = pytest_origin or Path(str(getattr(pytest, "__file__", "")))
    origin = origin_value.resolve()
    resolved_workspace = workspace.resolve()
    if (
        not origin_value.is_file()
        or (origin != prefix and prefix not in origin.parents)
        or origin == resolved_workspace
        or resolved_workspace in origin.parents
    ):
        raise RuntimeError(f"pytest trust root mismatch: origin={origin}, runtime_prefix={prefix}")
    return origin, prefix


def run(target: str) -> int:
    try:
        pytest_origin, runtime_prefix = _trusted_pytest_origin()
    except RuntimeError as exc:
        print(f"HARNESS: {exc}", file=sys.stderr, flush=True)
        return TRUST_FAILURE_EXIT_CODE
    sys.path.insert(0, "/workspace")
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
            "no:cacheprovider",
        ],
        plugins=[plugin],
    )
    logical_exit_code = int(exit_code)
    payload = {
        "schema_version": 2,
        "completed": True,
        "exit_code": logical_exit_code,
        "collected": plugin.collected,
        "terminal": plugin.terminal,
        "pytest_origin": str(pytest_origin),
        "runtime_prefix": str(runtime_prefix),
    }
    print(
        ATTESTATION_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
        flush=True,
    )
    if not 0 <= logical_exit_code <= MAX_PYTEST_EXIT_CODE:
        return TRUST_FAILURE_EXIT_CODE
    return COMPLETION_EXIT_BASE + logical_exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    args = parser.parse_args()
    return run(args.target)


if __name__ == "__main__":
    raise SystemExit(main())

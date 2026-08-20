#!/usr/bin/env python3
"""Run one pytest target and attest that every collected item reached a terminal report."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest


class CompletionPlugin:
    """Collect the minimum trusted lifecycle evidence needed by the parent scorer."""

    def __init__(self) -> None:
        self.collected: list[str] = []
        self.terminal: dict[str, str] = {}

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.collected = [item.nodeid for item in session.items]

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
            self.terminal[report.nodeid] = report.outcome


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("attestation", type=Path)
    parser.add_argument("target")
    args = parser.parse_args()
    plugin = CompletionPlugin()
    exit_code = pytest.main(
        [
            args.target,
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
    _write_atomic(
        args.attestation,
        {
            "schema_version": 1,
            "completed": True,
            "exit_code": int(exit_code),
            "collected": plugin.collected,
            "terminal": plugin.terminal,
        },
    )
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())

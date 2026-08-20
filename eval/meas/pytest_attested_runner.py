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
WORKER_INTEGRITY_GUARD = "plugin-registration-frozen+runtime-introspection-audit/v1"
_WORKER_GUARD_INSTALLED = False
_BLOCKED_AUDIT_EVENTS = frozenset(
    {
        "gc.get_objects",
        "gc.get_referents",
        "gc.get_referrers",
        "sys._current_frames",
        "sys._getframe",
        "sys.setprofile",
        "sys.settrace",
    }
)


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
        self.worker_integrity_guard = False

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

    def pytest_testnodedown(self, node: Any, error: object | None) -> None:
        workeroutput = getattr(node, "workeroutput", {})
        self.worker_integrity_guard = error is None and (
            workeroutput.get("meas_worker_integrity_guard") == WORKER_INTEGRITY_GUARD
        )


def pytest_configure(config: pytest.Config) -> None:
    """Expose the solution checkout only after pytest is trusted in the xdist worker."""
    if hasattr(config, "workerinput") and "/workspace" not in sys.path:
        sys.path.insert(0, "/workspace")


def _worker_audit_hook(event: str, args: tuple[Any, ...]) -> None:
    del args
    if event in _BLOCKED_AUDIT_EVENTS:
        raise RuntimeError(
            f"worker runtime introspection is disabled at the scoring boundary ({event}). "
            "Next action: remove pytest-runtime introspection from the solution and rerun."
        )


def _install_worker_integrity_guard(config: pytest.Config) -> None:
    """Freeze new plugin registration before workspace test modules are imported."""
    global _WORKER_GUARD_INSTALLED
    if _WORKER_GUARD_INSTALLED:
        return
    plugin_manager = config.pluginmanager
    manager_type = type(plugin_manager)
    original_register = manager_type.register

    def guarded_register(
        manager: Any,
        plugin: object,
        name: str | None = None,
    ) -> Any:
        if manager is plugin_manager:
            del plugin, name
            raise RuntimeError(
                "pytest plugin registration is frozen before solution import. "
                "Next action: remove runtime pytest-hook registration from the solution "
                "and rerun."
            )
        return original_register(manager, plugin, name)

    manager_type.register = guarded_register
    sys.addaudithook(_worker_audit_hook)
    _WORKER_GUARD_INSTALLED = True


def pytest_collection(session: pytest.Session) -> None:
    """Seal worker pytest control surfaces before collection imports solution code."""
    if os.environ.get("PYTEST_XDIST_WORKER"):
        if "/workspace" not in sys.path:
            sys.path.insert(0, "/workspace")
        _install_worker_integrity_guard(session.config)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del exitstatus
    if os.environ.get("PYTEST_XDIST_WORKER") and hasattr(session.config, "workeroutput"):
        session.config.workeroutput["meas_worker_integrity_guard"] = (
            WORKER_INTEGRITY_GUARD if _WORKER_GUARD_INSTALLED else "missing"
        )


def _worker_setup_with_conftests(original_setup: Any) -> Any:
    """Remove the controller-only conftest ban from each trusted worker invocation."""

    def setup(controller: Any) -> Any:
        original_params = controller.config.invocation_params
        worker_args = tuple(
            argument for argument in original_params.args if argument != "--noconftest"
        )
        if len(worker_args) != len(original_params.args) - 1:
            raise RuntimeError(
                "xdist worker invocation did not contain exactly one controller-only "
                "--noconftest flag. Next action: restore the locked pytest-xdist version "
                "and rerun the predicate."
            )
        controller.config.invocation_params = pytest.Config.InvocationParams(
            args=worker_args,
            plugins=original_params.plugins,
            dir=original_params.dir,
        )
        try:
            return original_setup(controller)
        finally:
            controller.config.invocation_params = original_params

    return setup


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
    original_worker_sys_path = getattr(xdist_workermanage, "_sys_path", None)
    worker_controller = getattr(xdist_workermanage, "WorkerController", None)
    original_worker_setup = getattr(worker_controller, "setup", None)
    if not isinstance(original_worker_sys_path, list) or not callable(original_worker_setup):
        print(
            "HARNESS: pytest-xdist worker setup API is incompatible with the pinned "
            "controller/worker boundary. Next action: restore the locked pytest-xdist "
            "version and rerun the predicate.",
            file=sys.stderr,
            flush=True,
        )
        return TRUST_FAILURE_EXIT_CODE
    worker_sys_path = ["/harness", *sys.path]
    xdist_workermanage._sys_path = worker_sys_path
    worker_controller.setup = _worker_setup_with_conftests(original_worker_setup)
    sys.path.insert(0, "/harness")
    sys.modules["pytest_attested_runner"] = sys.modules[__name__]
    plugin = CompletionPlugin()
    try:
        exit_code = pytest.main(
            [
                target,
                "-q",
                "--no-header",
                "-c",
                "/dev/null",
                "--rootdir=/workspace",
                "--confcutdir=/workspace",
                "--noconftest",
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
    finally:
        worker_controller.setup = original_worker_setup
        xdist_workermanage._sys_path = original_worker_sys_path
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
        "worker_integrity_guard": (
            WORKER_INTEGRITY_GUARD if plugin.worker_integrity_guard else "missing"
        ),
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

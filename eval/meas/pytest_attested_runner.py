#!/usr/bin/env python3
"""Run one pytest target and attest that every collected item reached a terminal report."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys
import time
from pathlib import Path
from types import FunctionType
from typing import Any

WORKSPACE = Path("/workspace")
ATTESTATION_PREFIX = "MEAS_PYTEST_ATTESTATION "
MAX_PYTEST_EXIT_CODE = 5
TRUST_FAILURE_EXIT_CODE = 87
WORKER_INTEGRITY_GUARD = (
    "early-runtime-introspection-and-hook-mutation-audit+collection-plugin-registration-freeze+"
    "sealed-call-capture+raw-worker-outcomes/v5"
)
_WORKER_AUDIT_INSTALLED = False
_WORKER_CALL_CAPTURE_SEALED = False
_WORKER_REGISTRATION_FROZEN = False
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
_BLOCKED_FUNCTION_ATTRIBUTES = frozenset({"__code__", "__defaults__", "__kwdefaults__"})
_BLOCKED_FUNCTION_MUTATION_EVENTS = frozenset({"object.__setattr__", "object.__delattr__"})


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
from _pytest import runner as pytest_runner  # noqa: E402
from _pytest._code import ExceptionInfo  # noqa: E402


class CompletionPlugin:
    """Collect the minimum trusted lifecycle evidence needed by the parent scorer."""

    def __init__(self) -> None:
        self.collected: list[str] = []
        self.worker_terminal: dict[str, str] = {}
        self.worker_integrity_guard = False

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        local_items = [item.nodeid for item in session.items]
        if local_items:
            self.collected = local_items

    def pytest_xdist_node_collection_finished(self, node: Any, ids: list[str]) -> None:
        del node
        self.collected = list(ids)

    def pytest_testnodedown(self, node: Any, error: object | None) -> None:
        workeroutput = getattr(node, "workeroutput", {})
        raw_terminal = workeroutput.get("meas_raw_terminal")
        if isinstance(raw_terminal, dict):
            self.worker_terminal = raw_terminal
        self.worker_integrity_guard = error is None and (
            workeroutput.get("meas_worker_integrity_guard") == WORKER_INTEGRITY_GUARD
            and isinstance(raw_terminal, dict)
        )


def pytest_configure(config: pytest.Config) -> None:
    """Expose the solution checkout only after pytest is trusted in the xdist worker."""
    if hasattr(config, "workerinput") and "/workspace" not in sys.path:
        sys.path.insert(0, "/workspace")


def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> None:
    """Record raw worker call outcomes without consulting mutable pytest report globals."""
    when = call.when
    failed = call.excinfo is not None
    if when == "call" or (when == "setup" and failed) or (when == "teardown" and failed):
        terminal = item.config.workeroutput.setdefault("meas_raw_terminal", {})
        terminal[item.nodeid] = "failed" if failed else "passed"


def _worker_audit_hook(
    event: str,
    args: tuple[Any, ...],
    blocked_events: frozenset[str] = _BLOCKED_AUDIT_EVENTS,
    blocked_attributes: frozenset[str] = _BLOCKED_FUNCTION_ATTRIBUTES,
    mutation_events: frozenset[str] = _BLOCKED_FUNCTION_MUTATION_EVENTS,
    error_type: type[RuntimeError] = RuntimeError,
) -> None:
    if event in blocked_events:
        raise error_type(
            f"worker runtime introspection is disabled at the scoring boundary ({event}). "
            "Next action: remove pytest-runtime introspection from the solution and rerun."
        )
    if event in mutation_events and args[1] in blocked_attributes:
        raise error_type(
            f"worker function mutation is disabled at the scoring boundary ({args[1]}). "
            "Next action: remove runtime mutation of pytest hooks from the solution and "
            "rerun."
        )


def _install_worker_audit_guard() -> None:
    """Install the non-removable audit boundary before worker conftest import."""
    global _WORKER_AUDIT_INSTALLED
    if _WORKER_AUDIT_INSTALLED:
        return
    sys.addaudithook(_worker_audit_hook)
    _WORKER_AUDIT_INSTALLED = True


def _clone_function(function: Any, global_overrides: dict[str, Any]) -> Any:
    cloned_globals = function.__globals__.copy()
    cloned_globals.update(global_overrides)
    return FunctionType(
        function.__code__,
        cloned_globals,
        function.__name__,
        function.__defaults__,
        function.__closure__,
    )


def _sealed_call_info_factory() -> object:
    call_info_type = pytest_runner.CallInfo
    exception_info_type = ExceptionInfo
    object_new = object.__new__
    object_setattr = object.__setattr__
    wall_clock = time.time
    duration_clock = time.perf_counter

    def from_call(
        func: Any,
        when: str,
        reraise: object = None,
        base_exception: type[BaseException] = BaseException,
        is_instance: Any = isinstance,
        type_of: Any = type,
    ) -> object:
        started_at = wall_clock()
        duration_start = duration_clock()
        excinfo = None
        try:
            result = func()
        except base_exception as error:
            if reraise is not None and is_instance(error, reraise):
                raise
            traceback = error.__traceback__
            excinfo = object_new(exception_info_type)
            object_setattr(excinfo, "_excinfo", (type_of(error), error, traceback))
            object_setattr(excinfo, "_striptext", "")
            object_setattr(excinfo, "_traceback", None)
            result = None
        duration = duration_clock() - duration_start
        call = object_new(call_info_type)
        object_setattr(call, "start", started_at)
        object_setattr(call, "stop", wall_clock())
        object_setattr(call, "duration", duration)
        object_setattr(call, "when", when)
        object_setattr(call, "_result", result)
        object_setattr(call, "excinfo", excinfo)
        return call

    class CallInfoFactory:
        pass

    factory = CallInfoFactory()
    factory.from_call = from_call
    return factory


def _seal_worker_call_capture(config: pytest.Config) -> None:
    """Detach pytest's call-capture chain from public module globals before imports."""
    global _WORKER_CALL_CAPTURE_SEALED
    if _WORKER_CALL_CAPTURE_SEALED:
        return
    sealed_call_and_report = _clone_function(
        pytest_runner.call_and_report,
        {"CallInfo": _sealed_call_info_factory()},
    )
    sealed_runtestprotocol = _clone_function(
        pytest_runner.runtestprotocol,
        {"call_and_report": sealed_call_and_report},
    )
    sealed_protocol_hook = _clone_function(
        pytest_runner.pytest_runtest_protocol,
        {"runtestprotocol": sealed_runtestprotocol},
    )
    hook_implementations = config.hook.pytest_runtest_protocol.get_hookimpls()
    runner_implementations = [
        implementation
        for implementation in hook_implementations
        if implementation.function is pytest_runner.pytest_runtest_protocol
    ]
    if len(runner_implementations) != 1:
        raise RuntimeError(
            "pytest runner call-capture hook identity drifted. "
            "Next action: restore the pinned pytest version and rerun the predicate."
        )
    runner_implementations[0].function = sealed_protocol_hook
    _WORKER_CALL_CAPTURE_SEALED = True


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(
    early_config: pytest.Config,
    parser: pytest.Parser,
    args: list[str],
) -> None:
    """Seal mutation/introspection before a trusted conftest can import solution code."""
    del parser, args
    if os.environ.get("PYTEST_XDIST_WORKER"):
        _install_worker_audit_guard()
        _seal_worker_call_capture(early_config)


def _freeze_worker_plugin_registration(config: pytest.Config) -> None:
    """Freeze new plugin registration before collection imports test modules."""
    global _WORKER_REGISTRATION_FROZEN
    if _WORKER_REGISTRATION_FROZEN:
        return
    if not _WORKER_AUDIT_INSTALLED:
        raise RuntimeError(
            "worker audit guard was not installed before conftest import. "
            "Next action: restore the pinned pytest startup lifecycle and rerun."
        )
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
                "pytest plugin registration is frozen before test-module collection. "
                "Next action: remove runtime pytest-hook registration from the solution "
                "and rerun."
            )
        return original_register(manager, plugin, name)

    manager_type.register = guarded_register
    _WORKER_REGISTRATION_FROZEN = True


def pytest_collection(session: pytest.Session) -> None:
    """Freeze plugin registration before collection imports test modules."""
    if os.environ.get("PYTEST_XDIST_WORKER"):
        if "/workspace" not in sys.path:
            sys.path.insert(0, "/workspace")
        _freeze_worker_plugin_registration(session.config)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del exitstatus
    if os.environ.get("PYTEST_XDIST_WORKER") and hasattr(session.config, "workeroutput"):
        session.config.workeroutput["meas_worker_integrity_guard"] = (
            WORKER_INTEGRITY_GUARD
            if (
                _WORKER_AUDIT_INSTALLED
                and _WORKER_CALL_CAPTURE_SEALED
                and _WORKER_REGISTRATION_FROZEN
            )
            else "missing"
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


def _write_attestation(payload: dict[str, Any]) -> None:
    """Write one complete protocol record directly to the controller stderr fd."""
    pending = (
        ATTESTATION_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    while pending:
        written = os.write(2, pending)
        if written <= 0:
            raise RuntimeError(
                "HARNESS: unable to write the pytest attestation record. "
                "Next action: restore the controller stderr pipe and rerun the predicate."
            )
        pending = pending[written:]


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
        "schema_version": 4,
        "completed": True,
        "exit_code": logical_exit_code,
        "collected": plugin.collected,
        "terminal": plugin.worker_terminal,
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
    _write_attestation(payload)
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

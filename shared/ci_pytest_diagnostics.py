"""Opt-in native pytest evidence, consumed by the CI shard classifier.

One append-only stream per process incarnation; never capture values, environment,
traceback locals or report bodies. Missing evidence is not a successful protocol.
"""

from __future__ import annotations

import ctypes
import faulthandler
import json
import math
import os
import select
import signal
import subprocess
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

import pytest


def context():
    return {
        key: os.environ.get(env, "unknown")
        for key, env in {
            "run_id": "GITHUB_RUN_ID",
            "run_attempt": "GITHUB_RUN_ATTEMPT",
            "head_sha": "GITHUB_SHA",
            "source_head_sha": "HAPAX_CI_SOURCE_HEAD_SHA",
            "job": "GITHUB_JOB",
            "event_name": "GITHUB_EVENT_NAME",
            "shard": "PYTEST_SHARD",
            "shard_count": "PYTEST_SHARD_COUNT",
        }.items()
    }


def write_record(fd, record):
    data = (json.dumps(record, sort_keys=True) + "\n").encode()
    if os.write(fd, data) != len(data):
        raise OSError("short diagnostic write")


def pidfd_call(name, *args):
    # The declared standalone Python can omit os.pidfd_open despite a capable
    # Linux/glibc host. Use the same libc API directly, with no PID-based fallback.
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, name)
    result = function(*args)
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return result


class Diagnostics:
    def __init__(self, config, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.identity = {
            **context(),
            "pid": os.getpid(),
            "worker": getattr(config, "workerinput", {}).get("workerid", "controller"),
            "incarnation": uuid.uuid4().hex,
            "stage": os.environ.get("HAPAX_CI_PHASE", "tests"),
        }
        stem = self.directory / self.identity["incarnation"]
        self.fd = os.open(str(stem) + ".events.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        # Raw descriptors deliberately live until OS process exit. Closing a
        # Python file in unconfigure/atexit would lose interpreter-shutdown stacks.
        self.stack_fd = os.open(
            str(stem) + ".stacks.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        self.guard_path = str(stem) + ".guard.jsonl"
        self.sequence = 0
        self.protocol = 0
        self.nodeid = ""
        self.seconds = float(os.environ.get("HAPAX_CI_EXIT_SECONDS", "30"))
        if not math.isfinite(self.seconds) or not 0 < self.seconds <= 30:
            raise ValueError("HAPAX_CI_EXIT_SECONDS must be in (0, 30]")
        self.pidfd = pidfd_call("pidfd_open", os.getpid(), 0)
        # Reuse pytest's own per-protocol watchdog and fatal-error destination.
        # Its duplicated descriptor may close at unconfigure; ours must not.
        from _pytest.faulthandler import fault_handler_stderr_fd_key

        if fault_handler_stderr_fd_key not in config.stash:
            raise ValueError("native pytest faulthandler plugin is required")
        os.dup2(self.stack_fd, config.stash[fault_handler_stderr_fd_key])
        self.emit("configured", origin=str(Path(__file__).resolve()))

    def emit(self, event, **fields):
        self.sequence += 1
        try:
            write_record(
                self.fd,
                {
                    **self.identity,
                    "seq": self.sequence,
                    "time": time.time(),
                    "event": event,
                    **fields,
                },
            )
        except OSError as exc:
            raise RuntimeError(f"CI diagnostics unavailable: {exc}") from exc

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item):
        self.protocol += 1
        self.nodeid = item.nodeid
        self.emit("protocol_start", nodeid=self.nodeid, protocol=self.protocol)
        result = yield
        self.emit("protocol_complete", nodeid=self.nodeid, protocol=self.protocol)
        return result

    def phase(self, when):
        self.emit("phase_start", nodeid=self.nodeid, protocol=self.protocol, when=when)

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_setup(self):
        self.phase("setup")

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_call(self):
        self.phase("call")

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_teardown(self):
        self.phase("teardown")

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_makereport(self):
        report = yield
        self.emit(
            "report",
            nodeid=report.nodeid,
            protocol=self.protocol,
            when=report.when,
            outcome=report.outcome,
        )
        return report

    def pytest_runtest_logreport(self, report):
        # Controller forwarding is useful corroboration, never another execution.
        if hasattr(report, "node"):
            self.emit(
                "forwarded_report",
                worker_id=report.node.gateway.id,
                nodeid=report.nodeid,
                when=report.when,
                outcome=report.outcome,
            )

    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node):
        node.workerinput["ci_diagnostics_dir"] = str(self.directory)

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodeready(self, node):
        self.emit("worker_ready", worker_id=node.gateway.id)

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node, error):
        self.emit("worker_down", worker_id=node.gateway.id, crashed=error is not None)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_sessionfinish(self, exitstatus):
        self.emit("sessionfinish_start", exitstatus=int(exitstatus))
        # Arm before root cleanup, keep armed through unconfigure and atexit.
        # CPython's C watchdog dumps all threads even if the GIL is held.
        faulthandler.dump_traceback_later(self.seconds, file=self.stack_fd, exit=True)
        # CPython itself retires faulthandler late in finalization. A tiny Linux
        # pidfd guard bounds the remaining lifetime without PID reuse races or
        # treating a returned hook / inherited pipe EOF as process death.
        pidfd = self.pidfd
        try:
            self.guard = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).resolve()),
                    "watch",
                    str(pidfd),
                    str(self.seconds + 2),
                    self.guard_path,
                    json.dumps(self.identity),
                ],
                pass_fds=(pidfd,),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=self.stack_fd,
            )
        finally:
            os.close(pidfd)
        result = yield
        self.emit("sessionfinish_complete", exitstatus=int(exitstatus))
        return result


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    # Consume activation once. Unrelated nested pytest subprocesses must not
    # contaminate this shard's outcomes; xdist receives an explicit worker input.
    directory = os.environ.pop("HAPAX_CI_DIAGNOSTICS_DIR", None)
    directory = getattr(config, "workerinput", {}).get("ci_diagnostics_dir", directory)
    if directory:
        try:
            config.pluginmanager.register(Diagnostics(config, directory), "ci-native-diagnostics")
        except (OSError, ValueError, AttributeError) as exc:
            raise pytest.UsageError(f"CI diagnostics unavailable: {exc}") from exc


def watch(pidfd, seconds, path, identity):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    if select.select([pidfd], [], [], seconds)[0]:
        event = "process_exit_observed"
    else:
        event = "session_exit_forced"
        try:
            pidfd_call("pidfd_send_signal", pidfd, signal.SIGKILL, None, 0)
        except ProcessLookupError:
            event = "process_exit_observed"
    write_record(fd, {**identity, "event": event, "seq": 1, "time": time.time()})
    os.close(fd)
    os.close(pidfd)


def phase(name, status):
    directory = Path(os.environ["HAPAX_CI_DIAGNOSTICS_DIR"])
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / "phases.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        write_record(fd, {**context(), "event": name, "status": status, "time": time.time()})
    finally:
        os.close(fd)


def summarize(directory):
    paths = sorted(Path(directory).glob("*.jsonl"))
    unknown = not paths
    protocols = {}
    outcomes = Counter()
    workers, expected = set(), set()
    sessions, finished = set(), set()
    armed, exited = set(), set()
    for path in paths:
        seq = 0
        try:
            lines = path.read_text().splitlines(keepends=True)
        except OSError:
            print(f"diagnostic unreadable: {path.name}")
            unknown = True
            continue
        for line in lines:
            try:
                e = json.loads(line)
                if not line.endswith("\n") or any(e[k] != v for k, v in context().items()):
                    raise ValueError("truncated or foreign identity")
                event = e["event"]
                if path.name == "phases.jsonl":
                    print(f"step phase: {event} status={e['status']}")
                    continue
                if e["seq"] != seq + 1:
                    raise ValueError("sequence gap or duplicate")
                seq = e["seq"]
                identity = e["incarnation"]
                if event == "configured":
                    sessions.add(identity)
                    workers.add(e["worker"])
                if event == "sessionfinish_complete":
                    finished.add(identity)
                if event == "sessionfinish_start":
                    armed.add(identity)
                if event in {"process_exit_observed", "session_exit_forced"}:
                    exited.add(identity)
                if event == "worker_ready":
                    expected.add(e["worker_id"])
                if event in {
                    "sessionfinish_start",
                    "sessionfinish_complete",
                    "root_cleanup_start",
                    "root_cleanup_complete",
                    "worker_down",
                    "session_exit_forced",
                }:
                    print(f"session evidence: {json.dumps(e, sort_keys=True)}")
                if event == "session_exit_forced":
                    unknown = True
                if event == "forwarded_report":
                    continue
                if "protocol" not in e:
                    continue
                key = (identity, e["protocol"])
                p = protocols.setdefault(
                    key,
                    {
                        "nodeid": e["nodeid"],
                        "worker": e["worker"],
                        "started": False,
                        "complete": False,
                        "last": "unknown",
                    },
                )
                if event == "protocol_start":
                    p["started"] = True
                elif event == "protocol_complete":
                    p["complete"] = True
                elif event == "phase_start":
                    p["last"] = e["when"] + " started"
                elif event == "report":
                    outcomes[(e["when"], e["outcome"])] += 1
                    p["last"] = e["when"] + " " + e["outcome"]
                    if e["outcome"] == "failed":
                        print(
                            f"observed failed phase: {e['nodeid']} {e['when']} worker={e['worker']} incarnation={identity}"
                        )
            except (ValueError, KeyError, TypeError):
                print(f"diagnostic truncated/invalid/foreign record: {path.name}")
                unknown = True
                break
    for (identity, _), p in protocols.items():
        if not (p["started"] and p["complete"]):
            print(
                f"unfinished protocol: {p['nodeid']} worker={p['worker']} incarnation={identity} last={p['last']}"
            )
            unknown = True
    for worker in sorted(expected - workers):
        print(f"missing worker event file: {worker}")
        unknown = True
    if not sessions or sessions - finished or armed - exited:
        unknown = True
    print(
        "observed phase counts: "
        + json.dumps({f"{k[0]}:{k[1]}": v for k, v in sorted(outcomes.items())})
    )
    print(
        "diagnostic coverage: "
        + (
            "incomplete/unknown"
            if unknown
            else "recorded protocols complete; process exit classified separately"
        )
    )
    print(f"stack files: {directory}/*.stacks.txt (absence is unobserved, not pass)")
    return int(unknown or any(outcome == "failed" for _, outcome in outcomes))


if __name__ == "__main__":
    if sys.argv[1] == "watch":
        watch(int(sys.argv[2]), float(sys.argv[3]), sys.argv[4], json.loads(sys.argv[5]))
    elif sys.argv[1] == "phase":
        phase(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "summary":
        sys.exit(summarize(sys.argv[2]))

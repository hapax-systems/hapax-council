"""Tests for scripts/hapax-flow-reader — the durable reader of the merge-flow verdict."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import re
import shlex
import subprocess
from pathlib import Path

import pytest

from agents.health_monitor.models import CheckResult, HealthReport, Status, build_group_result

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "hapax-flow-reader"
UNITS = ("hapax-flow-reader.service", "hapax-flow-reader.timer")
FORBIDDEN_TOKENS = ("--apply", "--fix", "--dry-run", "health-watchdog")


def _load():
    loader = importlib.machinery.SourceFileLoader("hapax_flow_reader", str(SCRIPT))
    spec = importlib.util.spec_from_loader("hapax_flow_reader", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def reader(tmp_path, monkeypatch):
    module = _load()
    monkeypatch.setattr(module, "ALERT_STATE_PATH", tmp_path / "alert-state.json")
    monkeypatch.setattr(module, "UNREAD_STATE_PATH", tmp_path / "unread-state.json")
    clock = [1_000_000.0]
    monkeypatch.setattr("shared.alert_state.time.time", lambda: clock[0])
    module.test_clock = clock
    return module


def _flow_report(status: str, message: str) -> str:
    """A flow report in the producer's own shape, as the CLI prints it."""

    check = CheckResult(
        name="flow.merge_plane", group="flow", status=Status(status), message=message
    )
    group = build_group_result("flow", [check])
    return HealthReport(
        timestamp="2026-10-10T00:00:00+00:00",
        hostname="test-host",
        overall_status=group.status,
        groups=[group],
    ).model_dump_json()


class _FakeRun:
    """Stands in for subprocess.run: the flow check prints ``stdout``; sends are recorded."""

    def __init__(self, stdout: str = "", *, send_ok: bool = True, raise_timeout: bool = False):
        self.stdout = stdout
        self.send_ok = send_ok
        self.raise_timeout = raise_timeout
        self.flow_calls: list[list[str]] = []
        self.sends: list[dict[str, str]] = []

    def __call__(self, argv, **kwargs):
        if "agents.health_monitor" in argv:
            self.flow_calls.append(list(argv))
            if self.raise_timeout:
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
            return subprocess.CompletedProcess(argv, 0, stdout=self.stdout, stderr="")
        options = {argv[i]: argv[i + 1] for i in range(2, len(argv) - 1, 2)}
        self.sends.append(options)
        return subprocess.CompletedProcess(argv, 0 if self.send_ok else 1, stdout="", stderr="")


# ── Units are parked, and the command is a read ─────────────────────────────


def test_both_units_are_parked_against_auto_activation() -> None:
    marker = re.compile(r"(?mi)^[#;][ \t]*Hapax-Parked:[ \t]*(?:true|yes|1)[ \t]*$")
    for unit in UNITS:
        text = (ROOT / "systemd" / "units" / unit).read_text(encoding="utf-8")
        assert marker.search(text), unit


def test_the_flow_command_is_exactly_the_flow_check_and_nothing_mutating() -> None:
    module = _load()
    assert tuple(module.FLOW_COMMAND[1:]) == (
        "-m",
        "agents.health_monitor",
        "--check",
        "flow",
        "--json",
    )
    assert not set(module.FLOW_COMMAND) & set(FORBIDDEN_TOKENS)


def test_the_service_runs_only_this_script() -> None:
    text = (ROOT / "systemd" / "units" / "hapax-flow-reader.service").read_text(encoding="utf-8")
    exec_lines = [line for line in text.splitlines() if line.startswith("ExecStart=")]
    assert len(exec_lines) == 1
    tokens = shlex.split(exec_lines[0].removeprefix("ExecStart="))
    assert len(tokens) == 2
    assert tokens[0].endswith("/.venv/bin/python")
    assert tokens[1].endswith("/scripts/hapax-flow-reader")
    assert not set(tokens) & set(FORBIDDEN_TOKENS)


def test_the_reader_invokes_the_flow_command_it_declares(reader) -> None:
    run = _FakeRun(_flow_report("healthy", "merging"))

    assert reader.main(run=run) == 0

    assert run.flow_calls == [list(reader.FLOW_COMMAND)]


# ── Delivery semantics on producer-shaped reports ───────────────────────────


def test_failed_is_delivered_once_at_priority_one_and_never_repeated_unchanged(reader) -> None:
    run = _FakeRun(_flow_report("failed", "merge group red: test_x"))

    reader.main(run=run)
    reader.test_clock[0] += 6 * 3600
    reader.main(run=run)

    assert len(run.sends) == 1
    sent = run.sends[0]
    assert sent["--subject"] == "Health: flow"
    assert sent["--priority"] == "1"
    assert sent["--task-id"] == reader.TASK_ID
    assert "test_x" in sent["--payload"]


def test_a_failure_with_a_new_cause_is_delivered_again(reader) -> None:
    run = _FakeRun(_flow_report("failed", "merge group red: test_x"))
    reader.main(run=run)
    run.stdout = _flow_report("failed", "merge group red: test_y")

    reader.main(run=run)

    assert [s["--payload"] for s in run.sends] == [
        "flow.merge_plane: merge group red: test_x",
        "flow.merge_plane: merge group red: test_y",
    ]


def test_degraded_waits_two_hours_then_is_delivered_once(reader) -> None:
    run = _FakeRun(_flow_report("degraded", "no merge for 13h"))

    reader.main(run=run)
    reader.test_clock[0] += 7199
    reader.main(run=run)
    assert run.sends == []

    reader.test_clock[0] += 1
    reader.main(run=run)
    reader.test_clock[0] += 3600
    reader.main(run=run)

    assert len(run.sends) == 1
    assert run.sends[0]["--priority"] == "2"


def test_recovery_is_delivered_once_as_an_advisory(reader) -> None:
    run = _FakeRun(_flow_report("failed", "red"))
    reader.main(run=run)
    run.stdout = _flow_report("healthy", "merging")

    reader.main(run=run)
    reader.main(run=run)

    assert [s["--subject"] for s in run.sends] == ["Health: flow", "Recovered"]
    assert run.sends[1]["--priority"] == "2"
    assert run.sends[1]["--type"] == "advisory"


def test_a_failed_send_restores_the_state_so_the_next_run_delivers(reader) -> None:
    run = _FakeRun(_flow_report("failed", "red"), send_ok=False)

    assert reader.main(run=run) == 1

    run.send_ok = True
    assert reader.main(run=run) == 0
    assert len(run.sends) == 2


# ── An unread verdict is never a healthy one ────────────────────────────────


@pytest.mark.parametrize(
    ("fake", "cause_fragment"),
    [
        (_FakeRun(raise_timeout=True), "timed out"),
        (_FakeRun("Traceback: boom"), "no JSON"),
        (_FakeRun(json.dumps({"groups": []})), "no overall_status"),
    ],
)
def test_an_unread_verdict_delivers_one_flow_unread_advisory(reader, fake, cause_fragment) -> None:
    reader.main(run=fake)
    reader.main(run=fake)

    assert len(fake.sends) == 1
    assert fake.sends[0]["--subject"] == "flow unread"
    assert cause_fragment in fake.sends[0]["--payload"]
    assert not reader.ALERT_STATE_PATH.exists()


def test_unread_after_a_failure_does_not_count_as_recovery(reader) -> None:
    run = _FakeRun(_flow_report("failed", "red"))
    reader.main(run=run)
    run.stdout = "not json"
    reader.main(run=run)
    run.stdout = _flow_report("failed", "red")

    reader.main(run=run)

    assert [s["--subject"] for s in run.sends] == ["Health: flow", "flow unread"]


def test_a_changed_unread_cause_is_delivered_again(reader) -> None:
    run = _FakeRun("not json")
    reader.main(run=run)
    run.stdout = json.dumps({"groups": []})

    reader.main(run=run)

    assert [s["--subject"] for s in run.sends] == ["flow unread", "flow unread"]

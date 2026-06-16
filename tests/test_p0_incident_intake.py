from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import pytest

import shared.p0_incident_intake as p0_intake
from shared.p0_incident_intake import (
    DEFAULT_AUTHORITY_CASE,
    DEFAULT_PARENT_SPEC,
    classify_notification,
    record_notification,
    replace_id_for_fingerprint,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
INTAKE_SCRIPT = REPO_ROOT / "scripts" / "hapax-p0-incident-intake"


def _latest_alert_section(text: str) -> str:
    return text.split("## Latest Alert", 1)[1].split("## Evidence", 1)[0]


def _write_fake_bin(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _load_cli_module():
    loader = SourceFileLoader("hapax_p0_incident_intake_cli", str(INTAKE_SCRIPT))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_service_failure_creates_governed_p0_task(tmp_path):
    task_root = tmp_path / "tasks"
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "events.jsonl"
    now = datetime(2026, 6, 12, 20, 0, tzinfo=UTC)

    result = record_notification(
        "Service Failed: hapax-youtube-video-id.service",
        "Google OAuth token is revoked; inspect the user unit journal.",
        priority="urgent",
        tags=["skull"],
        task_root=task_root,
        state_path=state_path,
        ledger_path=ledger_path,
        now=now,
    )

    assert result.technical is True
    assert result.created is True
    assert result.updated is False
    assert result.task_id is not None
    assert result.fingerprint == "systemd_service_failed:hapax-youtube-video-id.service"
    assert result.replace_id == replace_id_for_fingerprint(result.fingerprint)
    assert result.click_url and result.click_url.startswith("obsidian://open?vault=Personal")
    assert result.task_path is not None and result.task_path.exists()

    task = result.task_path.read_text(encoding="utf-8")
    assert "priority: p0" in task
    assert "quality_floor: frontier_review_required" in task
    assert "route_metadata_schema: 1" in task
    assert f"parent_spec: {DEFAULT_PARENT_SPEC}" in task
    assert f"authority_case: {DEFAULT_AUTHORITY_CASE}" in task
    assert "stage: S6_IMPLEMENTATION" in task
    assert "implementation_authorized: true" in task
    assert "source_mutation_authorized: true" in task
    assert "runtime_mutation_authorized: true" in task
    assert "## Required Work" in task
    assert str(ledger_path) in task
    assert str(state_path) in task

    events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 1
    assert events[0]["kind"] == "p0_incident_notification"
    assert events[0]["task_id"] == result.task_id


def test_same_incident_updates_existing_task(tmp_path):
    task_root = tmp_path / "tasks"
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "events.jsonl"
    first = datetime(2026, 6, 12, 20, 0, tzinfo=UTC)
    second = first + timedelta(minutes=5)

    first_result = record_notification(
        "SDLC invariant violation",
        "INV-2 false: local worktree ledger drift",
        priority="urgent",
        tags=["skull"],
        task_root=task_root,
        state_path=state_path,
        ledger_path=ledger_path,
        now=first,
    )
    second_result = record_notification(
        "SDLC invariant violation",
        r"INV-2 false: local worktree ledger drift remains; literal backref \1 must survive",
        priority="urgent",
        tags=["skull"],
        task_root=task_root,
        state_path=state_path,
        ledger_path=ledger_path,
        now=second,
    )

    assert first_result.created is True
    assert second_result.created is False
    assert second_result.updated is True
    assert second_result.task_path == first_result.task_path
    assert list((task_root / "active").glob("*.md")) == [first_result.task_path]

    state = json.loads(state_path.read_text(encoding="utf-8"))
    incident = state["incidents"][first_result.fingerprint]
    assert incident["count"] == 2

    task = first_result.task_path.read_text(encoding="utf-8")
    assert "incident_count: 2" in task
    assert task.count("## Latest Alert") == 1
    assert "- Count: 2" in task
    assert "- Last seen: `2026-06-12T20:05:00Z`" in task
    latest = _latest_alert_section(task)
    assert r"literal backref \1 must survive" in latest
    assert "INV-2 false: local worktree ledger drift remains" in latest
    assert "INV-2 false: local worktree ledger drift\n```" not in latest
    assert "p0-incident-intake updated" in task


def test_existing_task_without_latest_alert_gets_repaired(tmp_path):
    task_root = tmp_path / "tasks"
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "events.jsonl"
    first = datetime(2026, 6, 12, 20, 0, tzinfo=UTC)
    second = first + timedelta(minutes=5)

    first_result = record_notification(
        "Service Failed: demo.service",
        "first failure text",
        priority="urgent",
        tags=["skull"],
        task_root=task_root,
        state_path=state_path,
        ledger_path=ledger_path,
        now=first,
    )
    task_text = first_result.task_path.read_text(encoding="utf-8")
    task_text = re.sub(r"(?s)## Latest Alert\n\n.*?\n## Evidence\n", "## Evidence\n", task_text)
    first_result.task_path.write_text(task_text, encoding="utf-8")

    record_notification(
        "Service Failed: demo.service",
        "second failure text",
        priority="urgent",
        tags=["skull"],
        task_root=task_root,
        state_path=state_path,
        ledger_path=ledger_path,
        now=second,
    )

    repaired = first_result.task_path.read_text(encoding="utf-8")
    assert repaired.count("## Latest Alert") == 1
    assert repaired.index("## Latest Alert") < repaired.index("## Evidence")
    assert "second failure text" in _latest_alert_section(repaired)


def test_concurrent_alerts_preserve_single_task_and_count(tmp_path):
    task_root = tmp_path / "tasks"
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "events.jsonl"
    start_path = tmp_path / "start"
    worker_count = 8
    code = textwrap.dedent(
        """
        import sys
        import time
        from pathlib import Path

        from shared.p0_incident_intake import record_notification

        task_root = Path(sys.argv[1])
        state_path = Path(sys.argv[2])
        ledger_path = Path(sys.argv[3])
        start_path = Path(sys.argv[4])
        deadline = time.time() + 10
        while not start_path.exists():
            if time.time() > deadline:
                raise SystemExit("start timeout")
            time.sleep(0.005)
        result = record_notification(
            "Service Failed: demo.service",
            "systemd OnFailure fired.",
            priority="urgent",
            tags=["skull"],
            task_root=task_root,
            state_path=state_path,
            ledger_path=ledger_path,
        )
        print(result.task_id)
        """
    )
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                code,
                str(task_root),
                str(state_path),
                str(ledger_path),
                str(start_path),
            ],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(worker_count)
    ]

    start_path.write_text("go", encoding="utf-8")
    outputs = [process.communicate(timeout=20) for process in processes]

    for process, (stdout, stderr) in zip(processes, outputs, strict=True):
        assert process.returncode == 0, f"stdout={stdout}\nstderr={stderr}"

    task_files = list((task_root / "active").glob("p0-incident-*.md"))
    assert len(task_files) == 1

    state = json.loads(state_path.read_text(encoding="utf-8"))
    incident = next(iter(state["incidents"].values()))
    assert incident["count"] == worker_count
    assert len(ledger_path.read_text(encoding="utf-8").splitlines()) == worker_count
    assert f"incident_count: {worker_count}" in task_files[0].read_text(encoding="utf-8")


def test_record_notification_requires_durable_ledger_append(tmp_path, monkeypatch):
    task_root = tmp_path / "tasks"
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "events.jsonl"

    def fake_append_jsonl(*_args, **_kwargs):
        return False

    monkeypatch.setattr(p0_intake, "append_jsonl", fake_append_jsonl)

    with pytest.raises(RuntimeError, match="p0 incident ledger append failed"):
        record_notification(
            "Service Failed: demo.service",
            "systemd OnFailure fired.",
            priority="urgent",
            tags=["skull"],
            task_root=task_root,
            state_path=state_path,
            ledger_path=ledger_path,
            now=datetime(2026, 6, 12, 20, 0, tzinfo=UTC),
        )

    assert not state_path.exists()
    assert not ledger_path.exists()


def test_high_priority_nontechnical_notification_does_not_create_task(tmp_path):
    task_root = tmp_path / "tasks"
    result = record_notification(
        "T",
        "M",
        priority="urgent",
        tags=["skull"],
        task_root=task_root,
        state_path=tmp_path / "state.json",
        ledger_path=tmp_path / "events.jsonl",
        now=datetime(2026, 6, 12, 20, 0, tzinfo=UTC),
    )

    assert result.technical is False
    assert result.reason == "no_technical_pattern"
    assert not (task_root / "active").exists()


def test_technical_pattern_below_p0_priority_is_not_intake():
    classification = classify_notification(
        "Service Failed: example.service",
        "journalctl hint",
        priority="default",
        tags=[],
    )

    assert classification.technical is False
    assert classification.reason == "below_p0_priority"


def test_lane_supervisor_alert_gets_stable_operational_fingerprint():
    classification = classify_notification(
        "Hapax lane-supervisor: zeta launcher over lifetime ceiling",
        "Headless launcher exceeded the max lifetime and was reaped.",
        priority="urgent",
        tags=["skull"],
    )

    assert classification.technical is True
    assert classification.kind == "lane_supervisor_alert"
    assert classification.fingerprint == "lane_supervisor_alert:launcher_lifetime:zeta"


def test_lufs_panic_cap_alert_gets_technical_intake():
    classification = classify_notification(
        "LUFS panic-cap",
        "Broadcast master peaked -3.50 LUFS-S sustained 1000ms.",
        priority="high",
        tags=[],
    )

    assert classification.technical is True
    assert classification.kind == "audio_lufs_breach"
    assert classification.fingerprint == "audio_lufs_breach:lufs-panic-cap"


def test_service_failed_cli_records_incident_and_sends_bounded_pointer(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    notify_log = tmp_path / "notify.log"
    _write_fake_bin(
        fake_bin / "gdbus",
        """
        #!/usr/bin/env bash
        printf '%s\n' "$@" >> "$HAPAX_NOTIFY_CAPTURE"
        """,
    )
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "HAPAX_NOTIFY_CAPTURE": str(notify_log),
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            str(INTAKE_SCRIPT),
            "service-failed",
            "--task-root",
            str(tmp_path / "tasks"),
            "--state-path",
            str(tmp_path / "state.json"),
            "--ledger-path",
            str(tmp_path / "events.jsonl"),
            "demo.service",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "created p0-incident-systemd-service-failed-demo-service" in result.stdout
    assert list((tmp_path / "tasks" / "active").glob("p0-incident-*.md"))
    assert (tmp_path / "state.json").is_file()
    assert (tmp_path / "events.jsonl").is_file()
    notify_text = notify_log.read_text(encoding="utf-8")
    notify_args = notify_text.splitlines()
    assert "org.freedesktop.Notifications.Notify" in notify_text
    assert json.loads(notify_args[8]) == "Hapax System"
    assert json.loads(notify_args[10]) == "dialog-error"
    assert json.loads(notify_args[11]) == "Service Failed: demo.service"
    assert json.loads(notify_args[12]).startswith(
        "SDLC intake: p0-incident-systemd-service-failed-demo-service"
    )
    assert "SDLC intake: p0-incident-systemd-service-failed-demo-service" in notify_text
    assert "journalctl --user -u demo.service" in notify_text


def test_service_failed_cli_falls_back_to_desktop_when_recording_fails(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    notify_log = tmp_path / "notify.log"
    _write_fake_bin(
        fake_bin / "notify-send",
        """
        #!/usr/bin/env bash
        printf '%s\n' "$@" >> "$HAPAX_NOTIFY_CAPTURE"
        """,
    )
    task_root_file = tmp_path / "task-root-is-file"
    task_root_file.write_text("not a directory", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "HAPAX_NOTIFY_CAPTURE": str(notify_log),
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            str(INTAKE_SCRIPT),
            "service-failed",
            "--task-root",
            str(task_root_file),
            "--state-path",
            str(tmp_path / "state.json"),
            "--ledger-path",
            str(tmp_path / "events.jsonl"),
            "demo.service",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "p0 incident intake failed:" in result.stderr
    assert "Next action: inspect P0 intake storage" in result.stderr
    assert "task_root=" in result.stderr
    notify_text = notify_log.read_text(encoding="utf-8")
    assert "--urgency=critical" in notify_text
    assert "P0 intake failed: Service Failed: demo.service" in notify_text
    assert "SDLC intake failed before task creation" in notify_text


def test_cli_dismiss_existing_intake_notifications_uses_mako_marker(monkeypatch):
    cli = _load_cli_module()
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd == ["makoctl", "list", "-j"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    [
                        {"id": 21, "body": "SDLC intake: p0-incident-cli\nold"},
                        {"id": 22, "body": "other task"},
                        {"id": 23, "body": "SDLC intake: p0-incident-cli\nnew"},
                    ]
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    cli._dismiss_existing_intake_notifications("p0-incident-cli")

    assert calls[0][0] == ["makoctl", "list", "-j"]
    assert [call[0] for call in calls[1:]] == [
        ["makoctl", "dismiss", "--no-history", "-n", "21"],
        ["makoctl", "dismiss", "--no-history", "-n", "23"],
    ]

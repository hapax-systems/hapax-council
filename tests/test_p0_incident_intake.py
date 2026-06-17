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
    assert "## Acceptance criteria" in task
    assert "## Post-mortem" in task
    assert "recurrence-prevention notes are written" in task
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


def test_recurrence_after_closed_task_mints_new_active_task_with_prior_context(tmp_path):
    task_root = tmp_path / "tasks"
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "events.jsonl"
    first = datetime(2026, 6, 12, 20, 0, tzinfo=UTC)
    second = first + timedelta(hours=2)

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
    assert first_result.task_path is not None
    first_task = first_result.task_path.read_text(encoding="utf-8")
    first_task = first_task.replace("status: offered", "status: done", 1)
    first_task = first_task.replace("completed_at: null", "completed_at: 2026-06-12T20:30:00Z", 1)
    first_task += textwrap.dedent(
        """

        ## Resolution

        Root cause: demo unit used a stale deploy path.
        Remediation: unit path was source-activation rooted.
        Verification: journal stayed clean for one timer cycle.
        """
    )
    closed_dir = task_root / "closed"
    closed_dir.mkdir(parents=True)
    closed_path = closed_dir / first_result.task_path.name
    closed_path.write_text(first_task, encoding="utf-8")
    first_result.task_path.unlink()

    second_result = record_notification(
        "Service Failed: demo.service",
        "second failure text after the prior task was closed",
        priority="urgent",
        tags=["skull"],
        task_root=task_root,
        state_path=state_path,
        ledger_path=ledger_path,
        now=second,
    )

    assert second_result.created is True
    assert second_result.updated is False
    assert second_result.recurrence is True
    assert second_result.recurrence_of_task_id == first_result.task_id
    assert second_result.recurrence_of_task_path == closed_path
    assert second_result.task_id != first_result.task_id
    assert second_result.task_id == f"{first_result.task_id}-r1"
    assert second_result.task_path is not None
    assert second_result.task_path.parent == task_root / "active"
    assert closed_path.exists()

    task = second_result.task_path.read_text(encoding="utf-8")
    assert "## Prior Incident Context" in task
    assert f"recurrence_of_task_id: {first_result.task_id}" in task
    assert f'recurrence_of_task_path: "{closed_path}"' in task
    assert "This alert recurred after prior task" in task
    assert "Root cause: demo unit used a stale deploy path." in task
    assert "second failure text after the prior task was closed" in task

    state = json.loads(state_path.read_text(encoding="utf-8"))
    incident = state["incidents"][first_result.fingerprint]
    assert incident["task_id"] == second_result.task_id
    assert incident["base_task_id"] == first_result.task_id
    assert incident["recurrence_count"] == 1
    assert incident["recurrence_of_task_id"] == first_result.task_id
    assert incident["recurrence_of_task_path"] == str(closed_path)

    events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert events[-1]["recurrence"] is True
    assert events[-1]["recurrence_count"] == 1
    assert events[-1]["recurrence_of_task_id"] == first_result.task_id


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


def test_ledger_append_failure_fails_open_and_persists_state(tmp_path, monkeypatch):
    """Fail-open: a ledger IO failure must NOT abort the coalescing-state write (else the
    next identical alert re-mints -> re-flood). No exception; state persisted; recurrence
    still coalesces even while the ledger is failing."""
    task_root = tmp_path / "tasks"
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "events.jsonl"

    monkeypatch.setattr(p0_intake, "append_jsonl", lambda *_a, **_k: False)

    result = record_notification(
        "Service Failed: demo.service",
        "systemd OnFailure fired.",
        priority="urgent",
        tags=["skull"],
        task_root=task_root,
        state_path=state_path,
        ledger_path=ledger_path,
        now=datetime(2026, 6, 12, 20, 0, tzinfo=UTC),
    )
    assert result.created is True
    assert state_path.exists()
    assert len(json.loads(state_path.read_text())["incidents"]) == 1

    result2 = record_notification(
        "Service Failed: demo.service",
        "systemd OnFailure fired again.",
        priority="urgent",
        tags=["skull"],
        task_root=task_root,
        state_path=state_path,
        ledger_path=ledger_path,
        now=datetime(2026, 6, 12, 20, 1, tzinfo=UTC),
    )
    assert result2.task_id == result.task_id
    assert result2.created is False
    assert list(json.loads(state_path.read_text())["incidents"].values())[0]["count"] == 2


def test_rotate_ledger_when_oversized(tmp_path):
    ledger = tmp_path / "events.jsonl"
    ledger.write_text("x" * 100)
    p0_intake._rotate_ledger(ledger, max_bytes=50)
    assert (tmp_path / "events.jsonl.1").exists()
    assert not ledger.exists()
    ledger.write_text("y" * 10)
    p0_intake._rotate_ledger(ledger, max_bytes=50)
    assert ledger.exists()


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


def test_audio_topology_drift_alert_gets_technical_intake():
    classification = classify_notification(
        "Audio: Topology Drift",
        "Topology drift: module appeared — +module-loopback:source=hapax-livestream",
        priority="high",
        tags=["audio", "warning"],
    )

    assert classification.technical is True
    assert classification.kind == "audio_topology_drift"
    assert classification.fingerprint == "audio_topology_drift:audio-topology-drift"


def test_sdlc_dispatch_refusal_alert_gets_technical_intake():
    classification = classify_notification(
        "SDLC: dispatch refusal circuit breaker",
        "Task p0-incident-demo refused 3x on lane delta. Reason: dispatch_exit_16",
        priority="high",
        tags=["sdlc", "no-spin"],
    )

    assert classification.technical is True
    assert classification.kind == "sdlc_dispatch_refusal"
    assert classification.fingerprint == "sdlc_dispatch_refusal:p0-incident-demo"


def test_sdlc_task_stuck_on_normal_task_gets_technical_intake():
    classification = classify_notification(
        "SDLC: task stuck, blocked",
        "segprep-g1-config-criterion-20260615 stalled and was reoffered 3x without progress; set to blocked.",
        priority="high",
        tags=["sdlc", "stalled"],
    )

    assert classification.technical is True
    assert classification.kind == "sdlc_task_stalled"
    assert classification.fingerprint == "sdlc_task_stalled:segprep-g1-config-criterion-20260615"


def test_sdlc_task_stuck_on_incident_task_does_not_remint():
    # Self-amplification break: a stalled AUTO-MINTED p0-incident task must NOT mint a
    # fresh sdlc_task_stalled P0 -- it would loop forever (these tasks are not lane-workable).
    classification = classify_notification(
        "SDLC: task stuck, blocked",
        "p0-incident-demo stalled and was reoffered 3x without progress; set to blocked.",
        priority="high",
        tags=["sdlc", "stalled"],
    )

    assert classification.technical is False
    assert classification.reason == "stalled_incident_task_no_remint"


def test_sdlc_dispatch_starvation_alert_gets_technical_intake():
    classification = classify_notification(
        "SDLC: dispatch starvation detected",
        "225 offered tasks have not dispatched for 3600s.",
        priority="high",
        tags=["sdlc", "no-spin"],
    )

    assert classification.technical is True
    assert classification.kind == "sdlc_dispatch_starvation"


def test_service_failed_cli_records_incident_and_consumes_desktop_by_default(tmp_path):
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
    assert not notify_log.exists()


def test_service_failed_cli_can_send_bounded_pointer_when_requested(tmp_path):
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
            "--desktop-confirmation",
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


def test_cli_drain_desktop_dismisses_consumed_intake_notifications(tmp_path, monkeypatch, capsys):
    cli = _load_cli_module()
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "events.jsonl"
    task_root = tmp_path / "tasks"
    state_path.write_text(
        json.dumps(
            {
                "incidents": {
                    "systemd_service_failed:demo.service": {
                        "fingerprint": "systemd_service_failed:demo.service",
                        "task_id": "p0-incident-demo",
                        "last_title": "Service Failed: demo.service",
                    },
                    "sdlc_dispatch_refusal:p0-incident-demo": {
                        "fingerprint": "sdlc_dispatch_refusal:p0-incident-demo",
                        "task_id": "p0-incident-refusal",
                        "last_title": "SDLC: dispatch refusal circuit breaker",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd == ["makoctl", "list", "-j"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    [
                        {"id": 21, "body": "SDLC intake: p0-incident-demo\nold"},
                        {
                            "id": 22,
                            "app_name": "Hapax System",
                            "summary": "Service Failed: demo.service",
                            "body": "raw",
                        },
                        {
                            "id": 23,
                            "app_name": "LLM Stack",
                            "summary": "SDLC: dispatch refusal circuit breaker",
                            "body": "Task p0-incident-demo refused 3x",
                        },
                        {"id": 24, "summary": "Service Failed: demo.service", "body": "user"},
                        {
                            "id": 26,
                            "app_name": "LLM Stack",
                            "summary": "Stack Failed",
                            "body": "101/123 healthy, 17 degraded, 5 failed",
                        },
                        {"id": 25, "app_name": "Hapax System", "summary": "Other", "body": ""},
                    ]
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    rc = cli.main(
        [
            "drain-desktop",
            "--task-root",
            str(task_root),
            "--state-path",
            str(state_path),
            "--ledger-path",
            str(ledger_path),
        ]
    )

    assert rc == 0
    assert [call[0] for call in calls[1:]] == [
        ["makoctl", "dismiss", "--no-history", "-n", "21"],
        ["makoctl", "dismiss", "--no-history", "-n", "22"],
        ["makoctl", "dismiss", "--no-history", "-n", "23"],
        ["makoctl", "dismiss", "--no-history", "-n", "26"],
    ]
    assert "dismissed 4 consumed P0 intake" in capsys.readouterr().out
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "health_stack_failed:stack-failed" in state["incidents"]
    assert list((task_root / "active").glob("p0-incident-health-stack-failed-*.md"))


def test_reap_resolved_incidents_drains_closed_and_recovered(tmp_path):
    # The 'drain' half: a closed remediation task OR a recovered systemd unit reaps
    # its incident from state.json; an active task / still-failing unit is kept.
    task_root = tmp_path / "tasks"
    (task_root / "active").mkdir(parents=True)
    (task_root / "closed").mkdir(parents=True)
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "events.jsonl"

    (task_root / "closed" / "p0-incident-aaa.md").write_text("closed", encoding="utf-8")
    (task_root / "active" / "p0-incident-bbb.md").write_text("active", encoding="utf-8")

    state = {
        "version": 1,
        "incidents": {
            "operational:aaa": {"kind": "lane_supervisor", "task_id": "p0-incident-aaa"},
            "operational:bbb": {"kind": "lane_supervisor", "task_id": "p0-incident-bbb"},
            "systemd_service_failed:demo.service": {
                "kind": "systemd_service_failed",
                "task_id": "p0-incident-ccc",
            },
            "systemd_service_failed:broken.service": {
                "kind": "systemd_service_failed",
                "task_id": "p0-incident-ddd",
            },
        },
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")

    reaped = p0_intake.reap_resolved_incidents(
        state_path=state_path,
        ledger_path=ledger_path,
        task_root=task_root,
        unit_recovered=lambda u: u == "demo.service",  # demo recovered; broken still down
    )

    assert dict(reaped) == {
        "operational:aaa": "task_closed",
        "systemd_service_failed:demo.service": "unit_recovered",
    }
    remaining = json.loads(state_path.read_text())["incidents"]
    assert set(remaining) == {"operational:bbb", "systemd_service_failed:broken.service"}

    rows = [json.loads(line) for line in ledger_path.read_text().splitlines() if line.strip()]
    assert {r["fingerprint"] for r in rows} == {
        "operational:aaa",
        "systemd_service_failed:demo.service",
    }
    assert all(r["kind"] == "p0_incident_resolved" for r in rows)


def test_reap_keeps_incident_when_unit_check_raises(tmp_path):
    # A health-probe exception must NOT reap (fail-safe: keep the incident).
    task_root = tmp_path / "tasks"
    (task_root / "active").mkdir(parents=True)
    (task_root / "closed").mkdir(parents=True)
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "events.jsonl"
    state = {
        "version": 1,
        "incidents": {
            "systemd_service_failed:flaky.service": {
                "kind": "systemd_service_failed",
                "task_id": "p0-incident-flaky",
            }
        },
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")

    def boom(_unit):
        raise RuntimeError("systemctl unavailable")

    reaped = p0_intake.reap_resolved_incidents(
        state_path=state_path,
        ledger_path=ledger_path,
        task_root=task_root,
        unit_recovered=boom,
    )
    assert reaped == []
    assert set(json.loads(state_path.read_text())["incidents"]) == {
        "systemd_service_failed:flaky.service"
    }
    assert not ledger_path.exists()  # fail-safe keep writes no p0_incident_resolved row


def test_reap_subcommand_drains_closed_task(tmp_path):
    # Exercises the `reap` CLI subcommand end-to-end against a closed-task incident.
    task_root = tmp_path / "tasks"
    (task_root / "active").mkdir(parents=True)
    (task_root / "closed").mkdir(parents=True)
    (task_root / "closed" / "p0-incident-zzz.md").write_text("closed", encoding="utf-8")
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "events.jsonl"
    state = {
        "version": 1,
        "incidents": {
            "operational:zzz": {"kind": "lane_supervisor", "task_id": "p0-incident-zzz"},
            # Drives the real `systemctl --user is-failed` callback end-to-end so a
            # NameError / missing import in the CLI cannot hide. Its fate depends on
            # the host's is-failed output, so the test only asserts the run succeeds.
            "systemd_service_failed:hapax-no-such-unit-xyz.service": {
                "kind": "systemd_service_failed",
                "task_id": "p0-incident-nosuch",
            },
        },
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(INTAKE_SCRIPT),
            "reap",
            "--task-root",
            str(task_root),
            "--state-path",
            str(state_path),
            "--ledger-path",
            str(ledger_path),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    assert result.returncode == 0, result.stderr
    remaining = json.loads(state_path.read_text())["incidents"]
    assert "operational:zzz" not in remaining  # closed-task incident drained


def test_reap_keeps_systemd_incident_when_unit_none_or_colonless(tmp_path):
    # systemd incidents are kept when no probe is supplied (unit_recovered=None) and
    # when the fingerprint has no ":" to derive a unit name from.
    task_root = tmp_path / "tasks"
    (task_root / "active").mkdir(parents=True)
    (task_root / "closed").mkdir(parents=True)
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "events.jsonl"
    state = {
        "version": 1,
        "incidents": {
            "systemd_service_failed:demo.service": {
                "kind": "systemd_service_failed",
                "task_id": "p0-incident-demo",
            },
            "malformedfingerprint": {
                "kind": "systemd_service_failed",
                "task_id": "p0-incident-mal",
            },
        },
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")

    # unit_recovered=None: no probe -> nothing reaped even if the unit is actually up
    assert (
        p0_intake.reap_resolved_incidents(
            state_path=state_path,
            ledger_path=ledger_path,
            task_root=task_root,
            unit_recovered=None,
        )
        == []
    )
    # colon-less fingerprint yields unit "" -> never reaped even with a True probe
    reaped = p0_intake.reap_resolved_incidents(
        state_path=state_path,
        ledger_path=ledger_path,
        task_root=task_root,
        unit_recovered=lambda _u: True,
    )
    assert ("malformedfingerprint", "unit_recovered") not in reaped
    assert "malformedfingerprint" in json.loads(state_path.read_text())["incidents"]


def test_reap_mutates_state_inside_the_lock(tmp_path, monkeypatch):
    # Regression guard for the concurrency fix: the load->decide->delete->store
    # cycle MUST happen INSIDE _state_file_lock, not merely enter it. An unlocked
    # store racing a live intake drops a freshly recorded incident. We assert the
    # actual _store_state call observes the lock held.
    import contextlib

    task_root = tmp_path / "tasks"
    (task_root / "active").mkdir(parents=True)
    (task_root / "closed").mkdir(parents=True)
    (task_root / "closed" / "p0-incident-l.md").write_text("closed", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "incidents": {
                    "operational:l": {"kind": "lane_supervisor", "task_id": "p0-incident-l"}
                },
            }
        ),
        encoding="utf-8",
    )
    held = {"now": False}
    store_observed_lock: list = []

    @contextlib.contextmanager
    def tracking_lock(_path):
        held["now"] = True
        try:
            yield
        finally:
            held["now"] = False

    real_store = p0_intake._store_state

    def tracking_store(path, state):
        store_observed_lock.append(held["now"])
        return real_store(path, state)

    monkeypatch.setattr(p0_intake, "_state_file_lock", tracking_lock)
    monkeypatch.setattr(p0_intake, "_store_state", tracking_store)
    reaped = p0_intake.reap_resolved_incidents(
        state_path=state_path,
        ledger_path=tmp_path / "events.jsonl",
        task_root=task_root,
    )
    assert reaped == [("operational:l", "task_closed")]
    # _store_state ran exactly once, and the lock was held when it ran
    assert store_observed_lock == [True]

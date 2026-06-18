from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WATCHDOG = REPO_ROOT / "systemd" / "watchdogs" / "health-watchdog"


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)
    return path


def _make_checkout(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / ".git").write_text("gitdir: fake\n", encoding="utf-8")
    return path


def _write_fake_intake_cli(root: Path, log_path: Path) -> Path:
    cli = root / "scripts" / "hapax-p0-incident-intake"
    cli.parent.mkdir(parents=True, exist_ok=True)
    return _write_executable(
        cli,
        f"""
        #!/usr/bin/env python3
        import json
        import sys
        with open({str(log_path)!r}, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(sys.argv[1:]) + "\\n")
        sys.exit(0)
        """,
    )


def _write_fake_uv(path: Path) -> Path:
    return _write_executable(
        path,
        r"""
        #!/usr/bin/env python3
        import json
        import os
        import subprocess
        import sys

        args = sys.argv[1:]
        log_path = os.environ.get("FAKE_UV_LOG")
        if log_path:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"args": args, "cwd": os.getcwd()}) + "\n")

        if args[:4] == ["run", "python", "-m", "agents.health_monitor"]:
            marker = os.environ.get("FAKE_APPLY_MARKER")
            status = os.environ.get("FAKE_HEALTH_STATUS", "healthy")
            if marker and os.environ.get("FAKE_HEALTH_STATUS_AFTER_APPLY") and os.path.exists(marker):
                status = os.environ["FAKE_HEALTH_STATUS_AFTER_APPLY"]
            failed = 2 if status == "failed" else 0
            report = {
                "timestamp": "2026-06-18T00:00:00Z",
                "overall_status": status,
                "summary": "98/100 healthy, 0 degraded, 2 failed" if failed else "all healthy",
                "healthy_count": 98 if failed else 100,
                "degraded_count": 0,
                "failed_count": failed,
                "duration_ms": 12,
                "groups": [
                    {
                        "checks": [
                            {"name": "demo", "status": "failed" if failed else "healthy"},
                        ],
                    },
                ],
            }
            if "--json" in args:
                if os.environ.get("FAKE_HEALTH_EMPTY_STDOUT"):
                    sys.exit(int(os.environ.get("FAKE_HEALTH_EMPTY_RC", "0")))
                print(json.dumps(report))
                sys.exit(2 if status == "failed" else 0)
            if "--apply" in args:
                if marker:
                    with open(marker, "w", encoding="utf-8") as fh:
                        fh.write("applied\n")
                print("apply attempted")
                sys.exit(0)

        if args[:3] == ["run", "python", "-c"]:
            proc = subprocess.run(
                [sys.executable, "-c", args[3]],
                env=os.environ,
                stdin=sys.stdin.buffer,
            )
            sys.exit(proc.returncode)

        print(f"unexpected fake uv args: {args}", file=sys.stderr)
        sys.exit(97)
        """,
    )


def _write_fake_shared_notify(root: Path) -> None:
    package = root / "shared"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "notify.py").write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import json
            import os

            def _append(record: dict) -> None:
                path = os.environ.get("FAKE_NOTIFY_LOG")
                if path:
                    with open(path, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(record, sort_keys=True) + "\\n")

            def send_notification(title: str, message: str, **kwargs) -> bool:
                _append(
                    {
                        "fn": "send_notification",
                        "title": title,
                        "message": message,
                        "kwargs": kwargs,
                    }
                )
                return True

            def send_webhook(url: str, payload: dict, **kwargs) -> bool:
                _append({"fn": "send_webhook", "url": url, "payload": payload})
                return True

            def nudges_uri() -> str:
                return "obsidian://nudges"
            """
        ).lstrip(),
        encoding="utf-8",
    )


def _base_env(
    tmp_path: Path,
    *,
    status: str = "healthy",
    pass_succeeds: bool = False,
    set_history_file: bool = True,
) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_uv = _write_fake_uv(bin_dir / "uv")
    pass_body = (
        "#!/usr/bin/env sh\nprintf 'fake-secret\\n'\n"
        if pass_succeeds
        else "#!/usr/bin/env sh\nexit 1\n"
    )
    _write_executable(bin_dir / "pass", pass_body)
    _write_executable(
        bin_dir / "notify-send",
        """
        #!/usr/bin/env sh
        printf '%s\n' "$*" >> "${FAKE_NOTIFY_SEND_LOG:-/dev/null}"
        exit 0
        """,
    )
    stub_root = tmp_path / "pythonpath"
    _write_fake_shared_notify(stub_root)

    env = os.environ.copy()
    env.update(
        {
            "FAKE_HEALTH_STATUS": status,
            "FAKE_NOTIFY_LOG": str(tmp_path / "notify.jsonl"),
            "FAKE_NOTIFY_SEND_LOG": str(tmp_path / "notify-send.log"),
            "FAKE_UV_LOG": str(tmp_path / "uv.jsonl"),
            "HAPAX_UV": str(fake_uv),
            "N8N_HEALTH_WEBHOOK_URL": "",
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "PYTHONPATH": f"{stub_root}:{env.get('PYTHONPATH', '')}",
        }
    )
    if set_history_file:
        env["HAPAX_HEALTH_HISTORY_FILE"] = str(tmp_path / "health-history.jsonl")
    return env


def _run_watchdog(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(WATCHDOG)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_source_activation_checkout_wins_over_runtime_override_by_default(tmp_path: Path) -> None:
    activation = _make_checkout(tmp_path / "source-activation")
    runtime = _make_checkout(tmp_path / "runtime")
    env = _base_env(tmp_path)
    env["HAPAX_HEALTH_MONITOR_REPO"] = str(runtime)
    env["HAPAX_SOURCE_ACTIVATION_WORKTREE"] = str(activation)

    result = _run_watchdog(env)

    assert result.returncode == 0, result.stderr
    records = _jsonl(tmp_path / "uv.jsonl")
    assert records[0]["cwd"] == str(activation)
    assert "/home/hapax/projects/hapax-council" not in result.stderr


def test_explicit_runtime_override_is_fallback_when_activation_missing(tmp_path: Path) -> None:
    runtime = _make_checkout(tmp_path / "runtime")
    env = _base_env(tmp_path)
    env["HAPAX_HEALTH_MONITOR_REPO"] = str(runtime)
    env["HAPAX_SOURCE_ACTIVATION_WORKTREE"] = str(tmp_path / "missing-activation")

    result = _run_watchdog(env)

    assert result.returncode == 0, result.stderr
    records = _jsonl(tmp_path / "uv.jsonl")
    assert records[0]["cwd"] == str(runtime)
    assert "using explicit HAPAX_HEALTH_MONITOR_REPO override" in result.stderr


def test_missing_activation_checkouts_fail_before_uv(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["HAPAX_HEALTH_MONITOR_REPO"] = str(tmp_path / "missing-runtime")
    env["HAPAX_SOURCE_ACTIVATION_WORKTREE"] = str(tmp_path / "missing-activation")

    result = _run_watchdog(env)

    assert result.returncode == 1
    assert "no health-monitor activation checkout available" in result.stderr
    assert "NEXT ACTION: run source activation" in result.stderr
    assert not (tmp_path / "uv.jsonl").exists()
    assert "/home/hapax/projects/hapax-council" not in result.stderr
    notify_send = (tmp_path / "notify-send.log").read_text(encoding="utf-8")
    assert "Health Monitor Failed" in notify_send
    assert "No activation checkout available" in notify_send


def test_default_history_file_uses_selected_activation_checkout(tmp_path: Path) -> None:
    activation = _make_checkout(tmp_path / "source-activation")
    (activation / "profiles").mkdir()
    env = _base_env(tmp_path, set_history_file=False)
    env["HAPAX_SOURCE_ACTIVATION_WORKTREE"] = str(activation)

    result = _run_watchdog(env)

    assert result.returncode == 0, result.stderr
    history = _jsonl(activation / "profiles" / "health-history.jsonl")
    assert history[0]["status"] == "healthy"
    assert not (tmp_path / "health-history.jsonl").exists()


def test_failed_stack_routes_through_intake_cli(tmp_path: Path) -> None:
    activation = _make_checkout(tmp_path / "source-activation")
    intake_log = tmp_path / "intake.jsonl"
    intake_cli = _write_executable(
        tmp_path / "hapax-p0-incident-intake",
        f"""
        #!/usr/bin/env python3
        import json
        import sys
        with open({str(intake_log)!r}, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(sys.argv[1:]) + "\\n")
        sys.exit(0)
        """,
    )
    env = _base_env(tmp_path, status="failed")
    env["HAPAX_SOURCE_ACTIVATION_WORKTREE"] = str(activation)
    env["HAPAX_P0_INTAKE_CLI"] = str(intake_cli)

    result = _run_watchdog(env)

    assert result.returncode == 2, result.stderr
    calls = _jsonl(intake_log)
    assert calls == [
        [
            "notification",
            "--title",
            "Stack Failed",
            "--message",
            "98/100 healthy, 0 degraded, 2 failed\n"
            "Run: uv run python -m agents.health_monitor --verbose",
            "--technical",
            "--priority",
            "high",
            "--tag",
            "rotating_light",
        ]
    ]
    assert _jsonl(tmp_path / "notify.jsonl") == []


def test_failed_stack_default_intake_cli_uses_selected_activation_root(
    tmp_path: Path,
) -> None:
    activation = _make_checkout(tmp_path / "source-activation")
    intake_log = tmp_path / "default-intake.jsonl"
    _write_fake_intake_cli(activation, intake_log)
    env = _base_env(tmp_path, status="failed")
    env["HAPAX_SOURCE_ACTIVATION_WORKTREE"] = str(activation)

    result = _run_watchdog(env)

    assert result.returncode == 2, result.stderr
    calls = _jsonl(intake_log)
    assert calls[0][0:3] == ["notification", "--title", "Stack Failed"]
    assert _jsonl(tmp_path / "notify.jsonl") == []


def test_failed_stack_default_intake_cli_uses_runtime_fallback_root(
    tmp_path: Path,
) -> None:
    runtime = _make_checkout(tmp_path / "runtime")
    intake_log = tmp_path / "runtime-intake.jsonl"
    _write_fake_intake_cli(runtime, intake_log)
    env = _base_env(tmp_path, status="failed")
    env["HAPAX_HEALTH_MONITOR_REPO"] = str(runtime)
    env["HAPAX_SOURCE_ACTIVATION_WORKTREE"] = str(tmp_path / "missing-activation")

    result = _run_watchdog(env)

    assert result.returncode == 2, result.stderr
    calls = _jsonl(intake_log)
    assert calls[0][0:3] == ["notification", "--title", "Stack Failed"]
    assert _jsonl(tmp_path / "notify.jsonl") == []


def test_failed_stack_missing_intake_cli_falls_back_to_notification(tmp_path: Path) -> None:
    activation = _make_checkout(tmp_path / "source-activation")
    env = _base_env(tmp_path, status="failed")
    env["HAPAX_SOURCE_ACTIVATION_WORKTREE"] = str(activation)
    env["HAPAX_P0_INTAKE_CLI"] = str(tmp_path / "missing-intake")

    result = _run_watchdog(env)

    assert result.returncode == 2, result.stderr
    notifications = _jsonl(tmp_path / "notify.jsonl")
    assert notifications[0]["title"] == "Stack Failed"
    assert notifications[0]["kwargs"]["priority"] == "high"
    assert notifications[0]["kwargs"]["tags"] == ["rotating_light"]


def test_failed_stack_nonzero_intake_cli_falls_back_to_notification(tmp_path: Path) -> None:
    activation = _make_checkout(tmp_path / "source-activation")
    intake_cli = _write_executable(
        tmp_path / "rejecting-intake",
        """
        #!/usr/bin/env sh
        exit 3
        """,
    )
    env = _base_env(tmp_path, status="failed")
    env["HAPAX_SOURCE_ACTIVATION_WORKTREE"] = str(activation)
    env["HAPAX_P0_INTAKE_CLI"] = str(intake_cli)

    result = _run_watchdog(env)

    assert result.returncode == 2, result.stderr
    notifications = _jsonl(tmp_path / "notify.jsonl")
    assert notifications[0]["title"] == "Stack Failed"


def test_failed_stack_timed_out_intake_cli_falls_back_to_notification(tmp_path: Path) -> None:
    activation = _make_checkout(tmp_path / "source-activation")
    intake_cli = _write_executable(
        tmp_path / "slow-intake",
        """
        #!/usr/bin/env sh
        sleep 1
        exit 0
        """,
    )
    env = _base_env(tmp_path, status="failed")
    env["HAPAX_SOURCE_ACTIVATION_WORKTREE"] = str(activation)
    env["HAPAX_P0_INTAKE_CLI"] = str(intake_cli)
    env["HAPAX_P0_INTAKE_TIMEOUT_SECONDS"] = "0.01"

    result = _run_watchdog(env)

    assert result.returncode == 2, result.stderr
    notifications = _jsonl(tmp_path / "notify.jsonl")
    assert notifications[0]["title"] == "Stack Failed"


def test_failed_stack_auto_fix_success_notifies_auto_fixed(tmp_path: Path) -> None:
    activation = _make_checkout(tmp_path / "source-activation")
    env = _base_env(tmp_path, status="failed", pass_succeeds=True)
    env["HAPAX_SOURCE_ACTIVATION_WORKTREE"] = str(activation)
    env["FAKE_APPLY_MARKER"] = str(tmp_path / "apply.marker")
    env["FAKE_HEALTH_STATUS_AFTER_APPLY"] = "healthy"

    result = _run_watchdog(env)

    assert result.returncode == 0, result.stderr
    uv_calls = _jsonl(tmp_path / "uv.jsonl")
    assert ["run", "python", "-m", "agents.health_monitor", "--apply"] in [
        call["args"] for call in uv_calls
    ]
    notifications = _jsonl(tmp_path / "notify.jsonl")
    assert notifications[0]["title"] == "Auto-Fixed"


def test_empty_health_report_stdout_alerts_before_history_write(tmp_path: Path) -> None:
    activation = _make_checkout(tmp_path / "source-activation")
    env = _base_env(tmp_path)
    env["HAPAX_SOURCE_ACTIVATION_WORKTREE"] = str(activation)
    env["FAKE_HEALTH_EMPTY_STDOUT"] = "1"

    result = _run_watchdog(env)

    assert result.returncode == 1, result.stderr
    notifications = _jsonl(tmp_path / "notify.jsonl")
    assert notifications[0]["title"] == "Health Monitor Failed"
    assert not (tmp_path / "health-history.jsonl").exists()

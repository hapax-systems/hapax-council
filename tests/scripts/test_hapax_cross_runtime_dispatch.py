"""Tests for cross-runtime dispatch delegating to methodology dispatch."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-cross-runtime-dispatch"


def _env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    registry = tmp_path / "team-registry"
    ledger = tmp_path / "ledger"
    relay = tmp_path / "relay"
    for path in (registry, ledger, relay):
        path.mkdir(parents=True)
    (registry / "beta.json").write_text(
        json.dumps(
            {
                "platform": "claude",
                "last_probe_utc": time.time(),
                "freshness_ttl_s": 3600,
            }
        ),
        encoding="utf-8",
    )
    dispatcher_log = tmp_path / "methodology-dispatch-args.txt"
    fake_dispatcher = tmp_path / "hapax-methodology-dispatch"
    fake_dispatcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {dispatcher_log}
""",
        encoding="utf-8",
    )
    fake_dispatcher.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["HAPAX_TEAM_REGISTRY_DIR"] = str(registry)
    env["HAPAX_ORCHESTRATION_LEDGER_DIR"] = str(ledger)
    env["HAPAX_SESSION_PROTECTION"] = str(relay / "session-protection.md")
    env["HAPAX_METHODOLOGY_DISPATCH"] = str(fake_dispatcher)
    env["HAPAX_AGENT_NAME"] = "tester"
    return env, dispatcher_log


def test_task_dispatch_delegates_to_methodology_dispatch(tmp_path: Path) -> None:
    env, dispatcher_log = _env(tmp_path)

    result = subprocess.run(
        [
            str(SCRIPT),
            "--lane",
            "beta",
            "--platform",
            "claude",
            "--task",
            "demo-task",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "delegating:" in result.stdout
    assert dispatcher_log.read_text(encoding="utf-8").splitlines() == [
        "--task",
        "demo-task",
        "--lane",
        "beta",
        "--platform",
        "claude",
        "--mode",
        "headless",
        "--profile",
        "full",
        "--launch",
    ]


def test_task_dispatch_forwards_mq_profile_and_policy_flags(tmp_path: Path) -> None:
    env, dispatcher_log = _env(tmp_path)

    result = subprocess.run(
        [
            str(SCRIPT),
            "--lane",
            "beta",
            "--platform",
            "codex",
            "--task",
            "demo-task",
            "--mq-message-id",
            "msg-123",
            "--runtime-mode",
            "receipt-only",
            "--profile",
            "spark",
            "--policy-rollback",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert dispatcher_log.read_text(encoding="utf-8").splitlines() == [
        "--task",
        "demo-task",
        "--lane",
        "beta",
        "--platform",
        "codex",
        "--mode",
        "receipt-only",
        "--profile",
        "spark",
        "--launch",
        "--mq-message-id",
        "msg-123",
        "--policy-rollback",
    ]


def test_taskless_dispatch_is_blocked(tmp_path: Path) -> None:
    env, dispatcher_log = _env(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), "--lane", "beta", "--platform", "claude"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "require --task and methodology dispatch" in result.stderr
    assert not dispatcher_log.exists()


def test_vibe_and_antigrav_delegate_to_methodology_dispatch(tmp_path: Path) -> None:
    for platform in ("vibe", "antigrav"):
        env, dispatcher_log = _env(tmp_path / platform)

        result = subprocess.run(
            [
                str(SCRIPT),
                "--lane",
                "beta",
                "--platform",
                platform,
                "--task",
                "demo-task",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

        assert result.returncode == 0, result.stderr
        assert "--platform\n" + platform in dispatcher_log.read_text(encoding="utf-8")

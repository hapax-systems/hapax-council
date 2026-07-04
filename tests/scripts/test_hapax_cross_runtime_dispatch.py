"""Tests for cross-runtime dispatch delegating to methodology dispatch."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

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


def test_vibe_delegates_to_methodology_dispatch(tmp_path: Path) -> None:
    env, dispatcher_log = _env(tmp_path / "vibe")

    result = subprocess.run(
        [
            str(SCRIPT),
            "--lane",
            "beta",
            "--platform",
            "vibe",
            "--task",
            "demo-task",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "--platform\nvibe" in dispatcher_log.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "retired_platform",
    ["agy", "antigrav", "Antigrav", "antigravity", "gemini-cli"],
)
def test_antigrav_is_not_cross_runtime_dispatchable(tmp_path: Path, retired_platform: str) -> None:
    env, dispatcher_log = _env(tmp_path / "antigrav")

    result = subprocess.run(
        [
            str(SCRIPT),
            "--lane",
            "beta",
            "--platform",
            retired_platform,
            "--task",
            "demo-task",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 10
    canonical_platform = retired_platform.lower()
    assert f"platform '{canonical_platform}' is retired/excised" in result.stderr
    assert "measured agy supply-leaf intake" in result.stderr
    assert not dispatcher_log.exists()
    ledger_path = Path(env["HAPAX_ORCHESTRATION_LEDGER_DIR"]) / "dispatch-ledger.jsonl"
    records = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["outcome"] == "blocked"
    assert records[-1]["target_platform"] == canonical_platform
    assert records[-1]["dispatch_id"].startswith("BLOCKED-")
    assert records[-1]["replay_key"]
    assert "measured agy supply-leaf intake" in records[-1]["reason"]

    second = subprocess.run(
        [
            str(SCRIPT),
            "--lane",
            "beta",
            "--platform",
            retired_platform,
            "--task",
            "demo-task",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert second.returncode == 10
    records_after = [
        json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()
    ]
    assert records_after == records


def test_blocked_dispatch_receipt_dedup_is_flock_guarded() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'local lock="$LEDGER_DIR/dispatch-ledger.lock"' in source
    assert 'flock "$lock" python3 - "$ledger"' in source


@pytest.mark.parametrize(
    "retired_lane",
    ["agy", "agy-2", "antigrav", "antigravity", "antigravity-2", "gemini-cli", "gemini-cli-2"],
)
def test_antigrav_lane_name_is_not_cross_runtime_dispatchable(
    tmp_path: Path, retired_lane: str
) -> None:
    env, dispatcher_log = _env(tmp_path / "antigrav-lane")
    registry = Path(env["HAPAX_TEAM_REGISTRY_DIR"])
    (registry / f"{retired_lane}.json").write_text(
        json.dumps(
            {
                "platform": "codex",
                "last_probe_utc": time.time(),
                "freshness_ttl_s": 3600,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            str(SCRIPT),
            "--lane",
            retired_lane,
            "--platform",
            "codex",
            "--task",
            "demo-task",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 10
    assert f"lane '{retired_lane}' is retired/excised" in result.stderr
    assert "measured agy supply-leaf intake" in result.stderr
    assert not dispatcher_log.exists()
    ledger_path = Path(env["HAPAX_ORCHESTRATION_LEDGER_DIR"]) / "dispatch-ledger.jsonl"
    records = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["outcome"] == "blocked"
    assert records[-1]["target_lane"] == retired_lane
    assert records[-1]["target_platform"] == "codex"
    assert f"lane '{retired_lane}' is retired/excised" in records[-1]["reason"]


def test_list_eligible_skips_retired_antigrav_metadata(tmp_path: Path) -> None:
    env, _dispatcher_log = _env(tmp_path / "antigrav-list")
    registry = Path(env["HAPAX_TEAM_REGISTRY_DIR"])
    for lane, platform in [
        ("antigrav", "codex"),
        ("agy", "codex"),
        ("agy-2", "codex"),
        ("antigravity", "codex"),
        ("antigravity-2", "codex"),
        ("cx-retired-platform", "antigrav"),
        ("cx-retired-platform-full", "antigravity"),
        ("cx-retired-gemini-cli", "gemini-cli"),
        ("cx-unsupported-api", "api"),
        ("cx-unsupported-gemini", "gemini"),
        ("cx-unsupported-unknown", "unknown"),
    ]:
        (registry / f"{lane}.json").write_text(
            json.dumps(
                {
                    "platform": platform,
                    "last_probe_utc": time.time(),
                    "freshness_ttl_s": 3600,
                }
            ),
            encoding="utf-8",
        )

    result = subprocess.run(
        [str(SCRIPT), "--list-eligible"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "beta" in result.stdout
    assert "agy" not in result.stdout
    assert "antigrav" not in result.stdout
    assert "antigravity" not in result.stdout
    assert "cx-retired-platform" not in result.stdout
    assert "cx-retired-platform-full" not in result.stdout
    assert "cx-retired-gemini-cli" not in result.stdout
    assert "cx-unsupported-api" not in result.stdout
    assert "cx-unsupported-gemini" not in result.stdout
    assert "cx-unsupported-unknown" not in result.stdout
    assert "gemini-cli" not in result.stdout


def test_list_eligible_marks_malformed_freshness_unknown(tmp_path: Path) -> None:
    env, _dispatcher_log = _env(tmp_path / "malformed-freshness")
    registry = Path(env["HAPAX_TEAM_REGISTRY_DIR"])
    (registry / "bad-freshness.json").write_text(
        json.dumps(
            {
                "platform": "codex",
                "last_probe_utc": "not-a-number",
                "freshness_ttl_s": 3600,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(SCRIPT), "--list-eligible"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    row = next(line for line in result.stdout.splitlines() if "bad-freshness" in line)
    assert "unknown" in row
    assert "eligible" not in row

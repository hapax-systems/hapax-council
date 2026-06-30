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


@pytest.mark.parametrize("platform", ["antigrav", "antigravity"])
def test_list_eligible_marks_antigrav_metadata_deprecated(
    tmp_path: Path,
    platform: str,
) -> None:
    env, _dispatcher_log = _env(tmp_path)
    registry = Path(env["HAPAX_TEAM_REGISTRY_DIR"])
    (registry / "agy-candidate.json").write_text(
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
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    antigrav_line = next(line for line in result.stdout.splitlines() if "agy-candidate" in line)
    assert "deprecated" in antigrav_line
    assert "eligible" not in antigrav_line


def test_list_eligible_marks_antigravity_lane_deprecated_even_with_agy_platform(
    tmp_path: Path,
) -> None:
    env, _dispatcher_log = _env(tmp_path)
    registry = Path(env["HAPAX_TEAM_REGISTRY_DIR"])
    (registry / "antigravity.json").write_text(
        json.dumps(
            {
                "platform": "agy",
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
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    antigravity_line = next(line for line in result.stdout.splitlines() if "antigravity" in line)
    assert "deprecated" in antigravity_line
    assert "eligible" not in antigravity_line


def test_list_eligible_marks_malformed_agy_stem_invalid(tmp_path: Path) -> None:
    env, _dispatcher_log = _env(tmp_path)
    registry = Path(env["HAPAX_TEAM_REGISTRY_DIR"])
    (registry / "agyity-2.json").write_text(
        json.dumps(
            {
                "platform": "agy",
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
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    agyity_line = next(line for line in result.stdout.splitlines() if "agyity-2" in line)
    assert "invalid" in agyity_line
    assert "eligible" not in agyity_line


def test_list_eligible_normalizes_legacy_gemini_cli_platform(tmp_path: Path) -> None:
    env, _dispatcher_log = _env(tmp_path)
    registry = Path(env["HAPAX_TEAM_REGISTRY_DIR"])
    (registry / "agy-legacy.json").write_text(
        json.dumps(
            {
                "platform": "gemini-cli",
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
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    line = next(line for line in result.stdout.splitlines() if "agy-legacy" in line)
    assert "agy" in line
    assert "gemini-cli" not in line


def test_check_lane_refuses_deprecated_antigrav_lane(tmp_path: Path) -> None:
    env, _dispatcher_log = _env(tmp_path)
    registry = Path(env["HAPAX_TEAM_REGISTRY_DIR"])
    (registry / "antigrav.json").write_text(
        json.dumps(
            {
                "platform": "antigrav",
                "last_probe_utc": time.time(),
                "freshness_ttl_s": 3600,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(SCRIPT), "--check-lane", "antigrav"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "DEPRECATED: lane antigrav is retired; use lane agy or agy-* instead" in result.stderr
    assert "FRESH" not in result.stdout


def test_check_lane_refuses_deprecated_antigravity_lane(tmp_path: Path) -> None:
    env, _dispatcher_log = _env(tmp_path)
    registry = Path(env["HAPAX_TEAM_REGISTRY_DIR"])
    (registry / "antigravity.json").write_text(
        json.dumps(
            {
                "platform": "agy",
                "last_probe_utc": time.time(),
                "freshness_ttl_s": 3600,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(SCRIPT), "--check-lane", "antigravity"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "DEPRECATED: lane antigravity is retired; use lane agy or agy-* instead" in result.stderr
    assert "FRESH" not in result.stdout


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


def test_duplicate_dispatch_check_parses_json_with_default_spacing(tmp_path: Path) -> None:
    env, dispatcher_log = _env(tmp_path)
    ledger = Path(env["HAPAX_ORCHESTRATION_LEDGER_DIR"]) / "dispatch-ledger.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "target_lane": "beta",
                "target_platform": "claude",
                "outcome": "dispatched",
            }
        )
        + "\n",
        encoding="utf-8",
    )

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

    assert result.returncode == 1
    assert "BLOCKED: duplicate session" in result.stderr
    assert not dispatcher_log.exists()


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


def test_vibe_and_agy_delegate_to_methodology_dispatch(tmp_path: Path) -> None:
    cases = (("vibe", "beta", "headless"), ("agy", "agy", "interactive"))
    for platform, lane, expected_mode in cases:
        env, dispatcher_log = _env(tmp_path / platform)
        registry = Path(env["HAPAX_TEAM_REGISTRY_DIR"])
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
            [
                str(SCRIPT),
                "--lane",
                lane,
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
        args = dispatcher_log.read_text(encoding="utf-8")
        assert "--platform\n" + platform in args
        assert "--mode\n" + expected_mode in args


def test_agy_failed_methodology_delegate_does_not_write_false_dispatch_receipt(
    tmp_path: Path,
) -> None:
    env, dispatcher_log = _env(tmp_path)
    registry = Path(env["HAPAX_TEAM_REGISTRY_DIR"])
    (registry / "agy.json").write_text(
        json.dumps(
            {
                "platform": "agy",
                "last_probe_utc": time.time(),
                "freshness_ttl_s": 3600,
            }
        ),
        encoding="utf-8",
    )
    fake_dispatcher = Path(env["HAPAX_METHODOLOGY_DISPATCH"])
    fake_dispatcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {dispatcher_log}
exit 7
""",
        encoding="utf-8",
    )
    fake_dispatcher.chmod(0o755)

    result = subprocess.run(
        [
            str(SCRIPT),
            "--lane",
            "agy",
            "--platform",
            "agy",
            "--task",
            "demo-task",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 7
    args = dispatcher_log.read_text(encoding="utf-8")
    assert "--mode\ninteractive" in args
    ledger = Path(env["HAPAX_ORCHESTRATION_LEDGER_DIR"]) / "dispatch-ledger.jsonl"
    assert not ledger.exists()


def test_fallback_failed_launcher_does_not_write_false_dispatch_receipt(
    tmp_path: Path,
) -> None:
    env, dispatcher_log = _env(tmp_path)
    fake_dispatcher = Path(env["HAPAX_METHODOLOGY_DISPATCH"])
    fake_dispatcher.chmod(0o644)

    launcher_log = tmp_path / "codex-launcher-args.txt"
    fake_launcher = tmp_path / "codex-launcher"
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_log}
exit 7
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)
    env["HAPAX_CROSS_RUNTIME_CODEX_LAUNCHER"] = str(fake_launcher)

    result = subprocess.run(
        [
            str(SCRIPT),
            "--lane",
            "beta",
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

    assert result.returncode == 7
    assert "launcher failed rc=7; no dispatched receipt written" in result.stderr
    assert launcher_log.read_text(encoding="utf-8").splitlines() == [
        "--session",
        "beta",
        "--terminal",
        "tmux",
        "--task",
        "demo-task",
    ]
    assert not dispatcher_log.exists()
    ledger = Path(env["HAPAX_ORCHESTRATION_LEDGER_DIR"]) / "dispatch-ledger.jsonl"
    assert not ledger.exists()


def test_fallback_missing_launcher_does_not_write_false_dispatch_receipt(
    tmp_path: Path,
) -> None:
    env, dispatcher_log = _env(tmp_path)
    fake_dispatcher = Path(env["HAPAX_METHODOLOGY_DISPATCH"])
    fake_dispatcher.chmod(0o644)
    env["HAPAX_CROSS_RUNTIME_CODEX_LAUNCHER"] = str(tmp_path / "missing-codex-launcher")

    result = subprocess.run(
        [
            str(SCRIPT),
            "--lane",
            "beta",
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

    assert result.returncode == 2
    assert "launcher not found" in result.stderr
    assert "no dispatched receipt written" in result.stderr
    assert not dispatcher_log.exists()
    ledger = Path(env["HAPAX_ORCHESTRATION_LEDGER_DIR"]) / "dispatch-ledger.jsonl"
    assert not ledger.exists()


def test_fallback_successful_launcher_writes_dispatch_receipt(tmp_path: Path) -> None:
    env, dispatcher_log = _env(tmp_path)
    fake_dispatcher = Path(env["HAPAX_METHODOLOGY_DISPATCH"])
    fake_dispatcher.chmod(0o644)

    launcher_log = tmp_path / "codex-launcher-args.txt"
    fake_launcher = tmp_path / "codex-launcher"
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_log}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)
    env["HAPAX_CROSS_RUNTIME_CODEX_LAUNCHER"] = str(fake_launcher)

    result = subprocess.run(
        [
            str(SCRIPT),
            "--lane",
            "beta",
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

    assert result.returncode == 0, result.stderr
    assert "receipt written" in result.stdout
    assert launcher_log.exists()
    assert not dispatcher_log.exists()
    ledger = Path(env["HAPAX_ORCHESTRATION_LEDGER_DIR"]) / "dispatch-ledger.jsonl"
    receipts = [
        json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert receipts[-1]["outcome"] == "dispatched"
    assert receipts[-1]["target_lane"] == "beta"
    assert receipts[-1]["target_platform"] == "codex"


def test_explicit_noninteractive_agy_runtime_mode_fails_before_delegate_or_receipt(
    tmp_path: Path,
) -> None:
    env, dispatcher_log = _env(tmp_path)

    result = subprocess.run(
        [
            str(SCRIPT),
            "--lane",
            "agy",
            "--platform",
            "agy",
            "--task",
            "demo-task",
            "--runtime-mode",
            "headless",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 2
    assert "agy supports runtime-mode interactive only" in result.stderr
    assert not dispatcher_log.exists()
    ledger = Path(env["HAPAX_ORCHESTRATION_LEDGER_DIR"]) / "dispatch-ledger.jsonl"
    assert not ledger.exists()


def test_runtime_mode_default_is_platform_sensitive() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    init_line = next(line for line in text.splitlines() if 'MODE="single_lane"' in line)
    assert 'RUNTIME_MODE=""' in init_line
    assert 'RUNTIME_MODE="headless"' not in init_line
    assert 'RUNTIME_MODE="interactive"' in text
    assert 'RUNTIME_MODE="headless"' in text


@pytest.mark.parametrize("platform", ["antigrav", "antigravity"])
def test_antigrav_platform_is_deprecated(tmp_path: Path, platform: str) -> None:
    env, dispatcher_log = _env(tmp_path)

    result = subprocess.run(
        [
            str(SCRIPT),
            "--lane",
            "antigrav",
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

    assert result.returncode == 2
    assert f"deprecated platform: {platform}; use platform agy" in result.stderr
    assert not dispatcher_log.exists()
    ledger = Path(env["HAPAX_ORCHESTRATION_LEDGER_DIR"]) / "dispatch-ledger.jsonl"
    assert not ledger.exists()


@pytest.mark.parametrize("lane", ["antigrav", "antigravity"])
def test_antigrav_lane_is_deprecated_even_on_agy_platform(tmp_path: Path, lane: str) -> None:
    env, dispatcher_log = _env(tmp_path)

    result = subprocess.run(
        [
            str(SCRIPT),
            "--lane",
            lane,
            "--platform",
            "agy",
            "--task",
            "demo-task",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 2
    assert f"deprecated lane: {lane}; use lane agy or agy-*" in result.stderr
    assert not dispatcher_log.exists()


def test_antigrav_suffixed_lane_is_deprecated_even_on_agy_platform(tmp_path: Path) -> None:
    env, dispatcher_log = _env(tmp_path)

    for lane in ("antigrav-2", "antigravity-2"):
        result = subprocess.run(
            [
                str(SCRIPT),
                "--lane",
                lane,
                "--platform",
                "agy",
                "--task",
                "demo-task",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

        assert result.returncode == 2
        assert f"deprecated lane: {lane}; use lane agy or agy-*" in result.stderr
        assert not dispatcher_log.exists()


def test_malformed_agy_stem_is_invalid_on_agy_platform(tmp_path: Path) -> None:
    env, dispatcher_log = _env(tmp_path)
    registry = Path(env["HAPAX_TEAM_REGISTRY_DIR"])
    (registry / "agyity-2.json").write_text(
        json.dumps(
            {
                "platform": "agy",
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
            "agyity-2",
            "--platform",
            "agy",
            "--task",
            "demo-task",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 2
    assert "invalid agy lane: agyity-2; use lane agy or agy-*" in result.stderr
    assert not dispatcher_log.exists()

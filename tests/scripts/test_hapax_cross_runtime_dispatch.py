"""Tests for the effect-pure cross-runtime methodology entrypoint."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from shared.methodology_dispatch_carrier import validate_methodology_dispatch_carrier_line

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-cross-runtime-dispatch"


def _env(tmp_path: Path) -> dict[str, str]:
    registry = tmp_path / "team-registry"
    registry.mkdir(parents=True)
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
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "HAPAX_CC_TASK_ROOT": str(tmp_path / "tasks"),
            "HAPAX_TEAM_REGISTRY_DIR": str(registry),
            "HAPAX_SESSION_PROTECTION": str(tmp_path / "session-protection.md"),
            "HAPAX_METHODOLOGY_DISPATCH": "/bin/echo",
            "HAPAX_METHODOLOGY_DISPATCHER": "/bin/echo",
        }
    )
    return env


def _run(
    env: dict[str, str],
    *args: str,
    script: Path = SCRIPT,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(script), *args],
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )


def _carrier(stdout: bytes, **identity: str) -> dict[str, object]:
    return validate_methodology_dispatch_carrier_line(stdout, **identity)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_task_bearing_request_ignores_executable_overrides_and_emits_carrier(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    env["PYTHONPATH"] = "/tmp/hostile-pythonpath"
    env["PYTHONHOME"] = "/tmp/hostile-pythonhome"
    hostile_marker = tmp_path / "hostile-python-used"
    hostile_env_marker = tmp_path / "hostile-env-used"
    hostile_bin = tmp_path / "hostile-bin"
    hostile_bin.mkdir()
    hostile_python = hostile_bin / "python3"
    hostile_python.write_text(
        f"#!/bin/sh\nprintf used > {hostile_marker}\nexit 99\n",
        encoding="utf-8",
    )
    hostile_python.chmod(0o755)
    hostile_env = hostile_bin / "env"
    hostile_env.write_text(
        f"#!/bin/sh\nprintf used > {hostile_env_marker}\nexit 98\n",
        encoding="utf-8",
    )
    hostile_env.chmod(0o755)
    env["PATH"] = f"{hostile_bin}:{env['PATH']}"

    result = _run(
        env,
        "--task",
        "missing-task",
        "--lane",
        "cx-red",
        "--platform",
        "Codex",
    )

    assert result.returncode == 10
    assert b"--task missing-task" not in result.stdout
    carrier = _carrier(
        result.stdout,
        task_id="missing-task",
        lane="cx-red",
        platform="codex",
        mode="headless",
        profile="full",
    )
    assert carrier["effect_state"] == "held_not_admitted"
    assert carrier["materialization_state"] == "not_materialized"
    assert carrier["launched"] is False
    assert not hostile_marker.exists()
    assert not hostile_env_marker.exists()


def test_interactive_mode_and_profile_reach_exact_repository_dispatcher(
    tmp_path: Path,
) -> None:
    result = _run(
        _env(tmp_path),
        "--task",
        "missing-task",
        "--lane",
        "cx-red",
        "--platform",
        "codex",
        "--mode",
        "interactive",
        "--profile",
        "spark",
    )

    assert result.returncode == 10
    carrier = _carrier(
        result.stdout,
        task_id="missing-task",
        lane="cx-red",
        platform="codex",
        mode="interactive",
        profile="spark",
    )
    assert carrier["mode"] == "interactive"
    assert carrier["profile"] == "spark"
    assert carrier["requested_operation"] == "launch"
    assert carrier["launched"] is False


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        (("--lane", "beta", "--platform", "claude"), "task_required"),
        (("--task", "demo", "--platform", "claude"), "lane_required"),
        (("--task", "demo", "--lane", "beta"), "platform_required"),
    ],
)
def test_incomplete_task_bearing_request_holds_before_delegation(
    tmp_path: Path,
    args: tuple[str, ...],
    reason: str,
) -> None:
    result = _run(_env(tmp_path), *args)

    assert result.returncode == 10
    assert result.stdout == b""
    assert f"HOLD: {reason}:".encode() in result.stderr


def test_isolated_wrapper_holds_when_exact_sibling_is_missing(tmp_path: Path) -> None:
    isolated = tmp_path / "repo" / "scripts" / SCRIPT.name
    isolated.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT, isolated)

    result = _run(
        _env(tmp_path),
        "--task",
        "demo",
        "--lane",
        "beta",
        "--platform",
        "claude",
        script=isolated,
    )

    assert result.returncode == 10
    assert result.stdout == b""
    assert b"methodology_dispatch_unavailable" in result.stderr


def test_list_and_check_modes_remain_read_only(tmp_path: Path) -> None:
    env = _env(tmp_path)
    registry = Path(env["HAPAX_TEAM_REGISTRY_DIR"])
    protection = Path(env["HAPAX_SESSION_PROTECTION"])
    protection.write_text("`beta` protected\n", encoding="utf-8")
    before_registry = _tree_bytes(registry)
    before_protection = protection.read_bytes()

    listed = _run(env, "--list-eligible")
    checked = _run(env, "--check-lane", "beta")

    assert listed.returncode == 0
    assert b"beta" in listed.stdout
    assert checked.returncode == 0
    assert b"PROTECTED: lane beta is protected" in checked.stdout
    assert _tree_bytes(registry) == before_registry
    assert protection.read_bytes() == before_protection


def test_source_has_one_exact_delegation_path_and_no_runtime_substitution() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.startswith("#!/usr/bin/bash\n")
    assert "$(dirname " not in source
    task_bearing = source.split(
        "# Structural preconditions are the wrapper's entire task-bearing behavior.",
        maxsplit=1,
    )[1]

    assert 'METHODOLOGY_DISPATCH="$SCRIPT_DIR/hapax-methodology-dispatch"' in task_bearing
    assert "HAPAX_METHODOLOGY_DISPATCH" not in task_bearing
    assert "export PYTHONPATH" not in task_bearing
    assert "unset PYTHONPATH PYTHONHOME" in task_bearing
    assert "exec env " not in task_bearing
    assert 'PROJECT_PYTHON="$REPO_ROOT/.venv/bin/python"' in task_bearing
    assert '"$PROJECT_PYTHON" -I "$METHODOLOGY_DISPATCH"' in task_bearing
    assert "/usr/bin/python3 -I" in source
    assert "command -v uv" not in task_bearing
    assert "uv run" not in task_bearing
    for forbidden in (
        "dispatch-ledger",
        "write_blocked_dispatch_receipt",
        "sqlite3",
        "hapax-claude",
        "hapax-codex",
        "hapax-vibe",
        "mkdir ",
    ):
        assert forbidden not in source

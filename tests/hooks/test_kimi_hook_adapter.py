"""Kimi's exit-status contract must deliver the existing Codex guard dispatch.

Harness contract (Kimi Code 2.1.1, checked 2026-10-12):
https://www.kimi.com/code/docs/en/kimi-code-cli/customization/hooks.html
PreToolUse/Stop can block with exit 2; SessionStart/PostToolUse are observational.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks/scripts"
EVENTS = ("SessionStart", "PreToolUse", "PostToolUse", "Stop")


def clean_env(home: Path) -> dict[str, str]:
    return {"HOME": str(home), "PATH": os.environ["PATH"], "LANG": "C.UTF-8"}


@pytest.fixture
def harness(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    scripts = tmp_path / "release/hooks/scripts"
    scripts.mkdir(parents=True)
    for name in (
        "codex-hook-adapter.sh",
        "kimi-hook-adapter.sh",
        "agent-role.sh",
        "codex_patch_events.py",
    ):
        shutil.copy2(HOOKS / name, scripts / name)
    spec = importlib.util.spec_from_file_location(
        "manifest", ROOT / "scripts/gate-manifest-check.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    phases = module.collect_codex_adapter(HOOKS / "codex-hook-adapter.sh")
    names = set()
    for value in phases.values():
        for group in value.values() if isinstance(value, dict) else [value]:
            names.update(group)
    for name in names:
        script = scripts / name
        script.write_text(
            '#!/usr/bin/env bash\ninput="$(cat)"\n'
            'jq -cn --arg hook "${0##*/}" --arg interface "$HAPAX_AGENT_INTERFACE" '
            '--arg sid "$HAPAX_SESSION_ID" --argjson payload "$input" '
            "'{hook:$hook,interface:$interface,sid:$sid,payload:$payload}' >>\"$TRACE\"\n"
            'if [ "${BLOCK_HOOK:-}" = "${0##*/}" ]; then echo refusal >&2; exit 2; fi\n'
            'case "${0##*/}" in session-context.sh) echo startup-context;; '
            "session-summary.sh) echo stop-summary;; esac\n"
        )
        script.chmod(0o755)
    env = clean_env(tmp_path)
    env.update(
        HAPAX_AGENT_INTERFACE="glmcp",
        HAPAX_AGENT_NAME="glm-probe",
        HAPAX_SESSION_ID="launcher-uuid",
        HAPAX_CANONICAL_HOOKS=str(scripts),
        TRACE=str(tmp_path / "trace.jsonl"),
        HAPAX_KIMI_HOOK_ADAPTER_LOG=str(tmp_path / "adapter.jsonl"),
    )
    return scripts, env


def invoke(scripts: Path, env: dict[str, str], adapter: str, event: str, tool: str = ""):
    payload = {
        "hook_event_name": event,
        "session_id": "harness-session",
        "cwd": env["HOME"],
        "tool_name": tool,
        "tool_input": {"file_path": "sample.txt", "content": "harmless", "command": "true"},
    }
    return subprocess.run(
        ["bash", str(scripts / adapter)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        cwd=env["HOME"],
        timeout=20,
    )


@pytest.mark.parametrize(
    ("event", "tool"),
    [("SessionStart", ""), ("Stop", "")]
    + [
        (event, tool)
        for event in EVENTS[1:3]
        for tool in ("Bash", "Write", "Edit", "mcp__x__write")
    ],
)
def test_dispatch_matches_codex(harness, event, tool):
    scripts, env = harness
    trace = Path(env["TRACE"])
    codex = invoke(scripts, env, "codex-hook-adapter.sh", event, tool)
    assert codex.returncode == 0, codex.stderr
    expected = trace.read_text()
    trace.unlink()
    kimi = invoke(scripts, env, "kimi-hook-adapter.sh", event, tool)
    assert kimi.returncode == 0, kimi.stderr
    assert trace.exists(), f"Kimi skipped {event}"
    assert trace.read_text() == expected
    log = json.loads(Path(env["HAPAX_KIMI_HOOK_ADAPTER_LOG"]).read_text().splitlines()[-1])
    assert log["event"] == event
    assert log["ts"]
    if event == "SessionStart":
        assert "startup-context" in kimi.stdout
    if event == "Stop":
        assert "stop-summary" in kimi.stdout


def test_write_is_blocked_by_real_pii_guard(harness):
    scripts, env = harness
    for name in ("pii-guard.sh", "principal-name-map.sh"):
        shutil.copy2(HOOKS / name, scripts / name)
    # Synthetic principal; no real person's name is placed in the fixture.
    registry = Path(env["HOME"]) / "principals.yaml"
    registry.write_text("principal-z99: Harmless\n")
    env["HAPAX_PRINCIPAL_NAME_MAP"] = str(registry)
    result = invoke(scripts, env, "kimi-hook-adapter.sh", "PreToolUse", "Write")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "pii-guard.sh" in result.stderr
    assert "Registered principal given name" in result.stderr


@pytest.mark.parametrize("fault", ["missing", "crash", "invalid-json"])
def test_unusable_dispatcher_refuses_pretooluse(harness, fault):
    scripts, env = harness
    dispatcher = scripts / "codex-hook-adapter.sh"
    if fault == "missing":
        dispatcher.unlink()
    else:
        dispatcher.write_text("#!/bin/bash\n" + ("exit 1\n" if fault == "crash" else "echo junk\n"))
    result = invoke(scripts, env, "kimi-hook-adapter.sh", "PreToolUse", "Write")
    assert result.returncode == 2
    assert "Next action:" in result.stderr


@pytest.fixture
def launched(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    release = home / ".cache/hapax/source-activation/worktree"
    (release / "scripts/lib").mkdir(parents=True)
    (release / "hooks/scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/lib/secret.sh", release / "scripts/lib/secret.sh")
    for name in ("kimi-hook-adapter.sh", "codex-hook-adapter.sh"):
        shutil.copy2(HOOKS / name, release / "hooks/scripts" / name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {
        "tmux": "exit 1\n",
        "pass": 'echo legacy-pass >>"$SECRET_TRACE"; echo test-only-value\n',
        "hapax-secret": 'echo "$1" >>"$SECRET_TRACE"; echo test-only-value\n',
        "kimi": 'printf "%s\\n%s\\n" "$KIMI_CODE_HOME" "$HAPAX_SESSION_ID" >"$LAUNCH_TRACE"\n',
    }.items():
        p = bin_dir / name
        p.write_text("#!/bin/bash\n" + body)
        p.chmod(0o755)
    env = clean_env(home)
    env.update(
        PATH=f"{bin_dir}:{env['PATH']}",
        XDG_RUNTIME_DIR=str(tmp_path / "runtime"),
        KIMI_BIN=str(bin_dir / "kimi"),
        HAPAX_SESSION_ID="inherited-parent-id",
        LAUNCH_TRACE=str(tmp_path / "launch"),
        SECRET_TRACE=str(tmp_path / "secrets"),
    )
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/hapax-glmcp"), "glm-test", "--terminal", "none"],
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    config_path = tmp_path / "runtime/kimi-glm/glm-test/config.toml"
    return tomllib.loads(config_path.read_text()), config_path, release, env


def test_launcher_wires_all_parity_events(launched):
    config, _, _, _ = launched
    assert {hook["event"] for hook in config["hooks"]} == set(EVENTS)
    assert all(hook.get("matcher", ".*") == ".*" for hook in config["hooks"])


def test_launcher_binds_activated_adapter(launched):
    config, _, release, _ = launched
    assert all(
        str(release / "hooks/scripts/kimi-hook-adapter.sh") in h["command"] for h in config["hooks"]
    )


def test_launcher_uses_filestore_private_config_and_fresh_identity(launched):
    _, path, _, env = launched
    assert Path(env["SECRET_TRACE"]).read_text().splitlines() == ["glmcp/api-key"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert Path(env["LAUNCH_TRACE"]).read_text().splitlines()[1] != "inherited-parent-id"

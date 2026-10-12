"""Kimi's exit-status contract must deliver the existing Codex guard dispatch.

Harness contract (Kimi Code 2.1.1, checked 2026-10-12):
https://www.kimi.com/code/docs/en/kimi-code-cli/customization/hooks.html
PreToolUse/Stop can block with exit 2; SessionStart/PostToolUse are observational.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
import tomllib
from contextlib import suppress
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks/scripts"
EVENTS = ("SessionStart", "PreToolUse", "PostToolUse", "Stop")
REQUIRED_PHASES = yaml.safe_load((ROOT / "hooks/gate-manifest.yaml").read_text())["runtimes"][
    "codex"
]["adapter_phases"]


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
    # Fixture availability and expected traces come from the independent contract,
    # never from the dispatcher being tested (including when a guard is removed).
    phases = REQUIRED_PHASES
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
    assert_required_trace(trace, event, tool)
    log = json.loads(Path(env["HAPAX_KIMI_HOOK_ADAPTER_LOG"]).read_text().splitlines()[-1])
    assert log["event"] == event
    assert log["ts"]
    if event == "SessionStart":
        assert "startup-context" in kimi.stdout
    if event == "Stop":
        assert "stop-summary" in kimi.stdout


def assert_required_trace(trace: Path, event: str, tool: str = "") -> None:
    expected = REQUIRED_PHASES[event]
    if isinstance(expected, dict):
        expected = expected["shell" if tool == "Bash" else "mutation"]
    assert [json.loads(line)["hook"] for line in trace.read_text().splitlines()] == expected


def test_missing_shared_guard_is_detected(harness):
    scripts, env = harness
    dispatcher = scripts / "codex-hook-adapter.sh"
    source = dispatcher.read_text()
    assert "    pii-guard.sh\n" in source
    dispatcher.write_text(source.replace("    pii-guard.sh\n", ""))
    result = invoke(scripts, env, "kimi-hook-adapter.sh", "PreToolUse", "Write")
    assert result.returncode == 0
    with pytest.raises(AssertionError):
        assert_required_trace(Path(env["TRACE"]), "PreToolUse", "Write")


@pytest.mark.parametrize("hook", REQUIRED_PHASES["SessionStart"])
@pytest.mark.parametrize("fault", ["exit", "missing"])
def test_sessionstart_dependency_failure_is_visible_without_payloads(harness, hook, fault):
    scripts, env = harness
    dependency = scripts / hook
    if fault == "missing":
        dependency.unlink()
    else:
        dependency.write_text("#!/bin/bash\necho secret-sentinel-do-not-log >&2\nexit 7\n")
    result = invoke(scripts, env, "kimi-hook-adapter.sh", "SessionStart")
    assert result.returncode == 0
    assert hook in result.stdout and "Next action:" in result.stdout
    assert "secret-sentinel-do-not-log" not in result.stdout + result.stderr
    records = [
        json.loads(line)
        for line in Path(env["HAPAX_KIMI_HOOK_ADAPTER_LOG"]).read_text().splitlines()
    ]
    failure = next(r for r in records if r.get("hook") == hook)
    assert failure["status"] == (127 if fault == "missing" else 7)
    assert failure["event"] == "SessionStart" and failure["ts"]
    assert "Next action:" in failure["notice"]
    assert "secret-sentinel-do-not-log" not in json.dumps(records)
    other = next(name for name in REQUIRED_PHASES["SessionStart"] if name != hook)
    assert other in [
        json.loads(line)["hook"] for line in Path(env["TRACE"]).read_text().splitlines()
    ]


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
def launcher(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    release = home / ".cache/hapax/source-activation/worktree"
    (release / "scripts/lib").mkdir(parents=True)
    (release / "hooks/scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/lib/secret.sh", release / "scripts/lib/secret.sh")
    shutil.copy2(ROOT / "scripts/hapax-relay-retire", release / "scripts/hapax-relay-retire")
    for name in ("kimi-hook-adapter.sh", "codex-hook-adapter.sh"):
        shutil.copy2(HOOKS / name, release / "hooks/scripts" / name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {
        "tmux": 'if [ "$1" = has-session ]; then exit 1; fi\n'
        'printf "%s" "${@: -1}" >"$RUNNER_TRACE"\n'
        'if [ "${RUNNER_ONLY:-0}" = 1 ]; then exit 0; fi\n'
        'status=0; bash "${@: -1}" || status=$?\n'
        'echo "$status" >"$CHILD_STATUS"\n',
        "pass": 'echo legacy-pass >>"$SECRET_TRACE"; echo test-only-value\n',
        "hapax-secret": 'echo "$1" >>"$SECRET_TRACE"; echo test-only-value\n',
        "kimi": 'printf "%s\\n%s\\n" "$KIMI_CODE_HOME" "$HAPAX_SESSION_ID" >"$LAUNCH_TRACE"\n'
        'if [ "${KIMI_READ_STDIN:-0}" = 1 ]; then IFS= read -r line; '
        'printf "%s" "$line" >"$STDIN_TRACE"; fi\n'
        'if [ "${KIMI_WAIT:-0}" = 1 ]; then trap "exit 143" TERM; '
        'while :; do sleep 0.05; done; fi\nexit "${KIMI_EXIT:-0}"\n',
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
        RUNNER_TRACE=str(tmp_path / "runner-path"),
        CHILD_STATUS=str(tmp_path / "child-status"),
        STDIN_TRACE=str(tmp_path / "stdin"),
    )
    relay = home / ".cache/hapax/relay/glm-test.yaml"
    relay.parent.mkdir(parents=True)
    relay.write_text("role: glm-test\nstatus: active\n")
    return tmp_path, release, env, relay


def launch(env, terminal="none", input=None):
    args = ["bash", str(ROOT / "scripts/hapax-glmcp"), "glm-test"]
    if terminal == "none":
        args += ["--terminal", "none"]
    return subprocess.run(args, env=env, input=input, text=True, capture_output=True, timeout=15)


@pytest.fixture
def launched(launcher):
    tmp_path, release, env, _ = launcher
    result = launch(env)
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


@pytest.mark.parametrize("terminal", ["none", "tmux"])
@pytest.mark.parametrize("status", [0, 7])
def test_launcher_retires_relay_and_preserves_child_status(launcher, terminal, status):
    _, _, env, relay = launcher
    env["KIMI_EXIT"] = str(status)
    result = launch(env, terminal)
    assert result.returncode == (status if terminal == "none" else 0), result.stderr
    if terminal == "tmux":
        assert Path(env["CHILD_STATUS"]).read_text().strip() == str(status)
    fields = yaml.safe_load(relay.read_text())
    assert fields["status"] == "retired" and fields["retired_at"]
    assert Path(env["LAUNCH_TRACE"]).read_text().splitlines()[1] != "inherited-parent-id"


@pytest.mark.parametrize("terminal", ["none", "tmux"])
def test_runner_setup_failure_still_retires_relay(launcher, terminal):
    _, _, env, relay = launcher
    env["HAPAX_GLMCP_WORKDIR"] = str(Path(env["HOME"]) / "missing-directory")
    result = launch(env, terminal)
    assert (
        result.returncode if terminal == "none" else int(Path(env["CHILD_STATUS"]).read_text())
    ) != 0
    assert yaml.safe_load(relay.read_text())["status"] == "retired"
    assert not Path(env["LAUNCH_TRACE"]).exists()


@pytest.mark.parametrize("terminal", ["none", "tmux"])
@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_termination_reaches_child_and_retires_relay(launcher, terminal, sig):
    _, _, env, relay = launcher
    env.update(KIMI_WAIT="1", RUNNER_ONLY="1")
    if terminal == "tmux":
        assert launch(env, terminal).returncode == 0
        args = ["bash", Path(env["RUNNER_TRACE"]).read_text()]
    else:
        args = ["bash", str(ROOT / "scripts/hapax-glmcp"), "glm-test", "--terminal", "none"]
    proc = subprocess.Popen(
        args,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not Path(env["LAUNCH_TRACE"]).exists():
            assert proc.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.02)
        proc.send_signal(sig)
        _, stderr = proc.communicate(timeout=5)
        assert proc.returncode == 128 + sig, stderr
        assert yaml.safe_load(relay.read_text())["status"] == "retired"
    finally:
        # Reap this test's whole private process group even when a broken signal
        # handler leaves the fake child holding captured pipes open.
        with suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate(timeout=5)


@pytest.mark.parametrize("terminal", ["none", "tmux"])
def test_child_retains_session_stdin(launcher, terminal):
    _, _, env, _ = launcher
    env["KIMI_READ_STDIN"] = "1"
    result = launch(env, terminal, input="session input\n")
    assert result.returncode == 0, result.stderr
    assert Path(env["STDIN_TRACE"]).read_text() == "session input"


def test_tmux_runner_quotes_paths(launcher):
    tmp_path, _, env, relay = launcher
    work = tmp_path / "work 'quoted' 🦆"
    work.mkdir()
    binary = Path(env["KIMI_BIN"])
    moved = binary.with_name("kimi 'quoted' 🦆")
    binary.rename(moved)
    env.update(KIMI_BIN=str(moved), HAPAX_GLMCP_WORKDIR=str(work))
    result = launch(env, "tmux")
    assert result.returncode == 0, result.stderr
    assert Path(env["CHILD_STATUS"]).read_text().strip() == "0"
    assert yaml.safe_load(relay.read_text())["status"] == "retired"


@pytest.mark.parametrize("fault", ["chmod", "marker"])
def test_launcher_setup_write_failures_stop_before_kimi(launcher, fault):
    tmp_path, release, env, _ = launcher
    if fault == "chmod":
        stub = tmp_path / "bin/chmod"
        stub.write_text("#!/bin/bash\nexit 1\n")
        stub.chmod(0o755)
    else:
        cache = Path(env["HOME"]) / ".cache/hapax"
        moved = tmp_path / "activated-release"
        release.rename(moved)
        env["HAPAX_COUNCIL_DIR"] = str(moved)
        # This must fail even as root: the marker's parent is a regular file.
        shutil.rmtree(cache)
        cache.write_text("not a directory")
    result = launch(env)
    assert result.returncode != 0
    assert "Next action:" in result.stderr
    assert not Path(env["LAUNCH_TRACE"]).exists()
    assert not (tmp_path / "runtime/kimi-glm/glm-test/config.toml").exists()


@pytest.mark.parametrize("value", ["non-BMP 🦆", 'quote"\\\ncontrol\x01', "delete\x7f"])
def test_launcher_quotes_every_toml_string(launcher, value):
    tmp_path, release, env, _ = launcher
    moved = release.with_name('worktree 🦆"\\')
    release.rename(moved)
    env.update(HAPAX_COUNCIL_DIR=str(moved), HAPAX_GLMCP_MODEL=value)
    result = launch(env)
    assert result.returncode == 0, result.stderr
    config = tomllib.loads((tmp_path / "runtime/kimi-glm/glm-test/config.toml").read_text())
    assert config["models"]["zai/glm-5.3"]["model"] == value
    assert all(
        str(moved / "hooks/scripts/kimi-hook-adapter.sh") in h["command"] for h in config["hooks"]
    )

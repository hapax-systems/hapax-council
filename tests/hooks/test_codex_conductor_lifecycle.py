"""Turn hooks cannot terminate the process-owned conductor; no live hooks run."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("interface", ["codex", "kimi"])
def test_codex_stop_keeps_conductor_across_two_turns(tmp_path, interface):
    hooks = tmp_path / "hooks/scripts"
    hooks.mkdir(parents=True)
    shutil.copy2(ROOT / "hooks/scripts/codex-hook-adapter.sh", hooks)
    trace = tmp_path / "trace"
    for name in ("session-summary.sh", "conductor-stop.sh"):
        stub = hooks / name
        stub.write_text(f'#!/bin/bash\nprintf "%s\\n" "{name}" >>"$TRACE"\n')
        stub.chmod(0o755)
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TRACE": str(trace)}
    env["HAPAX_AGENT_INTERFACE"] = interface
    for _ in range(2):
        result = subprocess.run(
            ["bash", str(hooks / "codex-hook-adapter.sh"), "Stop"],
            input=json.dumps({"session_id": "native-session"}),
            text=True,
            capture_output=True,
            env=env,
            check=True,
        )
        assert json.loads(result.stdout)["continue"] is True
    expected = ["session-summary.sh"]
    if interface != "codex":
        expected.append("conductor-stop.sh")
    assert trace.read_text().splitlines() == expected * 2


def test_direct_codex_stop_does_not_signal_conductor(tmp_path):
    council = tmp_path / "projects/hapax-council"
    council.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    trace = tmp_path / "stop-called"
    uv = bin_dir / "uv"
    uv.write_text('#!/bin/bash\nprintf "called" >"$TRACE"\n')
    uv.chmod(0o755)
    env = {
        "HOME": str(tmp_path),
        "TRACE": str(trace),
        "HAPAX_AGENT_INTERFACE": "codex",
        "HAPAX_AGENT_ROLE": "fixture-lane",
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    subprocess.run(
        ["bash", str(ROOT / "hooks/scripts/conductor-stop.sh")],
        input=json.dumps({"session_id": "native-session"}),
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    assert not trace.exists()


@pytest.mark.parametrize("observed", [True, False])
def test_start_forwards_observed_owner_and_session_without_live_launch(tmp_path, observed):
    source = tmp_path / "source"
    hooks = source / "hooks/scripts"
    hooks.mkdir(parents=True)
    for name in ("conductor-start.sh", "agent-role.sh"):
        shutil.copy2(ROOT / "hooks/scripts" / name, hooks)
    helper = source / "agents/session_conductor/lifecycle.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("print('345 678')\n" if observed else "raise SystemExit(1)\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    trace = tmp_path / "launch"
    systemd = bin_dir / "systemd-run"
    systemd.write_text('#!/bin/bash\nprintf "%s\\n" "$@" >"$TRACE"\n')
    systemd.chmod(0o755)
    # Avoid a three-second readiness wait; this stub cannot launch anything.
    sleep = bin_dir / "sleep"
    sleep.write_text("#!/bin/bash\nexit 0\n")
    sleep.chmod(0o755)
    env = {
        "HOME": str(tmp_path),
        "TRACE": str(trace),
        "HAPAX_AGENT_INTERFACE": "codex",
        "HAPAX_AGENT_ROLE": "fixture-lane",
        "HAPAX_SESSION_ID": "lane-uuid",
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    result = subprocess.run(
        ["bash", str(hooks / "conductor-start.sh")],
        input=json.dumps({"session_id": "native-uuid"}),
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    if not observed:
        assert not trace.exists()
        assert "unobserved" in result.stderr
        return
    args = trace.read_text().splitlines()
    assert args[args.index("--role") + 1] == "fixture-lane"
    assert args[args.index("--directory") + 1] == str(source)
    start = args[args.index("start") + 1 :]
    values = dict(zip(start[::2], start[1::2], strict=True))
    assert values == {
        "--session-id": "lane-uuid",
        "--session-id-kind": "lane",
        "--native-session-id": "native-uuid",
        "--owner-pid": "345",
        "--owner-start-ticks": "678",
    }

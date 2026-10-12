"""Observe the native child, including runners born from a foreign tmux server."""

from __future__ import annotations

import base64
import json
import os
import resource
import runpy
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COLLISIONS = {
    "COUNCIL_DIR": "/parent/source",
    "LANE_ENVIRONMENT": "/parent/helper",
    "LANE_RESET": "parent-reset",
}
FOREIGN = {
    "HAPAX_SESSION_ID": "11111111-2222-4333-8444-555555555555",
    "HAPAX_AGENT_NAME": "parent-seat",
    "HAPAX_AGENT_ROLE": "parent-seat",
    "HAPAX_AGENT_INTERFACE": "parent-interface",
    "HAPAX_AGENT_UNRECOGNIZED": "parent-state",
    "HAPAX_METHODOLOGY_DISPATCH_TASK": "parent-task",
    "CLAUDE_ROLE": "parent-seat",
    "CLAUDE_PID": "12345",
    "CLAUDE_CODE_SESSION_ID": "parent-native-session",
    "CLAUDE_CODE_MESSAGING_TOKEN": "foreign-messaging-value",
    "CLAUDE_CODE_MESSAGING_SOCKET": "/parent/socket",
    "CLAUDE_FUTURE_STATE": "parent-state",
    "ANTHROPIC_AUTH_TOKEN": "foreign-auth-value",
    "ANTHROPIC_API_KEY": "foreign-api-value",  # pragma: allowlist secret (synthetic fixture)
    "ANTHROPIC_FUTURE_SETTING": "foreign-setting",
    "OPENAI_API_KEY": "foreign-openai-value",  # pragma: allowlist secret (synthetic fixture)
    "GITHUB_TOKEN": "foreign-github-value",
    "UNDECLARED_PARENT_VALUE": "parent-state",
}
VARIANTS = [
    ("hapax-codex", "none"),
    ("hapax-codex", "tmux"),
    ("hapax-codex-headless", "none"),
    ("hapax-claude", "none"),
    ("hapax-claude", "tmux"),
    ("hapax-glmcp", "none"),
    ("hapax-glmcp", "tmux"),
    ("hapax-glmcp-claude", "none"),
]


def executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    path.chmod(0o755)


def launch(
    tmp: Path,
    launcher: str,
    terminal: str,
    *,
    sid: str = "",
    default: bool = False,
    refuse: bool = False,
    extra_env: dict[str, str] | None = None,
    receipt: Path | None = None,
    dispatch: bool = False,
    fail_reset_at: int = 0,
    collisions: bool = False,
):
    home = tmp / "home"
    work = home / "projects/lane"
    bins = tmp / "bin"
    runtime = tmp / "runtime"
    for path in (work, bins, runtime, home / ".cache/hapax"):
        path.mkdir(parents=True, exist_ok=True)
    activation = home / ".cache/hapax/source-activation/worktree"
    activation.parent.mkdir(parents=True)
    unused_release = tmp / "non-selected-release"
    unused_release.mkdir()
    activation.symlink_to(ROOT if default else unused_release, target_is_directory=True)
    output = tmp / "child.json"
    native = f"""#!{sys.executable}
import json, os, resource, sys
from pathlib import Path
if 'HAPAX_CODEX_EXEC_AUTH_OK' in ' '.join(sys.argv):
    print(json.dumps({{'type':'item.completed','item':{{'type':'agent_message','text':'HAPAX_CODEX_EXEC_AUTH_OK'}}}}))
    raise SystemExit(0)
Path({str(output)!r}).write_text(json.dumps({{'env':dict(os.environ), 'argv':sys.argv, 'nofile':resource.getrlimit(resource.RLIMIT_NOFILE)}}))
print(json.dumps({{'type':'thread.started','thread_id':'native-fixture'}}))
print(json.dumps({{'type':'turn.completed'}}))
"""
    for name in ("codex", "claude", "kimi"):
        executable(bins / name, native)
    executable(bins / "hapax-secret", "#!/bin/bash\nprintf 'declared-fixture-credential\\n'\n")
    executable(work / "scripts/cc-claim", "#!/bin/bash\nexit 0\n")
    # A server has its own foreign environment and low limits even if the
    # outer launcher cleans/raises its own. Never touch the user's tmux server.
    executable(
        bins / "tmux",
        f"""#!{sys.executable}
import json, os, resource, subprocess, sys
from pathlib import Path
state = Path({str(tmp / "tmux-state")!r})
args = sys.argv[1:]
if args[0] == 'has-session':
    raise SystemExit(0 if state.exists() else 1)
if args[0] == 'new-session':
    state.touch()
    env = dict(os.environ)
    env.update({FOREIGN!r})
    env.update({COLLISIONS if collisions else {}!r})
    resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1048576))
    raise SystemExit(subprocess.call([args[-1]], env=env))
if args[0] == 'capture-pane':
    print('❯\\n⏵⏵ bypass permissions on (shift+tab to cycle)')
""",
    )
    env = {
        "HOME": str(home),
        "PATH": f"{bins}:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TMPDIR": str(tmp),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_RUNTIME_DIR": str(runtime),
        "HAPAX_DISPATCH_HOST": "local",
        "HAPAX_CODEX_HEADLESS_ALLOW": "1",
        "HAPAX_CODEX_HEADLESS_WORKDIR": str(work),
        "HAPAX_CODEX_HEADLESS_PID_DIR": str(tmp / "pids"),
        "HAPAX_GLMCP_WORKDIR": str(work),
        "KIMI_BIN": str(bins / "kimi"),
        "HAPAX_CLAUDE_READY_TIMEOUT": "1",
        **FOREIGN,
    }
    if not default:
        env["HAPAX_COUNCIL_DIR"] = str(ROOT)
    env.update(extra_env or {})
    if collisions:
        env.update(COLLISIONS)
    if fail_reset_at:
        executable(
            bins / "python3",
            f"""#!{sys.executable}
import os, sys
from pathlib import Path
if sys.argv[-1] == 'shell':
    counter = Path({str(tmp / "resets")!r})
    count = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(count))
    if count == {fail_reset_at}:
        raise SystemExit(42)
os.execv('/usr/bin/python3', ['python3', *sys.argv[1:]])
""",
        )
    args = [str(ROOT / "scripts" / launcher)]
    identity = ["--session-id", sid] if sid else []
    if launcher == "hapax-codex":
        args += [
            "--session",
            "cx-fixture",
            "--slot",
            "alpha",
            "--cd",
            str(work),
            "--terminal",
            terminal,
            "--no-claim",
            *identity,
        ]
    elif launcher == "hapax-codex-headless":
        args += ["--task", "own-task", "--no-claim", *identity, "cx-fixture", "fixture prompt"]
        if receipt:
            args[1:1] = ["--lifecycle-receipt", str(receipt)]
    elif launcher == "hapax-claude":
        args += [
            "--role",
            "dev9",
            "--cd",
            str(work),
            "--terminal",
            terminal,
            "--readonly",
            *identity,
        ]
    elif launcher == "hapax-glmcp":
        args += ["dev9", "--terminal", terminal, *identity]
    else:
        args += identity
    if dispatch:
        env["PYTEST_CURRENT_TEST"] = "hermetic dispatcher launch"
        args = [
            sys.executable,
            "-c",
            "import runpy; from pathlib import Path; from types import SimpleNamespace; "
            f"d=runpy.run_path({str(ROOT / 'scripts/hapax-methodology-dispatch')!r}); "
            "v=SimpleNamespace(task=SimpleNamespace(fields={'status':'claimed'})); "
            "raise SystemExit(d['launch_codex_headless']('own-task','cx-fixture','fixture prompt',"
            f"v,d['route_for']('codex','headless','full'),lifecycle_receipt=Path({str(receipt)!r})))",
        ]
    result = subprocess.run(
        args,
        env=env,
        text=True,
        capture_output=True,
        timeout=45,
        preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1048576)),
    )
    if refuse:
        assert result.returncode != 0, result.stdout + result.stderr
        assert not output.exists()
        return result
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.exists(), result.stdout + result.stderr
    return json.loads(output.read_text()), env, activation


@pytest.mark.parametrize(("launcher", "terminal"), VARIANTS)
@pytest.mark.parametrize("explicit", [False, True], ids=["fresh", "explicit"])
def test_child_identity_environment_and_limits(tmp_path, launcher, terminal, explicit):
    sid = "fa223355-5555-4777-8888-999999999999" if explicit else ""
    child, parent, _ = launch(tmp_path, launcher, terminal, sid=sid)
    env = child["env"]
    observed = env.get("HAPAX_SESSION_ID")
    if explicit:
        assert observed == sid
    else:
        assert observed != FOREIGN["HAPAX_SESSION_ID"]
        assert uuid.UUID(observed).version == 4
    assert all(env.get(key) != value for key, value in FOREIGN.items())
    assert env["HOME"] == parent["HOME"]
    assert env["PATH"] == parent["PATH"]
    assert child["nofile"] == [65536, 1048576]
    if launcher == "hapax-glmcp-claude":
        assert env["ANTHROPIC_AUTH_TOKEN"] == "declared-fixture-credential"
    else:
        assert "ANTHROPIC_AUTH_TOKEN" not in env


@pytest.mark.parametrize("launcher", sorted({name for name, _ in VARIANTS}))
@pytest.mark.parametrize("default", [False, True], ids=["override", "activated-default"])
def test_child_uses_activated_source_or_explicit_override(tmp_path, launcher, default):
    child, _, activation = launch(tmp_path, launcher, "none", default=default)
    assert Path(child["env"]["HAPAX_COUNCIL_DIR"]).resolve() == ROOT
    if default:
        assert activation.is_symlink()


@pytest.mark.parametrize("launcher", sorted({name for name, _ in VARIANTS}))
def test_unsafe_explicit_identity_refuses_before_native_exec(tmp_path, launcher):
    result = launch(tmp_path, launcher, "none", sid="../../parent", refuse=True)
    assert "unsafe --session-id" in result.stderr


@pytest.mark.parametrize(
    ("soft", "hard", "expected"), [(1024, 8192, 8192), (131072, 1048576, 131072)]
)
def test_limit_is_capped_by_hard_and_never_lowered(soft, hard, expected):
    helper = ROOT / "scripts/lane_environment.py"
    result = subprocess.run(
        [
            "bash",
            "-ec",
            'reset="$(python3 -I "$1" shell)"; eval "$reset"; ulimit -Sn',
            "test",
            str(helper),
        ],
        env={"HOME": str(ROOT), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard)),
    )
    assert result.returncode == 0, result.stderr
    assert int(result.stdout) == expected


def test_dispatch_launch_drops_foreign_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPAX_COUNCIL_DIR", str(ROOT))
    dispatcher = runpy.run_path(str(ROOT / "scripts/hapax-methodology-dispatch"))
    for key, value in FOREIGN.items():
        monkeypatch.setenv(key, value)
    output = tmp_path / "env.json"
    code = f"import json, os; open({str(output)!r}, 'w').write(json.dumps(dict(os.environ)))"
    assert dispatcher["_sliced_call"]([sys.executable, "-c", code]) == 0
    child = json.loads(output.read_text())
    assert all(key not in child for key in FOREIGN)


@pytest.mark.parametrize("launcher", ["hapax-codex", "hapax-codex-headless"])
def test_remote_native_child_starts_clean(tmp_path, launcher):
    text = (ROOT / "scripts" / launcher).read_text()
    source = text.split("REMOTE_EXEC_PY='", 1)[1].split("'\n", 1)[0]
    output = tmp_path / "remote.json"
    probe = tmp_path / "codex"
    executable(
        probe,
        f"#!{sys.executable}\nimport json, os, resource\nopen({str(output)!r}, 'w').write(json.dumps({{'env':dict(os.environ), 'nofile':resource.getrlimit(resource.RLIMIT_NOFILE)}}))\n",
    )
    payload = {
        "workdir": str(tmp_path),
        "argv": [str(probe)],
        "env": {"HAPAX_SESSION_ID": "owned-remote-session"},
        "codex_bin_path": str(probe),
    }
    env = {
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin",
        "HAPAX_COUNCIL_DIR": str(ROOT),
        **FOREIGN,
        "HAPAX_REMOTE_PAYLOAD": base64.b64encode(json.dumps(payload).encode()).decode(),
    }
    result = subprocess.run(
        [sys.executable, "-c", source],
        env=env,
        capture_output=True,
        text=True,
        preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1048576)),
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(output.read_text())
    assert observed["env"]["HAPAX_SESSION_ID"] == "owned-remote-session"
    assert all(observed["env"].get(key) != value for key, value in FOREIGN.items())
    assert observed["nofile"] == [65536, 1048576]


@pytest.mark.parametrize("control", ["disable", "enable_file", "enable_env"])
def test_dispatch_claude_headless_controls_reach_real_launcher(
    tmp_path, monkeypatch, capfd, control
):
    home = tmp_path / "home"
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    stop = tmp_path / "operator-stop"
    enable = tmp_path / "operator-enable"
    missing_worktree = tmp_path / "absent-worktree"
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "HAPAX_COUNCIL_DIR": str(ROOT),
        "HAPAX_METHODOLOGY_CLAUDE_HEADLESS": str(ROOT / "scripts/hapax-claude-headless"),
        "HAPAX_SDLC_SLICE_ATTACHED": "1",
        "PYTEST_CURRENT_TEST": "hermetic stop-control test",
    }
    if control == "disable":
        (cache / "enable-claude-headless").touch()
        stop.touch()
        env["HAPAX_CLAUDE_HEADLESS_DISABLE_FILE"] = str(stop)
    elif control == "enable_file":
        enable.touch()
        env["HAPAX_CLAUDE_HEADLESS_ENABLE_FILE"] = str(enable)
    else:
        env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
    monkeypatch.setattr(os, "environ", env)
    d = runpy.run_path(str(ROOT / "scripts/hapax-methodology-dispatch"))
    # Stop at the real launcher's next preflight; no native process, claims,
    # systemd scopes, or runtime writes outside this private HOME.
    d["launch_claude_headless"].__globals__["lane_worktree"] = lambda *_: missing_worktree
    rc = d["launch_claude_headless"](
        "own-task", "alpha", "fixture", d["route_for"]("claude", "headless", "full")
    )
    err = capfd.readouterr().err
    if control == "disable":
        assert rc == 77, err
        assert f"disabled by {stop}" in err
        assert not list(cache.glob("session-role-*"))
    else:
        assert rc == 3, err
        assert f"worktree not found: {missing_worktree}" in err


@pytest.mark.parametrize("parent_exists", [False, True], ids=["unused-parent", "existing-parent"])
@pytest.mark.parametrize("delivery", ["default", "explicit", "dispatcher"])
def test_nested_headless_receipt_is_owned_by_child(tmp_path, parent_exists, delivery):
    parent = tmp_path / "parent-receipt.json"
    original = b"preserved parent witness\n"
    if parent_exists:
        parent.write_bytes(original)
    explicit = tmp_path / "child-receipt.json" if delivery != "default" else None
    child, _, _ = launch(
        tmp_path,
        "hapax-codex-headless",
        "none",
        extra_env={"HAPAX_NATIVE_LIFECYCLE_RECEIPT": str(parent)},
        receipt=explicit,
        dispatch=delivery == "dispatcher",
    )
    assert "HAPAX_NATIVE_LIFECYCLE_RECEIPT" not in child["env"]
    if parent_exists:
        assert parent.read_bytes() == original
    else:
        assert not parent.exists()
    receipts = list(
        (tmp_path / "home/.cache/hapax/codex-headless/cx-fixture").glob("native-*.receipt.json")
    )
    if explicit:
        assert receipts == []
        receipts = [explicit]
    assert len(receipts) == 1
    observation = json.loads(receipts[0].read_text())
    assert observation["complete"] is True
    assert observation["session_id"] == "native-fixture"


@pytest.mark.parametrize("launcher", sorted({name for name, _ in VARIANTS}))
@pytest.mark.parametrize("failure", ["missing-root", "missing-helper", "python-failed"])
def test_launch_dependency_failure_has_next_action(tmp_path, launcher, failure):
    selected = tmp_path / "broken-release"
    if failure == "missing-helper":
        selected.mkdir()
    if failure == "python-failed":
        selected = ROOT
    result = launch(
        tmp_path,
        launcher,
        "none",
        refuse=True,
        extra_env={"HAPAX_COUNCIL_DIR": str(selected)},
        fail_reset_at=1 if failure == "python-failed" else 0,
    )
    assert result.returncode == 9
    assert str(selected) in result.stderr
    assert "next action:" in result.stderr
    assert "activated release" in result.stderr
    assert "HAPAX_COUNCIL_DIR" in result.stderr


@pytest.mark.parametrize("launcher", ["hapax-codex", "hapax-claude", "hapax-glmcp"])
def test_runner_reset_failure_has_next_action(tmp_path, launcher):
    result = launch(tmp_path, launcher, "tmux", refuse=True, fail_reset_at=2)
    assert result.returncode != 0
    assert str(ROOT) in result.stderr
    assert "next action:" in result.stderr


@pytest.mark.parametrize("launcher", ["hapax-codex", "hapax-codex-headless"])
def test_remote_missing_helper_has_next_action(tmp_path, launcher):
    text = (ROOT / "scripts" / launcher).read_text()
    source = text.split("REMOTE_EXEC_PY='", 1)[1].split("'\n", 1)[0]
    selected = tmp_path / "remote-release"
    payload = {"workdir": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-c", source],
        env={
            "HOME": str(tmp_path),
            "PATH": "/usr/bin:/bin",
            "HAPAX_COUNCIL_DIR": str(selected),
            "HAPAX_REMOTE_PAYLOAD": base64.b64encode(json.dumps(payload).encode()).decode(),
        },
        text=True,
        capture_output=True,
    )
    assert result.returncode == 9
    assert str(selected) in result.stderr
    assert "next action:" in result.stderr
    assert "activated release" in result.stderr


@pytest.mark.parametrize(("launcher", "terminal"), VARIANTS)
def test_exported_launcher_names_do_not_erase_owned_state(tmp_path, launcher, terminal):
    child, _, _ = launch(tmp_path, launcher, terminal, collisions=True)
    assert child["env"]["HAPAX_COUNCIL_DIR"] == str(ROOT)
    assert all(key not in child["env"] for key in COLLISIONS)

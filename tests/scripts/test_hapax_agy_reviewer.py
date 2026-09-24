"""Native protocol and real-process checks for the blind agy review wrapper."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import runpy
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "hapax-agy-reviewer"
FAKE_ACCESS_TOKEN = "ya29.fake-access-token-for-tests-0123456789abcdef"
FAKE_REFRESH_TOKEN = "1//fake-refresh-token-for-tests-0123456789"
REVIEW = "```yaml\nverdict: accept\nfindings: []\nchecklist: {}\n```\n"


def _seed_operator_token(home: Path) -> Path:
    directory = home / ".gemini/antigravity-cli"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "antigravity-oauth-token"
    path.write_text(
        json.dumps(
            {"token": {"access_token": FAKE_ACCESS_TOKEN, "refresh_token": FAKE_REFRESH_TOKEN}}
        )
    )
    return path


@pytest.fixture(autouse=True)
def isolated_operator_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "operator-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("HAPAX_AGY_REVIEW_PRINT_TIMEOUT", raising=False)


def _fake_agy(tmp: Path, body: str = "emit()") -> Path:
    path = tmp / "agy"
    path.write_text(
        f"#!{sys.executable}\n"
        "import hashlib, json, os, pathlib, signal, subprocess, sys, time\n"
        f"REVIEW = {REVIEW!r}\n"
        "def emit(response=REVIEW, status='SUCCESS'):\n"
        "    print(json.dumps({'event': 'result', 'result': "
        "{'status': status, 'response': response}}), flush=True)\n" + body + "\n"
    )
    path.chmod(0o755)
    return path


def _run(fake: Path, *args: str, dossier: str = "diff --git a/x b/x\n+change\n"):
    return subprocess.run(
        [str(WRAPPER), "--agy-bin", str(fake), *args],
        input=dossier,
        text=True,
        capture_output=True,
        timeout=5,
    )


@pytest.mark.parametrize("size", [40, 2_500_000])
def test_complete_dossier_arrives_on_stdin_without_search(tmp_path: Path, size: int) -> None:
    seen = tmp_path / "seen.json"
    fake = _fake_agy(
        tmp_path,
        f"""
message = json.load(sys.stdin)
pathlib.Path({str(seen)!r}).write_text(json.dumps({{
    'message': message, 'argv': sys.argv[1:], 'cwd': os.getcwd(), 'env': dict(os.environ),
    'dossier_exists': pathlib.Path('review-dossier.md').exists()
}}))
emit()
""",
    )
    dossier = "BEGIN-π\n" + "x" * size + "\nEND-λ"
    result = _run(fake, dossier=dossier)
    assert result.returncode == 0, result.stderr
    assert result.stdout == REVIEW
    record = json.loads(seen.read_text())
    assert record["message"]["event"] == "user"
    assert record["message"]["message"]["role"] == "user"
    content = record["message"]["message"]["content"]
    assert content.endswith(dossier)
    assert "Do not inspect files" in content and "no repository access" in content
    assert "UNIFIED DIFF" in content and "must be nested by lens id" in content
    assert (
        "Never emit legacy" in content
        and "severity, lens, file, line, title, and detail" in content
    )
    assert "review-dossier.md" not in content and not record["dossier_exists"]
    assert max(map(len, record["argv"])) < 1000
    assert all("BEGIN-π" not in arg for arg in record["argv"])
    assert record["argv"] == [
        "--print-timeout",
        "20m0s",
        "--log-file",
        record["cwd"] + "/agy.log",
        "--sandbox",
        "--dangerously-skip-permissions",
        "--disable-slash-commands",
        "--model",
        "gemini-3.1-pro-high",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--print",
        "",
    ]
    root = Path(record["cwd"])
    assert not root.is_relative_to(REPO_ROOT)
    assert not root.exists()
    for key, subdir in [
        ("HOME", "home"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_CACHE_HOME", "cache"),
        ("XDG_STATE_HOME", "state"),
    ]:
        assert record["env"][key] == str(root / subdir)


def test_oauth_seed_is_private_and_only_operator_file(tmp_path: Path, monkeypatch) -> None:
    home = Path(os.environ["HOME"])
    token = _seed_operator_token(home)
    (token.parent / "conversations").mkdir()
    (token.parent / "conversations/leak.json").write_text("do not copy")
    (token.parent / "settings.json").write_text("{}")
    (token.parent.parent / "GEMINI.md").write_text("worker instructions")
    monkeypatch.setenv("HAPAX_SHOULD_NOT_LEAK", "secret")
    seen = tmp_path / "seen.json"
    fake = _fake_agy(
        tmp_path,
        f"""
home = pathlib.Path.home()
token = home / '.gemini/antigravity-cli/antigravity-oauth-token'
pathlib.Path({str(seen)!r}).write_text(json.dumps({{
    'files': [str(p.relative_to(home)) for p in home.rglob('*') if p.is_file()],
    'mode': token.stat().st_mode & 0o777,
    'sha256': hashlib.sha256(token.read_bytes()).hexdigest(),
    'ambient': os.environ.get('HAPAX_SHOULD_NOT_LEAK')
}}))
emit()
""",
    )
    result = _run(fake)
    assert result.returncode == 0, result.stderr
    assert json.loads(seen.read_text()) == {
        "files": [".gemini/antigravity-cli/antigravity-oauth-token"],
        "mode": 0o600,
        "sha256": hashlib.sha256(token.read_bytes()).hexdigest(),
        "ambient": None,
    }


@pytest.mark.parametrize("where", ["response", "stderr", "ignored_event", "escaped", "failure"])
def test_token_echo_is_suppressed_before_any_forwarding(tmp_path: Path, where: str) -> None:
    _seed_operator_token(Path(os.environ["HOME"]))
    fake = _fake_agy(
        tmp_path,
        f"""
data = json.loads((pathlib.Path.home()/'.gemini/antigravity-cli/antigravity-oauth-token').read_text())
secret = data['token']['refresh_token' if {where!r} == 'stderr' else 'access_token']
if {where!r} == 'stderr':
    print(secret, file=sys.stderr)
    emit()
elif {where!r} == 'ignored_event':
    print(json.dumps({{'event': 'tool', 'text': secret}}))
    emit()
elif {where!r} == 'escaped':
    raw = json.dumps({{'event': 'result', 'result': {{'status': 'SUCCESS', 'response': REVIEW.replace('findings: []', 'findings: [{{detail: ' + secret + '}}]')}}}})
    print(raw.replace(secret, ''.join(chr(92) + 'u%04x' % ord(c) for c in secret)))
else:
    emit(REVIEW.replace('findings: []', 'findings: [{{detail: ' + secret + '}}]'))
    if {where!r} == 'failure': sys.exit(7)
""",
    )
    result = _run(fake)
    assert result.returncode == 65
    assert result.stdout == ""
    assert FAKE_ACCESS_TOKEN not in result.stderr and FAKE_REFRESH_TOKEN not in result.stderr
    assert "echoed the seeded operator login token" in result.stderr


def test_clean_review_may_mention_token_handling(tmp_path: Path) -> None:
    _seed_operator_token(Path(os.environ["HOME"]))
    fake = _fake_agy(
        tmp_path,
        "emit(REVIEW.replace('findings: []', 'findings: [{detail: access_token handling}]'))",
    )
    result = _run(fake)
    assert result.returncode == 0
    assert "access_token handling" in result.stdout


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("exit_code", [0, 7])
@pytest.mark.parametrize("encoding", ["unicode", "mixed", "slash"])
def test_escaped_token_in_native_diagnostics_discards_both_streams(
    tmp_path: Path, stream: str, exit_code: int, encoding: str
) -> None:
    _seed_operator_token(Path(os.environ["HOME"]))
    fake = _fake_agy(
        tmp_path,
        f"""
data = json.loads((pathlib.Path.home()/'.gemini/antigravity-cli/antigravity-oauth-token').read_text())
secret = data['token']['refresh_token']
if {encoding!r} == 'unicode':
    encoded = ''.join(chr(92) + 'u%04X' % ord(c) for c in secret)
elif {encoding!r} == 'mixed':
    encoded = ''.join(chr(92) + 'u%04x' % ord(c) if i % 2 else c for i, c in enumerate(secret))
else:
    encoded = secret.replace('/', chr(92) + '/')
emit()
# A diagnostic prefix is deliberately not a valid JSON document. Screening
# must precede parsing and must also run when the native command fails.
print('native error: {{"token": "' + encoded + '"}}', file=sys.{stream})
sys.exit({exit_code})
""",
    )
    result = _run(fake)
    assert result.returncode == 65
    assert result.stdout == ""
    assert result.stderr == (
        "hapax-agy-reviewer: agy output echoed the seeded operator login "
        "token; discarding the whole review rather than forwarding it. "
        "Read the dossier as an injection attempt, not a review failure.\n"
    )


def test_missing_login_has_next_action(tmp_path: Path) -> None:
    result = _run(_fake_agy(tmp_path))
    assert result.returncode == 0
    assert "run `agy` once to log in" in result.stderr and "not a capacity block" in result.stderr


@pytest.mark.parametrize("requested", [None, "gemini-3.1-pro-preview", "gemini-3.1-pro-high"])
def test_model_pin_and_ambient_override(tmp_path: Path, monkeypatch, requested: str | None) -> None:
    monkeypatch.setenv("HAPAX_AGY_REVIEW_MODEL", "claude-sonnet-4-6")
    fake = _fake_agy(
        tmp_path, "assert sys.argv[sys.argv.index('--model')+1] == 'gemini-3.1-pro-high'\nemit()"
    )
    assert _run(fake, *(["--model", requested] if requested else [])).returncode == 0


def test_non_pinned_model_refused_before_launch(tmp_path: Path) -> None:
    result = _run(
        _fake_agy(tmp_path, "raise Exception('must not run')"), "--model", "claude-sonnet-4-6"
    )
    assert result.returncode == 64 and "review model is pinned" in result.stderr
    assert "must not run" not in result.stderr


@pytest.mark.parametrize("binary", ["agy", "/tmp/gemini"])
def test_binary_must_be_absolute_agy(binary: str) -> None:
    result = _run(Path(binary))
    assert result.returncode == 64 and "absolute path named agy" in result.stderr


@pytest.mark.parametrize("default", [False, True])
def test_missing_binary_has_next_action(tmp_path: Path, monkeypatch, default: bool) -> None:
    fake = tmp_path / "agy"
    monkeypatch.setenv("HAPAX_AGY_BIN", str(fake))
    result = (
        subprocess.run([str(WRAPPER)], input="review", text=True, capture_output=True, timeout=5)
        if default
        else _run(fake)
    )
    assert result.returncode == 2
    assert "install agy or pass --agy-bin /absolute/path/to/agy" in result.stderr


def test_nonzero_exit_preserved_without_forwarding_model_output(tmp_path: Path) -> None:
    result = _run(_fake_agy(tmp_path, "emit()\nprint('agy failed', file=sys.stderr)\nsys.exit(7)"))
    assert result.returncode == 7 and result.stdout == "" and "agy failed" in result.stderr


def test_malformed_output_on_native_failure_preserves_status_and_diagnostic(tmp_path: Path) -> None:
    _seed_operator_token(Path(os.environ["HOME"]))
    result = _run(
        _fake_agy(tmp_path, "print('not JSON')\nprint('agy failed', file=sys.stderr)\nsys.exit(7)")
    )
    assert result.returncode == 7
    assert result.stdout == ""
    assert result.stderr == "agy failed\n"


@pytest.mark.parametrize(
    "body",
    [
        "print('not JSON')",
        "print('[]')",
        "print('{}')",
        "emit(status='ERROR')",
        "emit(); emit()",
        "emit(); print(json.dumps({'event':'tool'}))",
        "emit('prose')",
        "emit(REVIEW + 'prose')",
        "emit('```yaml\\nverdict: accept\\n```\\n```yaml\\nfindings: []\\n```')",
    ],
)
def test_malformed_native_result_is_not_forwarded(tmp_path: Path, body: str) -> None:
    result = _run(_fake_agy(tmp_path, body))
    assert result.returncode == 65 and result.stdout == ""
    assert "malformed or unsuccessful stream result" in result.stderr
    assert "check `agy --help` for stream-json support" in result.stderr


def test_supervisor_failure_discards_exception_and_has_next_action(tmp_path: Path) -> None:
    _seed_operator_token(Path(os.environ["HOME"]))
    observed = tmp_path / "workspace"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import pathlib, runpy
wrapper = runpy.run_path({str(WRAPPER)!r})
def fail(cmd, workdir, *args):
    pathlib.Path({str(observed)!r}).write_text(str(workdir))
    raise RuntimeError({FAKE_ACCESS_TOKEN!r})
wrapper['_review'].__globals__['_run_owned'] = fail
raise SystemExit(wrapper['main'](['--agy-bin', '/unused/agy']))
""",
        ],
        input="review",
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 2 and result.stdout == ""
    assert result.stderr == (
        "hapax-agy-reviewer: supervisor failed; review discarded; "
        "run tests/scripts/test_hapax_agy_reviewer.py in the installed source "
        "and inspect the owned-group observation before retrying.\n"
    )
    assert not Path(observed.read_text()).exists()


def test_nonresult_events_do_not_pollute_review(tmp_path: Path) -> None:
    result = _run(
        _fake_agy(
            tmp_path, "print(json.dumps({'event':'init','model':'gemini-3.1-pro-high'}))\nemit()"
        )
    )
    assert result.returncode == 0 and result.stdout == REVIEW


@pytest.mark.parametrize("exit_code", [0, 7])
@pytest.mark.parametrize(
    "event",
    [
        {
            "event": "step_update",
            "step_update": {"step_type": "tool", "state": "DONE", "step_index": 1},
        },
        {
            "event": "step_update",
            "step_update": {"step_type": "subagent", "state": "DONE", "step_index": 1},
        },
        *[
            {
                "event": "step_update",
                "step_update": {
                    "step_type": "agent_response",
                    "state": "DONE",
                    "step_index": 1,
                    key: value,
                },
            }
            for key, value in [
                ("tool_info", {}),
                ("subagent_info", {}),
                ("tool_name", "run_command"),
                ("subagent_info", None),
                ("future_invocation", {}),
            ]
        ],
        {"event": "step_update"},
        {"event": "step_update", "step_update": []},
        {"event": "step_update", "step_update": {}},
        *[
            {
                "event": "step_update",
                "step_update": {
                    "step_type": "agent_response",
                    "state": "DONE",
                    "step_index": 1,
                }
                | changes,
            }
            for changes in [
                {"step_type": "future_step"},
                {"step_type": []},
                {"state": "UNKNOWN"},
                {"state": []},
                {"step_index": -1},
                {"step_index": True},
                {"step_index": "1"},
                {"text_delta": {}},
            ]
        ],
        {"event": "future_event"},
        {
            "event": "step_update",
            "subagent_info": {},
            "step_update": {
                "step_type": "checkpoint",
                "state": "DONE",
                "step_index": 2,
            },
        },
    ],
)
def test_unsupported_stream_activity_discards_valid_review(
    tmp_path: Path, event: dict, exit_code: int
) -> None:
    result = _run(
        _fake_agy(tmp_path, f"print({json.dumps(event)!r})\nemit()\nsys.exit({exit_code})")
    )
    assert result.returncode == (exit_code or 65)
    assert result.stdout == ""
    assert "tool/subagent activity or unsupported stream shape; review discarded" in result.stderr
    assert "qualify a native no-tool configuration on the same admitted route" in result.stderr


@pytest.mark.parametrize("step_type", ["user_input", "agent_response", "checkpoint"])
@pytest.mark.parametrize("state", ["ACTIVE", "DONE"])
def test_known_non_tool_steps_preserve_review(tmp_path: Path, step_type: str, state: str) -> None:
    event = {
        "event": "step_update",
        "step_update": {
            "conversation_id": "synthetic",
            "step_index": 2,
            "step_type": step_type,
            "state": state,
            "text_delta": "partial response",
            "duration_seconds": 0.1,
            "usage": {"input_tokens": 5},
        },
    }
    result = _run(_fake_agy(tmp_path, f"print({json.dumps(event)!r})\nemit()"))
    assert result.returncode == 0 and result.stdout == REVIEW


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_tool_refusal_still_screens_secrets_first(tmp_path: Path, stream: str) -> None:
    _seed_operator_token(Path(os.environ["HOME"]))
    result = _run(
        _fake_agy(
            tmp_path,
            (
                "print(json.dumps({'event': 'step_update', 'step_update': {'step_type': 'tool'}}))\n"
                f"print({FAKE_ACCESS_TOKEN!r}, file=sys.{stream})\nemit()"
            ),
        )
    )
    assert result.returncode == 65 and result.stdout == ""
    assert "seeded operator login token" in result.stderr
    assert FAKE_ACCESS_TOKEN not in result.stderr


def test_tool_refusal_cleans_owned_child(tmp_path: Path, child_record: Path) -> None:
    fake = _fake_agy(
        tmp_path,
        (
            "print(json.dumps({'event': 'step_update', 'step_update': {'step_type': 'tool'}}))\n"
            + _child_script(tmp_path)
        ),
    )
    result = _run(fake)
    assert result.returncode == 65 and result.stdout == ""
    assert not _running(int(child_record.read_text()))
    assert not Path((tmp_path / "root").read_text()).exists()


def _running(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def _child_script(
    tmp: Path, *, escape: bool = False, linger: bool = False, exit_code: int = 0
) -> str:
    return f"""
child = subprocess.Popen([sys.executable, '-c',
    'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)'],
    start_new_session={escape!r})
pathlib.Path({str(tmp / "child.start")!r}).write_text(
    pathlib.Path(f'/proc/{{child.pid}}/stat').read_text().rsplit(')', 1)[1].split()[19])
pathlib.Path({str(tmp / "root")!r}).write_text(os.getcwd())
pathlib.Path({str(tmp / "child.ready")!r}).write_text(str(child.pid))
pathlib.Path({str(tmp / "child.ready")!r}).replace({str(tmp / "child.pid")!r})
{"time.sleep(30)" if linger else "time.sleep(0.05)"}
emit()
sys.exit({exit_code})
"""


@pytest.fixture
def child_record(tmp_path: Path):
    yield tmp_path / "child.pid"
    path = tmp_path / "child.pid"
    if path.exists() and _running(int(path.read_text())):
        # Use the system Python's pidfd binding (uv Python lacks this binding).
        subprocess.run(
            [
                "/usr/bin/python3",
                "-c",
                "import os,signal,sys,pathlib; "
                "pid=int(sys.argv[1]); fd=os.pidfd_open(pid); "
                "start=pathlib.Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]; "
                "signal.pidfd_send_signal(fd,signal.SIGKILL) if start == sys.argv[2] else None; "
                "os.close(fd)",
                path.read_text(),
                (tmp_path / "child.start").read_text(),
            ],
            check=True,
        )


def _await_record(path: Path) -> int:
    deadline = time.monotonic() + 3
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    return int(path.read_text())


@pytest.mark.parametrize("exit_code", [0, 7, 124])
def test_reaps_owned_child_after_exit(tmp_path: Path, child_record: Path, exit_code: int) -> None:
    result = _run(_fake_agy(tmp_path, _child_script(tmp_path, exit_code=exit_code)))
    assert result.returncode == exit_code, result.stderr
    assert not _running(int(child_record.read_text()))


def test_timeout_kills_owned_child_and_cleans_workspace(tmp_path: Path, child_record: Path) -> None:
    result = _run(
        _fake_agy(tmp_path, _child_script(tmp_path, linger=True)), "--print-timeout", "300ms"
    )
    assert result.returncode == 124 and result.stdout == ""
    assert "owned group cleaned" in result.stderr
    assert "check route admission and retry the same pinned review" in result.stderr
    assert not _running(int(child_record.read_text()))
    assert not Path((tmp_path / "root").read_text()).exists()


@pytest.mark.parametrize(
    ("window", "sig"),
    [
        ("spawn_return", signal.SIGTERM),
        ("spawn_return", signal.SIGINT),
        ("deadline", signal.SIGTERM),
        ("deadline", signal.SIGINT),
        ("deadline_exception", None),
    ],
)
def test_launch_window_signal_cleans_live_owned_group(
    tmp_path: Path, child_record: Path, window: str, sig: int | None
) -> None:
    fake = _fake_agy(tmp_path, _child_script(tmp_path, linger=True))
    observation = tmp_path / "launch-window.json"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"""
import json, os, pathlib, runpy, signal, subprocess, time
wrapper = runpy.run_path({str(WRAPPER)!r})
native_popen, clock = subprocess.Popen, time.monotonic
processes = []
observed = {{}}
def running(pid):
    try:
        return pathlib.Path(f'/proc/{{pid}}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False
def interrupted(signum, frame):
    raise InterruptedError('injected supervisor cancellation')
for sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(sig, interrupted)
def inject():
    observed['child_live_at_signal'] = running(int(pathlib.Path({str(child_record)!r}).read_text()))
    if {window!r} == 'deadline_exception':
        raise InterruptedError('injected deadline interruption')
    os.kill(os.getpid(), {sig})
def launch(*args, **kwargs):
    proc = native_popen(*args, **kwargs)
    processes.append(proc)
    deadline = clock() + 3
    while not pathlib.Path({str(child_record)!r}).exists():
        if clock() >= deadline:
            raise RuntimeError('fake child did not start')
        time.sleep(0.01)
    if {window!r} == 'spawn_return':
        inject()  # The real spawn succeeded; assignment in _run_owned has not.
    return proc
def deadline_clock():
    if processes and {window!r}.startswith('deadline') and not observed:
        inject()  # Popen returned; the predecessor cleanup try is still unarmed.
    return clock()
subprocess.Popen, time.monotonic = launch, deadline_clock
read_fd, write_fd = os.pipe()
try:
    try:
        wrapper['_run_owned']([{str(fake)!r}], pathlib.Path({str(tmp_path)!r}), 'review', 2, read_fd)
    except InterruptedError:
        observed['interrupted'] = True
    # The leader may already be reaped while the kernel still schedules the
    # descendant's SIGKILL. Bound that observation; rescue happens only below.
    child_pid = int(pathlib.Path({str(child_record)!r}).read_text())
    deadline = clock() + 1
    while running(child_pid) and clock() < deadline:
        time.sleep(0.01)
    observed['leader_running'] = running(processes[0].pid)
    observed['child_running'] = running(child_pid)
    observed['leader_reaped'] = processes[0].returncode is not None
    observed['handlers_restored'] = all(
        signal.getsignal(sig) is interrupted for sig in (signal.SIGTERM, signal.SIGINT))
    pathlib.Path({str(observation)!r}).write_text(json.dumps(observed))
finally:
    # Preserve the observation before rescue; never leave the deliberately red
    # case's owned processes running. Keep its unreaped leader as identity proof.
    subprocess.Popen, time.monotonic = native_popen, clock
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, signal.SIG_IGN)
    for proc in processes:
        if proc.returncode is None:
            wrapper['_stop_owned_group'](proc)
    os.close(read_fd)
    os.close(write_fd)
""",
        ],
        text=True,
        capture_output=True,
        timeout=6,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(observation.read_text())
    assert observed["child_live_at_signal"] and observed["interrupted"]
    assert not observed["child_running"], observed
    assert not observed["leader_running"] and observed["leader_reaped"], observed
    assert observed["handlers_restored"]


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT, signal.SIGKILL])
def test_caller_cancellation_still_cleans_group(
    tmp_path: Path, child_record: Path, sig: int
) -> None:
    fake = _fake_agy(tmp_path, _child_script(tmp_path, linger=True))
    with subprocess.Popen(
        [str(WRAPPER), "--agy-bin", str(fake), "--print-timeout", "2s"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as proc:
        proc.stdin.write("review")
        proc.stdin.close()
        proc.stdin = None
        pid = _await_record(child_record)
        cancelled_at = time.monotonic()
        proc.send_signal(sig)
        stdout, stderr = proc.communicate(timeout=3)
        assert time.monotonic() - cancelled_at < 1.5
    assert stdout == ""
    assert (
        "hapax-agy-reviewer: caller cancelled; owned group cleaned; review discarded; "
        "inspect the caller's cancellation or timeout before retrying the same pinned review.\n"
    ) in stderr
    assert not _running(pid)
    assert not Path((tmp_path / "root").read_text()).exists()


def test_unproven_escaped_child_is_not_killed(tmp_path: Path, child_record: Path) -> None:
    result = _run(_fake_agy(tmp_path, _child_script(tmp_path, escape=True)))
    assert result.returncode == 0, result.stderr
    assert _running(int(child_record.read_text()))


def test_unrelated_process_is_not_killed(tmp_path: Path, child_record: Path) -> None:
    with subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"], start_new_session=True
    ) as unrelated:
        try:
            assert _run(_fake_agy(tmp_path, _child_script(tmp_path))).returncode == 0
            assert unrelated.poll() is None
        finally:
            unrelated.terminate()
            unrelated.wait()


def test_ownership_mismatch_never_signals(monkeypatch) -> None:
    wrapper = runpy.run_path(str(WRAPPER))

    class FakeProcess:
        pid = 99999999

    monkeypatch.setattr(os, "waitid", lambda *args: None)
    monkeypatch.setattr(os, "getpgid", lambda pid: 123)
    monkeypatch.setattr(os, "killpg", lambda *args: pytest.fail("unowned process group signalled"))
    with pytest.raises(RuntimeError, match="ownership unavailable"):
        wrapper["_stop_owned_group"](FakeProcess())


def test_session_ownership_mismatch_never_signals(monkeypatch) -> None:
    wrapper = runpy.run_path(str(WRAPPER))

    class FakeProcess:
        pid = 99999999

    monkeypatch.setattr(os, "waitid", lambda *args: None)
    monkeypatch.setattr(os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(os, "getsid", lambda pid: 123)
    monkeypatch.setattr(os, "killpg", lambda *args: pytest.fail("unowned session signalled"))
    with pytest.raises(RuntimeError, match="ownership unavailable"):
        wrapper["_stop_owned_group"](FakeProcess())


@pytest.mark.parametrize("raw", ["-1s", "NaN", "20", "infh", "1sbad"])
def test_invalid_timeout_does_not_launch(tmp_path: Path, raw: str) -> None:
    result = _run(_fake_agy(tmp_path, "raise Exception('must not run')"), f"--print-timeout={raw}")
    assert result.returncode == 64 and "invalid --print-timeout" in result.stderr


def test_timeout_keeps_zero_and_compound_duration_semantics() -> None:
    parse = runpy.run_path(str(WRAPPER))["_timeout_seconds"]
    assert parse("0") is None and parse("0s") is None
    assert parse("20m0s") == 1200
    assert parse("1h2m3.5s") == 3723.5


@pytest.mark.parametrize("raw", ["9" * 400 + "s", "1" + "0" * 305 + "h"])
def test_nonfinite_duration_is_rejected_before_launch(tmp_path: Path, raw: str) -> None:
    parse = runpy.run_path(str(WRAPPER))["_timeout_seconds"]
    with pytest.raises(ValueError, match="invalid print timeout"):
        parse(raw)
    result = _run(_fake_agy(tmp_path, "raise Exception('must not run')"), "--print-timeout", raw)
    assert result.returncode == 64 and "invalid --print-timeout" in result.stderr
    assert "must not run" not in result.stderr


def test_native_load_flags_still_match_registry() -> None:
    registry = json.loads((REPO_ROOT / "config/platform-capability-registry.json").read_text())
    route = next(row for row in registry["routes"] if row["route_id"] == "agy.review.direct")
    declared = route["native_load_set"]
    assert declared["native_home"] == ".gemini" and declared["home_env"] is None
    assert declared["loading_flags"] == [
        "--sandbox",
        "--dangerously-skip-permissions",
        "--disable-slash-commands",
    ]
    assert declared["files"] == [
        {
            "root": "native_home",
            "path": "antigravity-cli/settings.json",
            "kind": "configuration",
            "sha256": None,
            "required": False,
        }
    ]
    assert "scripts/hapax-agy-reviewer" in declared["source_refs"]


@pytest.mark.parametrize("malformed_yaml", [False, True])
def test_native_response_retains_actual_caller_parse_contract(
    tmp_path: Path, malformed_yaml: bool
) -> None:
    spec = importlib.util.spec_from_file_location(
        "_agy_dispatch_contract", REPO_ROOT / "scripts/cc-pr-review-dispatch.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    body = "emit(REVIEW.replace('checklist: {}', 'checklist: []'))" if malformed_yaml else "emit()"
    result = _run(_fake_agy(tmp_path, body))
    assert result.returncode == 0, result.stderr
    parsed = module.extract_review(result.stdout)
    if malformed_yaml:
        assert parsed is None
    else:
        assert parsed == {
            "verdict": "accept",
            "findings": [],
            "checklist": {},
            "parse_path": "fence",
        }


@pytest.mark.parametrize("location", ["detail", "key"])
@pytest.mark.parametrize("encoding", ["unicode", "hex", "long_unicode", "continuation"])
def test_semantic_yaml_token_never_reaches_actual_caller(
    tmp_path: Path, location: str, encoding: str
) -> None:
    _seed_operator_token(Path(os.environ["HOME"]))
    spec = importlib.util.spec_from_file_location(
        "_agy_semantic_contract", REPO_ROOT / "scripts/cc-pr-review-dispatch.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    secret = FAKE_ACCESS_TOKEN
    if encoding == "continuation":
        encoded = secret[:12] + "\\\n    " + secret[12:]
    else:
        code = {"unicode": "u%04x", "hex": "x%02x", "long_unicode": "U%08x"}[encoding]
        encoded = "".join("\\" + code % ord(char) for char in secret)
    scalar = '"' + encoded + '"'
    finding = "detail: " + scalar if location == "detail" else scalar + ": safe"
    if location == "key" and encoding == "continuation":
        finding = "? " + scalar + "\n    : safe"
    response = REVIEW.replace("findings: []", "findings:\n  - " + finding)
    # Establish that the real consumer reconstructs the token from this payload;
    # do not mock the parser or claim rejection solely from a raw substring test.
    parsed = module.extract_review(response)
    assert parsed is not None
    assert secret in str(parsed["findings"])
    result = _run(_fake_agy(tmp_path, f"emit({response!r})"))
    forwarded = module.extract_review(result.stdout)
    assert forwarded is None or secret not in str(forwarded)
    assert result.returncode == 65
    assert result.stdout == ""
    assert "echoed the seeded operator login token" in result.stderr
    assert secret not in result.stderr


@pytest.mark.parametrize("exit_code", [0, 7])
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_nested_json_diagnostic_token_discards_both_streams(
    tmp_path: Path, stream: str, exit_code: int
) -> None:
    _seed_operator_token(Path(os.environ["HOME"]))
    encoded = "".join(f"\\u{ord(char):04x}" for char in FAKE_REFRESH_TOKEN)
    diagnostic = "native error: " + json.dumps({"detail": encoded})
    result = _run(
        _fake_agy(
            tmp_path,
            f"emit()\nprint({diagnostic!r}, file=sys.{stream})\nsys.exit({exit_code})",
        )
    )
    assert result.returncode == 65
    assert result.stdout == ""
    assert "echoed the seeded operator login token" in result.stderr
    assert "native error" not in result.stderr


def test_semantic_binary_token_is_not_forwarded(tmp_path: Path) -> None:
    import base64

    _seed_operator_token(Path(os.environ["HOME"]))
    encoded = base64.b64encode(FAKE_ACCESS_TOKEN.encode()).decode()
    response = REVIEW.replace("findings: []", f"findings: [{{detail: !!binary {encoded}}}]")
    result = _run(_fake_agy(tmp_path, f"emit({response!r})"))
    assert result.returncode == 65
    assert result.stdout == ""
    assert "echoed the seeded operator login token" in result.stderr


def test_malformed_yaml_cannot_bypass_semantic_screen(tmp_path: Path) -> None:
    _seed_operator_token(Path(os.environ["HOME"]))
    response = REVIEW.replace("findings: []", "findings: [unterminated")
    result = _run(_fake_agy(tmp_path, f"emit({response!r})"))
    assert result.returncode == 65
    assert result.stdout == ""
    assert "malformed or unsuccessful stream result" in result.stderr


def test_clean_yaml_aliases_and_escapes_preserve_response(tmp_path: Path) -> None:
    _seed_operator_token(Path(os.environ["HOME"]))
    response = REVIEW.replace(
        "findings: []",
        'findings: [&finding {detail: "ordinary \\u0074ext", related: *finding}]',
    )
    result = _run(_fake_agy(tmp_path, f"emit({response!r})"))
    assert result.returncode == 0
    assert result.stdout == response

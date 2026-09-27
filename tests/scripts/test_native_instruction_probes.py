"""Controlled clients exercise manual probes without native accounts or Docker."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_probe(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def client(tmp_path, body):
    path = tmp_path / "controlled-client"
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    path.chmod(0o700)
    return path


@pytest.fixture
def processes(monkeypatch):
    """Own real children; shorten waits only at the external-client boundary."""
    owned = []
    original = subprocess.Popen

    def install(module, translate):
        def spawn(command, *args, **kwargs):
            replacement = translate(command)
            process = original(replacement or command, *args, **kwargs)
            if replacement is not None:
                owned.append(process)
                wait = process.wait
                communicate = process.communicate
                process.wait = lambda timeout=None: wait(
                    timeout=min(timeout, 0.5) if timeout is not None else None
                )

                def bounded_communicate(input=None, timeout=None):
                    return communicate(
                        input, timeout=min(timeout, 0.5) if timeout is not None else None
                    )

                process.communicate = bounded_communicate
            return process

        monkeypatch.setattr(module.subprocess, "Popen", spawn)
        monkeypatch.setattr(
            module,
            "time",
            SimpleNamespace(monotonic=lambda: time.monotonic() * 10, sleep=time.sleep),
        )
        return owned

    yield install
    # Test cleanup is independent of the probe's cleanup, including failing cases.
    for process in owned:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)


@pytest.fixture
def instruction_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "AGENTS.md").write_text("Controlled project instruction.\n")
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "AGENTS.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Probe fixture",
            "-c",
            "user.email=probe@example.invalid",
            "commit",
            "--no-gpg-sign",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    return source


@pytest.mark.parametrize("mode", ["valid", "eof", "malformed", "timeout"])
def test_claude_entrypoint_receipts_failures_and_owned_cleanup(
    tmp_path, monkeypatch, processes, instruction_source, mode
):
    probe = load_probe("probe-claude-instruction-binding")
    binary = client(
        tmp_path,
        f"MODE = {mode!r}\n"
        + textwrap.dedent("""
        import json, os, shlex, subprocess, sys, time
        from pathlib import Path
        if "--version" in sys.argv:
            print("controlled-client-1")
            raise SystemExit(0)
        request = json.loads(sys.stdin.readline())
        assert request["request"]["subtype"] == "initialize"
        assert "ANTHROPIC_API_KEY" not in os.environ
        print("controlled initialization", flush=True)
        print("controlled stderr", file=sys.stderr, flush=True)
        settings = json.loads(Path(sys.argv[sys.argv.index("--settings") + 1]).read_text())
        hook = shlex.split(settings["hooks"]["InstructionsLoaded"][0]["hooks"][0]["command"])
        project = Path.cwd() if (Path.cwd() / "CLAUDE.md").exists() else Path.cwd().parent
        if MODE == "malformed":
            Path(hook[-1]).write_text("{broken-json\\n")
        elif MODE != "eof":
            event = {"memory_type": "Project", "file_path": str(project / "CLAUDE.md"),
                     "load_reason": "session_start", "hook_event_name": "InstructionsLoaded"}
            subprocess.run(hook, input=json.dumps(event), text=True, check=True)
        if MODE == "timeout":
            while True: time.sleep(1)
        if MODE != "eof": sys.stdin.read()
    """),
    )
    owned = processes(probe, lambda command: command if command[0] == str(binary) else None)
    output = tmp_path / "evidence"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-only-canary")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "probe",
            "--claude",
            str(binary),
            "--instructions",
            str(instruction_source / "AGENTS.md"),
            "--output-dir",
            str(output),
        ],
    )
    if mode in {"valid", "eof"}:
        assert probe.main() == (0 if mode == "valid" else 1)
        summary = json.loads((output / "summary.json").read_text())
        assert len(summary["cells"]) == 2
        assert all(cell["passed"] is (mode == "valid") for cell in summary["cells"])
        assert summary["user_turns"] == 0
    else:
        with pytest.raises(
            json.JSONDecodeError if mode == "malformed" else subprocess.TimeoutExpired
        ):
            probe.main()
    assert "controlled initialization" in (output / "root-stdout.jsonl").read_text()
    assert "controlled stderr" in (output / "root-stderr.log").read_text()
    assert owned and all(process.poll() is not None for process in owned)


FOREIGN_CLIENT = """
import json, os, signal, sys, time, tomllib
from pathlib import Path
mode = sys.argv[1]
if mode == "hang":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    print("owned hung client", flush=True)
    while True: time.sleep(1)
home, project = Path(os.environ["HOME"]), Path.cwd()
assert "ANTHROPIC_API_KEY" not in os.environ
if "inspect" in sys.argv:
    if mode == "malformed":
        print("{malformed receipt")
    else:
        enabled = tomllib.loads((home / ".grok/config.toml").read_text())["compat"]["claude"]["agents"]
        paths = [home / ".grok/AGENTS.md", project / "AGENTS.md", project / "CLAUDE.md"]
        paths += ([home / ".claude/CLAUDE.md", project / ".claude/CLAUDE.md"] if enabled
                  else [home / ".claude/rules/unique.md"])
        print(json.dumps({"grokVersion": "fixture", "projectTrusted": True,
                          "projectInstructions": [{"path": str(p)} for p in paths]}))
    raise SystemExit(0)
if mode == "missing-prompt":
    print("no prompt here", flush=True)
    raise SystemExit(0)
print("\\x1b[32m❯ echo\\x1b[0m", flush=True)
for line in sys.stdin:
    if line.strip() == "/exit": break
    if line.strip() == "/rules":
        print("Rules loaded this session (in precedence order):", flush=True)
        print("user: $CONFIG_DIR/AGENTS.md\\nproject: none", flush=True)
        for vendor, relative in [("Claude Code", ".claude/CLAUDE.md"), ("Codex", ".codex/AGENTS.md")]:
            print(f"{vendor} rules at {home}/{relative} — not read;", flush=True)
"""


@pytest.mark.parametrize("mode", ["valid", "malformed", "missing-prompt"])
def test_foreign_entrypoint_parsing_and_pty_cleanup(tmp_path, monkeypatch, processes, mode):
    probe = load_probe("probe-native-foreign-instructions")
    binary = str(Path(shutil.which("true")).resolve())
    controlled = client(tmp_path, FOREIGN_CLIENT)
    owned = processes(
        probe,
        lambda command: (
            [str(controlled), mode, *command[1:]]
            if str(Path(command[0]).resolve()) == binary
            else None
        ),
    )
    output = tmp_path / "evidence"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-only-canary")
    monkeypatch.setattr(
        sys, "argv", ["probe", "--grok", binary, "--muse", binary, "--output-dir", str(output)]
    )
    assert probe.main() == (0 if mode == "valid" else 1)
    summary = json.loads((output / "summary.json").read_text())
    assert len(summary["cells"]) == 4
    assert summary["may_authorize"] is False
    failed = [c for c in summary["cells"] if c["status"] != "observed"]
    assert len(failed) == (0 if mode == "valid" else 2)
    assert all("inspect raw_logs" in c["error"] for c in failed)
    assert all(Path(path).is_file() for c in summary["cells"] for path in c["raw_logs"])
    assert owned and all(process.poll() is not None for process in owned)


def test_foreign_timeout_forces_owned_child_exit_and_retains_logs(tmp_path, processes):
    probe = load_probe("probe-native-foreign-instructions")
    controlled = client(tmp_path, FOREIGN_CLIENT)
    owned = processes(probe, lambda command: command if command[0] == str(controlled) else None)
    prefix = tmp_path / "hung"
    with pytest.raises(subprocess.TimeoutExpired):
        probe.run([str(controlled), "hang"], tmp_path, {"PATH": os.defpath}, prefix)
    assert "owned hung client" in prefix.with_suffix(".stdout").read_text()
    assert prefix.with_suffix(".stderr").is_file()
    assert len(owned) == 1 and owned[0].returncode == -9


def test_foreign_wrapper_rejected_before_fixture_mutation(tmp_path, monkeypatch):
    probe = load_probe("probe-native-foreign-instructions")
    wrapper = client(tmp_path, "raise SystemExit(0)\n")
    output = tmp_path / "evidence"
    monkeypatch.setattr(
        sys,
        "argv",
        ["probe", "--grok", str(wrapper), "--muse", str(wrapper), "--output-dir", str(output)],
    )
    with pytest.raises(SystemExit) as error:
        probe.main()
    assert error.value.code == 2
    assert not output.exists()


RPC_CLIENT = """
import json, sys, time
mode = sys.argv[1]
print("controlled RPC stderr", file=sys.stderr, flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request: continue
    if mode == "eof": break
    if mode == "timeout": continue
    if mode == "malformed":
        print("{bad-json", flush=True)
        continue
    result = {"thread": {"id": "controlled-thread"},
              "instructionSources": ["global", "project"]}
    print(json.dumps({"id": request["id"], "result": result}), flush=True)
if mode == "forced-stop":
    while True: time.sleep(1)
"""


@pytest.mark.parametrize("mode", ["valid", "malformed", "eof", "timeout", "forced-stop"])
def test_container_codex_rpc_failures_and_owned_cleanup(tmp_path, monkeypatch, processes, mode):
    probe = load_probe("probe-native-harness-container")
    controlled = client(tmp_path, RPC_CLIENT)
    commands = []

    def translate(command):
        if command[0] == "docker":
            commands.append(command)
            return [str(controlled), mode]
        return None

    owned = processes(probe, translate)
    stopped = []

    def stop(command, **kwargs):
        assert command[:4] == ["docker", "stop", "-t", "1"]
        assert command[-1] == commands[0][commands[0].index("--name") + 1]
        stopped.append(command[-1])
        owned[0].terminate()
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(probe, "run", stop)
    project = tmp_path / "project"
    project.mkdir()
    evidence = tmp_path / "evidence"

    def invoke():
        return probe.codex("sha256:" + "1" * 64, project, tmp_path / "state", evidence)

    if mode == "valid":
        assert invoke()["result"]["thread"]["id"] == "controlled-thread"
    else:
        expected = {
            "malformed": json.JSONDecodeError,
            "eof": RuntimeError,
            "timeout": TimeoutError,
            "forced-stop": RuntimeError,
        }[mode]
        with pytest.raises(expected):
            invoke()
    assert len(owned) == 1 and owned[0].poll() is not None
    assert "controlled RPC stderr" in (evidence / "stderr.log").read_text()
    assert (evidence / "stdout.jsonl").is_file()
    if mode == "malformed":
        assert "{bad-json" in (evidence / "stdout.jsonl").read_text()
    assert bool(stopped) is (mode == "forced-stop")
    assert "--read-only" in commands[0] and "--network=none" in commands[0]


@pytest.mark.parametrize("mode", ["valid", "malformed", "eof", "forced-stop"])
def test_container_claude_receipts_and_owned_cleanup(tmp_path, monkeypatch, processes, mode):
    probe = load_probe("probe-native-harness-container")
    controlled = client(
        tmp_path,
        """
        import json, sys, time
        from pathlib import Path
        mode, evidence = sys.argv[1], Path(sys.argv[2])
        assert json.loads(sys.stdin.readline())["request"]["subtype"] == "initialize"
        print("controlled Claude output", flush=True)
        if mode == "malformed":
            (evidence / "loaded.jsonl").write_text("{bad-json\\n{bad-json\\n")
        elif mode != "eof":
            events = [{"file_path": p, "sha256": "fixture"} for p in
                      ["/opt/hapax-agent/.claude/CLAUDE.md", "/work/CLAUDE.md"]]
            (evidence / "loaded.jsonl").write_text("".join(json.dumps(e) + "\\n" for e in events))
        if mode != "eof": sys.stdin.read()
        if mode == "forced-stop":
            while True: time.sleep(1)
    """,
    )
    evidence = tmp_path / "evidence"
    commands = []

    def translate(command):
        commands.append(command)
        return [str(controlled), mode, str(evidence)]

    owned = processes(probe, translate)
    stopped = []

    def stop(command, **kwargs):
        assert command[:4] == ["docker", "stop", "-t", "1"]
        assert command[-1] == commands[0][commands[0].index("--name") + 1]
        stopped.append(command[-1])
        owned[0].terminate()
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(probe, "run", stop)
    if mode == "valid":
        events = probe.claude("sha256:" + "1" * 64, tmp_path, evidence, "/work")
        assert [e["file_path"] for e in events] == [
            "/opt/hapax-agent/.claude/CLAUDE.md",
            "/work/CLAUDE.md",
        ]
    else:
        expected = {
            "malformed": json.JSONDecodeError,
            "eof": FileNotFoundError,
            "forced-stop": RuntimeError,
        }[mode]
        with pytest.raises(expected):
            probe.claude("sha256:" + "1" * 64, tmp_path, evidence, "/work")
    assert len(owned) == 1 and owned[0].poll() is not None
    assert "controlled Claude output" in (evidence / "stdout.jsonl").read_text()
    assert (evidence / "stderr.log").is_file()
    assert bool(stopped) is (mode == "forced-stop")


@pytest.mark.parametrize("name", ["claude", "foreign", "container"])
def test_entrypoints_refuse_existing_output_without_overwriting(
    tmp_path, monkeypatch, instruction_source, name
):
    output = tmp_path / "evidence"
    output.mkdir()
    sentinel = output / "retained"
    sentinel.write_bytes(b"prior evidence")
    binary = str(Path(shutil.which("true")).resolve())
    if name == "claude":
        probe = load_probe("probe-claude-instruction-binding")
        args = ["--claude", binary, "--instructions", str(instruction_source / "AGENTS.md")]
    elif name == "foreign":
        probe = load_probe("probe-native-foreign-instructions")
        args = ["--grok", binary, "--muse", binary]
    else:
        probe = load_probe("probe-native-harness-container")
        args = [
            "--source",
            str(instruction_source),
            "--source-revision",
            "HEAD",
            "--claude-image",
            "unused",
            "--codex-image",
            "unused",
        ]
    monkeypatch.setattr(sys, "argv", ["probe", *args, "--output-dir", str(output)])
    with pytest.raises(FileExistsError):
        probe.main()
    assert list(output.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"prior evidence"


def test_container_entrypoint_rejects_mutable_image_before_launch(
    tmp_path, monkeypatch, instruction_source
):
    probe = load_probe("probe-native-harness-container")
    native_run = probe.run
    calls = []

    def inspect_only(command, **kwargs):
        if command[0] != "docker":
            return native_run(command, **kwargs)
        calls.append(command)
        assert command[:3] == ["docker", "image", "inspect"]
        return subprocess.CompletedProcess(command, 0, "sha256:" + "1" * 64 + "\n", "")

    monkeypatch.setattr(probe, "run", inspect_only)
    output = tmp_path / "evidence"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "probe",
            "--source",
            str(instruction_source),
            "--source-revision",
            "HEAD",
            "--claude-image",
            "mutable-tag",
            "--codex-image",
            "unused",
            "--output-dir",
            str(output),
        ],
    )
    with pytest.raises(ValueError, match="immutable image"):
        probe.main()
    assert len(calls) == 1
    assert not (output / "summary.json").exists()

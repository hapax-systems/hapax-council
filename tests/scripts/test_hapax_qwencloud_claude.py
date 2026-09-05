"""scripts/hapax-qwencloud-claude — Claude Code as the plan's listed client, key never on disk or argv."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "hapax-qwencloud-claude"
OFFICIAL = "https://token-plan.ap-southeast-1.maas.aliyuncs.com/apps/anthropic"
FAKE_KEY = "fixture-plan-key-0000"  # pragma: allowlist secret
_SECURE_CLIENT_LAUNCH = """        result = subprocess.run(
            ["claude", *claude_args],
            env=client_env,
            check=False,
        )
"""


def _mutate_credential_into_env_argv(source: str) -> str:
    insecure_launch = """        result = subprocess.run(
            [
                "env",
                "-i",
                *[f"{name}={value}" for name, value in client_env.items()],
                "claude",
                *claude_args,
            ],
            env=client_env,
            check=False,
        )
"""
    assert _SECURE_CLIENT_LAUNCH in source
    return source.replace(_SECURE_CLIENT_LAUNCH, insecure_launch, 1)


REGISTERED_MUTATIONS = {
    "credential-in-env-argv": _mutate_credential_into_env_argv,
}


@pytest.fixture
def bench(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A PATH with a fake `claude` that records its argv and environment, and a fake `hapax-secret`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "claude-seen.json"
    (bin_dir / "claude").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "parent_argv = open(f'/proc/{os.getppid()}/cmdline', 'rb').read().rstrip(b'\\0').split(b'\\0')\n"
        "parent_argv = [part.decode(errors='replace') for part in parent_argv]\n"
        f"json.dump({{'argv': sys.argv[1:], 'parent_argv': parent_argv, 'env': dict(os.environ)}}, open({str(record)!r}, 'w'))\n"
        "print(json.dumps({'result': 'OK', 'modelUsage': {os.environ.get('ANTHROPIC_MODEL', '?'): {}}}))\n",
        encoding="utf-8",
    )
    (bin_dir / "claude").chmod(0o755)
    (bin_dir / "hapax-secret").write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "--where" ]; then echo filestore; exit 0; fi\n'
        'if [ "$1" = "qwencloud/apikey" ]; then echo "fixture-plan-key-0000"; exit 0; fi\n'
        "exit 1\n",
        encoding="utf-8",
    )
    (bin_dir / "hapax-secret").chmod(0o755)
    argv_spy = record.with_name("env-argv.json")
    (bin_dir / "env").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"json.dump(sys.argv[1:], open({str(argv_spy)!r}, 'w'))\n"
        "os.execv('/usr/bin/env', ['env', *sys.argv[1:]])\n",
        encoding="utf-8",
    )
    (bin_dir / "env").chmod(0o755)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path / "real-home"),
        "TMPDIR": str(tmp_path / "tmp"),
    }
    (tmp_path / "real-home").mkdir()
    (tmp_path / "tmp").mkdir()
    return record, env


def _run_wrapper(
    wrapper: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(wrapper), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return _run_wrapper(WRAPPER, env, *args)


def _assert_no_credential_in_process_argv(record: Path) -> None:
    seen = json.loads(record.read_text())
    observed_argv = [seen["argv"], seen["parent_argv"]]
    argv_spy = record.with_name("env-argv.json")
    if argv_spy.exists():
        observed_argv.append(json.loads(argv_spy.read_text()))
    if any(FAKE_KEY in argument for argv in observed_argv for argument in argv):
        raise AssertionError("credential appeared in a wrapper child process argument vector")


def test_the_client_runs_isolated_with_the_key_only_in_its_environment(bench) -> None:
    record, env = bench

    proc = _run(env, "-p", "Reply with exactly: OK", "--output-format", "json")

    assert proc.returncode == 0, proc.stderr
    seen = json.loads(record.read_text())
    assert seen["argv"] == ["-p", "Reply with exactly: OK", "--output-format", "json"]
    assert seen["env"]["ANTHROPIC_BASE_URL"] == OFFICIAL
    assert seen["env"]["ANTHROPIC_AUTH_TOKEN"] == "fixture-plan-key-0000"
    assert seen["env"]["ANTHROPIC_MODEL"] == "qwen3.7-plus"
    assert seen["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "qwen3.7-plus"
    assert seen["env"]["HOME"] != env["HOME"], "the client must not see the real HOME"
    assert not Path(seen["env"]["HOME"]).exists(), "the isolated HOME is removed after the run"
    assert "fixture-plan-key" not in " ".join(seen["argv"])
    assert "fixture-plan-key" not in proc.stderr
    assert "TMPDIR" not in seen["env"] or seen["env"].get("TMPDIR") != env["TMPDIR"]
    assert json.loads(proc.stdout)["result"] == "OK"


def test_the_key_never_appears_in_wrapper_or_intermediate_process_argv(bench) -> None:
    record, env = bench

    proc = _run(env, "-p", "x")

    assert proc.returncode == 0, proc.stderr
    assert json.loads(record.read_text())["env"]["ANTHROPIC_AUTH_TOKEN"] == FAKE_KEY
    _assert_no_credential_in_process_argv(record)


def test_registered_credential_argv_mutation_turns_the_regression_red(
    bench, tmp_path: Path
) -> None:
    record, env = bench
    mutant = tmp_path / "hapax-qwencloud-claude-mutant"
    source = WRAPPER.read_text(encoding="utf-8")
    mutant.write_text(REGISTERED_MUTATIONS["credential-in-env-argv"](source), encoding="utf-8")
    mutant.chmod(0o755)

    proc = _run_wrapper(mutant, env, "-p", "x")

    assert proc.returncode == 0, proc.stderr
    assert json.loads(record.read_text())["env"]["ANTHROPIC_AUTH_TOKEN"] == FAKE_KEY
    with pytest.raises(
        AssertionError, match="credential appeared in a wrapper child process argument vector"
    ):
        _assert_no_credential_in_process_argv(record)


def test_check_reports_without_reading_the_key(bench) -> None:
    record, env = bench

    proc = _run(env, "--check")

    assert proc.returncode == 0, proc.stderr
    assert "endpoint " + OFFICIAL in proc.stdout and "qwen3.7-plus" in proc.stdout
    if record.exists():  # the version probe is the only client call --check may make
        seen = json.loads(record.read_text())
        assert seen["argv"] == ["--version"]
        assert "ANTHROPIC_AUTH_TOKEN" not in seen["env"] and "ANTHROPIC_BASE_URL" not in seen["env"]


def test_base_url_and_model_overrides_are_refused_unless_reviewed(bench) -> None:
    record, env = bench

    proc = _run(
        {**env, "HAPAX_QWENCLOUD_ANTHROPIC_BASE_URL": "https://evil.example/anthropic"}, "-p", "x"
    )
    assert proc.returncode == 2 and "refusing base URL" in proc.stderr
    assert not record.exists()

    proc = _run({**env, "HAPAX_QWENCLOUD_MODEL": "gpt-oss-120b"}, "-p", "x")
    assert proc.returncode == 2 and "not in the plan's documented catalogue" in proc.stderr
    assert not record.exists()

    proc = _run({**env, "HAPAX_QWENCLOUD_MODEL": "qwen3-coder-plus"}, "-p", "x")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(record.read_text())["env"]["ANTHROPIC_MODEL"] == "qwen3-coder-plus"


def test_missing_secret_or_client_names_the_remedy(bench, tmp_path: Path) -> None:
    record, env = bench
    (tmp_path / "bin" / "hapax-secret").write_text(
        "#!/usr/bin/env bash\nexit 1\n", encoding="utf-8"
    )

    proc = _run(env, "-p", "x")

    assert proc.returncode == 4 and "store the plan's sk-sp- key" in proc.stderr
    assert not record.exists()


@pytest.mark.parametrize("outcome", [7, -15], ids=["nonzero", "signal"])
def test_client_failure_exit_is_propagated_and_home_removed(bench, tmp_path, outcome):
    record, env = bench
    client = tmp_path / "bin" / "claude"
    client.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, signal, sys\n"
        f"with open({str(record)!r}, 'w') as fh:\n"
        "    json.dump({'home': os.environ['HOME']}, fh)\n"
        + (f"sys.exit({outcome})\n" if outcome >= 0 else "os.kill(os.getpid(), signal.SIGTERM)\n")
    )
    proc = _run(env, "-p", "synthetic brief")
    assert proc.returncode == (outcome if outcome >= 0 else 128 - outcome)
    isolated_home = Path(json.loads(record.read_text())["home"])
    assert isolated_home != Path(env["HOME"])
    assert not isolated_home.exists()
    assert list(Path(env["TMPDIR"]).iterdir()) == []
    assert FAKE_KEY not in proc.stdout + proc.stderr


def test_client_launch_failure_removes_isolated_home(bench, tmp_path):
    record, env = bench
    # execvp can skip a missing interpreter and fall through to another PATH
    # entry. Keep this failure fixture confined to its synthetic binaries.
    env["PATH"] = str(tmp_path / "bin")
    (tmp_path / "bin" / "python3").symlink_to(sys.executable)
    (tmp_path / "bin" / "bash").symlink_to("/bin/bash")
    # Discovery succeeds; exec then fails because this synthetic interpreter is absent.
    (tmp_path / "bin" / "claude").write_text(f"#!{tmp_path}/missing-interpreter\n")
    proc = _run(env, "-p", "synthetic brief")
    assert proc.returncode != 0
    assert not record.exists()
    assert list(Path(env["TMPDIR"]).iterdir()) == []
    assert FAKE_KEY not in proc.stdout + proc.stderr


@pytest.mark.parametrize("args", [["-p", "synthetic brief"], ["--check"]], ids=["run", "check"])
def test_client_startup_failure_names_remedy_and_cleans_home(bench, tmp_path, args):
    record, env = bench
    env["PATH"] = str(tmp_path / "bin")
    (tmp_path / "bin" / "python3").symlink_to(sys.executable)
    (tmp_path / "bin" / "bash").symlink_to("/bin/bash")
    (tmp_path / "bin" / "claude").write_text(f"#!{tmp_path}/missing-interpreter\n")
    proc = _run(env, *args)
    assert not record.exists()
    assert list(Path(env["TMPDIR"]).iterdir()) == []
    assert proc.stdout == "" and FAKE_KEY not in proc.stderr
    assert proc.returncode == 3
    assert len(proc.stderr.splitlines()) == 1
    assert "claude" in proc.stderr and "PATH" in proc.stderr
    assert "install" in proc.stderr and "retry" in proc.stderr


@pytest.mark.parametrize("failure", [FileNotFoundError, PermissionError, OSError])
def test_temporary_home_failure_names_remedy_without_launch(
    fake_boundary, monkeypatch, capsys, failure
):
    module, calls, removed = fake_boundary

    def fail_mkdtemp(**kwargs):
        raise failure(FAKE_KEY)

    monkeypatch.setattr(module.tempfile, "mkdtemp", fail_mkdtemp)
    try:
        rc = module.main(["-p", "synthetic brief"])
    except OSError:
        rc = None  # An uncaught startup error becomes a standalone traceback.
    captured = capsys.readouterr()
    assert rc == 3
    assert all(argv[0] == "hapax-secret" for argv, _ in calls)
    assert removed == []
    assert captured.out == "" and FAKE_KEY not in captured.err
    assert len(captured.err.splitlines()) == 1
    assert "temporary directory" in captured.err and "TMPDIR" in captured.err
    assert "writable" in captured.err and "retry" in captured.err


@pytest.mark.parametrize("failure", [FileNotFoundError, PermissionError, OSError])
@pytest.mark.parametrize("args", [["-p", "synthetic brief"], ["--check"]], ids=["run", "check"])
def test_discovered_client_launch_error_names_remedy_and_cleans_home(
    fake_boundary, monkeypatch, capsys, failure, args
):
    module, calls, removed = fake_boundary
    original_run = module.subprocess.run

    def fail_client(argv, **kwargs):
        if argv[0] == "claude":
            raise failure(FAKE_KEY)
        return original_run(argv, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", fail_client)
    try:
        rc = module.main(args)
    except OSError:
        rc = None  # Do not copy even a synthetic credential into assertion output.
    captured = capsys.readouterr()
    assert removed == ([] if args == ["--check"] else ["/synthetic/isolation"])
    assert rc == 3
    assert captured.out == "" and FAKE_KEY not in captured.err
    assert len(captured.err.splitlines()) == 1
    assert "claude" in captured.err and "PATH" in captured.err
    assert "install" in captured.err and "retry" in captured.err


@pytest.mark.parametrize("args", [["-p", "synthetic brief"], ["--check"]], ids=["run", "check"])
def test_missing_client_names_install_remedy(fake_boundary, monkeypatch, capsys, args):
    module, calls, removed = fake_boundary
    monkeypatch.setattr(module.shutil, "which", lambda name: None if name == "claude" else name)
    assert module.main(args) == 3
    captured = capsys.readouterr()
    assert "claude is not on PATH" in captured.err
    assert "install Claude Code, then retry" in captured.err
    assert captured.out == "" and calls == [] and removed == []


@pytest.mark.parametrize("stage", ["where", "read"])
def test_secret_helper_missing_interpreter_names_remedy(bench, tmp_path, stage):
    record, env = bench
    env["PATH"] = str(tmp_path / "bin")
    (tmp_path / "bin" / "python3").symlink_to(sys.executable)
    helper = tmp_path / "bin" / "hapax-secret"
    broken = f"#!{tmp_path}/missing-interpreter\n"
    helper.write_text(
        broken
        if stage == "where"
        else (
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            "assert sys.argv[1] == '--where'\n"
            f"pathlib.Path(__file__).write_text({broken!r})\n"
            "print('filestore')\n"
        )
    )
    proc = _run(env, "-p", "synthetic brief")
    assert proc.returncode == 3
    assert len(proc.stderr.splitlines()) == 1
    assert "hapax-secret" in proc.stderr and "PATH" in proc.stderr
    assert "interpreter" in proc.stderr and "retry" in proc.stderr
    assert proc.stdout == "" and FAKE_KEY not in proc.stderr
    assert not record.exists() and list(Path(env["TMPDIR"]).iterdir()) == []


@pytest.mark.parametrize("failure", [FileNotFoundError, PermissionError, OSError])
@pytest.mark.parametrize("stage", ["where-run", "where-check", "read"])
def test_secret_helper_launch_error_names_remedy(
    fake_boundary, monkeypatch, capsys, failure, stage
):
    module, calls, removed = fake_boundary
    original_run = module.subprocess.run

    def fail_helper(argv, **kwargs):
        if argv[0] == "hapax-secret" and (("--where" in argv) == stage.startswith("where")):
            raise failure(FAKE_KEY)
        return original_run(argv, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", fail_helper)
    try:
        rc = module.main(["--check"] if stage == "where-check" else ["-p", "synthetic brief"])
    except OSError:
        rc = None  # Keep even synthetic exception credentials out of assertion output.
    captured = capsys.readouterr()
    assert rc == 3, "helper launch escaped without a recovery action"
    assert captured.out == "" and FAKE_KEY not in captured.err
    assert len(captured.err.splitlines()) == 1
    assert "hapax-secret" in captured.err and "PATH" in captured.err
    assert "interpreter" in captured.err and "permissions" in captured.err
    assert "retry" in captured.err
    assert all(argv[0] == "hapax-secret" for argv, _ in calls) and removed == []


@pytest.mark.parametrize("outcome", [FileNotFoundError, PermissionError, OSError, 7, -15])
def test_check_negative_branches_directly(fake_boundary, monkeypatch, capsys, outcome):
    module, calls, removed = fake_boundary
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", FAKE_KEY)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://synthetic.example/anthropic")

    def probe(argv, **kwargs):
        calls.append(argv)
        assert argv == ["claude", "--version"]
        assert "ANTHROPIC_AUTH_TOKEN" not in kwargs["env"]
        assert "ANTHROPIC_BASE_URL" not in kwargs["env"]
        assert kwargs["stderr"] == subprocess.DEVNULL
        if isinstance(outcome, type):
            raise outcome(FAKE_KEY)
        return subprocess.CompletedProcess(argv, outcome, FAKE_KEY)

    monkeypatch.setattr(module.subprocess, "run", probe)
    try:
        rc = module._check(module.OFFICIAL_BASE_URL, module.DEFAULT_MODEL)
    except OSError:
        rc = None
    captured = capsys.readouterr()
    expected = 3 if isinstance(outcome, type) else outcome if outcome >= 0 else 128 - outcome
    assert rc == expected
    assert captured.out == "" and FAKE_KEY not in captured.err
    assert len(captured.err.splitlines()) == 1
    assert "claude" in captured.err and "PATH" in captured.err and "retry" in captured.err
    assert calls == [["claude", "--version"]] and removed == []


@pytest.mark.parametrize("probe_exit", [127, 1])
def test_check_propagates_failed_client_probe_with_remedy(bench, tmp_path, probe_exit):
    record, env = bench
    (tmp_path / "bin" / "claude").write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "assert sys.argv[1:] == ['--version']\n"
        "print('SYNTHETIC_PROBE_OUTPUT')\n"
        "print('SYNTHETIC_PROBE_ERROR', file=sys.stderr)\n"
        f"sys.exit({probe_exit})\n"
    )
    proc = _run(env, "--check")
    assert proc.returncode == probe_exit
    assert "ok — client" not in proc.stdout
    assert "claude --version" in proc.stderr
    assert str(probe_exit) in proc.stderr
    assert "install Claude Code" in proc.stderr and "PATH" in proc.stderr
    assert "SYNTHETIC_PROBE" not in proc.stdout + proc.stderr
    assert FAKE_KEY not in proc.stdout + proc.stderr
    assert not record.exists()


@pytest.fixture
def fake_boundary(monkeypatch):
    module = ModuleType("qwencloud_under_test")
    exec(compile(WRAPPER.read_text(), str(WRAPPER), "exec"), module.__dict__)
    for name in tuple(os.environ):
        if name.startswith("HAPAX_QWENCLOUD_"):
            monkeypatch.delenv(name)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/synthetic/bin/{name}")
    monkeypatch.setattr(module.tempfile, "mkdtemp", lambda **kw: "/synthetic/isolation")
    removed = []
    monkeypatch.setattr(module.shutil, "rmtree", removed.append)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv == ["hapax-secret", "--where", module.SECRET_NAME]:
            return subprocess.CompletedProcess(argv, 0, "filestore\n")
        if argv == ["hapax-secret", module.SECRET_NAME]:
            return subprocess.CompletedProcess(argv, 0, FAKE_KEY)
        assert argv == ["claude", "-p", "synthetic brief"]
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(module.subprocess, "run", run)
    return module, calls, removed


@pytest.mark.parametrize("client_exit", [0, 7], ids=["success", "failure"])
def test_cleanup_failure_keeps_the_client_result_and_names_the_directory(
    fake_boundary, monkeypatch, capsys, client_exit
):
    module, calls, removed = fake_boundary
    original_run = module.subprocess.run

    def run(argv, **kwargs):
        if argv[0] == "claude":
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, client_exit)
        return original_run(argv, **kwargs)

    def fail_rmtree(path):
        removed.append(path)
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.shutil, "rmtree", fail_rmtree)
    rc = module.main(["-p", "synthetic brief"])
    captured = capsys.readouterr()
    assert rc == client_exit  # the client's own result is never replaced by the cleanup error
    assert removed == ["/synthetic/isolation"]
    assert captured.out == "" and FAKE_KEY not in captured.err
    assert len(captured.err.splitlines()) == 1
    assert "cleanup_failed" in captured.err and "PermissionError" in captured.err
    assert "/synthetic/isolation" in captured.err and "rm -rf /synthetic/isolation" in captured.err
    assert "TMPDIR" in captured.err and "retry" in captured.err


def test_cleanup_failure_after_a_launch_failure_reports_both(fake_boundary, monkeypatch, capsys):
    module, calls, removed = fake_boundary
    original_run = module.subprocess.run

    def fail_client(argv, **kwargs):
        if argv[0] == "claude":
            raise FileNotFoundError(FAKE_KEY)
        return original_run(argv, **kwargs)

    def fail_rmtree(path):
        removed.append(path)
        raise OSError(30, "Read-only file system", path)

    monkeypatch.setattr(module.subprocess, "run", fail_client)
    monkeypatch.setattr(module.shutil, "rmtree", fail_rmtree)
    rc = module.main(["-p", "synthetic brief"])
    captured = capsys.readouterr()
    assert rc == 3
    assert removed == ["/synthetic/isolation"]
    assert FAKE_KEY not in captured.err
    lines = captured.err.splitlines()
    assert len(lines) == 2
    assert "claude" in lines[0] and "PATH" in lines[0]
    assert (
        "cleanup_failed" in lines[1]
        and "OSError" in lines[1]
        and "/synthetic/isolation" in lines[1]
    )


@pytest.mark.parametrize("args", [["-p", "synthetic brief"], ["--check"]], ids=["run", "check"])
def test_missing_secret_helper_names_install_action(fake_boundary, monkeypatch, capsys, args):
    module, calls, removed = fake_boundary
    monkeypatch.setenv("PATH", "/synthetic/bin")
    monkeypatch.setattr(
        module.shutil, "which", lambda name: "/synthetic/bin/claude" if name == "claude" else None
    )
    assert module.main(args) == 3
    captured = capsys.readouterr()
    assert "hapax-secret is not on PATH" in captured.err
    assert "install or restore" in captured.err
    assert "~/projects/reins/scripts/hapax-secret" in captured.err
    assert "~/.local/bin/hapax-secret" in captured.err
    assert "retry the same command" in captured.err
    assert captured.out == "" and calls == [] and removed == []


@pytest.mark.parametrize("allowed", [False, True], ids=["refused", "allowed"])
@pytest.mark.parametrize(
    ("setting", "flag", "override"),
    [
        (
            "HAPAX_QWENCLOUD_ANTHROPIC_BASE_URL",
            "HAPAX_QWENCLOUD_ALLOW_BASE_URL_OVERRIDE",
            "https://synthetic.example/anthropic",
        ),
        (
            "HAPAX_QWENCLOUD_MODEL",
            "HAPAX_QWENCLOUD_ALLOW_NON_PLAN_MODEL",
            "synthetic-reviewed-model",
        ),
    ],
    ids=["endpoint", "model"],
)
def test_reviewed_override_flags_control_client_configuration(
    fake_boundary, monkeypatch, capsys, allowed, setting, flag, override
):
    module, calls, removed = fake_boundary
    monkeypatch.setenv(setting, override)
    if allowed:
        monkeypatch.setenv(flag, "1")
    rc = module.main(["-p", "synthetic brief"])
    captured = capsys.readouterr()
    if not allowed:
        assert rc == 2 and f"{flag}=1" in captured.err
        assert calls == [] and removed == []
        return
    assert rc == 0 and captured.err == ""
    assert len(calls) == 3
    argv, kwargs = calls[-1]
    assert argv == ["claude", "-p", "synthetic brief"]
    client = kwargs["env"]
    assert client["ANTHROPIC_AUTH_TOKEN"] == FAKE_KEY
    assert client["ANTHROPIC_BASE_URL"] == (override if setting.endswith("BASE_URL") else OFFICIAL)
    model = override if setting.endswith("MODEL") else "qwen3.7-plus"
    for name in (
        "ANTHROPIC_MODEL",
        "ANTHROPIC_SMALL_FAST_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    ):
        assert client[name] == model
    assert client["HOME"] == "/synthetic/isolation" and removed == [client["HOME"]]
    assert FAKE_KEY not in json.dumps(argv) + captured.out + captured.err


@pytest.mark.parametrize("empty", ["", " \n\t"], ids=["empty", "whitespace"])
def test_empty_secret_refuses_before_constructing_or_requesting_client(
    fake_boundary, monkeypatch, capsys, empty
):
    module, calls, removed = fake_boundary

    def run(argv, **kwargs):
        calls.append(argv)
        assert argv[0] == "hapax-secret", "empty secret reached a client request"
        return subprocess.CompletedProcess(argv, 0, "filestore" if "--where" in argv else empty)

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(
        module, "_client_environment", lambda *a: pytest.fail("empty secret constructed a client")
    )
    assert module.main(["-p", "synthetic brief"]) == 4
    assert calls == [
        ["hapax-secret", "--where", module.SECRET_NAME],
        ["hapax-secret", module.SECRET_NAME],
    ]
    assert removed == []
    captured = capsys.readouterr()
    assert "read back empty" in captured.err and "re-store it with hapax-secret" in captured.err
    assert captured.out == ""

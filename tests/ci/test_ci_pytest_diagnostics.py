"""Candidate root hooks, CLI and workflow executed with owned synthetic processes."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LEAF = ROOT / "shared/ci_pytest_diagnostics.py"
ENV = {
    "GITHUB_RUN_ID": "fixture",
    "GITHUB_RUN_ATTEMPT": "2",
    "GITHUB_SHA": "fixture-head",
    "PYTEST_SHARD": "3",
    "PYTEST_SHARD_COUNT": "4",
}


def events(directory, kind=None):
    rows = [
        json.loads(line)
        for p in directory.glob("*.jsonl")
        for line in p.read_text().splitlines()
        if line.endswith("}")
    ]
    return [e for e in rows if kind is None or e["event"] == kind]


def start(tmp_path, source, *, extra="", args=(), enabled=True):
    (tmp_path / "home").mkdir()
    (tmp_path / "test_sample.py").write_text(source)
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    # Actual root cleanup and plugin declaration; inert provider modules keep
    # synthetic tests off real services without replacing the cleanup hook.
    (tmp_path / "conftest.py").write_text(
        "import importlib.util, sys, types\n"
        f"spec = importlib.util.spec_from_file_location('root', {str(ROOT / 'conftest.py')!r})\n"
        "root = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(root)\n"
        "pytest_plugins = root.pytest_plugins\npytest_sessionfinish = root.pytest_sessionfinish\n"
        "for name in ('litellm', 'shared.config'):\n    sys.modules[name] = types.ModuleType(name)\n"
        "sys.modules['agents.hapax_daimonion.pw_audio_output'] = types.SimpleNamespace(PwAudioOutput=type('Inert', (), {}))\n"
        + extra
    )
    env = {
        **os.environ,
        **ENV,
        "HOME": str(tmp_path / "home"),
        "TMPDIR": str(tmp_path),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HAPAX_CI_EXIT_SECONDS": "1",
        "HAPAX_CI_PHASE": "tests",
    }
    env.pop("HAPAX_CI_DIAGNOSTICS_DIR", None)
    if enabled:
        env["HAPAX_CI_DIAGNOSTICS_DIR"] = str(tmp_path / "diagnostics")
    with (tmp_path / "output.txt").open("w") as out:
        return subprocess.Popen(
            [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
            cwd=tmp_path,
            env=env,
            stdout=out,
            stderr=out,
            start_new_session=True,
        )


def finish(proc, tmp_path, timeout=15):
    try:
        return proc.wait(timeout=timeout)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


def await_event(proc, directory, predicate):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if any(predicate(e) for e in events(directory)):
            return
        time.sleep(0.02)
    pytest.fail(f"missing event; exit={proc.poll()}; events={events(directory)}")


def classify(tmp_path, code):
    env = {
        **os.environ,
        **ENV,
        "HAPAX_CI_DIAGNOSTICS_DIR": str(tmp_path / "diagnostics"),
        "HAPAX_CI_PYTHON": sys.executable,
    }
    return subprocess.run(
        [
            "bash",
            str(ROOT / "scripts/ci_classify_shard_exit.sh"),
            str(code),
            "0",
            str(tmp_path / "output.txt"),
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )


def stacks(tmp_path):
    return "".join(p.read_text() for p in (tmp_path / "diagnostics").glob("*.stacks.txt"))


def test_clean_success_has_attributable_complete_protocol(tmp_path):
    proc = start(tmp_path, "def test_ok(): pass\n")
    assert finish(proc, tmp_path) == 0, (tmp_path / "output.txt").read_text()
    directory = tmp_path / "diagnostics"
    await_event(proc, directory, lambda e: e["event"] == "process_exit_observed")
    reports = events(directory, "report")
    assert [(e["when"], e["outcome"]) for e in reports] == [
        (p, "passed") for p in ("setup", "call", "teardown")
    ]
    assert {(e["head_sha"], e["run_attempt"], e["shard"]) for e in reports} == {
        ("fixture-head", "2", "3")
    }
    assert len({e["incarnation"] for e in reports}) == 1
    assert events(directory, "configured")[0]["origin"] == str(LEAF)
    for kind in ("protocol_complete", "root_cleanup_complete", "sessionfinish_complete"):
        assert events(directory, kind)
    assert not events(directory, "session_exit_forced")
    result = classify(tmp_path, 0)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"call:passed": 1' in result.stdout


def test_named_failure_survives_interruption_and_teardown_is_unfinished(tmp_path):
    proc = start(
        tmp_path,
        """
import pytest, time
def test_failure(): assert False
@pytest.fixture
def hanging():
    yield
    time.sleep(60)
def test_pass(hanging): pass
""",
        args=("-o", "faulthandler_timeout=0.2"),
    )
    directory = tmp_path / "diagnostics"
    try:
        await_event(
            proc,
            directory,
            lambda e: (
                e["event"] == "phase_start"
                and e.get("when") == "teardown"
                and "test_pass" in e.get("nodeid", "")
            ),
        )
        time.sleep(0.4)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
        finish(proc, tmp_path)
    assert "hanging" in stacks(tmp_path)
    result = classify(tmp_path, 137)
    for text in (
        "observed failed phase: test_sample.py::test_failure call",
        "unfinished protocol: test_sample.py::test_pass",
        "last=teardown started",
        '"call:passed": 1',
    ):
        assert text in result.stdout
    assert result.returncode == 1
    assert not [e for e in events(directory, "protocol_complete") if "test_pass" in e["nodeid"]]


def test_setup_error_is_recorded_without_a_call(tmp_path):
    proc = start(
        tmp_path,
        "import pytest\n@pytest.fixture\ndef bad(): raise RuntimeError('setup')\ndef test_bad(bad): pass\n",
    )
    assert finish(proc, tmp_path) == 1
    assert [(e["when"], e["outcome"]) for e in events(tmp_path / "diagnostics", "report")] == [
        ("setup", "failed"),
        ("teardown", "passed"),
    ]
    assert "test_bad setup" in classify(tmp_path, 1).stdout


@pytest.mark.parametrize("stall", ["cleanup", "atexit", "thread", "late"])
def test_session_exit_stalls_dump_stacks_and_exit_nonzero(tmp_path, stall):
    source = "import sys, types, time, atexit, threading\ndef blocked(): time.sleep(60)\ndef test_ok():\n    "
    source += {
        "cleanup": "sys.modules['shared.telemetry'] = types.SimpleNamespace(_langfuse=types.SimpleNamespace(flush=blocked))",
        "atexit": "atexit.register(blocked)",
        "late": "atexit.register(blocked)",
        "thread": "threading.Thread(target=blocked).start()",
    }[stall]
    extra = (
        "def pytest_unconfigure():\n    import faulthandler\n    faulthandler.cancel_dump_traceback_later()\n"
        if stall == "late"
        else ""
    )
    proc = start(tmp_path, source, extra=extra)
    before = time.monotonic()
    code = finish(proc, tmp_path, timeout=10)
    assert code != 0 and time.monotonic() - before < 10
    directory = tmp_path / "diagnostics"
    assert events(directory, "sessionfinish_start")
    assert bool(events(directory, "sessionfinish_complete")) == (stall != "cleanup")
    if stall == "late":
        assert code == -signal.SIGKILL
        assert events(directory, "session_exit_forced")
    else:
        assert "blocked" in stacks(tmp_path)


def test_worker_crash_restart_uses_distinct_incarnations(tmp_path):
    proc = start(
        tmp_path,
        "import os\ndef test_crash(): os._exit(9)\ndef test_ok(): pass\n",
        args=("-p", "xdist.plugin", "-n", "1", "--max-worker-restart=1"),
    )
    assert finish(proc, tmp_path) != 0
    directory = tmp_path / "diagnostics"
    assert len({e["incarnation"] for e in events(directory, "protocol_start")}) == 2
    assert any(e["crashed"] for e in events(directory, "worker_down"))
    assert events(directory, "forwarded_report")
    result = classify(tmp_path, 1)
    assert '"call:passed": 1' in result.stdout
    assert '"call:failed"' not in result.stdout  # controller's synthetic crash report
    assert "unfinished protocol: test_sample.py::test_crash" in result.stdout


def test_disabled_mode_produces_no_artifacts(tmp_path):
    assert finish(start(tmp_path, "def test_ok(): pass\n", enabled=False), tmp_path) == 0
    assert not (tmp_path / "diagnostics").exists()


def test_nested_pytest_does_not_inherit_diagnostic_activation(tmp_path):
    proc = start(
        tmp_path,
        """
import subprocess, sys
def test_ok(tmp_path):
    child = tmp_path / 'test_child.py'
    child.write_text('def test_bad(): assert False')
    result = subprocess.run([sys.executable, '-m', 'pytest', '--noconftest', '-p', 'shared.ci_pytest_diagnostics', str(child)], capture_output=True)
    assert result.returncode == 1
""",
    )
    assert finish(proc, tmp_path) == 0
    assert len(events(tmp_path / "diagnostics", "configured")) == 1


def test_diagnostic_io_failure_is_explicit(tmp_path):
    (tmp_path / "diagnostics").write_text("not a directory")
    assert finish(start(tmp_path, "def test_ok(): pass\n"), tmp_path) != 0
    assert "CI diagnostics unavailable" in (tmp_path / "output.txt").read_text()


def test_incremental_write_failure_cannot_pass(tmp_path):
    proc = start(
        tmp_path,
        """
import os
def test_ok(request):
    diagnostics = request.config.pluginmanager.get_plugin('ci-native-diagnostics')
    fd = os.open('/dev/full', os.O_WRONLY)
    os.dup2(fd, diagnostics.fd)
    os.close(fd)
""",
    )
    assert finish(proc, tmp_path) != 0
    assert "CI diagnostics unavailable" in (tmp_path / "output.txt").read_text()


@pytest.mark.parametrize("damage", ["missing", "truncated", "duplicate", "foreign"])
def test_damaged_native_evidence_cannot_certify_success(tmp_path, damage):
    assert finish(start(tmp_path, "def test_ok(): pass\n"), tmp_path) == 0
    path = next((tmp_path / "diagnostics").glob("*.events.jsonl"))
    data = path.read_text()
    if damage == "missing":
        path.unlink()
    else:
        path.write_text(
            {
                "truncated": data + '{"event":',
                "duplicate": data + data.splitlines()[0] + "\n",
                "foreign": data.replace("fixture-head", "foreign-head"),
            }[damage]
        )
    result = classify(tmp_path, 0)
    assert result.returncode == 1 and "incomplete/unknown" in result.stdout
    assert "All tests passed" not in result.stdout

"""A replay must compare distinct, explicitly identified reader sources."""

import hashlib
import json
import os
import runpy
import subprocess
from pathlib import Path

import pytest

from scripts import quota_trace_cache_measurement as replay

ROOT = Path(__file__).resolve().parents[2]


def status(argv):
    try:
        return replay.main(argv)
    except SystemExit as exc:
        return exc.code


@pytest.fixture
def comparison(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "shared").mkdir(parents=True)
    for name in ("quota_headroom.py", "quota_trace_cache.py"):
        (repo / "shared" / name).write_bytes((ROOT / "shared" / name).read_bytes())
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "reader fixture",
        ],
        cwd=repo,
        check=True,
    )
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    monkeypatch.setattr(replay, "ROOT", repo)
    return repo, commit


def test_same_reader_bytes_cannot_claim_prechange_comparison(comparison, capsys):
    _, commit = comparison
    with pytest.raises(SystemExit) as exc:
        replay.main(["--baseline-ref", commit, "--scratch-root", "/unused"])
    assert exc.value.code == 2
    assert "identical reader bytes" in capsys.readouterr().err


def test_baseline_is_required_and_must_be_immutable(comparison, capsys):
    with pytest.raises(SystemExit):
        replay.main([])
    assert "--baseline-ref" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        replay.main(["--baseline-ref", "HEAD", "--scratch-root", "/unused"])
    assert "full commit SHA" in capsys.readouterr().err


@pytest.fixture
def prepared(comparison, tmp_path, monkeypatch):
    repo, commit = comparison
    # Different bytes suffice for this tool test; this fixture claims no historical speedup.
    with (repo / "shared/quota_headroom.py").open("ab") as stream:
        stream.write(b"\n# candidate fixture\n")
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    trace = sessions / "rollout-test.jsonl"
    trace.write_bytes(b'{"irrelevant":"' + b"x" * 70000 + b'"}\n')
    os.utime(trace, (1, 1))
    original = Path.read_text

    def quiet_psi(path, *args, **kwargs):
        if str(path) == "/proc/pressure/io":
            return "some avg10=0.00\nfull avg10=0.00\n"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", quiet_psi)
    argv = ["--baseline-ref", commit, "--scratch-root", str(tmp_path), "--sessions", str(sessions)]
    return argv, trace, tmp_path


def test_explicit_scratch_binding_and_resolved_sources(prepared, capsys):
    argv, trace, scratch = prepared
    before = trace.read_bytes()
    assert replay.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    report_path = Path(result["report"])
    assert report_path.is_relative_to(scratch)
    report = json.loads(report_path.read_text())
    assert report["baseline_commit"] == argv[1]
    assert report["baseline_sha256"] != report["candidate_sha256"]["shared/quota_headroom.py"]
    assert report["candidate_commit"] == argv[1]
    assert report["outputs"]["baseline"] == report["outputs"]["cold"] == report["outputs"]["warm"]
    assert report["exact_outputs_equal"] and report["raw_bytes_and_identity_preserved"]
    assert report["sources_before"][0]["sha256"] == hashlib.sha256(before).hexdigest()
    assert trace.read_bytes() == before


@pytest.mark.parametrize(
    "psi", [None, "full missing=value\n", "full avg10=nan\n", "full avg10=11\n"]
)
def test_unavailable_or_busy_pressure_refuses_replay(prepared, monkeypatch, capsys, psi):
    argv, _, scratch = prepared
    original = Path.read_text

    def pressure(path, *args, **kwargs):
        if str(path) == "/proc/pressure/io":
            if psi is None:
                raise FileNotFoundError("pressure unavailable")
            return psi
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", pressure)
    assert status(argv) == 2
    assert "Next action:" in capsys.readouterr().err
    assert not list(scratch.glob("quota-trace-measure-*"))


@pytest.mark.parametrize("failure", ["sample", "scratch", "bounds", "git"])
def test_measurement_failures_give_next_action(prepared, capsys, failure):
    argv, trace, scratch = prepared
    if failure == "sample":
        trace.unlink()
    elif failure == "scratch":
        argv[3] = str(scratch / "missing")
    elif failure == "bounds":
        argv += ["--max-files", "33"]
    else:
        argv[1] = "0" * 40
    with pytest.raises(SystemExit) as exc:
        replay.main(argv)
    assert exc.value.code == 2
    assert "Next action:" in capsys.readouterr().err
    assert not list(scratch.glob("quota-trace-measure-*"))


def test_existing_checker_forwards_explicit_measurement_arguments(monkeypatch):
    argv = ["--baseline-ref", "a" * 40, "--scratch-root", "/chosen/scratch"]
    received = []
    monkeypatch.setattr(replay, "main", lambda args: received.extend(args) or 0)
    checker = runpy.run_path(str(ROOT / "scripts/check-quota-headroom-mutations.py"))
    assert checker["main"](["--trace-cache-measure", "--", *argv]) == 0
    assert received == argv

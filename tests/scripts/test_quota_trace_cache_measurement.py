"""A replay must compare distinct, explicitly identified reader sources."""

import hashlib
import json
import os
import runpy
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import quota_trace_cache_measurement as replay

ROOT = Path(__file__).resolve().parents[2]


def commit_sources(repo):
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
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


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
    commit = commit_sources(repo)
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
    commit_sources(repo)
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    trace = sessions / "rollout-test.jsonl"
    event = {
        "timestamp": "2026-09-30T20:00:00Z",
        "payload": {
            "type": "token_count",
            "info": {"total_token_usage": {"total_tokens": 123}},
            "rate_limits": {
                "primary": {"used_percent": 20, "window_minutes": 10080, "resets_at": 1790899200},
                "credits": {"balance": 90},
            },
        },
    }
    trace.write_bytes(json.dumps(event).encode() + b'\n{"irrelevant":"' + b"x" * 70000 + b'"}\n')
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
    assert report["candidate_commit"] != argv[1]
    assert (
        report["candidate_commit"]
        == subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=replay.ROOT, text=True).strip()
    )
    assert report["outputs"]["baseline"] == report["outputs"]["cold"] == report["outputs"]["warm"]
    assert report["exact_outputs_equal"] and report["raw_bytes_and_identity_preserved"]
    assert report["sources_before"][0]["sha256"] == hashlib.sha256(before).hexdigest()
    assert trace.read_bytes() == before
    assert report["outputs"]["baseline"][0]["quantity"] == 20
    assert report["baseline"]["raw_bytes_read"] == len(before)
    assert report["cold"]["raw_bytes_read"] == len(before) + 8192
    assert report["warm"]["raw_bytes_read"] == 16384
    assert report["warm_read_reduction"] == 1 - 16384 / len(before)


@pytest.mark.parametrize("name", ["quota_headroom.py", "quota_trace_cache.py"])
def test_dirty_candidate_cannot_claim_commit(prepared, capsys, name):
    argv, _, scratch = prepared
    with (replay.ROOT / "shared" / name).open("ab") as stream:
        stream.write(b"\n# uncommitted reader behavior\n")
    assert status(argv) == 2
    assert "candidate source differs from HEAD" in capsys.readouterr().err
    assert not list(scratch.glob("quota-trace-measure-*"))


def test_candidate_execution_and_hashes_use_captured_commit(prepared, monkeypatch, capsys):
    argv, _, _ = prepared
    original = replay.replay
    captured = {
        name: (replay.ROOT / name).read_bytes()
        for name in ("shared/quota_headroom.py", "shared/quota_trace_cache.py")
    }

    def changed_after_admission(*args):
        for name in captured:
            (replay.ROOT / name).write_text(
                "def read_codex_token_count(*args, **kwargs): return []\n"
            )
        return original(*args)

    monkeypatch.setattr(replay, "replay", changed_after_admission)
    assert replay.main(argv) == 0
    report = json.loads(Path(json.loads(capsys.readouterr().out)["report"]).read_text())
    assert report["candidate_sha256"] == {
        name: hashlib.sha256(data).hexdigest() for name, data in captured.items()
    }
    assert report["outputs"]["warm"][0]["quantity"] == 20


def test_zero_baseline_reads_refuse_a_reduction_claim(prepared, capsys):
    argv, _, scratch = prepared
    path = replay.ROOT / "shared/quota_headroom.py"
    candidate = path.read_bytes()
    path.write_text("def read_codex_token_count(*args, **kwargs): return []\n")
    argv[1] = commit_sources(replay.ROOT)
    path.write_bytes(candidate)
    commit_sources(replay.ROOT)
    try:
        result = status(argv)
    except ZeroDivisionError:
        result = None
    assert result == 2
    assert "baseline read zero counted bytes" in capsys.readouterr().err
    assert not list(scratch.glob("quota-trace-measure-*/measurement.json"))


def test_committed_cache_behavior_is_the_executed_candidate(prepared, capsys):
    argv, _, _ = prepared
    path = replay.ROOT / "shared/quota_trace_cache.py"
    path.write_text(path.read_text().replace("PROBE_BYTES = 4096", "PROBE_BYTES = 1024"))
    candidate_commit = commit_sources(replay.ROOT)
    assert replay.main(argv) == 0
    report = json.loads(Path(json.loads(capsys.readouterr().out)["report"]).read_text())
    assert report["candidate_commit"] == candidate_commit
    assert report["warm"]["raw_bytes_read"] == 4096


@pytest.mark.parametrize("method", ["read", "readline", "iteration"])
def test_logical_read_accounting_has_known_scope(prepared, method):
    _, trace, scratch = prepared
    sessions = scratch / "linked"
    sessions.mkdir()
    link = sessions / trace.name
    link.symlink_to(trace)
    raw = trace.read_bytes()

    def reader(root, **kwargs):
        # Direct source spelling lies outside this explicitly scoped counter.
        trace.read_bytes()
        with (root / trace.name).open("rb") as stream:
            if method == "read":
                stream.read()
            elif method == "readline":
                while stream.readline():
                    pass
            else:
                list(stream)
            stream.seek(0)
            stream.read(7)
        return []

    _, measured = replay.measure(reader, sessions, now=datetime.now(UTC))
    assert measured["raw_bytes_read"] == len(raw) + 7


@pytest.mark.parametrize("max_files,expected", [(3, ["z", "x"]), (1, ["z"])])
def test_partial_sample_respects_byte_and_file_bounds(prepared, capsys, max_files, expected):
    argv, trace, _ = prepared
    raw = trace.read_bytes()
    for name, size in [("z", 80000), ("y", 76000), ("x", 66000)]:
        path = trace.with_name(f"rollout-{name}.jsonl")
        event = raw.split(b"\n", 1)[0] + b"\n"
        path.write_bytes(event + b" " * (size - len(event) - 1) + b"\n")
        os.utime(path, (1, 1))
    trace.unlink()
    assert replay.main([*argv, "--max-bytes", "150000", "--max-files", str(max_files)]) == 0
    report = json.loads(Path(json.loads(capsys.readouterr().out)["report"]).read_text())
    assert [Path(row["source"]).stem for row in report["sources_before"]] == [
        f"rollout-{name}" for name in expected
    ]
    assert report["source_bytes"] == (146000 if max_files == 3 else 80000)


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

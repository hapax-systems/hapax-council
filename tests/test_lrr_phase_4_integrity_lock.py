"""Tests for scripts/lrr-phase-4-integrity-lock.sh.

Shell-script integration tests. Each test sets up a tempdir acting as
``HOME/hapax-state/research-registry/``, creates a fake reactor-logs
directory with a few .jsonl files, invokes the script with
``--skip-snapshot`` (Qdrant is not reachable in tests), and asserts on
exit code + the sealed artifacts.

Spec: docs/superpowers/specs/2026-04-15-lrr-phase-4-phase-a-completion-osf-design.md §3.6
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "lrr-phase-4-integrity-lock.sh"


def _run(
    home: Path,
    *args: str,
    reactor_logs: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    if reactor_logs is not None:
        env["REACTOR_LOGS_DIR"] = str(reactor_logs)
    env.setdefault("QDRANT_URL", "http://127.0.0.1:1")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SCRIPT_PATH), *args],
        env=env,
        capture_output=True,
        text=True,
    )


def _init_condition(home: Path, condition_id: str) -> Path:
    registry = home / "hapax-state" / "research-registry"
    cond_dir = registry / condition_id
    cond_dir.mkdir(parents=True)
    (registry / "current.txt").write_text(f"{condition_id}\n")
    return cond_dir


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


class TestBasicLock:
    def test_lock_creates_all_three_artifacts(self, tmp_path: Path):
        cond_dir = _init_condition(tmp_path, "cond-phase-a-baseline-qwen-001")
        logs = tmp_path / "reactor-logs"
        _write_jsonl(logs / "reactor-log-2026-04.jsonl", ['{"a":1}', '{"a":2}', '{"a":3}'])
        _write_jsonl(logs / "reactor-log-2026-05.jsonl", ['{"b":1}'])

        result = _run(tmp_path, "--skip-snapshot", reactor_logs=logs)
        assert result.returncode == 0, result.stderr

        assert (cond_dir / "data-checksums.txt").exists()
        assert (cond_dir / "integrity-lock.yaml").exists()

    def test_checksums_include_every_jsonl_with_valid_sha256(self, tmp_path: Path):
        cond_dir = _init_condition(tmp_path, "cond-phase-a-baseline-qwen-001")
        logs = tmp_path / "reactor-logs"
        _write_jsonl(logs / "a.jsonl", ['{"x":1}'])
        _write_jsonl(logs / "sub" / "b.jsonl", ['{"y":2}'])

        _run(tmp_path, "--skip-snapshot", reactor_logs=logs)
        text = (cond_dir / "data-checksums.txt").read_text()

        expected_a = hashlib.sha256((logs / "a.jsonl").read_bytes()).hexdigest()
        expected_b = hashlib.sha256((logs / "sub" / "b.jsonl").read_bytes()).hexdigest()
        assert expected_a in text
        assert expected_b in text
        assert "a.jsonl" in text
        assert "b.jsonl" in text

    def test_manifest_records_file_count_and_git_head(self, tmp_path: Path):
        cond_dir = _init_condition(tmp_path, "cond-phase-a-baseline-qwen-001")
        logs = tmp_path / "reactor-logs"
        _write_jsonl(logs / "reactor-log-2026-04.jsonl", ['{"a":1}'])

        _run(tmp_path, "--skip-snapshot", reactor_logs=logs)
        manifest = (cond_dir / "integrity-lock.yaml").read_text()
        assert "condition: cond-phase-a-baseline-qwen-001" in manifest
        assert "reactor_logs_file_count: 1" in manifest
        assert "snapshot_status: skipped" in manifest
        assert "git_head:" in manifest
        assert "locked_at: 20" in manifest  # ISO-8601 prefix

    def test_handles_missing_reactor_logs_dir_gracefully(self, tmp_path: Path):
        cond_dir = _init_condition(tmp_path, "cond-phase-a-baseline-qwen-001")
        missing = tmp_path / "does-not-exist"
        result = _run(tmp_path, "--skip-snapshot", reactor_logs=missing)
        assert result.returncode == 0
        assert (cond_dir / "data-checksums.txt").exists()
        assert (cond_dir / "data-checksums.txt").read_text() == ""
        manifest = (cond_dir / "integrity-lock.yaml").read_text()
        assert "reactor_logs_file_count: 0" in manifest


class TestIdempotencyGuard:
    def test_refuses_to_overwrite_existing_lock(self, tmp_path: Path):
        _init_condition(tmp_path, "cond-phase-a-baseline-qwen-001")
        logs = tmp_path / "reactor-logs"
        _write_jsonl(logs / "a.jsonl", ['{"x":1}'])

        first = _run(tmp_path, "--skip-snapshot", reactor_logs=logs)
        assert first.returncode == 0

        second = _run(tmp_path, "--skip-snapshot", reactor_logs=logs)
        assert second.returncode == 1
        assert "integrity lock already exists" in second.stderr

    def test_force_overwrites_existing_lock(self, tmp_path: Path):
        cond_dir = _init_condition(tmp_path, "cond-phase-a-baseline-qwen-001")
        logs = tmp_path / "reactor-logs"
        _write_jsonl(logs / "a.jsonl", ['{"x":1}'])

        _run(tmp_path, "--skip-snapshot", reactor_logs=logs)
        first_manifest = (cond_dir / "integrity-lock.yaml").read_text()

        # Add another file and force-rerun
        _write_jsonl(logs / "b.jsonl", ['{"y":2}'])
        result = _run(tmp_path, "--skip-snapshot", "--force", reactor_logs=logs)
        assert result.returncode == 0

        second_manifest = (cond_dir / "integrity-lock.yaml").read_text()
        assert "reactor_logs_file_count: 2" in second_manifest
        assert first_manifest != second_manifest


class TestRegistryUninitialized:
    def test_exits_2_when_current_txt_missing(self, tmp_path: Path):
        (tmp_path / "hapax-state" / "research-registry").mkdir(parents=True)
        result = _run(tmp_path, "--skip-snapshot")
        assert result.returncode == 2
        assert "registry not initialized" in result.stderr

    def test_exits_2_when_condition_arg_refers_to_missing(self, tmp_path: Path):
        (tmp_path / "hapax-state" / "research-registry").mkdir(parents=True)
        result = _run(tmp_path, "--skip-snapshot", "--condition", "cond-nope-001")
        assert result.returncode == 2
        assert "not found at" in result.stderr


class TestExplicitConditionFlag:
    def test_honors_explicit_condition_over_current(self, tmp_path: Path):
        registry = tmp_path / "hapax-state" / "research-registry"
        # current.txt points at A
        _init_condition(tmp_path, "cond-a-001")
        # But also create B
        (registry / "cond-b-001").mkdir(parents=True)

        logs = tmp_path / "reactor-logs"
        _write_jsonl(logs / "a.jsonl", ['{"x":1}'])

        result = _run(tmp_path, "--skip-snapshot", "--condition", "cond-b-001", reactor_logs=logs)
        assert result.returncode == 0
        assert (registry / "cond-b-001" / "integrity-lock.yaml").exists()
        assert not (registry / "cond-a-001" / "integrity-lock.yaml").exists()


class TestHelp:
    def test_help_exits_zero_and_prints_spec(self, tmp_path: Path):
        result = _run(tmp_path, "--help")
        assert result.returncode == 0
        assert "LRR Phase 4 spec" in result.stdout
        assert "sha256" in result.stdout

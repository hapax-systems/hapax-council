"""Tests for scripts/hapax-lrr-phase-4-integrity-check.

Shell-script integration tests. Each test sets up a tempdir acting as
``HOME/hapax-state/research-registry/``, invokes the script with env
overrides, and asserts on exit code + log output. Qdrant + Langfuse
checks are stubbed by pointing at unreachable URLs (the script exits
with failures the test then verifies).

Spec: docs/superpowers/specs/2026-04-15-lrr-phase-4-phase-a-completion-osf-design.md §3.3
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "hapax-lrr-phase-4-integrity-check"
)
REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_condition(
    registry: Path,
    condition_id: str,
    *,
    frozen_files: list[str] | None = None,
    collection_halt_at: str | None = None,
) -> None:
    cond_dir = registry / condition_id
    cond_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"condition_id: {condition_id}",
        "claim_id: claim-shaikh-sft-vs-dpo",
        "opened_at: 2026-04-15T00:00:00Z",
        "closed_at: null",
        "substrate:",
        "  model: qwen3.5-9b",
        "  quant: exl3-5.0bpw",
        "  runtime: tabbyapi",
    ]
    if frozen_files:
        lines.append("frozen_files:")
        for f in frozen_files:
            lines.append(f"  - {f}")
    else:
        lines.append("frozen_files: []")
    if collection_halt_at is None:
        lines.append("collection_halt_at: null")
    else:
        lines.append(f"collection_halt_at: {collection_halt_at}")
    (cond_dir / "condition.yaml").write_text("\n".join(lines) + "\n")


def _run(
    home: Path, *args: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    # Point Qdrant at an unreachable URL so the count check predictably
    # fails rather than hitting a real Qdrant instance during tests.
    env.setdefault("QDRANT_URL", "http://127.0.0.1:1")
    # Strip any real Langfuse creds so check 4 deterministically skips.
    env.pop("LANGFUSE_PUBLIC_KEY", None)
    env.pop("LANGFUSE_SECRET_KEY", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SCRIPT_PATH), *args],
        env=env,
        capture_output=True,
        text=True,
    )


class TestRegistryUninitialized:
    def test_exits_2_when_current_txt_missing(self, tmp_path: Path):
        (tmp_path / "hapax-state" / "research-registry").mkdir(parents=True)
        result = _run(tmp_path)
        assert result.returncode == 2
        assert "registry not initialized" in result.stderr

    def test_exits_2_when_current_txt_empty(self, tmp_path: Path):
        registry = tmp_path / "hapax-state" / "research-registry"
        registry.mkdir(parents=True)
        (registry / "current.txt").write_text("")
        result = _run(tmp_path)
        assert result.returncode == 2
        assert "no active condition" in result.stderr


class TestConditionMismatch:
    def test_fails_when_current_condition_does_not_match_expected(self, tmp_path: Path):
        registry = tmp_path / "hapax-state" / "research-registry"
        registry.mkdir(parents=True)
        (registry / "current.txt").write_text("cond-other-001\n")
        _write_condition(registry, "cond-other-001")
        result = _run(
            tmp_path,
            "--quiet",
            "--expected-condition",
            "cond-phase-a-baseline-qwen-001",
        )
        assert result.returncode == 1
        assert (
            "active condition is cond-other-001, expected cond-phase-a-baseline-qwen-001"
            in result.stderr
        )

    def test_default_expected_condition_tracks_current_condition(self, tmp_path: Path):
        registry = tmp_path / "hapax-state" / "research-registry"
        registry.mkdir(parents=True)
        (registry / "current.txt").write_text("cond-other-001\n")
        _write_condition(registry, "cond-other-001")
        result = _run(tmp_path, "--quiet")
        # Still non-zero because Qdrant is unreachable, but the default
        # current-condition mode must not fail just because the active condition
        # is no longer the original baseline arm.
        assert result.returncode == 1
        assert "active condition is cond-other-001, expected" not in result.stderr

    def test_custom_expected_condition_matches(self, tmp_path: Path):
        registry = tmp_path / "hapax-state" / "research-registry"
        registry.mkdir(parents=True)
        (registry / "current.txt").write_text("cond-custom-001\n")
        _write_condition(registry, "cond-custom-001")
        result = _run(tmp_path, "--quiet", "--expected-condition", "cond-custom-001")
        # Still non-zero because Qdrant check fails, but check 1 passes —
        # the "active condition is" error should not be in stderr.
        assert "active condition is cond-custom-001, expected" not in result.stderr


class TestHaltWindowSealed:
    def test_exits_3_when_collection_halt_at_is_set(self, tmp_path: Path):
        registry = tmp_path / "hapax-state" / "research-registry"
        registry.mkdir(parents=True)
        (registry / "current.txt").write_text("cond-phase-a-baseline-qwen-001\n")
        _write_condition(
            registry,
            "cond-phase-a-baseline-qwen-001",
            collection_halt_at="2026-04-15T12:00:00Z",
        )
        result = _run(tmp_path)
        assert result.returncode == 3
        assert "integrity window is sealed" in result.stdout

    def test_exits_3_respected_by_systemd_success_exit_status(self, tmp_path: Path):
        # This asserts the contract the service unit depends on:
        # SuccessExitStatus=3 means exit 3 is not a systemd failure.
        # We only verify the exit code here; the systemd unit file is
        # covered by a separate static-parse test if one exists.
        registry = tmp_path / "hapax-state" / "research-registry"
        registry.mkdir(parents=True)
        (registry / "current.txt").write_text("cond-phase-a-baseline-qwen-001\n")
        _write_condition(
            registry,
            "cond-phase-a-baseline-qwen-001",
            collection_halt_at="2026-04-15T12:00:00Z",
        )
        result = _run(tmp_path)
        assert result.returncode == 3


class TestQdrantUnreachable:
    def test_fails_but_still_logs(self, tmp_path: Path):
        registry = tmp_path / "hapax-state" / "research-registry"
        registry.mkdir(parents=True)
        (registry / "current.txt").write_text("cond-phase-a-baseline-qwen-001\n")
        _write_condition(registry, "cond-phase-a-baseline-qwen-001")
        result = _run(tmp_path, "--quiet")
        # QDRANT_URL is unreachable; check 3 fails.
        assert result.returncode == 1
        assert "could not read stream-reactions count" in result.stderr
        # The run still appends a JSONL record.
        log_file = registry / "cond-phase-a-baseline-qwen-001" / "integrity-check-log.jsonl"
        assert log_file.exists()
        log_lines = log_file.read_text().strip().splitlines()
        assert len(log_lines) == 1
        assert '"condition":"cond-phase-a-baseline-qwen-001"' in log_lines[0]
        assert '"failures":1' in log_lines[0] or '"failures":2' in log_lines[0]


class TestHelp:
    def test_help_flag_prints_header(self, tmp_path: Path):
        result = _run(tmp_path, "--help")
        assert result.returncode == 0
        assert "LRR Phase 4 spec" in result.stdout
        assert "Exit codes:" in result.stdout

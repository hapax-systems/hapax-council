"""Tests for scripts/cc-migration-capability — the NEW-6 one-time migration grant.

Self-contained: each test pins HOME to a tmp vault + capability dir and invokes
the script via subprocess. Coordination reform Phase 2.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "cc-migration-capability"
NS = "stage-scope-backfill"


def _run(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def _make_task(home: Path, task_id: str, *, stage: str | None, scope: bool) -> Path:
    active = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    active.mkdir(parents=True, exist_ok=True)
    note = active / f"{task_id}-x.md"
    stage_line = f"stage: {stage}\n" if stage else ""
    scope_block = "mutation_scope_refs:\n  - shared/x.py\n" if scope else ""
    note.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "T"
status: offered
assigned_to: unassigned
authority_case: CASE-TEST-001
{stage_line}{scope_block}updated_at: 2026-01-01T00:00:00Z
---

# T

## Session log
""",
        encoding="utf-8",
    )
    return note


def _mint(home: Path) -> str:
    r = _run(home, "mint", "--namespace", NS, "--ttl-minutes", "60")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class TestCapabilityLifecycle:
    def test_mint_then_check_passes(self, tmp_path: Path) -> None:
        cap_id = _mint(tmp_path)
        assert cap_id.startswith("mig-")
        assert _run(tmp_path, "check", "--namespace", NS).returncode == 0

    def test_check_unknown_namespace_fails(self, tmp_path: Path) -> None:
        _mint(tmp_path)
        assert _run(tmp_path, "check", "--namespace", "other-ns").returncode == 2

    def test_expire_then_check_fails(self, tmp_path: Path) -> None:
        cap_id = _mint(tmp_path)
        assert _run(tmp_path, "expire", "--id", cap_id).returncode == 0
        assert _run(tmp_path, "check", "--namespace", NS).returncode == 2


class TestCapabilityGatedBackfill:
    def test_backfill_refused_without_capability(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t1", stage=None, scope=False)
        r = _run(tmp_path, "backfill", "--namespace", NS, "--apply")
        assert r.returncode == 2
        assert "no active capability" in r.stdout.lower() or "refused" in r.stdout.lower()

    def test_backfill_dry_run_does_not_mutate(self, tmp_path: Path) -> None:
        note = _make_task(tmp_path, "t1", stage=None, scope=False)
        _mint(tmp_path)
        before = note.read_text()
        r = _run(tmp_path, "backfill", "--namespace", NS)
        assert r.returncode == 0, r.stderr
        assert note.read_text() == before
        assert "dry-run" in r.stdout

    def test_backfill_apply_stamps_absent_fields_only(self, tmp_path: Path) -> None:
        stageless = _make_task(tmp_path, "t1", stage=None, scope=False)
        staged = _make_task(tmp_path, "t2", stage="S7_RELEASE", scope=True)
        _mint(tmp_path)
        r = _run(tmp_path, "backfill", "--namespace", NS, "--apply")
        assert r.returncode == 0, r.stderr
        # Stage-less task gets stamped.
        t1 = stageless.read_text()
        assert "stage: S6_IMPLEMENTATION" in t1
        assert "mutation_scope_refs: []" in t1
        # Already-staged task is untouched (diff discipline).
        t2 = staged.read_text()
        assert "stage: S7_RELEASE" in t2
        assert t2.count("stage:") == 1

    def test_backfill_is_idempotent(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t1", stage=None, scope=False)
        _mint(tmp_path)
        _run(tmp_path, "backfill", "--namespace", NS, "--apply")
        r2 = _run(tmp_path, "backfill", "--namespace", NS, "--apply")
        assert r2.returncode == 0
        assert "stage on 0 tasks" in r2.stdout

    def test_backfill_ledgers_the_run(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t1", stage=None, scope=False)
        _mint(tmp_path)
        _run(tmp_path, "backfill", "--namespace", NS, "--apply")
        ledger = tmp_path / ".cache" / "hapax" / "migration-capabilities" / "ledger.jsonl"
        kinds = [json.loads(line)["kind"] for line in ledger.read_text().splitlines()]
        assert "capability_mint" in kinds
        assert "migration_backfill" in kinds

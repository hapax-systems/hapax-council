"""Tests for scripts/cc-migration-capability — the NEW-6 migration record.

Self-contained: each test pins HOME to a tmp vault + migration-record dir and invokes
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


def _make_task(
    home: Path,
    task_id: str,
    *,
    status: str,
    stage: str | None,
    scope: bool,
) -> Path:
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
status: {status}
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
    def test_backfill_refused_without_record(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t1", status="offered", stage=None, scope=False)
        r = _run(tmp_path, "backfill", "--namespace", NS, "--apply")
        assert r.returncode == 2
        assert "no active migration record" in r.stdout.lower() or "refused" in r.stdout.lower()

    def test_backfill_dry_run_does_not_mutate(self, tmp_path: Path) -> None:
        note = _make_task(tmp_path, "t1", status="offered", stage=None, scope=False)
        _mint(tmp_path)
        before = note.read_text()
        r = _run(tmp_path, "backfill", "--namespace", NS)
        assert r.returncode == 0, r.stderr
        assert note.read_text() == before
        assert "dry-run" in r.stdout

    def test_backfill_apply_derives_stage_from_status(self, tmp_path: Path) -> None:
        offered = _make_task(
            tmp_path, "t1", status="offered", stage="S6_IMPLEMENTATION", scope=False
        )
        blocked = _make_task(
            tmp_path, "t2", status="blocked", stage="S6_IMPLEMENTATION", scope=True
        )
        ready = _make_task(tmp_path, "t3", status="ready", stage="S6_IMPLEMENTATION", scope=True)
        pr_open = _make_task(tmp_path, "t4", status="pr_open", stage=None, scope=False)
        claimed = _make_task(tmp_path, "t5", status="claimed", stage=None, scope=False)
        terminal = _make_task(tmp_path, "t6", status="done", stage="S6_IMPLEMENTATION", scope=False)
        _mint(tmp_path)
        r = _run(tmp_path, "backfill", "--namespace", NS, "--apply")
        assert r.returncode == 0, r.stderr
        assert "stage: S0_INTAKE" in offered.read_text()
        assert "mutation_scope_refs: []" in offered.read_text()
        assert "stage: S5_REVIEW_GATE" in blocked.read_text()
        assert "stage: S7_RELEASE" in ready.read_text()
        assert "stage: S7_RELEASE" in pr_open.read_text()
        assert "mutation_scope_refs: []" in pr_open.read_text()
        assert "stage: S6_IMPLEMENTATION" in claimed.read_text()
        terminal_text = terminal.read_text()
        assert "stage: S6_IMPLEMENTATION" in terminal_text
        assert "mutation_scope_refs:" not in terminal_text

    def test_backfill_consumes_record_after_apply(self, tmp_path: Path) -> None:
        cap_id = _mint(tmp_path)
        _make_task(tmp_path, "t1", status="offered", stage=None, scope=False)
        r = _run(tmp_path, "backfill", "--namespace", NS, "--apply")
        assert r.returncode == 0, r.stderr
        cap_path = tmp_path / ".cache" / "hapax" / "migration-capabilities" / f"{cap_id}.json"
        cap = json.loads(cap_path.read_text(encoding="utf-8"))
        assert cap["status"] == "consumed"
        assert cap["consumed_reason"] == "migration_backfill_apply"
        assert _run(tmp_path, "check", "--namespace", NS).returncode == 2

    def test_backfill_is_idempotent_with_fresh_record(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t1", status="offered", stage=None, scope=False)
        _mint(tmp_path)
        _run(tmp_path, "backfill", "--namespace", NS, "--apply")
        _mint(tmp_path)
        r2 = _run(tmp_path, "backfill", "--namespace", NS, "--apply")
        assert r2.returncode == 0
        assert "stage on 0 tasks" in r2.stdout

    def test_backfill_ledgers_per_task_records(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t1", status="ready", stage="S6_IMPLEMENTATION", scope=False)
        _make_task(tmp_path, "t2", status="done", stage="S6_IMPLEMENTATION", scope=False)
        _mint(tmp_path)
        _run(tmp_path, "backfill", "--namespace", NS, "--apply")
        ledger = tmp_path / ".cache" / "hapax" / "migration-capabilities" / "ledger.jsonl"
        records = [json.loads(line) for line in ledger.read_text().splitlines()]
        kinds = [record["kind"] for record in records]
        assert "capability_mint" in kinds
        assert "migration_backfill_task" in kinds
        assert "migration_backfill" in kinds
        assert "capability_consume" in kinds
        task_records = [record for record in records if record["kind"] == "migration_backfill_task"]
        assert len(task_records) == 1
        assert task_records[0]["task_id"] == "t1"
        assert task_records[0]["stage_before"] == "stage: S6_IMPLEMENTATION"
        assert task_records[0]["stage_after"] == "stage: S7_RELEASE"
        assert task_records[0]["scope_before"] is None
        assert task_records[0]["scope_after"] == "mutation_scope_refs: []"

    def test_script_wording_does_not_overstate_security_model(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        assert "unforgeable" not in text
        assert "root capability" not in text
        assert '"nonce"' not in text

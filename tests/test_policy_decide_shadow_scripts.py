"""Tests for the shadow PRODUCER/EVALUATOR scripts (reform fix: unblock 3b-cutover).

* ``scripts/policy-decide-shadow-replay`` — the timer entry: replays the gate
  decision log into the divergence ledger.
* ``scripts/policy-decide-shadow-eval`` — the checkable cutover gate: exit 0 iff
  "shadow-week-clean + asymmetric-divergence", exit 1 otherwise. This exit-code
  contract is what lets the manifest auto-advancer actually gate 3b-cutover.
"""

import json
import subprocess
import sys
from pathlib import Path

from shared.policy_decide import replay_decision_log

REPO_ROOT = Path(__file__).parent.parent
EVAL = REPO_ROOT / "scripts" / "policy-decide-shadow-eval"
REPLAY = REPO_ROOT / "scripts" / "policy-decide-shadow-replay"


def _row(**over) -> dict:
    base = dict(
        ts="2026-05-31T12:00:00Z",
        legacy_exit=0,
        role="theta",
        session_id="sid-1",
        task_id="reform-fix-shadow-producer-20260531",
        tool_name="Edit",
        command="",
        file_path="shared/policy_decide.py",
        mutation_surface="source",
        status="in_progress",
        assigned_to="theta",
        authority_case="CASE-FORMAL-GOVERNANCE-001",
        parent_spec="~/spec.md",
        stage="S6_IMPLEMENTATION",
        implementation_authorized="true",
        source_mutation_authorized="true",
        docs_mutation_authorized="true",
        runtime_mutation_authorized="false",
        mutation_scope_refs="shared/policy_decide.py\x1ftests/",
    )
    base.update(over)
    return base


def _seed_clean_week(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "decisions.jsonl"
    ledger = tmp_path / "shadow.jsonl"
    rows = [_row(ts=f"2026-05-{1 + (i * 7) // 39:02d}T12:00:00Z") for i in range(40)]
    rows.append(
        _row(tool_name="Bash", command="git checkout -b f origin/main", file_path="", legacy_exit=2)
    )
    log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    replay_decision_log(log, ledger)
    return log, ledger


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True, timeout=60
    )


class TestEvalScript:
    def test_absent_ledger_exits_nonzero(self, tmp_path: Path) -> None:
        r = _run(
            EVAL,
            "--decision-log",
            str(tmp_path / "absent.jsonl"),
            "--ledger",
            str(tmp_path / "absent-shadow.jsonl"),
        )
        assert r.returncode == 1
        assert json.loads(r.stdout)["clean"] is False

    def test_clean_week_exits_zero(self, tmp_path: Path) -> None:
        log, ledger = _seed_clean_week(tmp_path)
        r = _run(
            EVAL,
            "--decision-log",
            str(log),
            "--ledger",
            str(ledger),
            "--min-days",
            "7",
            "--min-decisions",
            "10",
        )
        assert r.returncode == 0, r.stdout + r.stderr
        out = json.loads(r.stdout)
        assert out["clean"] is True
        assert out["tightening"] == 0

    def test_tightening_week_exits_nonzero(self, tmp_path: Path) -> None:
        log = tmp_path / "decisions.jsonl"
        ledger = tmp_path / "shadow.jsonl"
        rows = [_row(ts=f"2026-05-{1 + (i * 7) // 39:02d}T12:00:00Z") for i in range(40)]
        rows.append(_row(legacy_exit=0, authority_case=""))  # legacy allowed, new blocks
        log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        replay_decision_log(log, ledger)
        r = _run(EVAL, "--decision-log", str(log), "--ledger", str(ledger), "--min-decisions", "10")
        assert r.returncode == 1
        assert json.loads(r.stdout)["tightening"] >= 1


class TestReplayScript:
    def test_builds_divergence_ledger_and_prints_summary(self, tmp_path: Path) -> None:
        log = tmp_path / "decisions.jsonl"
        ledger = tmp_path / "shadow.jsonl"
        log.write_text(
            json.dumps(
                _row(
                    tool_name="Bash",
                    command="git checkout -b f origin/main",
                    file_path="",
                    legacy_exit=2,
                )
            )
            + "\n",
            encoding="utf-8",
        )
        r = _run(REPLAY, "--decision-log", str(log), "--ledger", str(ledger))
        assert r.returncode == 0, r.stdout + r.stderr
        summary = json.loads(r.stdout)
        assert summary["divergences"] == 1
        assert summary["loosening"] == 1
        ledger_rows = [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]
        assert len(ledger_rows) == 1
        assert ledger_rows[0]["new_verdict"] == "allow"

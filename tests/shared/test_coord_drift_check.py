"""Tests for the projection<->vault stage drift check (master design §4.3)."""

from __future__ import annotations

from pathlib import Path

from shared.coord_event_log import CoordEventLog
from shared.coord_projection import (
    CoordProjection,
    StageDrift,
    diff_projection_vs_vault,
    emit_stage_transition,
    load_vault_task_stages,
)


def _log(tmp_path: Path) -> CoordEventLog:
    return CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )


def _note(directory: Path, task_id: str, stage: str | None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    stage_line = f"stage: {stage}\n" if stage else ""
    (directory / f"{task_id}-slug.md").write_text(
        f"---\ntype: cc-task\ntask_id: {task_id}\n{stage_line}---\n\n# body\n",
        encoding="utf-8",
    )


def test_load_vault_task_stages_reads_active_and_closed(tmp_path: Path) -> None:
    _note(tmp_path / "active", "task-a", "S6_IMPLEMENTATION")
    _note(tmp_path / "closed", "task-b", "S11_CLOSED")
    _note(tmp_path / "active", "task-c", None)  # no stage → skipped

    stages = load_vault_task_stages(tmp_path)
    assert stages == {"task-a": "S6_IMPLEMENTATION", "task-b": "S11_CLOSED"}


def test_load_vault_task_stages_missing_dir_is_empty(tmp_path: Path) -> None:
    assert load_vault_task_stages(tmp_path / "absent") == {}


def test_no_drift_when_ledger_matches_vault(tmp_path: Path) -> None:
    log = _log(tmp_path)
    emit_stage_transition(
        event_log=log,
        task_id="task-a",
        from_stage="S5",
        to_stage="S6_IMPLEMENTATION",
        authority_case="CASE-X",
        actor="zeta",
        no_go_snapshot={},
    )
    projection = CoordProjection.from_replay(log.replay())
    assert diff_projection_vs_vault(projection, {"task-a": "S6_IMPLEMENTATION"}) == []


def test_drift_when_vault_lags_ledger(tmp_path: Path) -> None:
    log = _log(tmp_path)
    emit_stage_transition(
        event_log=log,
        task_id="task-a",
        from_stage="S6",
        to_stage="S7_RELEASE",
        authority_case="CASE-X",
        actor="zeta",
        no_go_snapshot={},
    )
    projection = CoordProjection.from_replay(log.replay())
    drifts = diff_projection_vs_vault(projection, {"task-a": "S6_IMPLEMENTATION"})
    assert drifts == [
        StageDrift(task_id="task-a", ledger_stage="S7_RELEASE", vault_stage="S6_IMPLEMENTATION")
    ]


def test_drift_for_vault_only_and_ledger_only_subjects(tmp_path: Path) -> None:
    log = _log(tmp_path)
    emit_stage_transition(
        event_log=log,
        task_id="ledger-only",
        from_stage="S5",
        to_stage="S6",
        authority_case="CASE-X",
        actor="zeta",
        no_go_snapshot={},
    )
    projection = CoordProjection.from_replay(log.replay())
    drifts = diff_projection_vs_vault(projection, {"vault-only": "S7"})
    assert drifts == [
        StageDrift(task_id="ledger-only", ledger_stage="S6", vault_stage=None),
        StageDrift(task_id="vault-only", ledger_stage=None, vault_stage="S7"),
    ]

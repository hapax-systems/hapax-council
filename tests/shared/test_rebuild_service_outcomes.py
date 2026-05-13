from __future__ import annotations

import json
from pathlib import Path

from shared.rebuild_service_outcomes import assess_rebuild_outcome_ledger

NOW = 1_778_690_700.0
CURRENT_SHA = "a" * 40


def test_assess_rebuild_outcome_ledger_classifies_fresh_current_records(
    tmp_path: Path,
) -> None:
    _write_outcome(
        tmp_path,
        sha_key="voice",
        current_sha=CURRENT_SHA,
        outcome="restart_timeout_late_active",
        timestamp="2026-05-13T16:45:00Z",
    )
    _write_outcome(
        tmp_path,
        sha_key="compositor",
        current_sha=CURRENT_SHA,
        outcome="missing_unit",
        timestamp="2026-05-13T16:45:00Z",
    )
    _write_outcome(
        tmp_path,
        sha_key="reverie",
        current_sha=CURRENT_SHA,
        outcome="deferred_pressure",
        timestamp="2026-05-13T16:45:00Z",
    )

    assessment = assess_rebuild_outcome_ledger(
        tmp_path,
        current_sha=CURRENT_SHA,
        now_epoch=NOW,
        max_age_s=900.0,
    )

    assert [record.sha_key for record in assessment.clearable_records] == ["voice"]
    assert [record.sha_key for record in assessment.blocker_records] == ["compositor"]
    assert [record.sha_key for record in assessment.warning_records] == ["reverie"]
    assert assessment.to_evidence()["record_count"] == 3


def test_assess_rebuild_outcome_ledger_rejects_stale_and_sha_mismatched_records(
    tmp_path: Path,
) -> None:
    _write_outcome(
        tmp_path,
        sha_key="old",
        current_sha=CURRENT_SHA,
        outcome="restart_success",
        timestamp="2026-05-13T16:00:00Z",
    )
    _write_outcome(
        tmp_path,
        sha_key="other-sha",
        current_sha="b" * 40,
        outcome="restart_success",
        timestamp="2026-05-13T16:45:00Z",
    )

    assessment = assess_rebuild_outcome_ledger(
        tmp_path,
        current_sha=CURRENT_SHA,
        now_epoch=NOW,
        max_age_s=60.0,
    )

    assert not assessment.clearable_records
    assert [record.category for record in assessment.stale_or_unknown_records] == [
        "stale_unknown",
        "stale_unknown",
    ]
    assert {record.reason for record in assessment.stale_or_unknown_records} == {
        "outcome timestamp is stale",
        "outcome current_sha does not match origin/main",
    }


def _write_outcome(
    state_dir: Path,
    *,
    sha_key: str,
    current_sha: str,
    outcome: str,
    timestamp: str,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "timestamp": timestamp,
        "sha_key": sha_key,
        "service": f"hapax-{sha_key}.service",
        "current_sha": current_sha,
        "last_sha": "none",
        "outcome": outcome,
    }
    (state_dir / f"last-{sha_key}-outcome.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

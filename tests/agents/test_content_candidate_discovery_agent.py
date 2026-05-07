"""Tests for the runnable content candidate discovery agent."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from agents.content_candidate_discovery import run_once
from shared.content_candidate_discovery import ContentSourceObservation

NOW = datetime(2026, 4, 29, 4, 45, tzinfo=UTC)


def _observation() -> ContentSourceObservation:
    return ContentSourceObservation(
        observation_id="obs_agent_smoke",
        source_class="local_state",
        source_id="local_task_state",
        format_id="claim_audit",
        subject="content candidate discovery smoke",
        subject_cluster="discovery_infra",
        retrieved_at=NOW - timedelta(minutes=3),
        freshness_ttl_s=3600,
        public_mode="dry_run",
        rights_state="operator_original",
        rights_hints=("operator_original",),
        substrate_refs=("cc_task",),
        evidence_refs=("obsidian:cc_task",),
        provenance_refs=("obsidian:cc_task",),
        source_priors={"grounding_yield_prior": 0.6},
        grounding_question="Can the discovery daemon emit an auditable candidate?",
    )


def test_run_once_writes_candidate_and_health(tmp_path) -> None:
    source = tmp_path / "source.jsonl"
    output = tmp_path / "opportunities.jsonl"
    audit = tmp_path / "audit.jsonl"
    health = tmp_path / "health.json"
    source.write_text(_observation().model_dump_json() + "\n", encoding="utf-8")

    result = run_once(
        input_path=source, output_path=output, audit_path=audit, health_path=health, now=NOW
    )

    assert result["counts"] == {
        "emitted": 1,
        "held": 0,
        "blocked": 0,
        "malformed": 0,
        "no_candidate": 0,
    }
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["status"] == "emitted"
    assert rows[0]["scheduled_show_created"] is False
    assert json.loads(health.read_text(encoding="utf-8"))["schedules_programmes_directly"] is False
    assert not audit.exists()


def test_run_once_reports_malformed_rows_without_failing(tmp_path) -> None:
    source = tmp_path / "source.jsonl"
    output = tmp_path / "opportunities.jsonl"
    audit = tmp_path / "audit.jsonl"
    health = tmp_path / "health.json"
    source.write_text("{bad json\n" + _observation().model_dump_json() + "\n", encoding="utf-8")

    result = run_once(
        input_path=source, output_path=output, audit_path=audit, health_path=health, now=NOW
    )

    assert result["counts"]["malformed"] == 1
    assert result["counts"]["emitted"] == 1
    assert result["counts"]["no_candidate"] == 0
    audit_rows = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert audit_rows[0]["type"] == "malformed_observation"
    assert audit_rows[0]["diagnostic_only"] is True
    assert audit_rows[0]["release_boundary"] == "closed"
    assert audit_rows[0]["runtime_boundary"] == "closed"
    assert audit_rows[0]["loadable"] is False
    assert audit_rows[0]["line"] == "1"


def test_missing_source_path_is_healthy_zero_work(tmp_path) -> None:
    health = tmp_path / "health.json"

    result = run_once(
        input_path=tmp_path / "missing.jsonl",
        output_path=tmp_path / "out.jsonl",
        audit_path=tmp_path / "audit.jsonl",
        health_path=health,
        now=NOW,
    )

    assert result["counts"] == {
        "emitted": 0,
        "held": 0,
        "blocked": 0,
        "malformed": 0,
        "no_candidate": 1,
    }
    assert result["source_observation_path_exists"] is False
    assert health.exists()
    audit_rows = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert audit_rows == [
        {
            "candidate_count": 0,
            "diagnostic_only": True,
            "loadable": False,
            "malformed_count": 0,
            "manifest_eligible": False,
            "no_candidate_reason": "source_observation_path_missing",
            "nonempty_line_count": 0,
            "observed_at": NOW.isoformat(),
            "observation_count": 0,
            "qdrant_eligible": False,
            "raw_line_count": 0,
            "release_boundary": "closed",
            "release_eligible": False,
            "runtime_actionable": False,
            "runtime_boundary": "closed",
            "scheduled_show_created": False,
            "scheduler_action": "none",
            "source": str(tmp_path / "missing.jsonl"),
            "source_observation_path_exists": False,
            "type": "no_candidate_diagnostic",
        }
    ]


def test_empty_source_path_ledgers_no_candidate_metadata(tmp_path) -> None:
    source = tmp_path / "source.jsonl"
    source.write_text("\n\n", encoding="utf-8")

    result = run_once(
        input_path=source,
        output_path=tmp_path / "out.jsonl",
        audit_path=tmp_path / "audit.jsonl",
        health_path=tmp_path / "health.json",
        now=NOW,
    )

    assert result["counts"]["no_candidate"] == 1
    assert result["no_candidate_reason"] == "source_observation_jsonl_empty"
    audit_row = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8"))
    assert audit_row["type"] == "no_candidate_diagnostic"
    assert audit_row["source_observation_path_exists"] is True
    assert audit_row["raw_line_count"] == 2
    assert audit_row["nonempty_line_count"] == 0
    assert audit_row["release_boundary"] == "closed"
    assert audit_row["runtime_boundary"] == "closed"
    assert audit_row["loadable"] is False

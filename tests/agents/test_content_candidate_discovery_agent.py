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

    assert result["counts"] == {"emitted": 1, "held": 0, "blocked": 0, "malformed": 0}
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
    audit_rows = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert audit_rows[0]["type"] == "malformed_observation"
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

    assert result["counts"] == {"emitted": 0, "held": 0, "blocked": 0, "malformed": 0}
    assert result["source_observation_path_exists"] is False
    assert health.exists()

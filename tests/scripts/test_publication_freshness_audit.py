from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "publication-freshness-audit.py"
REPORT = REPO_ROOT / "docs/repo-pres/github-public-surface-live-state-reconcile.json"
GENERATED_AT = "2026-07-07T16:40:00Z"


def _report_generated_at() -> str:
    return json.loads(REPORT.read_text(encoding="utf-8"))["generated_at"]


def _iso_after_report(seconds: int = 0) -> str:
    generated_at = datetime.fromisoformat(_report_generated_at().replace("Z", "+00:00"))
    return (
        (generated_at + timedelta(seconds=seconds))
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def test_publication_freshness_audit_dry_run_prints_state_without_writing(
    tmp_path: Path,
) -> None:
    events = tmp_path / "freshness-events.jsonl"
    state = tmp_path / "freshness-state.json"
    generated_at = _iso_after_report()

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--github-report",
            str(REPORT),
            "--output-events",
            str(events),
            "--output-state",
            str(state),
            "--generated-at",
            generated_at,
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(result.stdout)
    report_generated_at = _report_generated_at()
    assert payload["authority"] == "freshness_witness_only"
    assert payload["claim_ceiling"] == "freshness_witness_only"
    assert payload["github_checked_at"] == report_generated_at
    assert payload["events"]
    assert {event["occurred_at"] for event in payload["events"]} == {report_generated_at}
    assert {event["generated_at"] for event in payload["events"]} == {generated_at}
    assert payload["state"]["envelopes"]
    assert {envelope["checked_at"] for envelope in payload["state"]["envelopes"]} == {
        report_generated_at
    }
    assert not events.exists()
    assert not state.exists()


def test_publication_freshness_audit_writes_events_and_state(tmp_path: Path) -> None:
    events = tmp_path / "freshness-events.jsonl"
    state = tmp_path / "freshness-state.json"
    generated_at = _iso_after_report()

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--github-report",
            str(REPORT),
            "--output-events",
            str(events),
            "--output-state",
            str(state),
            "--generated-at",
            generated_at,
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    summary = json.loads(result.stdout)
    event_rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    state_payload = json.loads(state.read_text(encoding="utf-8"))
    report_generated_at = _report_generated_at()
    assert summary["authority"] == "freshness_witness_only"
    assert summary["github_checked_at"] == report_generated_at
    assert summary["events_written"] == len(event_rows)
    assert state_payload["claim_ceiling"] == "freshness_witness_only"
    assert {row["occurred_at"] for row in event_rows} == {report_generated_at}
    assert any(row["event_type"] == "publication.surface_readback" for row in event_rows)


def test_publication_freshness_audit_events_match_assessed_snapshot(
    tmp_path: Path,
) -> None:
    events = tmp_path / "freshness-events.jsonl"
    state = tmp_path / "freshness-state.json"
    generated_at = _iso_after_report(seconds=60)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--github-report",
            str(REPORT),
            "--output-events",
            str(events),
            "--output-state",
            str(state),
            "--generated-at",
            generated_at,
            "--github-ttl-s",
            "1",
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    summary = json.loads(result.stdout)
    event_rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    state_payload = json.loads(state.read_text(encoding="utf-8"))
    snapshot_by_surface = {
        envelope["surface_id"]: envelope for envelope in state_payload["envelopes"]
    }
    assert summary["blockers"]
    assert any(envelope["freshness_result"] == "stale" for envelope in snapshot_by_surface.values())
    for event in event_rows:
        envelope = snapshot_by_surface[event["surface_id"]]
        assert event["result"] == envelope["freshness_result"]
        assert event["blocks"] == envelope["blocks"]


def test_publication_freshness_audit_rejects_run_time_before_source_report(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--github-report",
            str(REPORT),
            "--output-events",
            str(tmp_path / "freshness-events.jsonl"),
            "--output-state",
            str(tmp_path / "freshness-state.json"),
            "--generated-at",
            "2026-05-01T00:50:00Z",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "generated_at predates the source GitHub report generated_at" in result.stderr


def test_publication_freshness_audit_rejects_malformed_generated_at(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--github-report",
            str(REPORT),
            "--output-events",
            str(tmp_path / "freshness-events.jsonl"),
            "--output-state",
            str(tmp_path / "freshness-state.json"),
            "--generated-at",
            "not-a-timestamp",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "invalid --generated-at timestamp" in result.stderr
    assert "Next action: rerun with a valid UTC ISO timestamp" in result.stderr
    assert "Traceback" not in result.stderr


def test_publication_freshness_audit_rejects_invalid_github_ttl(
    tmp_path: Path,
) -> None:
    generated_at = _iso_after_report()

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--github-report",
            str(REPORT),
            "--output-events",
            str(tmp_path / "freshness-events.jsonl"),
            "--output-state",
            str(tmp_path / "freshness-state.json"),
            "--generated-at",
            generated_at,
            "--github-ttl-s",
            "315360000",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "invalid --github-ttl-s 315360000" in result.stderr
    assert "Next action: rerun with the governed GitHub public-readback freshness SLO" in (
        result.stderr
    )
    assert "Traceback" not in result.stderr


def test_publication_freshness_audit_malformed_report_names_next_action(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "malformed-report.json"
    malformed.write_text("{not-json", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--github-report",
            str(malformed),
            "--output-events",
            str(tmp_path / "freshness-events.jsonl"),
            "--output-state",
            str(tmp_path / "freshness-state.json"),
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "malformed GitHub public-surface report" in result.stderr
    assert "Next action: regenerate the report" in result.stderr


def test_publication_freshness_audit_schema_invalid_report_names_next_action(
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "schema-invalid-report.json"
    invalid.write_text(json.dumps({"generated_at": GENERATED_AT}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--github-report",
            str(invalid),
            "--output-events",
            str(tmp_path / "freshness-events.jsonl"),
            "--output-state",
            str(tmp_path / "freshness-state.json"),
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "schema-invalid GitHub public-surface report" in result.stderr
    assert "Next action: regenerate the report" in result.stderr

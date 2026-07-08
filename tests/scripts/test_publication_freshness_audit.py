from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "publication-freshness-audit.py"
REPORT = REPO_ROOT / "docs/repo-pres/github-public-surface-live-state-reconcile.json"
GENERATED_AT = "2026-05-01T00:50:00Z"


def test_publication_freshness_audit_dry_run_prints_state_without_writing(
    tmp_path: Path,
) -> None:
    events = tmp_path / "freshness-events.jsonl"
    state = tmp_path / "freshness-state.json"

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
            GENERATED_AT,
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(result.stdout)
    assert payload["authority"] == "freshness_witness_only"
    assert payload["claim_ceiling"] == "freshness_witness_only"
    assert payload["events"]
    assert payload["state"]["envelopes"]
    assert not events.exists()
    assert not state.exists()


def test_publication_freshness_audit_writes_events_and_state(tmp_path: Path) -> None:
    events = tmp_path / "freshness-events.jsonl"
    state = tmp_path / "freshness-state.json"

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
            GENERATED_AT,
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    summary = json.loads(result.stdout)
    event_rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    state_payload = json.loads(state.read_text(encoding="utf-8"))
    assert summary["authority"] == "freshness_witness_only"
    assert summary["events_written"] == len(event_rows)
    assert state_payload["claim_ceiling"] == "freshness_witness_only"
    assert any(row["event_type"] == "publication.surface_readback" for row in event_rows)

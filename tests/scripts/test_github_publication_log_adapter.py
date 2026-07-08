from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "github-publication-log-adapter.py"
REPORT = REPO_ROOT / "docs/repo-pres/github-public-surface-live-state-reconcile.json"
GENERATED_AT = "2026-05-01T00:50:00Z"


def test_adapter_dry_run_prints_jsonl_without_writing(tmp_path: Path) -> None:
    output = tmp_path / "publication-log.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--report",
            str(REPORT),
            "--output",
            str(output),
            "--generated-at",
            GENERATED_AT,
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert rows
    assert not output.exists()
    assert rows[0]["event_type"].startswith("publication.github.")
    assert rows[0]["claim_ceiling"] == "publication_witness_rows"
    assert rows[0]["truth_authority"] is False


def test_adapter_appends_rows_and_reports_witness_only_summary(tmp_path: Path) -> None:
    output = tmp_path / "publication-log.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--report",
            str(REPORT),
            "--output",
            str(output),
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    summary = json.loads(result.stdout)
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert summary == {
        "authority": "witness_only",
        "claim_ceiling": "publication_witness_rows",
        "events_written": len(rows),
        "output": str(output),
        "report": str(REPORT),
    }
    assert any(row["publication_state"] == "missing_or_private" for row in rows)
    assert any(row["surface"] == "package" for row in rows)

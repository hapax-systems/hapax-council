"""CLI tests for scripts/hapax-formal-governance-export."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from shared.formal_governance_runtime import template_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-formal-governance-export"
NOW = "2026-05-17T08:40:00Z"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPT), *args], text=True, capture_output=True, check=False)


def test_dry_run_exports_unknown_without_constraints(tmp_path: Path) -> None:
    result = _run(
        "--constraints-root", str(tmp_path / "constraints"), "--dry-run", "--json", "--now", NOW
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    operation = payload["status_predicates"]["operations"][0]
    assert operation["gate_state"] == "unknown"
    assert operation["authority_class"] == "control"


def test_writes_status_and_constraint_snapshots(tmp_path: Path) -> None:
    constraints = tmp_path / "constraints"
    active = constraints / "active"
    active.mkdir(parents=True)
    text = template_frontmatter(
        constraint_id="CONSTRAINT-cli",
        title="CLI constraint",
        scope_type="surface",
        scope_ref="sbcl-clog-control-surface",
        effect="deny",
        reason="test",
        created_at=datetime(2026, 5, 17, 8, 39, tzinfo=UTC),
    ).replace("lifecycle_state: draft", "lifecycle_state: active")
    (active / "CONSTRAINT-cli.md").write_text(text, encoding="utf-8")
    output = tmp_path / "out"

    result = _run("--constraints-root", str(constraints), "--output-dir", str(output), "--now", NOW)

    assert result.returncode == 0, result.stderr
    status = json.loads((output / "status-predicates.json").read_text(encoding="utf-8"))
    constraints_payload = json.loads(
        (output / "operator-constraints.json").read_text(encoding="utf-8")
    )
    assert status["operations"][0]["gate_state"] == "forbidden"
    assert constraints_payload["constraints"][0]["constraint_id"] == "CONSTRAINT-cli"

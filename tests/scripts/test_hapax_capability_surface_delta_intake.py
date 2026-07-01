from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-capability-surface-delta-intake"
FIXTURES = REPO_ROOT / "config" / "capability-surface-delta-fixtures.json"
NOW = "2026-07-01T04:30:00Z"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _write_live_producer(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "schema_ref": "schemas/capability-surface-delta.schema.json",
                "generated_from": [
                    "cc-task-capability-freshness-remediation-and-discovery-automation-20260630"
                ],
                "declared_at": NOW,
                "descriptors": [
                    {
                        "descriptor_schema": 1,
                        "surface_id": "route.codex.headless.full",
                        "descriptor_ref": "platform-capability-registry:codex.headless.full",
                        "surface_kind": "model_route",
                        "authority_ceiling": "authoritative",
                        "observed_at": "2026-07-01T04:00:00Z",
                        "stale_after": "1h",
                        "evidence_refs": ["test:descriptor"],
                        "route_id": "codex.headless.full",
                        "resource_pools": ["subscription_quota"],
                    }
                ],
                "deltas": [
                    {
                        "delta_schema": 1,
                        "delta_id": "test:single-live-producer-delta",
                        "source": "unit-test",
                        "observed_at": NOW,
                        "detected_by": "unit-test",
                        "surface_id": "route.codex.headless.full",
                        "delta_kind": "stale_determination",
                        "prior_descriptor_ref": "platform-capability-registry:codex.headless.full",
                        "observed_descriptor_ref": "platform-capability-receipt:codex:expired",
                        "evidence_refs": ["test:expired-codex-receipt"],
                        "authority_ceiling": "authoritative",
                        "affected_resource_pools": ["subscription_quota"],
                        "privacy_sensitive": True,
                        "public_egress": False,
                        "money_rail": False,
                        "freshness_state": "stale",
                        "required_intake_action": "refresh_receipt",
                        "remediation_ref": "cc-task-capability-freshness-remediation-and-discovery-automation-20260630",
                        "summary": "single live producer row",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_dry_run_reports_would_write_without_mutating_task_root(tmp_path: Path) -> None:
    result = _run(
        "--fixtures",
        str(FIXTURES),
        "--task-root",
        str(tmp_path),
        "--now",
        NOW,
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["applied"] is False
    assert payload["loaded"] == 3
    assert len(payload["would_write"]) == 3
    assert payload["written"] == []
    assert not (tmp_path / "active").exists()


def test_apply_writes_delta_tasks_and_is_idempotent(tmp_path: Path) -> None:
    result = _run(
        "--fixtures",
        str(FIXTURES),
        "--task-root",
        str(tmp_path),
        "--now",
        NOW,
        "--apply",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert len(payload["written"]) == 3
    written_paths = list((tmp_path / "active").glob("*.md"))
    assert len(written_paths) == 3
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in written_paths)
    assert "capability_surface_delta_id:" in rendered
    assert "capability_surface_id:" in rendered
    assert "required_intake_action:" in rendered
    assert "cc-task-capability-freshness-remediation-and-discovery-automation-20260630" in rendered

    again = _run(
        "--fixtures",
        str(FIXTURES),
        "--task-root",
        str(tmp_path),
        "--now",
        NOW,
        "--apply",
        "--json",
    )

    assert again.returncode == 0, again.stderr
    second = json.loads(again.stdout)
    assert second["written"] == []
    assert len(second["skipped_existing"]) == 3


def test_apply_refuses_default_fixture_to_default_task_vault() -> None:
    result = _run("--now", NOW, "--apply", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "refusing to apply checked-in capability-surface delta fixtures" in payload["error"]
    assert "next action: pass a live producer file" in payload["error"]


def test_cli_accepts_live_producer_file_without_fixture_set_id(tmp_path: Path) -> None:
    producer = tmp_path / "producer.json"
    task_root = tmp_path / "tasks"
    _write_live_producer(producer)

    result = _run(
        "--fixtures",
        str(producer),
        "--task-root",
        str(task_root),
        "--now",
        NOW,
        "--apply",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["loaded"] == 1
    assert len(payload["written"]) == 1
    written = Path(payload["written"][0]).read_text(encoding="utf-8")
    assert 'capability_surface_delta_id: "test:single-live-producer-delta"' in written
    assert 'capability_surface_id: "route.codex.headless.full"' in written
    assert 'required_intake_action: "refresh_receipt"' in written


def test_cli_detect_from_descriptors_smoke(tmp_path: Path) -> None:
    result = _run(
        "--fixtures",
        str(FIXTURES),
        "--task-root",
        str(tmp_path),
        "--now",
        NOW,
        "--detect-from-descriptors",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["loaded"] >= 3
    assert payload["would_write"]
    assert payload["written"] == []


def test_cli_bad_now_reports_next_action(tmp_path: Path) -> None:
    result = _run(
        "--fixtures",
        str(FIXTURES),
        "--task-root",
        str(tmp_path),
        "--now",
        "not-a-timestamp",
        "--json",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "invalid --now value" in payload["error"]
    assert "next action: pass an ISO-8601 UTC timestamp" in payload["error"]

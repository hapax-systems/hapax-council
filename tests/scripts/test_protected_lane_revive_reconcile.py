"""Fixture tests for the protected-lane revive/reconcile guard."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "protected-lane-revive-reconcile.py"
NOW = "2026-04-30T11:05:00Z"


def _write_task(
    vault: Path,
    task_id: str,
    *,
    status: str = "claimed",
    assigned_to: str = "cx-violet",
    claimed_at: str = "2026-04-30T10:00:00Z",
) -> Path:
    path = vault / "active" / f"{task_id}.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        dedent(
            f"""\
            ---
            task_id: {task_id}
            title: Fixture task
            status: {status}
            assigned_to: {assigned_to}
            claimed_at: {claimed_at}
            updated_at: 2026-04-30T10:00:00Z
            ---

            # Fixture task

            ## Session log
            """
        ),
        encoding="utf-8",
    )
    return path


def _write_relay(
    relay_dir: Path, *, current_claim: object = None, extra: dict | None = None
) -> Path:
    payload = {
        "session": "cx-violet",
        "status": "restore_watch",
        "current_claim": current_claim,
        "updated": "2026-04-30T10:01:00Z",
    }
    if extra:
        payload.update(extra)
    relay_dir.mkdir(parents=True)
    path = relay_dir / "cx-violet.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _write_dashboard(
    path: Path, *, warning: str = "claim_file_without_relay_current_claim"
) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                "# Codex session health",
                "",
                "| Session | Role | Control | Screen | Task | Task status | Branch | PR | Why / current status | Warnings |",
                "|---|---|---|---|---|---|---|---|---|---|",
                f"| cx-violet | protected research lane | tmux | visible | task-a | claimed | branch | - | stale | {warning} |",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _dashboard_regenerator(tmp_path: Path, dashboard: Path) -> Path:
    script = tmp_path / "regen-dashboard"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"cat > {dashboard} <<'EOF'\n"
        "# Codex session health\n"
        "| Session | Role | Control | Screen | Task | Task status | Branch | PR | Why / current status | Warnings |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
        "| cx-violet | protected research lane | none | required-missing | - | offered | - | - | restored | - |\n"
        "EOF\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _run(
    tmp_path: Path,
    *,
    protected_active: str = "false",
    dashboard_command: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    args = [
        sys.executable,
        str(SCRIPT),
        "--session",
        "cx-violet",
        "--vault-root",
        str(tmp_path / "vault"),
        "--cache-dir",
        str(tmp_path / "cache"),
        "--relay-dir",
        str(tmp_path / "relay"),
        "--dashboard",
        str(tmp_path / "vault" / "_dashboard" / "codex-session-health.md"),
        "--worktree-path",
        str(tmp_path / "worktree"),
        "--now",
        NOW,
        "--protected-active",
        protected_active,
        "--tmux-visible",
        "false",
        "--ack-token",
        "ack-fixture",
    ]
    if dashboard_command is not None:
        args.extend(["--dashboard-command", str(dashboard_command)])
    return subprocess.run(args, capture_output=True, text=True, check=False, timeout=10)


def _json(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def test_relay_null_claim_file_present_archives_marker_restores_task_and_dashboard(
    tmp_path: Path,
) -> None:
    task_id = "grant-opportunity-scout-attestation-queue"
    task = _write_task(tmp_path / "vault", task_id)
    _write_relay(tmp_path / "relay", current_claim=None)
    claim = tmp_path / "cache" / "cc-active-task-cx-violet"
    claim.parent.mkdir(parents=True)
    claim.write_text(f"{task_id}\n", encoding="utf-8")
    dashboard = tmp_path / "vault" / "_dashboard" / "codex-session-health.md"
    _write_dashboard(dashboard)
    regen = _dashboard_regenerator(tmp_path, dashboard)

    result = _run(tmp_path, dashboard_command=regen)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = _json(result)
    assert payload["resolution"] == "stale_claim_archived_task_restored"
    archive = Path(payload["archive_path"])
    assert archive.exists()
    assert archive.read_text(encoding="utf-8") == f"{task_id}\n"
    assert not claim.exists()
    text = task.read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    assert frontmatter["status"] == "offered"
    assert frontmatter["assigned_to"] == "unassigned"
    assert frontmatter["claimed_at"] is None
    assert "revive-reconcile guard archived stale claim marker" in text
    assert "claim_file_without_relay_current_claim" not in dashboard.read_text(encoding="utf-8")
    relay = yaml.safe_load((tmp_path / "relay" / "cx-violet.yaml").read_text(encoding="utf-8"))
    assert relay["revive_checkpoint"]["ack_token"] == "ack-fixture"
    assert relay["revive_checkpoint"]["archive_path"] == str(archive)
    audit = Path(payload["audit_path"])
    assert audit.exists()
    assert json.loads(audit.read_text(encoding="utf-8"))["resolution"] == payload["resolution"]
    assert relay["revive_checkpoint"]["audit_path"] == str(audit)


def test_relay_claim_matches_marker_makes_no_cleanup(tmp_path: Path) -> None:
    task_id = "active-protected-task"
    task = _write_task(tmp_path / "vault", task_id)
    _write_relay(tmp_path / "relay", current_claim=task_id)
    claim = tmp_path / "cache" / "cc-active-task-cx-violet"
    claim.parent.mkdir(parents=True)
    claim.write_text(f"{task_id}\n", encoding="utf-8")
    _write_dashboard(tmp_path / "vault" / "_dashboard" / "codex-session-health.md", warning="-")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = _json(result)
    assert payload["resolution"] == "relay_claim_matches_marker"
    assert claim.exists()
    frontmatter = yaml.safe_load(task.read_text(encoding="utf-8").split("---", 2)[1])
    assert frontmatter["status"] == "claimed"
    assert payload["archive_path"] is None


def test_task_claimed_by_another_lane_is_conflict_not_cleanup(tmp_path: Path) -> None:
    task_id = "owned-elsewhere"
    _write_task(tmp_path / "vault", task_id, assigned_to="cx-amber")
    _write_relay(tmp_path / "relay", current_claim=None)
    claim = tmp_path / "cache" / "cc-active-task-cx-violet"
    claim.parent.mkdir(parents=True)
    claim.write_text(f"{task_id}\n", encoding="utf-8")
    _write_dashboard(tmp_path / "vault" / "_dashboard" / "codex-session-health.md")

    result = _run(tmp_path, protected_active="false")

    assert result.returncode == 2
    payload = _json(result)
    assert payload["resolution"] == "conflict_no_cleanup"
    assert "task_claimed_by_other_lane" in payload["warnings"]
    assert claim.exists()


def test_named_durable_output_missing_is_degraded_not_green(tmp_path: Path) -> None:
    task_id = "durable-output-missing"
    _write_task(tmp_path / "vault", task_id)
    _write_relay(
        tmp_path / "relay",
        current_claim=task_id,
        extra={"durable_outputs": [str(tmp_path / "missing-output.json")]},
    )
    claim = tmp_path / "cache" / "cc-active-task-cx-violet"
    claim.parent.mkdir(parents=True)
    claim.write_text(f"{task_id}\n", encoding="utf-8")
    _write_dashboard(tmp_path / "vault" / "_dashboard" / "codex-session-health.md", warning="-")

    result = _run(tmp_path)

    assert result.returncode == 1
    payload = _json(result)
    assert payload["state"] == "degraded"
    assert payload["durable_outputs"] == [
        {"path": str(tmp_path / "missing-output.json"), "exists": False, "non_empty": False}
    ]


def test_open_and_unknown_research_agents_are_reported(tmp_path: Path) -> None:
    task_id = "research-agent-visible"
    _write_task(tmp_path / "vault", task_id)
    _write_relay(
        tmp_path / "relay",
        current_claim=task_id,
        extra={
            "spawned_research_agents": [
                {"id": "agent-open", "status": "running"},
                "agent-unknown",
            ]
        },
    )
    claim = tmp_path / "cache" / "cc-active-task-cx-violet"
    claim.parent.mkdir(parents=True)
    claim.write_text(f"{task_id}\n", encoding="utf-8")
    _write_dashboard(tmp_path / "vault" / "_dashboard" / "codex-session-health.md", warning="-")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = _json(result)
    assert payload["research_agents"] == [
        {"id": "agent-open", "status": "open"},
        {"id": "agent-unknown", "status": "unknown"},
    ]
    assert "research_agent_open_or_unknown" in payload["warnings"]

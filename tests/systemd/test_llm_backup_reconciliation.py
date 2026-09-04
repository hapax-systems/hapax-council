from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "systemd" / "scripts" / "backup.sh"
UNITS = REPO / "systemd" / "units"
MANIFESTS = REPO / "agents" / "manifests"
RUNBOOK = REPO / "docs" / "runbooks" / "llm-stack-backup-reconciliation.md"
INFRA_REGISTRY = REPO / "config" / "infrastructure" / "host-storage-registry.json"
EXPECTED_TIMERS = REPO / "systemd" / "expected-timers.yaml"


def _unit_value(text: str, section: str, key: str) -> str | None:
    in_section = False
    values: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == f"[{section}]"
            continue
        if in_section and "=" in stripped:
            unit_key, _, value = stripped.partition("=")
            if unit_key.strip() == key:
                values.append(value.strip())
    return " ".join(values) if values else None


def test_llm_backup_script_is_deprecated_receipt() -> None:
    text = SCRIPT.read_text()

    assert "DEPRECATED" in text
    assert "hapax-backup-local.service" in text
    assert "hapax-backup-gdrive-critical.service" in text
    assert "hapax-backup-remote.service" in text
    assert "docs/runbooks/llm-stack-backup-reconciliation.md" in text
    assert "pg_dump" not in text
    assert "ragdb" not in text
    assert "LANGFUSE_SECRET_KEY" not in text


def test_llm_backup_receipt_writes_no_legacy_artifacts(tmp_path: Path) -> None:
    legacy_target = tmp_path / "legacy-backup-root"
    result = subprocess.run(
        [str(SCRIPT), str(legacy_target)],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert "No backup artifacts were written" in result.stdout
    assert not legacy_target.exists()


def test_llm_backup_unit_uses_source_controlled_receipt() -> None:
    text = (UNITS / "llm-backup.service").read_text()
    exec_start = _unit_value(text, "Service", "ExecStart")
    working_dir = _unit_value(text, "Service", "WorkingDirectory")

    assert exec_start is not None
    assert "/home/hapax/projects/hapax-council/systemd/scripts/backup.sh" in exec_start
    assert "/home/hapax/Scripts/setup" not in exec_start
    assert "llm-stack-scripts" not in exec_start
    assert working_dir == "/home/hapax/projects/hapax-council"


def test_backup_tier_units_execute_source_controlled_scripts() -> None:
    """Backup units execute only the governed source-activation worktree."""
    archived_repo = "-".join(("distro", "work"))
    activation_root = "%h/.cache/hapax/source-activation/worktree"
    mutable_project_path = re.compile(r"(?:~|/home/[^/]+)/projects(?:/|$)")
    for lane in ("local", "remote"):
        text = (UNITS / f"hapax-backup-{lane}.service").read_text()
        exec_start = _unit_value(text, "Service", "ExecStart")
        assert exec_start == f"{activation_root}/scripts/hapax-backup-{lane}", lane
        assert _unit_value(text, "Service", "WorkingDirectory") == activation_root
        assert "hapax-source-activate.service" in (_unit_value(text, "Unit", "Wants") or "")
        assert "hapax-source-activate.service" in (_unit_value(text, "Unit", "After") or "")
        assert _unit_value(text, "Service", "ExecCondition") is None
        assert not mutable_project_path.search(text), lane
        assert archived_repo not in text, lane
        assert _unit_value(text, "Unit", "RequiresMountsFor"), lane
        mount_conditions = _unit_value(text, "Unit", "ConditionPathIsMountPoint")
        assert mount_conditions is not None and "/store" in mount_conditions, lane
        if lane == "local":
            assert "/mnt/nas" in mount_conditions
        script = REPO / "scripts" / f"hapax-backup-{lane}"
        assert script.is_file(), script
        assert script.stat().st_mode & 0o111, f"{script} must be executable"
        subprocess.run(["bash", "-n", str(script)], check=True, capture_output=True, timeout=10)
        assert archived_repo not in script.read_text(), lane
        assert (UNITS / f"hapax-backup-{lane}.timer").is_file(), (
            f"{lane} timer must be source-controlled"
        )
    remote = (REPO / "scripts" / "hapax-backup-remote").read_text()
    assert 'SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"' in remote
    assert 'DR_SCRIPT="$SCRIPT_DIR/hapax-cachyos-restore"' in remote
    dr = REPO / "scripts" / "hapax-cachyos-restore"
    assert dr.is_file() and dr.stat().st_mode & 0o111, dr
    subprocess.run(["bash", "-n", str(dr)], check=True, capture_output=True, timeout=10)
    assert archived_repo not in dr.read_text()


def test_activation_hold_does_not_skip_backup_producers_or_watchdog() -> None:
    """A HOLD keeps the last activated release live; it must not disable backup health."""
    for unit_name in (
        "hapax-backup-local.service",
        "hapax-backup-remote.service",
        "hapax-backup-watchdog.service",
    ):
        text = (UNITS / unit_name).read_text()

        assert "hapax-source-activate.service" in (_unit_value(text, "Unit", "Wants") or "")
        assert "hapax-source-activate.service" in (_unit_value(text, "Unit", "After") or "")
        assert _unit_value(text, "Service", "ExecCondition") is None
        assert _unit_value(text, "Unit", "OnFailure") == "notify-failure@%n.service"


def test_backup_watchdog_executes_only_governed_source_activation() -> None:
    """The scheduled verifier must observe the same code activated for its producers."""
    text = (UNITS / "hapax-backup-watchdog.service").read_text()
    activation_root = "%h/.cache/hapax/source-activation/worktree"
    mutable_project_path = re.compile(r"(?:~|/home/[^/]+|%h)/projects(?:/|$)")

    assert _unit_value(text, "Service", "ExecStart") == (
        f"{activation_root}/scripts/hapax-backup-watchdog"
    )
    assert _unit_value(text, "Service", "WorkingDirectory") == activation_root
    assert "hapax-source-activate.service" in (_unit_value(text, "Unit", "Wants") or "")
    assert "hapax-source-activate.service" in (_unit_value(text, "Unit", "After") or "")
    assert _unit_value(text, "Service", "ExecCondition") is None
    assert not mutable_project_path.search(text)


def test_backup_manifests_name_canonical_lanes() -> None:
    llm = yaml.safe_load((MANIFESTS / "llm_backup.yaml").read_text())
    local = yaml.safe_load((MANIFESTS / "backup_local.yaml").read_text())
    remote = yaml.safe_load((MANIFESTS / "backup_remote.yaml").read_text())
    gdrive = yaml.safe_load((MANIFESTS / "backup_gdrive_critical.yaml").read_text())

    assert "Deprecated compatibility receipt" in llm["purpose"]
    assert llm["outputs"] == ["Deprecation receipt in the systemd journal"]
    assert "backup_local" in llm["peers"]
    assert "backup_gdrive_critical" in llm["peers"]
    assert "backup_remote" in llm["peers"]
    assert "/mnt/nas/backups/restic" in local["outputs"][0]
    assert "PostgreSQL" in local["purpose"]
    assert "Qdrant" in local["purpose"]
    assert remote["schedule"] == {
        "type": "timer",
        "systemd_unit": "hapax-backup-remote.timer",
        "interval": "daily",
    }
    assert remote["autonomy"] == "full"
    assert "live daily" in remote["purpose"].lower()
    assert "must not" not in remote["decision_scope"].lower()
    assert gdrive["schedule"]["systemd_unit"] == "hapax-backup-gdrive-critical.timer"
    assert "rclone:gdrive:hapax-backups/restic-critical" in gdrive["narrative"]
    assert "prune" in gdrive["decision_scope"]


def test_reconciliation_runbook_documents_restore_path() -> None:
    text = RUNBOOK.read_text()

    for expected in [
        "hapax-backup-local.service",
        "hapax-backup-gdrive-critical.service",
        "postgres-all.sql",
        "Qdrant",
        "n8n",
        "$HOME/llm-stack/",
        "scripts/hapax-backup-watchdog",
        "rclone:gdrive:hapax-backups/restic-critical",
        "hapax-backup-remote.timer",
        "/store/llm-data/backup-dumps-local",
        "/store/llm-data/backup-dumps-remote",
        "hapax-cachyos-restore.sh",
        "## Recheck",
    ]:
        assert expected in text

    assert "No obsolete `ragdb` database assumption" in text
    assert "-".join(("distro", "work")) not in text


def test_backup_remote_policy_is_live_daily_everywhere() -> None:
    manifest = yaml.safe_load((MANIFESTS / "backup_remote.yaml").read_text())
    registry = json.loads(INFRA_REGISTRY.read_text())
    expected_timers = yaml.safe_load(EXPECTED_TIMERS.read_text())["timers"]
    policy = next(
        row for row in registry["backup_policies"] if row["store_id"] == "b2-restic-offsite"
    )

    assert manifest["schedule"]["type"] == "timer"
    assert manifest["schedule"]["interval"] == "daily"
    assert manifest["schedule"]["systemd_unit"] == "hapax-backup-remote.timer"
    assert policy["cadence"] == "daily"
    assert policy["intended_state"] == "enabled"
    assert policy["next_action"] is None
    assert expected_timers["backup_remote"] == "hapax-backup-remote.timer"


def test_backup_storage_roots_have_one_canonical_registry_table() -> None:
    registry = json.loads(INFRA_REGISTRY.read_text())
    policies = {row["store_id"]: row for row in registry["backup_policies"]}

    assert policies["local-nas-restic"]["required_mount_roots"] == [
        "/store",
        "/mnt/nas",
    ]
    assert policies["b2-restic-offsite"]["required_mount_roots"] == ["/store"]

    result = subprocess.run(
        [
            str(REPO / "scripts" / "hapax-cachyos-restore"),
            "--print-storage-roots",
            str(INFRA_REGISTRY),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.splitlines() == ["/mnt/nas", "/store"]

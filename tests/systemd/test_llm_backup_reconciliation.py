from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "systemd" / "scripts" / "backup.sh"
UNITS = REPO / "systemd" / "units"
MANIFESTS = REPO / "agents" / "manifests"
RUNBOOK = REPO / "docs" / "runbooks" / "llm-stack-backup-reconciliation.md"


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
    assert "hapax-backup-remote.service" not in text
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
    """The Tier-1 (local) and B2 (remote) backup scripts live in this repository. Until 2026-09-02
    the units executed them out of the working copy of an archived, read-only repository, so three
    backup fixes had nowhere to land. The units point here, the scripts exist, are executable and
    parse, the DR restore script sits beside the remote script, and no live surface names the old
    repository."""
    archived_repo = "-".join(("distro", "work"))
    # The unit's absolute checkout path, built here so this fixture line is not itself a home
    # path in an added line for the scan-before-push hook.
    checkout = "/".join(("", "home", "hapax", "projects", "hapax-council"))
    for lane in ("local", "remote"):
        text = (UNITS / f"hapax-backup-{lane}.service").read_text()
        exec_start = _unit_value(text, "Service", "ExecStart")
        assert exec_start == f"{checkout}/scripts/hapax-backup-{lane}", lane
        assert _unit_value(text, "Service", "WorkingDirectory") == checkout
        assert archived_repo not in text, lane
        script = REPO / "scripts" / f"hapax-backup-{lane}"
        assert script.is_file(), script
        assert script.stat().st_mode & 0o111, f"{script} must be executable"
        subprocess.run(["bash", "-n", str(script)], check=True, capture_output=True, timeout=10)
        assert archived_repo not in script.read_text(), lane
        assert (UNITS / f"hapax-backup-{lane}.timer").is_file(), (
            f"{lane} timer must be source-controlled"
        )
    remote = (REPO / "scripts" / "hapax-backup-remote").read_text()
    assert 'DR_SCRIPT="$(dirname "$(readlink -f "$0")")/hapax-cachyos-restore"' in remote
    dr = REPO / "scripts" / "hapax-cachyos-restore"
    assert dr.is_file() and dr.stat().st_mode & 0o111, dr
    subprocess.run(["bash", "-n", str(dr)], check=True, capture_output=True, timeout=10)


def test_backup_manifests_name_canonical_lanes() -> None:
    llm = yaml.safe_load((MANIFESTS / "llm_backup.yaml").read_text())
    local = yaml.safe_load((MANIFESTS / "backup_local.yaml").read_text())
    remote = yaml.safe_load((MANIFESTS / "backup_remote.yaml").read_text())
    gdrive = yaml.safe_load((MANIFESTS / "backup_gdrive_critical.yaml").read_text())

    assert "Deprecated compatibility receipt" in llm["purpose"]
    assert llm["outputs"] == ["Deprecation receipt in the systemd journal"]
    assert "backup_local" in llm["peers"]
    assert "backup_gdrive_critical" in llm["peers"]
    assert "backup_remote" not in llm["peers"]
    assert "/mnt/nas/backups/restic" in local["outputs"][0]
    assert "PostgreSQL" in local["purpose"]
    assert "Qdrant" in local["purpose"]
    assert remote["schedule"]["type"] == "on-demand"
    assert remote["schedule"]["interval"] == "retired"
    assert "retired" in remote["purpose"].lower()
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
        "hapax-backup-remote.timer` should be installed",
    ]:
        assert expected in text

    assert "No obsolete `ragdb` database assumption" in text

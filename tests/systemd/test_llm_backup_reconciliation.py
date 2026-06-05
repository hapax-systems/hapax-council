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


def test_backup_manifests_name_canonical_lanes() -> None:
    llm = yaml.safe_load((MANIFESTS / "llm_backup.yaml").read_text())
    local = yaml.safe_load((MANIFESTS / "backup_local.yaml").read_text())
    remote = yaml.safe_load((MANIFESTS / "backup_remote.yaml").read_text())

    assert "Deprecated compatibility receipt" in llm["purpose"]
    assert llm["outputs"] == ["Deprecation receipt in the systemd journal"]
    assert "backup_local" in llm["peers"]
    assert "backup_remote" in llm["peers"]
    assert "/mnt/nas/backups/restic" in local["outputs"][0]
    assert "PostgreSQL" in local["purpose"]
    assert "Qdrant" in local["purpose"]
    assert remote["schedule"]["interval"] == "weekly"
    assert "Backblaze B2" in remote["purpose"]


def test_reconciliation_runbook_documents_restore_path() -> None:
    text = RUNBOOK.read_text()

    for expected in [
        "hapax-backup-local.service",
        "hapax-backup-remote.service",
        "postgres-all.sql",
        "Qdrant",
        "n8n",
        "$HOME/llm-stack/",
        "scripts/hapax-backup-watchdog",
    ]:
        assert expected in text

    assert "No obsolete `ragdb` database assumption" in text

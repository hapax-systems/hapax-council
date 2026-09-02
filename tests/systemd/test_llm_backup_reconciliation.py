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
    assert "hapax-backup-critical-offsite.service" in text
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


def test_backup_manifests_name_canonical_lanes() -> None:
    llm = yaml.safe_load((MANIFESTS / "llm_backup.yaml").read_text())
    local = yaml.safe_load((MANIFESTS / "backup_local.yaml").read_text())
    remote = yaml.safe_load((MANIFESTS / "backup_remote.yaml").read_text())
    critical_offsite = yaml.safe_load((MANIFESTS / "backup_critical_offsite.yaml").read_text())

    assert "Deprecated compatibility receipt" in llm["purpose"]
    assert llm["outputs"] == ["Deprecation receipt in the systemd journal"]
    assert "backup_local" in llm["peers"]
    assert "backup_critical_offsite" in llm["peers"]
    assert "backup_remote" not in llm["peers"]
    assert "/mnt/nas/backups/restic" in local["outputs"][0]
    assert "PostgreSQL" in local["purpose"]
    assert "Qdrant" in local["purpose"]
    assert remote["schedule"]["type"] == "on-demand"
    assert remote["schedule"]["interval"] == "retired"
    assert "retired" in remote["purpose"].lower()
    assert critical_offsite["schedule"]["systemd_unit"] == "hapax-backup-critical-offsite.timer"
    assert "rclone:r2:hapax-restic-critical" in critical_offsite["narrative"]
    assert critical_offsite["capabilities"] == ["restic_backup", "s3_upload"]
    assert "prune" in critical_offsite["decision_scope"]


def test_reconciliation_runbook_documents_restore_path() -> None:
    text = RUNBOOK.read_text()

    for expected in [
        "hapax-backup-local.service",
        "hapax-backup-critical-offsite.service",
        "postgres-all.sql",
        "Qdrant",
        "n8n",
        "$HOME/llm-stack/",
        "scripts/hapax-backup-watchdog",
        "rclone:r2:hapax-restic-critical",
        "hapax-backup-remote.timer",
        "b2:hapax-backups/restic",
    ]:
        assert expected in text

    assert "No obsolete `ragdb` database assumption" in text


def test_backup_surfaces_have_no_retired_critical_provider_names() -> None:
    old_job_name = "-".join(("gdrive", "critical"))
    old_env_name = "_".join(("GDRIVE", "CRITICAL"))
    old_repo_name = "".join(("gdrive", ":hapax-backups"))
    allowed_vault_evidence_names = {
        f"{old_job_name}-offsite-bootstrap-proof-2026-06-05.md",
        f"{old_job_name}-offsite-source-automation-plan-2026-06-05.md",
    }
    forbidden = (old_job_name, old_env_name, old_repo_name)
    failures: list[str] = []

    for relative_root in (
        "scripts",
        "systemd",
        "config/infrastructure",
        "agents/manifests",
    ):
        for path in (REPO / relative_root).rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for allowed in allowed_vault_evidence_names:
                text = text.replace(allowed, "")
            for old_name in forbidden:
                if old_name in text:
                    failures.append(f"{path.relative_to(REPO)}: {old_name}")

    assert not failures, "Retired critical backup names remain:\n" + "\n".join(failures)

"""Tests for hapax-restore-verify: automated restore procedure validation.

Disaster recovery Phase 2 — verify that backup artifacts produced by
backup.sh can be validated for restorability without performing actual
restores (which require service downtime).
"""

from __future__ import annotations

import json
import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-restore-verify"
BACKUP_SCRIPT = REPO_ROOT / "systemd" / "scripts" / "backup.sh"


class TestScriptStructure:
    def test_script_exists_and_is_executable(self):
        assert SCRIPT.exists()
        assert SCRIPT.stat().st_mode & 0o111

    def test_script_has_strict_mode(self):
        text = SCRIPT.read_text()
        assert "set -euo pipefail" in text

    def test_script_exits_nonzero_on_failure(self):
        text = SCRIPT.read_text()
        assert "exit 1" in text

    def test_script_checks_all_backup_targets(self):
        text = SCRIPT.read_text()
        for target in [
            "claude-config",
            "langfuse",
            "qdrant",
            "postgres",
            "n8n",
            "systemd",
            "cache-state",
        ]:
            assert target in text, f"Missing restore check for {target}"


class TestRestoreVerifyEmpty:
    def test_no_args_exits_2(self):
        result = subprocess.run(
            [str(SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2

    def test_nonexistent_dir_exits_2(self):
        result = subprocess.run(
            [str(SCRIPT), "/tmp/nonexistent-hapax-backup-dir-abc123"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2

    def test_empty_backup_dir_fails(self, tmp_path):
        backup = tmp_path / "20260520-010000"
        backup.mkdir()
        result = subprocess.run(
            [str(SCRIPT), str(backup)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "No artifacts verified" in result.stdout


class TestRestoreVerifyValid:
    @pytest.fixture()
    def valid_backup(self, tmp_path):
        backup = tmp_path / "20260520-010000"
        backup.mkdir()

        claude = backup / "claude-config"
        claude.mkdir()
        (claude / "settings.json").write_text("{}")

        langfuse = backup / "langfuse-prompts.json"
        langfuse.write_text(json.dumps({"prompts": []}))

        qdrant = backup / "qdrant"
        qdrant.mkdir()
        (qdrant / "documents-snapshot.json").write_text(
            json.dumps({"name": "documents", "status": "ok"})
        )

        postgres = backup / "postgres"
        postgres.mkdir()
        (postgres / "litellm.sql").write_text(
            "-- PostgreSQL dump\nSET statement_timeout = 0;\n"
            "CREATE TABLE proxy_config (id serial PRIMARY KEY);\n"
            + "INSERT INTO proxy_config VALUES (1);\n"
            * 10
        )

        n8n = backup / "n8n"
        n8n.mkdir()
        (n8n / "workflows.json").write_text(json.dumps([{"id": "1", "name": "test"}]))

        systemd = backup / "systemd"
        systemd.mkdir()
        for i in range(6):
            (systemd / f"hapax-svc-{i}.service").write_text(f"[Unit]\nDescription=svc-{i}\n")

        cache = backup / "cache-state"
        cache.mkdir()
        logos = cache / "logos"
        logos.mkdir()
        (logos / "state.json").write_text("{}")

        return backup

    def test_valid_backup_passes(self, valid_backup):
        result = subprocess.run(
            [str(SCRIPT), str(valid_backup)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "All verified artifacts are restorable" in result.stdout

    def test_valid_backup_reports_check_count(self, valid_backup):
        result = subprocess.run(
            [str(SCRIPT), str(valid_backup)],
            capture_output=True,
            text=True,
        )
        assert "Checked: 7 passed" in result.stdout

    def test_latest_flag_resolves(self, tmp_path):
        backup = tmp_path / "20260519-010000"
        backup.mkdir()
        latest = tmp_path / "20260520-010000"
        latest.mkdir()
        claude = latest / "claude-config"
        claude.mkdir()
        (claude / "settings.json").write_text("{}")
        systemd = latest / "systemd"
        systemd.mkdir()
        for i in range(6):
            (systemd / f"svc-{i}.service").write_text(f"[Unit]\nDescription=svc-{i}\n")

        result = subprocess.run(
            [str(SCRIPT), "--latest", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert "20260520" in result.stdout


class TestRestoreVerifyCorrupt:
    def test_corrupt_langfuse_json_fails(self, tmp_path):
        backup = tmp_path / "20260520-010000"
        backup.mkdir()
        (backup / "langfuse-prompts.json").write_text("not json{{{")
        systemd = backup / "systemd"
        systemd.mkdir()
        for i in range(6):
            (systemd / f"svc-{i}.service").write_text(f"[Unit]\nDescription=svc-{i}\n")

        result = subprocess.run(
            [str(SCRIPT), str(backup)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "Langfuse prompts: invalid JSON" in result.stdout

    def test_empty_postgres_dump_fails(self, tmp_path):
        backup = tmp_path / "20260520-010000"
        backup.mkdir()
        postgres = backup / "postgres"
        postgres.mkdir()
        (postgres / "litellm.sql").write_text("tiny")

        result = subprocess.run(
            [str(SCRIPT), str(backup)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "suspiciously small" in result.stdout

    def test_corrupt_qdrant_snapshot_fails(self, tmp_path):
        backup = tmp_path / "20260520-010000"
        backup.mkdir()
        qdrant = backup / "qdrant"
        qdrant.mkdir()
        (qdrant / "documents-snapshot.json").write_text("broken{")

        result = subprocess.run(
            [str(SCRIPT), str(backup)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "invalid snapshot" in result.stdout

    def test_too_few_systemd_units_fails(self, tmp_path):
        backup = tmp_path / "20260520-010000"
        backup.mkdir()
        systemd = backup / "systemd"
        systemd.mkdir()
        (systemd / "one.service").write_text("[Unit]\n")

        result = subprocess.run(
            [str(SCRIPT), str(backup)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "only 1 unit files" in result.stdout


class TestBackupRestoreCoverage:
    def test_backup_targets_match_restore_checks(self):
        backup_text = BACKUP_SCRIPT.read_text()
        restore_text = SCRIPT.read_text()
        targets = [
            ("claude-config", "claude"),
            ("langfuse", "langfuse"),
            ("qdrant", "qdrant"),
            ("postgres", "postgres"),
            ("n8n", "n8n"),
            ("systemd", "systemd"),
            ("cache-state", "cache"),
        ]
        for restore_key, backup_key in targets:
            assert restore_key in restore_text, f"Restore missing: {restore_key}"
            assert backup_key in backup_text.lower(), f"Backup missing: {backup_key}"

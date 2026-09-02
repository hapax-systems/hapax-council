"""Tests for hapax-backup-watchdog script and systemd units."""

import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-backup-watchdog"
GDRIVE_SCRIPT = REPO_ROOT / "scripts" / "hapax-backup-gdrive-critical"
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-backup-watchdog.service"
TIMER = REPO_ROOT / "systemd" / "units" / "hapax-backup-watchdog.timer"
GDRIVE_SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-backup-gdrive-critical.service"
GDRIVE_TIMER = REPO_ROOT / "systemd" / "units" / "hapax-backup-gdrive-critical.timer"
USER_PRESET = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"


def _parse_unit(path: pathlib.Path) -> dict[str, dict[str, list[str]]]:
    """Parse a systemd unit file, handling duplicate keys."""
    sections: dict[str, dict[str, list[str]]] = {}
    current = None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, {})
        elif "=" in line and current is not None:
            key, _, val = line.partition("=")
            sections[current].setdefault(key.strip(), []).append(val.strip())
    return sections


class TestWatchdogScript:
    """Verify script structure and safety."""

    def test_script_exists_and_is_executable(self):
        assert SCRIPT.exists(), f"{SCRIPT} does not exist"
        assert SCRIPT.stat().st_mode & 0o111, f"{SCRIPT} is not executable"

    def test_script_has_set_euo_pipefail(self):
        text = SCRIPT.read_text()
        assert "set -euo pipefail" in text, "Script must use strict mode"

    def test_script_uses_pass_for_secrets(self):
        """Secrets must come from pass, never hardcoded."""
        text = SCRIPT.read_text()
        assert "pass show" in text, "Must use pass for restic password"

    def test_script_checks_tier1_and_live_b2(self):
        text = SCRIPT.read_text()
        assert "Tier1-NAS" in text, "Must check Tier 1 (NAS) snapshots"
        assert 'check_snapshot_age "$TIER2_B2_REPO" "Tier2-B2"' in text
        assert 'check_restic_integrity "$TIER2_B2_REPO" "Tier2-B2"' in text
        assert 'check_postgres_dump_in_snapshot "$TIER2_B2_REPO" "Tier2-B2"' in text
        assert "rclone:b2:hapax-backups/restic" in text
        assert "TIER2_B2_PASSWORD_ENTRY" in text

    def test_script_checks_gdrive_critical(self):
        text = SCRIPT.read_text()
        assert "GDrive-Critical" in text, "Must check GDrive critical snapshots"
        assert "rclone:gdrive:hapax-backups/restic-critical" in text
        assert "GDRIVE_CRITICAL_PASSWORD_ENTRY" in text

    def test_script_checks_qdrant(self):
        text = SCRIPT.read_text()
        assert "qdrant" in text.lower(), "Must check Qdrant snapshots"

    def test_script_sends_ntfy_on_failure(self):
        text = SCRIPT.read_text()
        assert "NTFY_URL" in text, "Must notify via ntfy on failure"

    def test_script_has_nonzero_exit_on_failure(self):
        text = SCRIPT.read_text()
        assert "exit 1" in text, "Must exit non-zero on failure"

    def test_script_checks_postgres_dump_presence_in_newest_snapshot(self):
        text = SCRIPT.read_text()
        assert "check_postgres_dump_in_snapshot" in text
        assert "postgres-all.sql" in text
        assert "implausibly small" in text

    def test_dump_check_fails_when_restic_listing_has_no_dump(self, tmp_path, monkeypatch):
        text = SCRIPT.read_text()
        start = text.index("check_postgres_dump_in_snapshot() {")
        end = text.index("\n}\n", start) + 3
        probe = tmp_path / "probe.sh"
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "pass").write_text("#!/usr/bin/env bash\necho secret\n", encoding="utf-8")
        (bin_dir / "restic").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        (bin_dir / "pass").chmod(0o755)
        (bin_dir / "restic").chmod(0o755)
        probe.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            "FAILURES=()\nlog() { :; }\n"
            + text[start:end]
            + "check_postgres_dump_in_snapshot repo lbl entry\n"
            + 'printf "%s\\n" "${FAILURES[@]}"\n'
            + "exit ${#FAILURES[@]}\n",
            encoding="utf-8",
        )
        probe.chmod(0o755)
        env = {**__import__("os").environ, "PATH": f"{bin_dir}:{__import__('os').environ['PATH']}"}
        result = subprocess.run([str(probe)], capture_output=True, text=True, timeout=10, env=env)
        assert result.returncode == 1
        assert "NO postgres-all.sql" in result.stdout

    def test_script_bash_syntax_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"


class TestGDriveCriticalScript:
    """Verify bounded GDrive critical backup source script."""

    def test_script_exists_and_is_executable(self):
        assert GDRIVE_SCRIPT.exists(), f"{GDRIVE_SCRIPT} does not exist"
        assert GDRIVE_SCRIPT.stat().st_mode & 0o111, "Script must be executable"

    def test_script_uses_gdrive_critical_repo(self):
        text = GDRIVE_SCRIPT.read_text()
        assert "rclone:gdrive:hapax-backups/restic-critical" in text
        assert "backblaze/restic-password" in text
        assert "pass show" in text

    def test_script_is_bounded_not_broad_b2(self):
        text = GDRIVE_SCRIPT.read_text()
        assert "docker exec postgres pg_dumpall" not in text
        assert "/tmp/hapax-backup-dumps" not in text
        assert "/data/minio" not in text
        assert 'snapshots" | jq' not in text
        assert "restic forget" in text
        assert "--dry-run" in text
        assert "--prune" not in text

    def test_script_refuses_unreadable_manifest_paths(self):
        text = GDRIVE_SCRIPT.read_text()
        assert "validate_manifest_readability" in text
        assert "refusing partial snapshot" in text

    def test_materialize_fails_when_tier1_has_no_dump(self, tmp_path):
        text = GDRIVE_SCRIPT.read_text()
        start = text.index("materialize_validated_dump() {")
        end = text.index("\nappend_required() {", start)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "pass").write_text("#!/usr/bin/env bash\necho secret\n", encoding="utf-8")
        (bin_dir / "restic").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        (bin_dir / "pass").chmod(0o755)
        (bin_dir / "restic").chmod(0o755)
        dump = tmp_path / "postgres-dumps" / "postgres-all.sql"
        probe = tmp_path / "probe.sh"
        probe.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            f"POSTGRES_DUMP_PATH={dump}\n"
            "TIER1_REPO=repo\nTIER1_PASSWORD_ENTRY=entry\n"
            "POSTGRES_DUMP_MIN_BYTES=1000000000\n"
            "log() { :; }\n" + text[start:end] + "materialize_validated_dump\n",
            encoding="utf-8",
        )
        probe.chmod(0o755)
        env = {**__import__("os").environ, "PATH": f"{bin_dir}:{__import__('os').environ['PATH']}"}
        result = subprocess.run([str(probe)], capture_output=True, text=True, timeout=10, env=env)
        assert result.returncode == 1
        assert "contains no postgres-all.sql" in result.stderr

    def test_materialize_does_not_truncate_durable_path_when_restic_fails(self, tmp_path):
        text = GDRIVE_SCRIPT.read_text()
        start = text.index("materialize_validated_dump() {")
        end = text.index("\nappend_required() {", start)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "pass").write_text("#!/usr/bin/env bash\necho secret\n", encoding="utf-8")
        (bin_dir / "restic").write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"$1\" == ls ]]; then echo '-rw- 1 1 2000000000 date /snap/postgres-all.sql'; exit 0; fi\n"
            "echo partial-bytes; exit 1\n",
            encoding="utf-8",
        )
        (bin_dir / "pass").chmod(0o755)
        (bin_dir / "restic").chmod(0o755)
        durable = tmp_path / "postgres-all.sql"
        durable.write_text("keep-me", encoding="utf-8")
        probe = tmp_path / "probe.sh"
        probe.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            f"POSTGRES_DUMP_PATH={durable}\n"
            "TIER1_REPO=repo\nTIER1_PASSWORD_ENTRY=entry\n"
            "POSTGRES_DUMP_MIN_BYTES=1000000000\n"
            "log() { :; }\n" + text[start:end] + "materialize_validated_dump\n",
            encoding="utf-8",
        )
        probe.chmod(0o755)
        env = {**__import__("os").environ, "PATH": f"{bin_dir}:{__import__('os').environ['PATH']}"}
        result = subprocess.run([str(probe)], capture_output=True, text=True, timeout=10, env=env)
        assert result.returncode != 0
        assert durable.read_text(encoding="utf-8") == "keep-me"

    def test_script_requires_validated_dump_on_durable_path(self):
        text = GDRIVE_SCRIPT.read_text()
        assert "append_required" in text
        assert "materialize_validated_dump" in text
        assert "/store/llm-data/postgres-dumps/postgres-all.sql" in text
        assert "/tmp/hapax-backup-dumps" not in text
        assert "restic dump latest" in text

    def test_script_names_the_pitr_rpo_decision_doc(self):
        text = GDRIVE_SCRIPT.read_text()
        assert "postgres-backup-rpo-pitr-decision-2026-06-05.md" in text
        assert "postgres-backup-rpo-decision-2026-06-05.md" not in text

    def test_script_appends_vault_bundle_dir_if_present(self):
        text = GDRIVE_SCRIPT.read_text()
        assert "VAULT_BUNDLE_DIR" in text
        assert "/store/llm-data/vault-bundles" in text

    def test_append_required_fails_closed_when_the_path_is_absent(self, tmp_path):
        """Drive the real function, not a copy. The gdrive script is not source-safe."""
        text = GDRIVE_SCRIPT.read_text()
        start = text.index("append_required() {")
        end = text.index("\n}\n", start) + 3
        extract = tmp_path / "append_required.sh"
        extract.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            + text[start:end]
            + 'append_required "$1" "$2" dump\n',
            encoding="utf-8",
        )
        extract.chmod(0o755)
        manifest = tmp_path / "m"
        missing = tmp_path / "nope"
        result = subprocess.run(
            [str(extract), str(missing), str(manifest)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 1
        assert "required dump missing" in result.stderr
        assert not manifest.exists() or manifest.read_text() == ""

    def test_append_required_writes_the_path_when_it_exists(self, tmp_path):
        text = GDRIVE_SCRIPT.read_text()
        start = text.index("append_required() {")
        end = text.index("\n}\n", start) + 3
        extract = tmp_path / "append_required.sh"
        extract.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            + text[start:end]
            + 'append_required "$1" "$2" dump\n',
            encoding="utf-8",
        )
        extract.chmod(0o755)
        present = tmp_path / "dump.sql"
        present.write_text("ok", encoding="utf-8")
        manifest = tmp_path / "m"
        result = subprocess.run(
            [str(extract), str(present), str(manifest)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert (
            present.resolve().as_posix() in manifest.read_text()
            or str(present) in manifest.read_text()
        )

    def test_script_bash_syntax_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(GDRIVE_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"


class TestWatchdogSystemdUnits:
    """Verify systemd unit file structure."""

    def test_service_file_exists(self):
        assert SERVICE.exists()

    def test_timer_file_exists(self):
        assert TIMER.exists()

    def test_service_is_oneshot(self):
        unit = _parse_unit(SERVICE)
        assert unit["Service"]["Type"] == ["oneshot"]

    def test_service_has_memory_limit(self):
        unit = _parse_unit(SERVICE)
        assert "MemoryMax" in unit["Service"], "Must have MemoryMax"

    def test_service_has_on_failure(self):
        unit = _parse_unit(SERVICE)
        assert "OnFailure" in unit["Unit"], "Must have OnFailure handler"

    def test_service_exec_start_points_to_script(self):
        unit = _parse_unit(SERVICE)
        exec_start = unit["Service"]["ExecStart"][0]
        assert "hapax-backup-watchdog" in exec_start

    def test_timer_has_persistent(self):
        unit = _parse_unit(TIMER)
        assert unit["Timer"]["Persistent"] == ["true"], "Timer must be Persistent=true"

    def test_timer_has_install_section(self):
        unit = _parse_unit(TIMER)
        assert "Install" in unit, "Timer must have [Install] section"

    def test_timer_fires_after_backup_window(self):
        unit = _parse_unit(TIMER)
        on_calendar = unit["Timer"]["OnCalendar"][0]
        time_part = on_calendar.split()[-1]
        hour = int(time_part.split(":")[0])
        assert hour >= 5, f"Timer fires at {hour}:00, should be >=05:00"


class TestGDriveCriticalSystemdUnits:
    """Verify GDrive critical service/timer are source-defined but not auto-enabled."""

    def test_service_and_timer_exist(self):
        assert GDRIVE_SERVICE.exists()
        assert GDRIVE_TIMER.exists()

    def test_service_is_oneshot_and_uses_source_script(self):
        unit = _parse_unit(GDRIVE_SERVICE)
        assert unit["Service"]["Type"] == ["oneshot"]
        exec_start = unit["Service"]["ExecStart"][0]
        assert "scripts/hapax-backup-gdrive-critical" in exec_start
        assert unit["Service"]["MemoryMax"] == ["2G"]
        assert unit["Service"]["CPUQuota"] == ["25%"]

    def test_timer_is_persistent_and_not_auto_enabled(self):
        unit = _parse_unit(GDRIVE_TIMER)
        assert unit["Timer"]["Persistent"] == ["true"]
        assert unit["Timer"]["RandomizedDelaySec"] == ["45m"]
        assert "Install" in unit
        assert "# Hapax-Auto-Enable: true" not in GDRIVE_TIMER.read_text()
        assert "enable hapax-backup-gdrive-critical.timer" not in USER_PRESET.read_text()

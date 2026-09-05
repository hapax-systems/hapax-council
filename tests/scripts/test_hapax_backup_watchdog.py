"""Tests for hapax-backup-watchdog script and systemd units."""

import os
import pathlib
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from tests.scripts.backup_test_support import run_watchdog

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
        result, _, receipt = run_watchdog(tmp_path, listing_mode="absent")
        assert result.returncode == 1
        assert "Tier2-B2: newest snapshot contains NO postgres-all.sql" in result.stdout
        assert "Tier2-B2: newest snapshot contains NO postgres-all.sql" in receipt

    @staticmethod
    def _run_b2_failure(tmp_path: pathlib.Path, mode: str) -> subprocess.CompletedProcess[str]:
        bin_dir = tmp_path / "bin"
        qdrant_dir = tmp_path / "qdrant"
        bin_dir.mkdir()
        qdrant_dir.mkdir()
        for index in range(5):
            (qdrant_dir / f"collection-{index}").mkdir()

        (bin_dir / "pass").write_text(
            "#!/bin/sh\nprintf '%s\\n' test-password\n",
            encoding="utf-8",
        )
        (bin_dir / "restic").write_text(
            """#!/bin/sh
set -eu
is_b2=0
[ "${RESTIC_REPOSITORY:-}" = b2 ] && is_b2=1
case "${1:-}" in
    snapshots)
        if [ "$is_b2" = 1 ] && [ "$B2_MODE" = inaccessible ]; then
            exit 11
        fi
        if [ "$is_b2" = 1 ] && [ "$B2_MODE" = stale ]; then
            printf '[{"id":"abcdef0123456789","time":"%s"}]\n' "$STALE_TIME"
        else
            printf '[{"id":"abcdef0123456789","time":"%s"}]\n' "$RECENT_TIME"
        fi
        ;;
    check)
        if [ "$is_b2" = 1 ] && [ "$B2_MODE" = corrupt ]; then
            exit 12
        fi
        ;;
    ls)
        if [ "$is_b2" = 1 ] && [ "$B2_MODE" = dump-less ]; then
            exit 0
        fi
        printf '%s\n' '-rw-r--r-- 0 0 1000 2026-09-02 00:00:00 /dump/postgres-all.sql'
        ;;
esac
""",
            encoding="utf-8",
        )
        for command in ("pass", "restic"):
            (bin_dir / command).chmod(0o755)
        for command in ("curl", "notify-send"):
            (bin_dir / command).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (bin_dir / command).chmod(0o755)
        alert = tmp_path / "hapax-alert"
        alert.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        alert.chmod(0o755)

        now = datetime.now(UTC)
        env = os.environ.copy()
        env.update(
            {
                "B2_MODE": mode,
                "HAPAX_MONOCLE_MAX_AGE_HOURS": "96",
                "HAPAX_ALERT_BIN": str(alert),
                "HAPAX_GDRIVE_CRITICAL_REPO": "gdrive",
                "HAPAX_POSTGRES_DUMP_MIN_BYTES": "100",
                "HAPAX_QDRANT_SNAP_DIR": str(qdrant_dir),
                "HAPAX_TIER1_REPO": "tier1",
                "HAPAX_TIER2_B2_REPO": "b2",
                "PATH": f"{bin_dir}:/usr/bin:/bin",
                "RECENT_TIME": now.isoformat(),
                "STALE_TIME": (now - timedelta(hours=72)).isoformat(),
            }
        )
        return subprocess.run(
            [str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )

    def test_b2_watchdog_executes_failure_paths(self, tmp_path):
        expected = {
            "stale": "Tier2-B2: latest snapshot is",
            "inaccessible": "Tier2-B2: cannot read snapshots",
            "corrupt": "Tier2-B2: restic check failed",
            "dump-less": "Tier2-B2: newest snapshot contains NO postgres-all.sql",
        }
        for mode, message in expected.items():
            case_dir = tmp_path / mode
            case_dir.mkdir()
            result = self._run_b2_failure(case_dir, mode)
            assert result.returncode == 1, (mode, result.stdout, result.stderr)
            assert message in result.stdout, (mode, result.stdout)

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


@pytest.mark.parametrize("own_age,foreign_age,healthy", [(72, 0, False), (0, 72, True)])
def test_round4_freshness_belongs_to_exact_producer(tmp_path, own_age, foreign_age, healthy):
    result, commands, _ = run_watchdog(
        tmp_path,
        ages={
            "tier2-remote": own_age,
            "monocle-daily": foreign_age,
            "foreign-host": foreign_age,
            "foreign-tag": foreign_age,
        },
        monocle_threshold="96",
    )
    if healthy:
        assert result.returncode == 0
        assert "Tier2-B2: OK" in result.stdout
    else:
        assert result.returncode == 1, "foreign snapshot hid stale podium producer"
        assert "Tier2-B2: latest snapshot is 72h old" in result.stdout
    for host, tag in [
        ("hapax-podium", "tier1-local"),
        ("hapax-podium", "tier2-remote"),
        ("hapax-podium", "gdrive-critical"),
    ]:
        assert any(
            row["args"][0] == "snapshots"
            and "--host" in row["args"]
            and host in row["args"]
            and "--tag" in row["args"]
            and tag in row["args"]
            for row in commands
        )


def test_round4_missing_own_snapshot_is_named_failure(tmp_path):
    result, _, receipt = run_watchdog(tmp_path, ages={"tier2-remote": None})
    assert result.returncode == 1
    assert "Tier2-B2: no snapshots found for hapax-podium/tier2-remote" in receipt


@pytest.mark.parametrize("mode", ["present", "absent", "failed", "foreign-only"])
def test_round4_dump_listing_reports_selected_snapshot_outcome(tmp_path, mode):
    result, commands, receipt = run_watchdog(tmp_path, listing_mode=mode)
    if mode == "present":
        assert result.returncode == 0
        assert "Tier2-B2: postgres dump present, 1000 bytes" in receipt
    elif mode in ("absent", "foreign-only"):
        assert result.returncode == 1
        assert "Tier2-B2: newest snapshot contains NO postgres-all.sql" in receipt
        assert "listing failed" not in receipt
    else:
        assert result.returncode == 1
        assert (
            "Tier2-B2: PostgreSQL listing failed (restic exit 23): simulated listing denied"
            in receipt
        )
        assert "NO postgres-all.sql" not in receipt
    listings = [row["args"] for row in commands if row["repo"] == "b2" and row["args"][0] == "ls"]
    assert len(listings) == 1
    assert f"{2:064x}" in listings[0], "dump check did not use podium freshness snapshot ID"
    assert "latest" not in listings[0]


@pytest.mark.parametrize("mode", ["locked", "locked-legacy", "corrupt"])
def test_round4_integrity_distinguishes_lock_from_corruption(tmp_path, mode):
    result, commands, receipt = run_watchdog(tmp_path, check_mode=mode)
    assert result.returncode == 1
    if mode.startswith("locked"):
        assert "Tier1-NAS: locked / could not acquire the lock" in receipt
        assert "corruption" not in receipt
        assert "hapax-backup-local.service" in receipt
        assert "restic unlock" in receipt and "operator" in receipt
    else:
        assert "possible repo corruption" in receipt
        assert "pack checksum mismatch" in receipt
    assert not any("unlock" in row["args"] for row in commands)


def test_round4_monocle_has_independent_freshness_receipt(tmp_path):
    result, _, receipt = run_watchdog(tmp_path, ages={"tier2-remote": 0, "monocle-daily": 72})
    assert result.returncode == 1, "stale Monocle producer was not checked"
    assert "Tier2-B2: OK" in receipt
    assert "Monocle-B2: latest snapshot is 72h old (max 36h)" in receipt


@pytest.mark.parametrize("threshold", [None, "", "oops", "0", "-1"])
def test_round4_monocle_threshold_must_be_configured(tmp_path, threshold):
    result, _, receipt = run_watchdog(tmp_path, monocle_threshold=threshold)
    assert result.returncode == 1
    assert "Monocle-B2: configuration failure" in receipt
    assert "HAPAX_MONOCLE_MAX_AGE_HOURS" in receipt


def test_round4_every_password_failure_reaches_summary_and_receipt_in_order(tmp_path):
    result, _, receipt = run_watchdog(tmp_path, fail_entries=("nas-password", "b2-password"))
    assert result.returncode == 1
    first = "Tier1-NAS freshness: cannot read restic password from pass entry 'nas-password'"
    second = "Tier2-B2 freshness: cannot read restic password from pass entry 'b2-password'"
    for output in (result.stdout, receipt):
        assert first in output, "first failed password check diagnostic was lost"
        assert second in output, "second failed password check diagnostic was lost"
        assert output.index(first) < output.index(second)
        assert "Tier1-NAS integrity: cannot read restic password" in output
        assert "Tier2-B2 PostgreSQL: cannot read restic password" in output


def test_round4_missing_monocle_snapshot_is_independent_failure(tmp_path):
    result, _, receipt = run_watchdog(tmp_path, ages={"monocle-daily": None})
    assert result.returncode == 1
    assert "Tier2-B2: OK" in receipt
    assert "Monocle-B2: no snapshots found for hapax-monocle/monocle-daily" in receipt


@pytest.mark.parametrize(
    "options,diagnostic,guidance",
    [
        (
            {"fail_entries": ("nas-password",)},  # pragma: allowlist secret
            "cannot read restic password",
            "pass show 'nas-password' >/dev/null",  # pragma: allowlist secret
        ),  # pragma: allowlist secret
        (
            {"empty_entries": ("nas-password",)},  # pragma: allowlist secret
            "is empty",
            "pass insert 'nas-password'",  # pragma: allowlist secret
        ),
        (
            {"ages": {"tier2-remote": None}},
            "PostgreSQL listing not attempted",
            "restic -r 'b2' snapshots --json",
        ),
        (
            {"ages": {"tier2-remote": None}},
            "no snapshots found",
            "restic -r 'b2' snapshots --host hapax-podium --tag tier2-remote",
        ),
        (
            {"check_mode": "corrupt"},
            "possible repo corruption",
            "restic -r 'nas' check --read-data",
        ),
        (
            {"listing_mode": "failed"},
            "PostgreSQL listing failed",
            "restic -r 'b2' ls --long " + f"{2:064x}",
        ),
    ],
)
def test_round5_failure_receipts_include_next_action(tmp_path, options, diagnostic, guidance):
    result, _, receipt = run_watchdog(tmp_path, **options)
    assert result.returncode == 1
    for output in (result.stdout, receipt):
        line = next(line for line in output.splitlines() if diagnostic in line)
        assert guidance in line, "failure receipt omitted recovery command"


def test_round5_runbook_recheck_uses_configured_unit_and_preserves_status():
    text = (REPO_ROOT / "docs/runbooks/llm-stack-backup-reconciliation.md").read_text()
    block = (
        text.split("Recheck the B2 lane's claims on podium:", 1)[1]
        .split("```bash", 1)[1]
        .split("```", 1)[0]
    )
    assert "set -o pipefail" in block
    assert "systemctl --user start hapax-backup-watchdog.service &&" in block
    assert "journalctl --user -u hapax-backup-watchdog.service" in block
    assert "| grep" not in block
    assert "worktree/scripts/hapax-backup-watchdog" not in block

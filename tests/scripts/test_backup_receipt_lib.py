"""Tests for the backup receipt library + receipt-instrumented backup scripts.

Class-closure pins for audit-w0-backup-integrity-20260611:

1. A backup run CANNOT exit green with a failed component — the exit status
   is derived from the per-component witness record in the EXIT trap
   (impossible-by-construction, CLASS-CLOSURE preference (a)).
2. Every component leaves a witness in the backup receipt JSON.
3. n8n export distinguishes "store is empty" (healthy, empty artifact
   written so the artifact is always present in the backup set) from
   "export mechanism broken" (component FAIL).
4. DR script upload fails honestly when the source file is missing
   (the 2026-06-11 instance: ~/.local/bin/hapax-dr-restore.sh never
   existed on podium; upload WARNed and the run stayed green).
5. Units exec the council-versioned scripts, not the unversioned
   distro-work copies; the deployed-only remote timer is versioned.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "scripts" / "hapax-backup-lib.sh"
LOCAL_SH = REPO_ROOT / "scripts" / "hapax-backup-local.sh"
REMOTE_SH = REPO_ROOT / "scripts" / "hapax-backup-remote.sh"
WATCHDOG = REPO_ROOT / "scripts" / "hapax-backup-watchdog"
UNIT_LOCAL = REPO_ROOT / "systemd" / "units" / "hapax-backup-local.service"
UNIT_REMOTE = REPO_ROOT / "systemd" / "units" / "hapax-backup-remote.service"
TIMER_REMOTE = REPO_ROOT / "systemd" / "units" / "hapax-backup-remote.timer"


def run_bash(snippet: str, env_extra: dict[str, str] | None = None, cwd: Path | None = None):
    """Run a bash snippet that sources the receipt lib; return CompletedProcess."""
    env = os.environ.copy()
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", "-c", snippet],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd or REPO_ROOT,
        timeout=60,
    )


def read_receipt(receipt_dir: Path, tier: str) -> dict:
    path = receipt_dir / f"{tier}-latest.json"
    assert path.is_file(), f"receipt not written at {path}"
    with path.open() as f:
        return json.load(f)


@pytest.fixture
def receipt_dir(tmp_path: Path) -> Path:
    d = tmp_path / "receipts"
    return d


class TestReceiptCore:
    def test_all_ok_run_exits_zero_with_full_witness_record(self, receipt_dir):
        proc = run_bash(
            f"""
            set -euo pipefail
            source {LIB}
            receipt_init tier-test
            component step_one true
            component step_two true
            receipt_complete
            """,
            {"HAPAX_BACKUP_RECEIPT_DIR": str(receipt_dir)},
        )
        assert proc.returncode == 0, proc.stderr
        receipt = read_receipt(receipt_dir, "tier-test")
        assert receipt["schema"] == 1
        assert receipt["tier"] == "tier-test"
        assert receipt["failures"] == 0
        assert receipt["aborted"] is False
        assert receipt["exit_code"] == 0
        names = [c["name"] for c in receipt["components"]]
        assert names == ["step_one", "step_two"]
        assert all(c["status"] == "ok" for c in receipt["components"])
        assert all("seconds" in c for c in receipt["components"])

    def test_failed_component_forces_nonzero_exit(self, receipt_dir):
        proc = run_bash(
            f"""
            set -euo pipefail
            source {LIB}
            receipt_init tier-test
            component step_bad false
            component step_after true
            receipt_complete
            """,
            {"HAPAX_BACKUP_RECEIPT_DIR": str(receipt_dir)},
        )
        assert proc.returncode == 1
        receipt = read_receipt(receipt_dir, "tier-test")
        assert receipt["failures"] == 1
        assert receipt["exit_code"] == 1
        # soft component failure does not stop later components
        assert [c["name"] for c in receipt["components"]] == ["step_bad", "step_after"]

    def test_explicit_exit_zero_cannot_mask_a_failed_component(self, receipt_dir):
        """The construction pin: there is no code path to green with a fail witness."""
        proc = run_bash(
            f"""
            set -euo pipefail
            source {LIB}
            receipt_init tier-test
            component step_bad false
            receipt_complete
            exit 0
            """,
            {"HAPAX_BACKUP_RECEIPT_DIR": str(receipt_dir)},
        )
        assert proc.returncode == 1
        assert read_receipt(receipt_dir, "tier-test")["failures"] == 1

    def test_early_exit_zero_without_receipt_complete_is_not_green(self, receipt_dir):
        """An unwitnessed early green exit is forced red + marked aborted."""
        proc = run_bash(
            f"""
            set -euo pipefail
            source {LIB}
            receipt_init tier-test
            component step_one true
            exit 0
            """,
            {"HAPAX_BACKUP_RECEIPT_DIR": str(receipt_dir)},
        )
        assert proc.returncode == 1
        receipt = read_receipt(receipt_dir, "tier-test")
        assert receipt["aborted"] is True

    def test_set_e_abort_still_writes_receipt_and_stays_red(self, receipt_dir):
        proc = run_bash(
            f"""
            set -euo pipefail
            source {LIB}
            receipt_init tier-test
            component step_one true
            false  # unwitnessed crash mid-script
            receipt_complete
            """,
            {"HAPAX_BACKUP_RECEIPT_DIR": str(receipt_dir)},
        )
        assert proc.returncode != 0
        receipt = read_receipt(receipt_dir, "tier-test")
        assert receipt["aborted"] is True
        assert receipt["exit_code"] != 0

    def test_required_component_failure_aborts_run(self, receipt_dir):
        proc = run_bash(
            f"""
            set -euo pipefail
            source {LIB}
            receipt_init tier-test
            component_required must_work false
            component never_reached true
            receipt_complete
            """,
            {"HAPAX_BACKUP_RECEIPT_DIR": str(receipt_dir)},
        )
        assert proc.returncode == 1
        receipt = read_receipt(receipt_dir, "tier-test")
        names = [c["name"] for c in receipt["components"]]
        assert "must_work" in names
        assert "never_reached" not in names
        assert receipt["failures"] >= 1

    def test_component_failure_detail_captures_command_output(self, receipt_dir):
        proc = run_bash(
            f"""
            set -euo pipefail
            source {LIB}
            receipt_init tier-test
            boom() {{ echo "disk on fire" >&2; return 3; }}
            component step_boom boom
            receipt_complete
            """,
            {"HAPAX_BACKUP_RECEIPT_DIR": str(receipt_dir)},
        )
        assert proc.returncode == 1
        receipt = read_receipt(receipt_dir, "tier-test")
        comp = receipt["components"][0]
        assert comp["status"] == "fail"
        assert "disk on fire" in comp["detail"]
        assert "rc=3" in comp["detail"]

    def test_receipt_precommit_writes_partial_witnesses(self, receipt_dir, tmp_path):
        precommit = tmp_path / "dump" / "backup-receipt-precommit.json"
        precommit.parent.mkdir()
        proc = run_bash(
            f"""
            set -euo pipefail
            source {LIB}
            receipt_init tier-test
            component step_one true
            receipt_precommit {precommit}
            receipt_complete
            """,
            {"HAPAX_BACKUP_RECEIPT_DIR": str(receipt_dir)},
        )
        assert proc.returncode == 0
        with precommit.open() as f:
            partial = json.load(f)
        assert partial["tier"] == "tier-test"
        assert [c["name"] for c in partial["components"]] == ["step_one"]

    def test_cleanup_dir_removed_on_exit(self, receipt_dir, tmp_path):
        dump = tmp_path / "dump-cleanup"
        dump.mkdir()
        (dump / "x").write_text("y")
        proc = run_bash(
            f"""
            set -euo pipefail
            source {LIB}
            HAPAX_BACKUP_CLEANUP_DIR={dump}
            receipt_init tier-test
            component step_one true
            receipt_complete
            """,
            {"HAPAX_BACKUP_RECEIPT_DIR": str(receipt_dir)},
        )
        assert proc.returncode == 0
        assert not dump.exists()


def make_docker_shim(shim_dir: Path, state_dir: Path) -> None:
    """A `docker` shim driven by N8N_* env vars, recording invocations."""
    shim = shim_dir / "docker"
    shim.write_text(
        """#!/usr/bin/env bash
state="${SHIM_STATE_DIR:?}"
echo "$*" >> "$state/docker-invocations.log"
case "$1 $2" in
  "exec n8n")
    shift 2
    case "$*" in
      "n8n list:workflow")
        printf '%b' "${N8N_LIST_OUTPUT:-}"
        exit "${N8N_LIST_RC:-0}"
        ;;
      "n8n export:workflow"*)
        if [[ "${N8N_EXPORT_RC:-0}" == "0" ]]; then
          printf '%s' "${N8N_EXPORT_CONTENT:-[]}" > "$state/n8n-workflows.json"
        else
          echo "Error exporting workflows. See log messages for details." >&2
        fi
        exit "${N8N_EXPORT_RC:-0}"
        ;;
    esac
    ;;
  "cp n8n:/tmp/n8n-workflows.json")
    cp "$state/n8n-workflows.json" "$3"
    exit $?
    ;;
esac
echo "docker shim: unhandled: $*" >&2
exit 64
"""
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)


class TestN8nExportComponent:
    def run_n8n(self, tmp_path, receipt_dir, env_extra):
        shim_dir = tmp_path / "shims"
        state_dir = tmp_path / "state"
        dump_dir = tmp_path / "dump"
        for d in (shim_dir, state_dir, dump_dir):
            d.mkdir(exist_ok=True)
        make_docker_shim(shim_dir, state_dir)
        env = {
            "HAPAX_BACKUP_RECEIPT_DIR": str(receipt_dir),
            "SHIM_STATE_DIR": str(state_dir),
            "PATH": f"{shim_dir}:{os.environ['PATH']}",
        }
        env.update(env_extra)
        proc = run_bash(
            f"""
            set -euo pipefail
            source {LIB}
            receipt_init tier-test
            backup_n8n_export {dump_dir}
            receipt_complete
            """,
            env,
        )
        return proc, dump_dir, state_dir

    def test_zero_workflows_is_healthy_and_writes_empty_artifact(self, tmp_path, receipt_dir):
        """The 2026-06-11 instance: empty store must not fail the backup,
        and the artifact must still be present in the backup set."""
        proc, dump_dir, _ = self.run_n8n(
            tmp_path, receipt_dir, {"N8N_LIST_OUTPUT": "", "N8N_LIST_RC": "0"}
        )
        assert proc.returncode == 0, proc.stderr
        artifact = dump_dir / "n8n-workflows.json"
        assert artifact.is_file()
        assert json.loads(artifact.read_text()) == []
        receipt = read_receipt(receipt_dir, "tier-test")
        comp = {c["name"]: c for c in receipt["components"]}["n8n_export"]
        assert comp["status"] == "ok"
        assert "0 workflows" in comp["detail"]

    def test_workflows_present_export_success(self, tmp_path, receipt_dir):
        proc, dump_dir, state_dir = self.run_n8n(
            tmp_path,
            receipt_dir,
            {
                "N8N_LIST_OUTPUT": "1|wf-alpha\\n2|wf-beta\\n",
                "N8N_EXPORT_CONTENT": '[{"id":"1"},{"id":"2"}]',
            },
        )
        assert proc.returncode == 0, proc.stderr
        artifact = dump_dir / "n8n-workflows.json"
        assert json.loads(artifact.read_text()) == [{"id": "1"}, {"id": "2"}]
        receipt = read_receipt(receipt_dir, "tier-test")
        comp = {c["name"]: c for c in receipt["components"]}["n8n_export"]
        assert comp["status"] == "ok"
        assert "2 workflows" in comp["detail"]

    def test_export_failure_with_workflows_present_is_component_fail(self, tmp_path, receipt_dir):
        proc, dump_dir, _ = self.run_n8n(
            tmp_path,
            receipt_dir,
            {"N8N_LIST_OUTPUT": "1|wf-alpha\\n", "N8N_EXPORT_RC": "1"},
        )
        assert proc.returncode == 1
        receipt = read_receipt(receipt_dir, "tier-test")
        comp = {c["name"]: c for c in receipt["components"]}["n8n_export"]
        assert comp["status"] == "fail"
        assert "Error exporting workflows" in comp["detail"]

    def test_list_failure_is_component_fail_not_empty_artifact(self, tmp_path, receipt_dir):
        """A broken CLI must not be mistaken for an empty store."""
        proc, dump_dir, _ = self.run_n8n(
            tmp_path,
            receipt_dir,
            {"N8N_LIST_OUTPUT": "DB connection refused\\n", "N8N_LIST_RC": "1"},
        )
        assert proc.returncode == 1
        assert not (dump_dir / "n8n-workflows.json").exists()
        receipt = read_receipt(receipt_dir, "tier-test")
        comp = {c["name"]: c for c in receipt["components"]}["n8n_export"]
        assert comp["status"] == "fail"


def make_rclone_shim(shim_dir: Path, state_dir: Path, rc: int = 0) -> None:
    shim = shim_dir / "rclone"
    shim.write_text(
        f"""#!/usr/bin/env bash
echo "$*" >> "${{SHIM_STATE_DIR:?}}/rclone-invocations.log"
exit {rc}
"""
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)


class TestDrScriptUploadComponent:
    def run_dr(self, tmp_path, receipt_dir, src: Path, rclone_rc: int = 0):
        shim_dir = tmp_path / "shims"
        state_dir = tmp_path / "state"
        for d in (shim_dir, state_dir):
            d.mkdir(exist_ok=True)
        make_rclone_shim(shim_dir, state_dir, rclone_rc)
        proc = run_bash(
            f"""
            set -euo pipefail
            source {LIB}
            receipt_init tier-test
            backup_dr_script_upload {src} b2:hapax-backups/dr-scripts/
            receipt_complete
            """,
            {
                "HAPAX_BACKUP_RECEIPT_DIR": str(receipt_dir),
                "SHIM_STATE_DIR": str(state_dir),
                "PATH": f"{shim_dir}:{os.environ['PATH']}",
            },
        )
        return proc, state_dir

    def test_missing_source_is_component_fail_and_rclone_not_invoked(self, tmp_path, receipt_dir):
        """The 2026-06-11 instance: missing source WARNed and stayed green."""
        proc, state_dir = self.run_dr(tmp_path, receipt_dir, tmp_path / "does-not-exist.sh")
        assert proc.returncode == 1
        receipt = read_receipt(receipt_dir, "tier-test")
        comp = {c["name"]: c for c in receipt["components"]}["dr_script_upload"]
        assert comp["status"] == "fail"
        assert "does-not-exist.sh" in comp["detail"]
        assert not (state_dir / "rclone-invocations.log").exists()

    def test_upload_success(self, tmp_path, receipt_dir):
        src = tmp_path / "hapax-cachyos-restore.sh"
        src.write_text("#!/bin/bash\n")
        proc, state_dir = self.run_dr(tmp_path, receipt_dir, src)
        assert proc.returncode == 0, proc.stderr
        receipt = read_receipt(receipt_dir, "tier-test")
        comp = {c["name"]: c for c in receipt["components"]}["dr_script_upload"]
        assert comp["status"] == "ok"
        log = (state_dir / "rclone-invocations.log").read_text()
        assert "b2:hapax-backups/dr-scripts/" in log

    def test_rclone_failure_is_component_fail(self, tmp_path, receipt_dir):
        src = tmp_path / "hapax-cachyos-restore.sh"
        src.write_text("#!/bin/bash\n")
        proc, _ = self.run_dr(tmp_path, receipt_dir, src, rclone_rc=1)
        assert proc.returncode == 1
        receipt = read_receipt(receipt_dir, "tier-test")
        comp = {c["name"]: c for c in receipt["components"]}["dr_script_upload"]
        assert comp["status"] == "fail"


class TestBackupScriptPins:
    """Static pins on the re-homed tier-1/tier-2 scripts."""

    @pytest.mark.parametrize("script", [LOCAL_SH, REMOTE_SH])
    def test_script_exists_and_parses(self, script):
        assert script.is_file(), f"{script} missing — backup scripts must be versioned"
        subprocess.run(["bash", "-n", str(script)], check=True)

    @pytest.mark.parametrize("script", [LOCAL_SH, REMOTE_SH])
    def test_no_warn_swallow_pattern(self, script):
        """The class defect: `cmd || log "WARN: ..."` swallowed failures green."""
        text = script.read_text()
        assert '|| log "WARN' not in text
        assert "WARN:" not in text

    @pytest.mark.parametrize("script", [LOCAL_SH, REMOTE_SH])
    def test_script_uses_receipt_lib(self, script):
        text = script.read_text()
        assert "hapax-backup-lib.sh" in text
        assert "receipt_init" in text
        assert "receipt_complete" in text

    @pytest.mark.parametrize(
        ("script", "tier", "extra_components"),
        [
            (LOCAL_SH, "tier1-local", []),
            (REMOTE_SH, "tier2-remote", ["git_bundles", "dr_script_upload"]),
        ],
    )
    def test_script_witnesses_every_component(self, script, tier, extra_components):
        text = script.read_text()
        assert f"receipt_init {tier}" in text
        core = [
            "postgres_dump",
            "qdrant_snapshots",
            "backup_n8n_export",
            "docker_volume_metadata",
            "package_lists",
            "restic_backup",
            "retention_prune",
        ]
        for name in core + extra_components:
            assert name in text, f"{script.name} missing component {name}"

    def test_restic_backup_is_required_component(self):
        for script in (LOCAL_SH, REMOTE_SH):
            assert "component_required restic_backup" in script.read_text()


class TestUnitFiles:
    def test_local_unit_execs_versioned_script(self):
        text = UNIT_LOCAL.read_text()
        assert "/home/hapax/projects/hapax-council/scripts/hapax-backup-local.sh" in text
        assert "distro-work" not in text
        assert "OnFailure=notify-failure@%n.service" in text
        assert "SyslogIdentifier=hapax-backup-local" in text

    def test_remote_unit_execs_versioned_script(self):
        text = UNIT_REMOTE.read_text()
        assert "/home/hapax/projects/hapax-council/scripts/hapax-backup-remote.sh" in text
        assert "distro-work" not in text
        assert "OnFailure=notify-failure@%n.service" in text
        assert "SyslogIdentifier=hapax-backup-remote" in text

    def test_remote_unit_keeps_deployed_memory_override(self):
        """Deployed drop-in (OOM fix for B2 prune) folded into the repo unit."""
        text = UNIT_REMOTE.read_text()
        assert "MemoryMax=8G" in text
        assert "GOMEMLIMIT=6GiB" in text

    def test_remote_timer_is_versioned(self):
        assert TIMER_REMOTE.is_file(), (
            "hapax-backup-remote.timer is deployed on podium but unversioned"
        )
        text = TIMER_REMOTE.read_text()
        assert "OnCalendar=*-*-* 03:30:00" in text
        assert "Persistent=true" in text


class TestWatchdogReceiptCanary:
    """The watchdog independently alerts on stale/red/absent receipts."""

    def test_watchdog_parses(self):
        subprocess.run(["bash", "-n", str(WATCHDOG)], check=True)

    def test_watchdog_checks_both_tier_receipts(self):
        text = WATCHDOG.read_text()
        assert "check_backup_receipt" in text
        assert "tier1-local" in text
        assert "tier2-remote" in text

    def run_watchdog_check(self, receipt_dir: Path, tier: str, max_hours: int = 36):
        return run_bash(
            f"""
            set -uo pipefail
            export HAPAX_WATCHDOG_LIB_ONLY=1
            source {WATCHDOG}
            FAILURES=()
            check_backup_receipt {tier} "Tier-test" {max_hours} >/dev/null
            printf '%s\\n' "${{FAILURES[@]:-}}"
            """,
            {"HAPAX_BACKUP_RECEIPT_DIR": str(receipt_dir)},
        )

    def write_receipt(
        self,
        receipt_dir: Path,
        tier: str,
        *,
        failures=0,
        aborted=False,
        exit_code=0,
        finished_at: str | None = None,
    ):
        receipt_dir.mkdir(parents=True, exist_ok=True)
        import datetime

        finished = finished_at or datetime.datetime.now().astimezone().isoformat()
        (receipt_dir / f"{tier}-latest.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "tier": tier,
                    "host": "test",
                    "started_at": finished,
                    "finished_at": finished,
                    "components": [],
                    "failures": failures,
                    "aborted": aborted,
                    "exit_code": exit_code,
                }
            )
        )

    def test_fresh_green_receipt_passes(self, tmp_path):
        rd = tmp_path / "receipts"
        self.write_receipt(rd, "tier1-local")
        proc = self.run_watchdog_check(rd, "tier1-local")
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == ""

    def test_missing_receipt_fails(self, tmp_path):
        rd = tmp_path / "receipts"
        rd.mkdir()
        proc = self.run_watchdog_check(rd, "tier1-local")
        assert "no backup receipt" in proc.stdout

    def test_receipt_with_failures_fails(self, tmp_path):
        rd = tmp_path / "receipts"
        self.write_receipt(rd, "tier1-local", failures=2, exit_code=1)
        proc = self.run_watchdog_check(rd, "tier1-local")
        assert "2 failed component" in proc.stdout

    def test_stale_receipt_fails(self, tmp_path):
        rd = tmp_path / "receipts"
        self.write_receipt(rd, "tier1-local", finished_at="2020-01-01T00:00:00+00:00")
        proc = self.run_watchdog_check(rd, "tier1-local")
        assert "old" in proc.stdout

from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config" / "apcupsd"
HELPER = CONFIG_DIR / "hapax-power-event.py"
INSTALLER = REPO_ROOT / "scripts" / "install-apcupsd-power-alerts"


def test_apcupsd_config_uses_current_header() -> None:
    assert (CONFIG_DIR / "apcupsd.conf").read_text(encoding="utf-8").splitlines()[0] == (
        "## apcupsd.conf v1.1 ##"
    )


def test_apcupsd_hooks_delegate_to_provenance_helper() -> None:
    onbattery = (CONFIG_DIR / "onbattery").read_text(encoding="utf-8")
    offbattery = (CONFIG_DIR / "offbattery").read_text(encoding="utf-8")
    assert 'HELPER="/etc/apcupsd/hapax-power-event.py"' in onbattery
    assert 'HELPER="/etc/apcupsd/hapax-power-event.py"' in offbattery
    assert "HAPAX_APCUPSD_TEST_MODE" in onbattery
    assert "HAPAX_APCUPSD_TEST_MODE" in offbattery
    assert "HAPAX_APCUPSD_HELPER" in onbattery
    assert 'exec "$HELPER" onbattery "$@"' in onbattery
    assert "HAPAX_APCUPSD_HELPER" in offbattery
    assert 'exec "$HELPER" offbattery "$@"' in offbattery


def test_power_event_helper_records_jsonl_without_ntfy(tmp_path: Path) -> None:
    audit = tmp_path / "ups-events.jsonl"
    fake_apcaccess = tmp_path / "apcaccess"
    fake_apcaccess.write_text(
        "#!/bin/sh\nprintf 'STATUS   : ONLINE\\nBCHARGE  : 100.0 Percent\\nTONBATT  : 0 Seconds\\n'\n",
        encoding="utf-8",
    )
    fake_apcaccess.chmod(0o755)

    result = subprocess.run(
        [
            str(HELPER),
            "onbattery",
            "--audit-log",
            str(audit),
            "--apcaccess",
            str(fake_apcaccess),
            "--no-ntfy",
            "UPSNAME",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    records = [
        json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert [record["phase"] for record in records] == ["intent", "delivery"]
    assert records[0]["schema"] == "hapax.ups_power_event.v1"
    assert records[0]["event"] == "onbattery"
    assert "delivery" not in records[0]
    assert records[1]["provenance_degraded"] is False
    assert records[1]["delivery"]["attempted"] is False
    assert records[1]["delivery"]["ok"] is False
    assert records[1]["delivery"]["error"] == "ntfy disabled"
    assert records[1]["apcaccess"]["STATUS"] == "ONLINE"
    assert "observed_at=" in records[0]["message"]
    assert "STATUS=ONLINE" in records[0]["message"]
    assert "TONBATT=0 Seconds" in records[0]["message"]
    assert audit.stat().st_mode & 0o777 == 0o640


def test_power_event_helper_records_offbattery_delivery_failure(tmp_path: Path) -> None:
    audit = tmp_path / "ups-events.jsonl"
    fake_apcaccess = tmp_path / "apcaccess"
    fake_apcaccess.write_text(
        "#!/bin/sh\nprintf 'STATUS   : ONLINE\\nTONBATT  : 0 Seconds\\n'\n",
        encoding="utf-8",
    )
    fake_apcaccess.chmod(0o755)

    result = subprocess.run(
        [
            str(HELPER),
            "offbattery",
            "--audit-log",
            str(audit),
            "--apcaccess",
            str(fake_apcaccess),
            "--ntfy-url",
            "http://127.0.0.1:9/hapax-alerts",
            "--timeout",
            "0.2",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    records = [
        json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert [record["phase"] for record in records] == ["intent", "delivery"]
    assert records[1]["event"] == "offbattery"
    assert records[1]["delivery"]["attempted"] is True
    assert records[1]["delivery"]["ok"] is False
    assert records[1]["delivery"]["error"]


def test_power_event_helper_notifies_when_intent_audit_fails(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit-dir"
    audit_dir.mkdir()
    seen: list[dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            seen.append({"title": self.headers.get("Title", ""), "body": body.decode()})
            self.send_response(204)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake_apcaccess = tmp_path / "apcaccess"
    fake_apcaccess.write_text(
        "#!/bin/sh\nprintf 'STATUS   : ONLINE\\nTONBATT  : 0 Seconds\\n'\n",
        encoding="utf-8",
    )
    fake_apcaccess.chmod(0o755)

    result = subprocess.run(
        [
            str(HELPER),
            "onbattery",
            "--audit-log",
            str(audit_dir),
            "--apcaccess",
            str(fake_apcaccess),
            "--ntfy-url",
            f"http://127.0.0.1:{server.server_port}/hapax-alerts",
            "--timeout",
            "0.2",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    server.shutdown()
    thread.join(timeout=2)

    assert result.returncode == 0
    assert "failed to append intent audit log" in result.stderr
    assert len(seen) == 1
    assert seen[0]["title"] == "UPS ON BATTERY - podium"
    assert "SRT3000XLA on battery" in seen[0]["body"]
    assert "observed_at=" in seen[0]["body"]
    assert "STATUS=ONLINE" in seen[0]["body"]
    assert "TONBATT=0 Seconds" in seen[0]["body"]


def test_installer_source_check_exercises_config_hooks_and_helper() -> None:
    result = subprocess.run(
        [str(INSTALLER), "--check"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "apcupsd power alert install/check complete" in result.stdout


def test_installer_install_and_verify_live_against_temp_destinations(tmp_path: Path) -> None:
    dest = tmp_path / "apcupsd"
    audit_dir = tmp_path / "hapax-log"
    logrotate_dest = tmp_path / "logrotate.d" / "hapax-ups-power-events"
    systemctl_calls = tmp_path / "systemctl-calls.txt"
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {systemctl_calls!s}\nexit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install", "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_DEST": str(dest),
            "HAPAX_APCUPSD_AUDIT_DIR": str(audit_dir),
            "HAPAX_APCUPSD_LOGROTATE_DEST": str(logrotate_dest),
            "HAPAX_APCUPSD_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
        },
    )

    assert result.returncode == 0, result.stderr
    assert (dest / "hapax-power-event.py").is_file()
    assert (dest / "onbattery").stat().st_mode & 0o100
    assert audit_dir.is_dir()
    assert audit_dir.stat().st_mode & 0o777 == 0o775
    assert logrotate_dest.is_file()
    assert "restart apcupsd" in systemctl_calls.read_text(encoding="utf-8")
    systemctl_calls.write_text("", encoding="utf-8")

    second_result = subprocess.run(
        [str(INSTALLER), "--install", "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_DEST": str(dest),
            "HAPAX_APCUPSD_AUDIT_DIR": str(audit_dir),
            "HAPAX_APCUPSD_LOGROTATE_DEST": str(logrotate_dest),
            "HAPAX_APCUPSD_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
        },
    )

    assert second_result.returncode == 0, second_result.stderr
    assert "restart apcupsd" not in systemctl_calls.read_text(encoding="utf-8")

    hook_audit = tmp_path / "hook.jsonl"
    hook_result = subprocess.run(
        [str(dest / "onbattery"), "UPSNAME"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_TEST_MODE": "1",
            "HAPAX_APCUPSD_HELPER": str(dest / "hapax-power-event.py"),
            "HAPAX_UPS_AUDIT_LOG": str(hook_audit),
            "HAPAX_UPS_APCACCESS": "",
            "HAPAX_UPS_NTFY_URL": "",
        },
    )

    assert hook_result.returncode == 0, hook_result.stderr
    records = [
        json.loads(line)
        for line in hook_audit.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records[0]["event"] == "onbattery"
    assert records[1]["delivery"]["attempted"] is False
    assert records[1]["delivery"]["ok"] is False


def test_installer_drains_root_required_deferral_after_success(tmp_path: Path) -> None:
    dest = tmp_path / "apcupsd"
    audit_dir = tmp_path / "hapax-log"
    logrotate_dest = tmp_path / "logrotate.d" / "hapax-ups-power-events"
    drain_dir = tmp_path / "root-required" / "sha" / "apcupsd-power-alerts"
    installed_source = tmp_path / "current-source"
    drain_dir.mkdir(parents=True)
    (drain_dir / "RUNBOOK.txt").write_text("run installer\n", encoding="utf-8")
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install", "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_DEST": str(dest),
            "HAPAX_APCUPSD_AUDIT_DIR": str(audit_dir),
            "HAPAX_APCUPSD_LOGROTATE_DEST": str(logrotate_dest),
            "HAPAX_APCUPSD_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
            "HAPAX_ROOT_REQUIRED_DRAIN_DIR": str(drain_dir),
            "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT": str(installed_source),
        },
    )

    assert result.returncode == 0, result.stderr
    assert not drain_dir.exists()
    assert (installed_source / "config" / "apcupsd" / "hapax-power-event.py").is_file()
    assert "root-required deferral drained" in result.stdout

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config" / "apcupsd"
HELPER = CONFIG_DIR / "hapax-power-event.py"
INSTALLER = REPO_ROOT / "scripts" / "install-apcupsd-power-alerts"
UPOWER_CONFIG = REPO_ROOT / "config" / "upower" / "90-hapax-apcupsd-owner.conf"
REPO_HEAD = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, text=True, capture_output=True
).stdout.strip()


@pytest.fixture(autouse=True)
def _isolate_installed_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT", str(tmp_path / "installed-source")
    )


def test_apcupsd_config_uses_current_header() -> None:
    assert (CONFIG_DIR / "apcupsd.conf").read_text(encoding="utf-8").splitlines()[0] == (
        "## apcupsd.conf v1.1 ##"
    )


def test_apcupsd_hooks_delegate_to_provenance_helper() -> None:
    onbattery = (CONFIG_DIR / "onbattery").read_text(encoding="utf-8")
    offbattery = (CONFIG_DIR / "offbattery").read_text(encoding="utf-8")
    doshutdown = (CONFIG_DIR / "doshutdown").read_text(encoding="utf-8")
    assert 'HELPER="/etc/apcupsd/hapax-power-event.py"' in onbattery
    assert 'HELPER="/etc/apcupsd/hapax-power-event.py"' in offbattery
    assert "HAPAX_APCUPSD_TEST_MODE" in onbattery
    assert "HAPAX_APCUPSD_TEST_MODE" in offbattery
    assert "HAPAX_APCUPSD_HELPER" in onbattery
    assert 'exec "$HELPER" onbattery "$@"' in onbattery
    assert "HAPAX_APCUPSD_HELPER" in offbattery
    assert 'exec "$HELPER" offbattery "$@"' in offbattery
    assert 'HELPER="/etc/apcupsd/hapax-power-event.py"' in doshutdown
    assert "HAPAX_APCUPSD_TEST_MODE" in doshutdown
    assert '"$TIMEOUT" --signal=KILL 3s "$HELPER" doshutdown "$@" || :' in doshutdown
    assert doshutdown.rstrip().endswith("exit 0")


def test_upower_is_observation_only_when_apcupsd_owns_shutdown_policy() -> None:
    policy = UPOWER_CONFIG.read_text(encoding="utf-8")
    assert "AllowRiskyCriticalPowerAction=true" in policy
    assert "CriticalPowerAction=Ignore" in policy


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
    assert records[0]["policy_owner"] == "apcupsd"
    assert records[0]["shutdown_requested"] is None
    assert records[0]["event_requests_shutdown"] is False
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
    assert records[1]["shutdown_requested"] is None
    assert records[1]["event_requests_shutdown"] is None
    assert "does not determine whether shutdown was previously requested" in records[1]["message"]
    assert records[1]["delivery"]["attempted"] is True
    assert records[1]["delivery"]["ok"] is False
    assert records[1]["delivery"]["error"]


def test_power_event_helper_marks_doshutdown_as_distinct_intent(tmp_path: Path) -> None:
    audit = tmp_path / "ups-events.jsonl"

    result = subprocess.run(
        [
            str(HELPER),
            "doshutdown",
            "--audit-log",
            str(audit),
            "--apcaccess",
            "",
            "--no-ntfy",
            "podium-srt3000xla",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert records[0]["event"] == "doshutdown"
    assert records[0]["shutdown_requested"] is True
    assert records[0]["event_requests_shutdown"] is True
    assert records[0]["priority"] == "max"
    assert records[0]["title"] == "UPS REQUESTED HOST SHUTDOWN - podium"
    assert records[0]["apcaccess_timeout_s"] == 1.0
    assert records[0]["notification_timeout_s"] == 1.0


def test_later_power_events_do_not_overwrite_prior_shutdown_intent(tmp_path: Path) -> None:
    audit = tmp_path / "ups-events.jsonl"
    for event in ("doshutdown", "offbattery", "onbattery"):
        result = subprocess.run(
            [
                str(HELPER),
                event,
                "--audit-log",
                str(audit),
                "--apcaccess",
                "",
                "--no-ntfy",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    intents = [
        json.loads(line)
        for line in audit.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["phase"] == "intent"
    ]
    assert [record["shutdown_requested"] for record in intents] == [True, None, None]
    assert [record["event_requests_shutdown"] for record in intents] == [True, None, False]


def test_doshutdown_external_io_is_bounded(tmp_path: Path) -> None:
    audit = tmp_path / "ups-events.jsonl"
    slow_apcaccess = tmp_path / "apcaccess"
    slow_apcaccess.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    slow_apcaccess.chmod(0o755)

    started = time.monotonic()
    result = subprocess.run(
        [
            str(HELPER),
            "doshutdown",
            "--audit-log",
            str(audit),
            "--apcaccess",
            str(slow_apcaccess),
            "--ntfy-url",
            "http://127.0.0.1:9/hapax-alerts",
            "--timeout",
            "5",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed = time.monotonic() - started

    assert result.returncode == 0, result.stderr
    assert elapsed < 3
    records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert records[0]["apcaccess_timeout_s"] == 1.0
    assert records[0]["notification_timeout_s"] == 1.0
    assert "TimeoutExpired" in records[0]["apcaccess_error"]


def test_doshutdown_hook_deadlines_blocked_provenance_write(tmp_path: Path) -> None:
    audit_fifo = tmp_path / "blocked-audit.fifo"
    os.mkfifo(audit_fifo)

    started = time.monotonic()
    result = subprocess.run(
        [str(CONFIG_DIR / "doshutdown"), "podium-srt3000xla", "1", "1"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_TEST_MODE": "1",
            "HAPAX_APCUPSD_HELPER": str(HELPER),
            "HAPAX_UPS_AUDIT_LOG": str(audit_fifo),
            "HAPAX_UPS_APCACCESS": "",
            "HAPAX_UPS_NTFY_URL": "",
        },
    )
    elapsed = time.monotonic() - started

    assert result.returncode == 0
    assert elapsed < 4


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
    assert seen[0]["title"] == "UPS transfer to battery - podium"
    assert "transfer event does not itself request host shutdown" in seen[0]["body"]
    assert "observed_at=" in seen[0]["body"]
    assert "STATUS=ONLINE" in seen[0]["body"]
    assert "TONBATT=0 Seconds" in seen[0]["body"]


def test_doshutdown_hook_records_intent_without_suppressing_default(tmp_path: Path) -> None:
    calls = tmp_path / "helper-calls.txt"
    fake_helper = tmp_path / "helper"
    fake_helper.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {calls!s}\nexit 99\n",
        encoding="utf-8",
    )
    fake_helper.chmod(0o755)

    result = subprocess.run(
        [str(CONFIG_DIR / "doshutdown"), "podium-srt3000xla", "1", "1"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_TEST_MODE": "1",
            "HAPAX_APCUPSD_HELPER": str(fake_helper),
        },
    )

    assert result.returncode == 0
    assert calls.read_text(encoding="utf-8").strip() == "doshutdown podium-srt3000xla 1 1"


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
    upower_dest = tmp_path / "UPower.conf.d" / "90-hapax-apcupsd-owner.conf"
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
            "HAPAX_UPOWER_CONF_DEST": str(upower_dest),
            "HAPAX_APCUPSD_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
        },
    )

    assert result.returncode == 0, result.stderr
    assert (dest / "hapax-power-event.py").is_file()
    assert (dest / "onbattery").stat().st_mode & 0o100
    assert (dest / "doshutdown").stat().st_mode & 0o100
    assert audit_dir.is_dir()
    assert audit_dir.stat().st_mode & 0o777 == 0o775
    assert logrotate_dest.is_file()
    assert "su root root" in logrotate_dest.read_text(encoding="utf-8")
    assert upower_dest.read_text(encoding="utf-8") == UPOWER_CONFIG.read_text(encoding="utf-8")
    assert "restart apcupsd" in systemctl_calls.read_text(encoding="utf-8")
    assert "try-restart upower.service" in systemctl_calls.read_text(encoding="utf-8")
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
            "HAPAX_UPOWER_CONF_DEST": str(upower_dest),
            "HAPAX_APCUPSD_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
        },
    )

    assert second_result.returncode == 0, second_result.stderr
    assert "restart apcupsd" not in systemctl_calls.read_text(encoding="utf-8")
    assert "try-restart upower.service" not in systemctl_calls.read_text(encoding="utf-8")

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
    upower_dest = tmp_path / "UPower.conf.d" / "90-hapax-apcupsd-owner.conf"
    drain_dir = tmp_path / "root-required" / "sha" / "apcupsd-power-alerts"
    installed_source = tmp_path / "current-source"
    drain_dir.mkdir(parents=True)
    (drain_dir / "RUNBOOK.txt").write_text("run installer\n", encoding="utf-8")
    sibling_dir = tmp_path / "root-required" / "other-sha" / "apcupsd-power-alerts"
    sibling_dir.mkdir(parents=True)
    (sibling_dir / "RUNBOOK.txt").write_text("run other installer\n", encoding="utf-8")
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
            "HAPAX_UPOWER_CONF_DEST": str(upower_dest),
            "HAPAX_APCUPSD_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": REPO_HEAD,
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(REPO_ROOT),
            "HAPAX_ROOT_REQUIRED_DRAIN_DIR": str(drain_dir),
            "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT": str(installed_source),
        },
    )

    assert result.returncode == 0, result.stderr
    assert not drain_dir.exists()
    assert sibling_dir.exists()
    assert (
        tmp_path / "root-required" / "installed-receipts" / "apcupsd-power-alerts.sha"
    ).read_text().strip() == REPO_HEAD
    assert (installed_source / "config" / "apcupsd" / "hapax-power-event.py").is_file()
    assert "root-required deferral drained" in result.stdout


def test_stale_deferred_apcupsd_package_does_not_roll_back_newer_install(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "ups-test@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "UPS Test"], cwd=repo, check=True)
    marker = repo / "marker"
    marker.write_text("A\n", encoding="utf-8")
    subprocess.run(["git", "add", "marker"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "A"], cwd=repo, check=True, capture_output=True)
    sha_a = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()
    marker.write_text("B\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "B"], cwd=repo, check=True, capture_output=True)
    sha_b = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    defer_root = tmp_path / "root-required"
    drain_dir = defer_root / sha_a / "apcupsd-power-alerts"
    drain_dir.mkdir(parents=True)
    (drain_dir / "RUNBOOK.txt").write_text("stale A\n", encoding="utf-8")
    receipt_root = defer_root / "installed-receipts"
    receipt_root.mkdir()
    receipt = receipt_root / "apcupsd-power-alerts.sha"
    receipt.write_text(f"{sha_b}\n", encoding="utf-8")
    live_dest = tmp_path / "live-apcupsd"
    live_dest.mkdir()
    live_marker = live_dest / "apcupsd.conf"
    live_marker.write_text("newer B policy\n", encoding="utf-8")
    staged_a = tmp_path / "staged-a"
    staged_a.mkdir()
    (staged_a / ".hapax-root-required-package-sha").write_text(f"{sha_a}\n", encoding="utf-8")

    result = subprocess.run(
        [str(INSTALLER), "--source", str(staged_a), "--install", "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
            "HAPAX_APCUPSD_DEST": str(live_dest),
            "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_root),
            "HAPAX_ROOT_REQUIRED_DRAIN_DIR": str(drain_dir),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": sha_a,
            "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT": str(receipt_root),
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(repo),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "superseded" in result.stdout
    assert not drain_dir.exists()
    assert receipt.read_text(encoding="utf-8").strip() == sha_b
    assert live_marker.read_text(encoding="utf-8") == "newer B policy\n"

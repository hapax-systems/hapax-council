from __future__ import annotations

import errno
import grp
import json
import os
import pwd
import runpy
import shutil
import stat
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
LOGROTATE_CONFIG = REPO_ROOT / "systemd" / "logrotate.d" / "hapax-ups-power-events"
REPO_HEAD = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, text=True, capture_output=True
).stdout.strip()
APCUPSD_PACKAGE_FILES = (
    "config/root-required/apcupsd-power-alerts.files",
    "scripts/install-apcupsd-power-alerts",
    "config/apcupsd/apcupsd.conf",
    "config/apcupsd/hapax-power-event.py",
    "config/apcupsd/onbattery",
    "config/apcupsd/offbattery",
    "config/apcupsd/doshutdown",
    "config/upower/90-hapax-apcupsd-owner.conf",
    "systemd/logrotate.d/hapax-ups-power-events",
)


def _copy_apcupsd_package(dest_root: Path) -> None:
    for relative in APCUPSD_PACKAGE_FILES:
        dest = dest_root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, dest)


@pytest.fixture(autouse=True)
def _isolate_installed_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_POST_MERGE_ROOT_DEFER_DIR", str(tmp_path / "root-required"))
    monkeypatch.setenv("HAPAX_ROOT_REQUIRED_STATE_ROOT", str(tmp_path / "root-state"))
    monkeypatch.setenv(
        "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT", str(tmp_path / "installed-source")
    )
    fake_busctl = tmp_path / "busctl"
    fake_busctl.write_text("#!/bin/sh\nprintf 's \\\"Ignore\\\"\\n'\n", encoding="utf-8")
    fake_busctl.chmod(0o755)
    monkeypatch.setenv("HAPAX_APCUPSD_BUSCTL", str(fake_busctl))
    fake_apcaccess = tmp_path / "apcaccess"
    fake_apcaccess.write_text(
        "#!/bin/sh\n"
        "printf 'STATUS   : ONLINE\\nMBATTCHG : 20 Percent\\nMINTIMEL : 5 Minutes\\nMAXTIME  : 0 Seconds\\n'\n",
        encoding="utf-8",
    )
    fake_apcaccess.chmod(0o755)
    monkeypatch.setenv("HAPAX_APCUPSD_APCACCESS", str(fake_apcaccess))
    monkeypatch.setenv("HAPAX_ROOT_REQUIRED_GIT_REPO", str(REPO_ROOT))


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
    assert '"$TIMEOUT" --signal=KILL "$DEADLINE" "$HELPER" onbattery "$@" || :' in onbattery
    assert 'DEADLINE="10s"' in onbattery
    assert onbattery.rstrip().endswith("exit 0")
    assert "HAPAX_APCUPSD_HELPER" in offbattery
    assert '"$TIMEOUT" --signal=KILL "$DEADLINE" "$HELPER" offbattery "$@" || :' in offbattery
    assert 'DEADLINE="10s"' in offbattery
    assert offbattery.rstrip().endswith("exit 0")
    assert 'HELPER="/etc/apcupsd/hapax-power-event.py"' in doshutdown
    assert "HAPAX_APCUPSD_TEST_MODE" in doshutdown
    assert 'DEADLINE="5s"' in doshutdown
    assert '"$TIMEOUT" --signal=KILL "$DEADLINE" "$HELPER" doshutdown "$@" || :' in doshutdown
    assert doshutdown.rstrip().endswith("exit 0")


def test_upower_is_observation_only_when_apcupsd_owns_shutdown_policy() -> None:
    policy = UPOWER_CONFIG.read_text(encoding="utf-8")
    assert "AllowRiskyCriticalPowerAction=true" in policy
    assert "CriticalPowerAction=Ignore" in policy
    assert "busctl call org.freedesktop.UPower" in policy
    assert "org.freedesktop.UPower GetCriticalAction" in policy
    assert "busctl get-property" not in policy


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


def test_power_event_helper_refuses_symlinked_privileged_audit_log(tmp_path: Path) -> None:
    target = tmp_path / "protected-target"
    target.write_text("sentinel\n", encoding="utf-8")
    audit = tmp_path / "ups-events.jsonl"
    audit.symlink_to(target)

    result = subprocess.run(
        [
            str(HELPER),
            "onbattery",
            "--audit-log",
            str(audit),
            "--apcaccess",
            str(tmp_path / "missing-apcaccess"),
            "--no-ntfy",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert target.read_text(encoding="utf-8") == "sentinel\n"
    assert "failed to append intent audit log" in result.stderr
    assert "failed to append delivery audit log" in result.stderr


def test_power_event_helper_refuses_hard_linked_audit_log(tmp_path: Path) -> None:
    target = tmp_path / "protected-target"
    target.write_text("sentinel\n", encoding="utf-8")
    audit = tmp_path / "ups-events.jsonl"
    os.link(target, audit)

    result = subprocess.run(
        [
            str(HELPER),
            "onbattery",
            "--audit-log",
            str(audit),
            "--apcaccess",
            str(tmp_path / "missing-apcaccess"),
            "--no-ntfy",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert target.read_text(encoding="utf-8") == "sentinel\n"
    assert "unsafe UPS audit log inode" in result.stderr
    assert "failed to append intent audit log" in result.stderr
    assert "failed to append delivery audit log" in result.stderr


def test_power_event_helper_refuses_nonregular_audit_log(tmp_path: Path) -> None:
    audit = tmp_path / "ups-events.jsonl"
    os.mkfifo(audit)
    reader_fd = os.open(audit, os.O_RDONLY | os.O_NONBLOCK)
    try:
        result = subprocess.run(
            [
                str(HELPER),
                "onbattery",
                "--audit-log",
                str(audit),
                "--apcaccess",
                str(tmp_path / "missing-apcaccess"),
                "--no-ntfy",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    finally:
        os.close(reader_fd)

    assert result.returncode == 0
    assert "unsafe UPS audit log inode" in result.stderr
    assert "failed to append intent audit log" in result.stderr
    assert "failed to append delivery audit log" in result.stderr


def test_power_event_append_refuses_wrong_owner_regular_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit = tmp_path / "ups-events.jsonl"
    audit.write_text("sentinel\n", encoding="utf-8")
    namespace = runpy.run_path(str(HELPER))
    actual_uid = os.geteuid()
    monkeypatch.setattr(namespace["os"], "geteuid", lambda: actual_uid + 1)

    with pytest.raises(OSError, match="unsafe UPS audit log inode"):
        namespace["append_jsonl"](audit, {"event": "test"})

    assert audit.read_text(encoding="utf-8") == "sentinel\n"


def test_power_event_append_completes_short_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit = tmp_path / "ups-events.jsonl"
    namespace = runpy.run_path(str(HELPER))
    real_write = namespace["os"].write
    writes = 0

    def short_first_write(fd: int, payload: bytes) -> int:
        nonlocal writes
        writes += 1
        if writes == 1:
            prefix = payload[:7]
            return real_write(fd, prefix)
        return real_write(fd, payload)

    monkeypatch.setattr(namespace["os"], "write", short_first_write)

    namespace["append_jsonl"](audit, {"event": "test", "complete": True})

    assert writes == 2
    assert json.loads(audit.read_text(encoding="utf-8")) == {
        "complete": True,
        "event": "test",
    }


def test_logrotate_rename_create_preserves_inflight_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logrotate = shutil.which("logrotate")
    if logrotate is None:
        pytest.skip("logrotate is not installed")
    source_config = LOGROTATE_CONFIG.read_text(encoding="utf-8")
    assert "copytruncate" not in source_config
    assert "create 0640 root hapax" in source_config
    assert "delaycompress" in source_config

    audit = tmp_path / "ups-power-events.jsonl"
    audit.write_text('{"phase":"seed"}\n', encoding="utf-8")
    audit.chmod(0o640)
    username = pwd.getpwuid(os.geteuid()).pw_name
    group = grp.getgrgid(os.getegid()).gr_name
    config = tmp_path / "logrotate.conf"
    config.write_text(
        source_config.replace("/var/log/hapax/ups-power-events.jsonl", str(audit), 1)
        .replace("su root root", f"su {username} {group}", 1)
        .replace("create 0640 root hapax", f"create 0640 {username} {group}", 1),
        encoding="utf-8",
    )

    namespace = runpy.run_path(str(HELPER))
    entered_write = threading.Event()
    release_write = threading.Event()
    real_write = namespace["os"].write
    errors: list[BaseException] = []

    def blocked_write(fd: int, payload: bytes) -> int:
        entered_write.set()
        if not release_write.wait(timeout=5):
            raise TimeoutError("rotation witness did not release writer")
        return real_write(fd, payload)

    def append_during_rotation() -> None:
        try:
            namespace["append_jsonl"](audit, {"phase": "during"})
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    monkeypatch.setattr(namespace["os"], "write", blocked_write)
    writer = threading.Thread(target=append_during_rotation, daemon=True)
    writer.start()
    assert entered_write.wait(timeout=2)
    try:
        result = subprocess.run(
            [logrotate, "--force", "--state", str(tmp_path / "state"), str(config)],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    finally:
        release_write.set()
        writer.join(timeout=5)
    assert not writer.is_alive()
    assert not errors

    namespace["append_jsonl"](audit, {"phase": "after"})
    rotated = Path(f"{audit}.1")
    assert rotated.is_file()
    assert not Path(f"{audit}.1.gz").exists()
    rotated_phases = [
        json.loads(line)["phase"]
        for line in rotated.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    current_phases = [
        json.loads(line)["phase"]
        for line in audit.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rotated_phases == ["seed", "during"]
    assert current_phases == ["after"]


def test_writer_entering_logrotate_create_gap_enforces_file_contract(tmp_path: Path) -> None:
    namespace = runpy.run_path(str(HELPER))
    audit_dir = tmp_path / "hapax-log"
    audit_dir.mkdir()
    audit_dir.chmod(0o2775)
    audit = audit_dir / "ups-power-events.jsonl"
    namespace["append_jsonl"](audit, {"phase": "before"})
    rotated = Path(f"{audit}.1")
    audit.rename(rotated)

    namespace["append_jsonl"](audit, {"phase": "gap"})

    inode = audit.stat()
    assert inode.st_uid == os.geteuid()
    assert inode.st_gid == audit_dir.stat().st_gid
    assert stat.S_IMODE(inode.st_mode) == 0o640
    assert inode.st_nlink == 1
    assert [json.loads(line)["phase"] for line in rotated.read_text().splitlines()] == ["before"]
    assert [json.loads(line)["phase"] for line in audit.read_text().splitlines()] == ["gap"]


def test_canonical_root_writer_resolves_required_hapax_gid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(HELPER))
    group = type("Group", (), {"gr_gid": 4242})()
    monkeypatch.setattr(namespace["os"], "geteuid", lambda: 0)
    monkeypatch.setattr(namespace["grp"], "getgrnam", lambda name: group)

    identity = namespace["audit_log_expected_identity"](Path(namespace["DEFAULT_AUDIT_LOG"]), 7)

    assert identity == (0, 4242)


def test_power_event_helper_records_offbattery_delivery_failure(tmp_path: Path) -> None:
    audit = tmp_path / "ups-events.jsonl"
    fake_apcaccess = tmp_path / "apcaccess"
    fake_apcaccess.write_text(
        "#!/bin/sh\nprintf 'STATUS   : ONLINE\\nTONBATT  : 0 Seconds\\n'\n",
        encoding="utf-8",
    )
    fake_apcaccess.chmod(0o755)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(500)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        result = subprocess.run(
            [
                str(HELPER),
                "offbattery",
                "--audit-log",
                str(audit),
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
    finally:
        server.shutdown()
        thread.join(timeout=2)

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
    assert records[1]["delivery"]["status"] == 500
    assert records[1]["delivery"]["error"] == (
        f"HTTPError: status=500; destination=http://127.0.0.1:{server.server_port}"
    )
    assert "UPS notification delivery failed" in result.stderr
    assert "next action:" in result.stderr


def test_power_event_helper_redacts_ntfy_credentials_and_topic(tmp_path: Path) -> None:
    audit = tmp_path / "ups-events.jsonl"
    secret_url = "https://agent:secret@example.test:8443/private-topic?token=credential"

    result = subprocess.run(
        [
            str(HELPER),
            "onbattery",
            "--audit-log",
            str(audit),
            "--apcaccess",
            "",
            "--ntfy-url",
            secret_url,
            "--no-ntfy",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    raw_audit = audit.read_text(encoding="utf-8")
    records = [json.loads(line) for line in raw_audit.splitlines() if line.strip()]
    assert {record["ntfy_url"] for record in records} == {"https://example.test:8443"}
    assert "agent" not in raw_audit
    assert "secret" not in raw_audit
    assert "private-topic" not in raw_audit
    assert "credential" not in raw_audit


def test_power_event_helper_redacts_ntfy_url_from_delivery_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(HELPER))
    secret_url = "https://agent:secret@example.test:8443/private-topic?token=credential"

    def fail_delivery(*args: object, **kwargs: object) -> None:
        raise ValueError(f"invalid destination {secret_url}")

    monkeypatch.setattr(namespace["urllib"].request, "urlopen", fail_delivery)
    delivery = namespace["post_ntfy"](secret_url, "title", "message", "urgent", 1.0)

    assert delivery.attempted is True
    assert delivery.ok is False
    assert delivery.error == "ValueError: destination=https://example.test:8443"
    assert "agent" not in delivery.error
    assert "secret" not in delivery.error
    assert "private-topic" not in delivery.error
    assert "credential" not in delivery.error


def test_power_event_helper_redacts_malformed_ntfy_url_error(tmp_path: Path) -> None:
    audit = tmp_path / "ups-events.jsonl"
    secret_url = "https://agent:secret@example.test:8443/private topic?token=credential"

    result = subprocess.run(
        [
            str(HELPER),
            "onbattery",
            "--audit-log",
            str(audit),
            "--apcaccess",
            "",
            "--ntfy-url",
            secret_url,
            "--timeout",
            "0.2",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    raw_audit = audit.read_text(encoding="utf-8")
    records = [json.loads(line) for line in raw_audit.splitlines() if line.strip()]
    assert [record["phase"] for record in records] == ["intent", "delivery"]
    assert records[1]["delivery"] == {
        "attempted": True,
        "error": "InvalidURL: destination=https://example.test:8443",
        "ok": False,
        "status": None,
    }
    assert "UPS notification delivery failed" in result.stderr
    assert "next action:" in result.stderr
    for secret in ("agent", "secret", "private topic", "credential"):
        assert secret not in raw_audit
        assert secret not in result.stderr


def test_power_event_helper_redacts_socket_error_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(HELPER))
    secret_url = "https://agent:secret@example.test:8443/private-topic?token=credential"

    def refuse_connection(*args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError(errno.ECONNREFUSED, f"refused {secret_url}")

    monkeypatch.setattr(namespace["urllib"].request, "urlopen", refuse_connection)
    delivery = namespace["post_ntfy"](secret_url, "title", "message", "urgent", 1.0)

    assert delivery.error == (
        f"ConnectionRefusedError: errno={errno.ECONNREFUSED}; destination=https://example.test:8443"
    )
    for secret in ("agent", "secret", "private-topic", "credential"):
        assert secret not in delivery.error


@pytest.mark.parametrize("invalid_timeout", ["invalid", "nan", "inf", "-1", "0"])
def test_power_event_helper_falls_back_for_invalid_env_timeout(
    tmp_path: Path, invalid_timeout: str
) -> None:
    audit = tmp_path / f"ups-events-{invalid_timeout}.jsonl"

    result = subprocess.run(
        [
            str(HELPER),
            "onbattery",
            "--audit-log",
            str(audit),
            "--apcaccess",
            "",
            "--no-ntfy",
        ],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HAPAX_UPS_NTFY_TIMEOUT": invalid_timeout},
    )

    assert result.returncode == 0, result.stderr
    records = [
        json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert {record["notification_timeout_s"] for record in records} == {5.0}


def test_power_event_helper_rejects_invalid_explicit_timeout(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            str(HELPER),
            "onbattery",
            "--audit-log",
            str(tmp_path / "ups-events.jsonl"),
            "--timeout",
            "nan",
            "--no-ntfy",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "timeout must be a positive finite number" in result.stderr


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


def test_power_event_helper_keeps_apcaccess_oserror_nonfatal(tmp_path: Path) -> None:
    audit = tmp_path / "ups-events.jsonl"
    non_executable_apcaccess = tmp_path / "apcaccess"
    non_executable_apcaccess.write_text("not executable\n", encoding="utf-8")
    non_executable_apcaccess.chmod(0o644)

    result = subprocess.run(
        [
            str(HELPER),
            "onbattery",
            "--audit-log",
            str(audit),
            "--apcaccess",
            str(non_executable_apcaccess),
            "--no-ntfy",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert records[0]["apcaccess"] == {}
    assert "PermissionError" in records[0]["apcaccess_error"]


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
            "HAPAX_APCUPSD_SHUTDOWN_DEADLINE": "1s",
            "HAPAX_UPS_AUDIT_LOG": str(audit_fifo),
            "HAPAX_UPS_APCACCESS": "",
            "HAPAX_UPS_NTFY_URL": "",
        },
    )
    elapsed = time.monotonic() - started

    assert result.returncode == 0
    assert elapsed < 2


def test_doshutdown_hook_records_shutdown_receipt(tmp_path: Path) -> None:
    audit = tmp_path / "ups-events.jsonl"

    result = subprocess.run(
        [str(CONFIG_DIR / "doshutdown"), "podium-srt3000xla", "1", "1"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_TEST_MODE": "1",
            "HAPAX_APCUPSD_HELPER": str(HELPER),
            "HAPAX_UPS_AUDIT_LOG": str(audit),
            "HAPAX_UPS_APCACCESS": "",
            "HAPAX_UPS_NTFY_URL": "",
        },
    )

    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert records[0]["event"] == "doshutdown"
    assert records[0]["phase"] == "intent"
    assert records[0]["shutdown_requested"] is True
    assert records[0]["event_requests_shutdown"] is True


@pytest.mark.parametrize("hook", ["onbattery", "offbattery"])
def test_transfer_hooks_deadline_blocked_provenance_write(tmp_path: Path, hook: str) -> None:
    audit_fifo = tmp_path / f"blocked-{hook}.fifo"
    os.mkfifo(audit_fifo)

    started = time.monotonic()
    result = subprocess.run(
        [str(CONFIG_DIR / hook), "podium-srt3000xla", "1", "1"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_TEST_MODE": "1",
            "HAPAX_APCUPSD_HELPER": str(HELPER),
            "HAPAX_APCUPSD_EVENT_DEADLINE": "1s",
            "HAPAX_UPS_AUDIT_LOG": str(audit_fifo),
            "HAPAX_UPS_APCACCESS": "",
            "HAPAX_UPS_NTFY_URL": "",
        },
    )
    elapsed = time.monotonic() - started

    assert result.returncode == 0
    assert elapsed < 2.5


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


def test_installer_fails_closed_when_canonical_audit_group_is_missing(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_getent = fake_bin / "getent"
    fake_getent.write_text("#!/usr/bin/env bash\nexit 2\n", encoding="utf-8")
    fake_getent.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HAPAX_APCUPSD_TARGET_HOME": str(tmp_path),
            "HAPAX_APCUPSD_TARGET_GID": str(os.getgid()),
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
        },
    )

    assert result.returncode == 1
    assert "required UPS audit group is missing: hapax" in result.stderr


def test_installer_install_implies_verify_live_against_temp_destinations(tmp_path: Path) -> None:
    dest = tmp_path / "apcupsd"
    audit_dir = tmp_path / "hapax-log"
    installed_source = Path(os.environ["HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT"])
    snapshot_dest = installed_source / "scripts" / "install-apcupsd-power-alerts"
    snapshot_dest.parent.mkdir(parents=True)
    snapshot_target = tmp_path / "snapshot-symlink-target"
    snapshot_target.write_text("do not overwrite\n", encoding="utf-8")
    snapshot_dest.symlink_to(snapshot_target)
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
        [str(INSTALLER), "--install"],
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
    assert not snapshot_dest.is_symlink()
    assert snapshot_dest.read_bytes() == INSTALLER.read_bytes()
    assert snapshot_target.read_text(encoding="utf-8") == "do not overwrite\n"
    assert (dest / "hapax-power-event.py").is_file()
    assert (dest / "onbattery").stat().st_mode & 0o100
    assert (dest / "doshutdown").stat().st_mode & 0o100
    audit_log = audit_dir / "ups-power-events.jsonl"
    assert audit_log.is_file()
    assert not audit_log.is_symlink()
    assert audit_log.stat().st_nlink == 1
    assert audit_log.stat().st_mode & 0o777 == 0o640
    assert audit_dir.is_dir()
    assert audit_dir.stat().st_mode & 0o777 == 0o775
    assert logrotate_dest.is_file()
    assert "su root root" in logrotate_dest.read_text(encoding="utf-8")
    assert upower_dest.read_text(encoding="utf-8") == UPOWER_CONFIG.read_text(encoding="utf-8")
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "enable --now apcupsd.service" in calls
    assert "restart apcupsd.service" in calls
    assert "is-enabled --quiet apcupsd.service" in calls
    assert "is-active --quiet apcupsd.service" in calls
    assert "try-restart upower.service" in systemctl_calls.read_text(encoding="utf-8")
    systemctl_calls.write_text("", encoding="utf-8")

    second_result = subprocess.run(
        [str(INSTALLER), "--install"],
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
    second_calls = systemctl_calls.read_text(encoding="utf-8")
    assert "enable --now apcupsd.service" in second_calls
    assert "restart apcupsd.service" not in second_calls
    assert "try-restart upower.service" not in second_calls

    logrotate_dest.write_text("stale logrotate config\n", encoding="utf-8")
    systemctl_calls.write_text("", encoding="utf-8")
    logrotate_only_result = subprocess.run(
        [str(INSTALLER), "--install"],
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

    assert logrotate_only_result.returncode == 0, logrotate_only_result.stderr
    assert logrotate_dest.read_text(encoding="utf-8") == (
        REPO_ROOT / "systemd" / "logrotate.d" / "hapax-ups-power-events"
    ).read_text(encoding="utf-8")
    logrotate_only_calls = systemctl_calls.read_text(encoding="utf-8")
    assert "enable --now apcupsd.service" in logrotate_only_calls
    assert "restart apcupsd.service" not in logrotate_only_calls
    assert "try-restart upower.service" not in logrotate_only_calls

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


def test_installer_retry_repairs_loaded_policy_after_interrupted_activation(tmp_path: Path) -> None:
    dest = tmp_path / "apcupsd"
    dest.mkdir()
    for name in ("apcupsd.conf", "hapax-power-event.py", "onbattery", "offbattery", "doshutdown"):
        shutil.copy2(CONFIG_DIR / name, dest / name)
    logrotate_dest = tmp_path / "logrotate.d" / "hapax-ups-power-events"
    logrotate_dest.parent.mkdir()
    shutil.copy2(REPO_ROOT / "systemd/logrotate.d/hapax-ups-power-events", logrotate_dest)
    upower_dest = tmp_path / "UPower.conf.d" / "90-hapax-apcupsd-owner.conf"
    upower_dest.parent.mkdir()
    shutil.copy2(UPOWER_CONFIG, upower_dest)

    apcupsd_reloaded = tmp_path / "apcupsd-reloaded"
    upower_reloaded = tmp_path / "upower-reloaded"
    systemctl_calls = tmp_path / "systemctl-calls.txt"
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {systemctl_calls!s}\n"
        f'if [ "$*" = "restart apcupsd.service" ]; then touch {apcupsd_reloaded!s}; fi\n'
        f'if [ "$*" = "try-restart upower.service" ]; then touch {upower_reloaded!s}; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    fake_apcaccess = tmp_path / "apcaccess"
    fake_apcaccess.write_text(
        "#!/usr/bin/env bash\n"
        f"if [ -f {apcupsd_reloaded!s} ]; then\n"
        "  printf 'MBATTCHG : 20 Percent\\nMINTIMEL : 5 Minutes\\nMAXTIME : 0 Seconds\\n'\n"
        "else\n"
        "  printf 'MBATTCHG : 99 Percent\\nMINTIMEL : 1 Minutes\\nMAXTIME : 60 Seconds\\n'\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_apcaccess.chmod(0o755)
    fake_busctl = tmp_path / "busctl"
    fake_busctl.write_text(
        "#!/usr/bin/env bash\n"
        f"if [ -f {upower_reloaded!s} ]; then printf 's \"Ignore\"\\n'; "
        "else printf 's \"PowerOff\"\\n'; fi\n",
        encoding="utf-8",
    )
    fake_busctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_DEST": str(dest),
            "HAPAX_APCUPSD_AUDIT_DIR": str(tmp_path / "hapax-log"),
            "HAPAX_APCUPSD_LOGROTATE_DEST": str(logrotate_dest),
            "HAPAX_UPOWER_CONF_DEST": str(upower_dest),
            "HAPAX_APCUPSD_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_APCUPSD_APCACCESS": str(fake_apcaccess),
            "HAPAX_APCUPSD_BUSCTL": str(fake_busctl),
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
        },
    )

    assert result.returncode == 0, result.stderr
    assert apcupsd_reloaded.exists()
    assert upower_reloaded.exists()
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "restart apcupsd.service" in calls
    assert "try-restart upower.service" in calls


def test_verify_live_rejects_stale_upower_loaded_action(tmp_path: Path) -> None:
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_systemctl.chmod(0o755)
    stale_busctl = tmp_path / "stale-busctl"
    stale_busctl.write_text("#!/bin/sh\nprintf 's \\\"PowerOff\\\"\\n'\n", encoding="utf-8")
    stale_busctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install", "--verify-live", "--no-restart"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_DEST": str(tmp_path / "apcupsd"),
            "HAPAX_APCUPSD_AUDIT_DIR": str(tmp_path / "hapax-log"),
            "HAPAX_APCUPSD_LOGROTATE_DEST": str(tmp_path / "logrotate"),
            "HAPAX_UPOWER_CONF_DEST": str(tmp_path / "upower"),
            "HAPAX_APCUPSD_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_APCUPSD_BUSCTL": str(stale_busctl),
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
        },
    )

    assert result.returncode == 1
    assert "UPower still owns a loaded shutdown action" in result.stderr


def test_verify_live_rejects_stale_apcupsd_loaded_thresholds(tmp_path: Path) -> None:
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_systemctl.chmod(0o755)
    stale_apcaccess = tmp_path / "stale-apcaccess"
    stale_apcaccess.write_text(
        "#!/bin/sh\n"
        "printf 'STATUS   : ONLINE\\nMBATTCHG : 99 Percent\\nMINTIMEL : 5 Minutes\\nMAXTIME  : 0 Seconds\\n'\n",
        encoding="utf-8",
    )
    stale_apcaccess.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install", "--verify-live", "--no-restart"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_DEST": str(tmp_path / "apcupsd"),
            "HAPAX_APCUPSD_AUDIT_DIR": str(tmp_path / "hapax-log"),
            "HAPAX_APCUPSD_LOGROTATE_DEST": str(tmp_path / "logrotate"),
            "HAPAX_UPOWER_CONF_DEST": str(tmp_path / "upower"),
            "HAPAX_APCUPSD_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_APCUPSD_APCACCESS": str(stale_apcaccess),
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
        },
    )

    assert result.returncode == 1
    assert "apcupsd loaded shutdown policy drift" in result.stderr
    assert "MBATTCHG=99 expected 20" in result.stderr


@pytest.mark.parametrize("link_kind", ("symlink", "hardlink"))
def test_installer_refuses_unsafe_existing_ups_audit_log(
    tmp_path: Path,
    link_kind: str,
) -> None:
    audit_dir = tmp_path / "hapax-log"
    audit_dir.mkdir()
    audit_log = audit_dir / "ups-power-events.jsonl"
    protected = tmp_path / "protected-target"
    protected.write_text("sentinel\n", encoding="utf-8")
    if link_kind == "symlink":
        audit_log.symlink_to(protected)
    else:
        os.link(protected, audit_log)

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_DEST": str(tmp_path / "apcupsd"),
            "HAPAX_APCUPSD_AUDIT_DIR": str(audit_dir),
            "HAPAX_APCUPSD_LOGROTATE_DEST": str(tmp_path / "logrotate"),
            "HAPAX_UPOWER_CONF_DEST": str(tmp_path / "upower"),
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
        },
    )

    assert result.returncode == 1
    assert "refused unsafe UPS audit log" in result.stderr
    assert protected.read_text(encoding="utf-8") == "sentinel\n"


def test_whole_script_root_mode_refuses_user_owned_lock_symlink(tmp_path: Path) -> None:
    state_root = tmp_path / "root-state"
    state_root.mkdir()
    protected = tmp_path / "protected-target"
    protected.write_text("sentinel\n", encoding="utf-8")
    lock = state_root / ".lock"
    lock.symlink_to(protected)
    live = tmp_path / "apcupsd"

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_DEST": str(live),
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
            "HAPAX_APCUPSD_INSTALL_TEST_ACTUAL_UID": "0",
            "HAPAX_ROOT_REQUIRED_STATE_ROOT": str(state_root),
            "HAPAX_ROOT_REQUIRED_LOCK_FILE": str(lock),
        },
    )

    assert result.returncode == 2
    assert "whole-script root execution is refused" in result.stderr
    assert protected.read_text(encoding="utf-8") == "sentinel\n"
    assert lock.is_symlink()
    assert not live.exists()


def test_nonroot_installer_refuses_shared_lock_symlink_before_mutation(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    protected = tmp_path / "protected-target"
    protected.write_text("sentinel\n", encoding="utf-8")
    lock = state_root / ".lock"
    lock.symlink_to(protected)
    live = tmp_path / "apcupsd"

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_DEST": str(live),
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
            "HAPAX_ROOT_REQUIRED_STATE_ROOT": str(state_root),
            "HAPAX_ROOT_REQUIRED_LOCK_FILE": str(lock),
            "HAPAX_ROOT_REQUIRED_LOCK_HELD": "1",
        },
    )

    assert result.returncode == 1
    assert "refused unsafe shared lock" in result.stderr
    assert protected.read_text(encoding="utf-8") == "sentinel\n"
    assert lock.is_symlink()
    assert not live.exists()


def test_installer_rejects_forged_inherited_lock_descriptor_before_mutation(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    lock = state_root / ".lock"
    forged = tmp_path / "forged-lock"
    forged_fd = os.open(forged, os.O_CREAT | os.O_RDWR, 0o600)
    live = tmp_path / "apcupsd"
    try:
        result = subprocess.run(
            [str(INSTALLER), "--install"],
            text=True,
            capture_output=True,
            check=False,
            pass_fds=(forged_fd,),
            env={
                **os.environ,
                "HAPAX_APCUPSD_DEST": str(live),
                "HAPAX_APCUPSD_INSTALL_SUDO": "",
                "HAPAX_ROOT_REQUIRED_STATE_ROOT": str(state_root),
                "HAPAX_ROOT_REQUIRED_LOCK_FILE": str(lock),
                "HAPAX_ROOT_REQUIRED_LOCK_FD": str(forged_fd),
            },
        )
    finally:
        os.close(forged_fd)

    assert result.returncode == 1
    assert "refused invalid shared lock descriptor" in result.stderr
    assert not lock.exists()
    assert not live.exists()


def test_unversioned_apcupsd_install_source_fails_before_live_mutation(tmp_path: Path) -> None:
    source = tmp_path / "not-a-repo"
    source.mkdir()
    live = tmp_path / "live-apcupsd"

    result = subprocess.run(
        [str(INSTALLER), "--source", str(source), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
            "HAPAX_APCUPSD_DEST": str(live),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": "",
        },
    )

    assert result.returncode == 1
    assert "source has no package SHA" in result.stderr
    assert not live.exists()


def test_apcupsd_manifest_shrink_fails_before_live_mutation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "ups-test@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "UPS Test"], cwd=repo, check=True)
    _copy_apcupsd_package(repo)
    manifest = repo / "config/root-required/apcupsd-power-alerts.files"
    retired_rel = "config/apcupsd/retired-hook"
    manifest.write_text(manifest.read_text(encoding="utf-8") + f"{retired_rel}\n", encoding="utf-8")
    retired = repo / retired_rel
    retired.write_text("formerly installed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "installed package"], cwd=repo, check=True, capture_output=True
    )
    installed_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    manifest.write_text(
        (REPO_ROOT / "config/root-required/apcupsd-power-alerts.files").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    retired.unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "candidate drops path"], cwd=repo, check=True, capture_output=True
    )
    candidate_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    receipt_root = tmp_path / "receipts"
    receipt_root.mkdir()
    receipt = receipt_root / "apcupsd-power-alerts.sha"
    receipt.write_text(f"{installed_sha}\n", encoding="utf-8")
    live = tmp_path / "live-apcupsd"
    result = subprocess.run(
        [str(INSTALLER), "--source", str(repo), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
            "HAPAX_APCUPSD_DEST": str(live),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": candidate_sha,
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(repo),
            "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT": str(receipt_root),
        },
    )

    assert result.returncode == 1
    assert f"refusing apcupsd package removal or rename of {retired_rel}" in result.stderr
    assert "explicit governed live-removal handling" in result.stderr
    assert receipt.read_text(encoding="utf-8").strip() == installed_sha
    assert not live.exists()


def test_apcupsd_install_implies_live_verification() -> None:
    body = INSTALLER.read_text(encoding="utf-8")
    assert 'if [ "$INSTALL" -eq 1 ]; then\n    VERIFY_LIVE=1\nfi' in body
    assert "$TARGET_HOME/.cache/hapax/source-activation/worktree" in body


def test_claimed_apcupsd_commit_rejects_modified_package_before_live_mutation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "staged"
    _copy_apcupsd_package(source)
    (source / ".hapax-root-required-package-sha").write_text(f"{REPO_HEAD}\n", encoding="utf-8")
    (source / "config" / "apcupsd" / "apcupsd.conf").write_text(
        "## apcupsd.conf v1.1 ##\nUPSNAME tampered\n", encoding="utf-8"
    )
    live = tmp_path / "live-apcupsd"

    result = subprocess.run(
        [str(INSTALLER), "--source", str(source), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
            "HAPAX_APCUPSD_DEST": str(live),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": REPO_HEAD,
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(REPO_ROOT),
        },
    )

    assert result.returncode == 1
    assert "does not match claimed commit" in result.stderr
    assert "config/apcupsd/apcupsd.conf" in result.stderr
    assert not live.exists()


@pytest.mark.parametrize("drift_kind", ("symlink", "git_mode"))
def test_claimed_apcupsd_commit_rejects_substituted_source_before_live_mutation(
    tmp_path: Path,
    drift_kind: str,
) -> None:
    source = tmp_path / "staged"
    _copy_apcupsd_package(source)
    relative = Path("config/apcupsd/apcupsd.conf")
    candidate = source / relative
    if drift_kind == "symlink":
        candidate.unlink()
        candidate.symlink_to(REPO_ROOT / relative)
    else:
        candidate.chmod(0o755)
    live = tmp_path / "live-apcupsd"

    result = subprocess.run(
        [str(INSTALLER), "--source", str(source), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
            "HAPAX_APCUPSD_DEST": str(live),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": REPO_HEAD,
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(REPO_ROOT),
        },
    )

    assert result.returncode == 1
    assert "not a regular file with the claimed Git mode" in result.stderr
    assert str(relative) in result.stderr
    assert not live.exists()


def test_claimed_apcupsd_commit_rejects_tracked_destination_mode_drift(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "apc-mode@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "APC Mode Test"], cwd=repo, check=True)
    _copy_apcupsd_package(repo)
    relative = Path("scripts/install-apcupsd-power-alerts")
    (repo / relative).chmod(0o644)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "mode drift"], cwd=repo, check=True, capture_output=True)
    candidate_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()
    live = tmp_path / "live-apcupsd"

    result = subprocess.run(
        [str(INSTALLER), "--source", str(repo), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
            "HAPAX_APCUPSD_DEST": str(live),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": candidate_sha,
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(repo),
        },
    )

    assert result.returncode == 1
    assert "Git mode violates the destination contract" in result.stderr
    assert str(relative) in result.stderr
    assert not live.exists()


def test_mismatched_apcupsd_deferral_is_rejected_before_live_mutation(tmp_path: Path) -> None:
    defer_root = tmp_path / "root-required"
    expected = defer_root / REPO_HEAD / "apcupsd-power-alerts"
    wrong = defer_root / REPO_HEAD / "wrong-package"
    _copy_apcupsd_package(expected)
    (expected / ".hapax-root-required-package-sha").write_text(f"{REPO_HEAD}\n", encoding="utf-8")
    (expected / "RUNBOOK.txt").write_text("expected\n", encoding="utf-8")
    wrong.mkdir(parents=True)
    (wrong / "RUNBOOK.txt").write_text("wrong\n", encoding="utf-8")
    live = tmp_path / "live-apcupsd"

    result = subprocess.run(
        [str(INSTALLER), "--source", str(expected), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
            "HAPAX_APCUPSD_DEST": str(live),
            "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_root),
            "HAPAX_ROOT_REQUIRED_DRAIN_DIR": str(wrong),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": REPO_HEAD,
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(REPO_ROOT),
        },
    )

    assert result.returncode == 1
    assert "refusing mismatched apcupsd deferral drain" in result.stderr
    assert not live.exists()


def test_apcupsd_installs_serialize_on_shared_package_lock(tmp_path: Path) -> None:
    dest = tmp_path / "apcupsd"
    audit_dir = tmp_path / "hapax-log"
    logrotate_dest = tmp_path / "logrotate.d" / "hapax-ups-power-events"
    upower_dest = tmp_path / "UPower.conf.d" / "90-hapax-apcupsd-owner.conf"
    calls = tmp_path / "systemctl-calls.txt"
    entered = tmp_path / "first-install-entered"
    release = tmp_path / "release-first-install"
    hold_claim = tmp_path / "hold-claim"
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {calls!s}\n"
        'if [ "$*" = "enable --now apcupsd.service" ] '
        f"&& mkdir {hold_claim!s} 2>/dev/null; then\n"
        f"  touch {entered!s}\n"
        f"  while [ ! -f {release!s} ]; do sleep 0.02; done\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    env = {
        **os.environ,
        "HAPAX_APCUPSD_DEST": str(dest),
        "HAPAX_APCUPSD_AUDIT_DIR": str(audit_dir),
        "HAPAX_APCUPSD_LOGROTATE_DEST": str(logrotate_dest),
        "HAPAX_UPOWER_CONF_DEST": str(upower_dest),
        "HAPAX_APCUPSD_SYSTEMCTL": str(fake_systemctl),
        "HAPAX_APCUPSD_INSTALL_SUDO": "",
        "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": REPO_HEAD,
        "HAPAX_ROOT_REQUIRED_GIT_REPO": str(REPO_ROOT),
        "HAPAX_ROOT_REQUIRED_LOCK_HELD": "1",
    }

    first = subprocess.Popen(
        [str(INSTALLER), "--install", "--verify-live"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    deadline = time.monotonic() + 5
    while not entered.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert entered.exists(), first.communicate(timeout=1)

    second = subprocess.Popen(
        [str(INSTALLER), "--install", "--verify-live"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    time.sleep(0.25)
    assert second.poll() is None
    assert calls.read_text(encoding="utf-8").splitlines().count("enable --now apcupsd.service") == 1

    release.touch()
    first_stdout, first_stderr = first.communicate(timeout=5)
    second_stdout, second_stderr = second.communicate(timeout=5)
    assert first.returncode == 0, (first_stdout, first_stderr)
    assert second.returncode == 0, (second_stdout, second_stderr)


def test_installer_drains_root_required_deferral_after_success(tmp_path: Path) -> None:
    dest = tmp_path / "apcupsd"
    audit_dir = tmp_path / "hapax-log"
    logrotate_dest = tmp_path / "logrotate.d" / "hapax-ups-power-events"
    upower_dest = tmp_path / "UPower.conf.d" / "90-hapax-apcupsd-owner.conf"
    drain_dir = tmp_path / "root-required" / REPO_HEAD / "apcupsd-power-alerts"
    installed_source = tmp_path / "current-source"
    drain_dir.mkdir(parents=True)
    _copy_apcupsd_package(drain_dir)
    (drain_dir / ".hapax-root-required-package-sha").write_text(f"{REPO_HEAD}\n", encoding="utf-8")
    (drain_dir / "RUNBOOK.txt").write_text("run installer\n", encoding="utf-8")
    sibling_dir = tmp_path / "root-required" / "other-sha" / "apcupsd-power-alerts"
    sibling_dir.mkdir(parents=True)
    (sibling_dir / "RUNBOOK.txt").write_text("run other installer\n", encoding="utf-8")
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--source", str(drain_dir), "--install", "--verify-live"],
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
    assert drain_dir.is_dir()
    assert (drain_dir / "DRAINED.txt").is_file()
    assert not (drain_dir / "RUNBOOK.txt").exists()
    assert sibling_dir.exists()
    assert (
        tmp_path / "root-state" / "installed-receipts" / "apcupsd-power-alerts.sha"
    ).read_text().strip() == REPO_HEAD
    assert (installed_source / "config" / "apcupsd" / "hapax-power-event.py").is_file()
    assert "root-required deferral marked drained" in result.stdout


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
    (drain_dir / ".hapax-root-required-package-sha").write_text(f"{sha_a}\n", encoding="utf-8")

    result = subprocess.run(
        [str(INSTALLER), "--source", str(drain_dir), "--install", "--verify-live"],
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
    assert drain_dir.is_dir()
    assert (drain_dir / "DRAINED.txt").is_file()
    assert not (drain_dir / "RUNBOOK.txt").exists()
    assert receipt.read_text(encoding="utf-8").strip() == sha_b
    assert live_marker.read_text(encoding="utf-8") == "newer B policy\n"


def test_installed_apcupsd_repair_cannot_erase_newer_desired_receipt(tmp_path: Path) -> None:
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
    (drain_dir / "RUNBOOK.txt").write_text("stale repair A\n", encoding="utf-8")
    (drain_dir / ".hapax-root-required-package-sha").write_text(f"{sha_a}\n", encoding="utf-8")
    installed_root = tmp_path / "root-state" / "installed-receipts"
    desired_root = tmp_path / "root-state" / "desired-receipts"
    installed_root.mkdir(parents=True)
    desired_root.mkdir(parents=True)
    installed = installed_root / "apcupsd-power-alerts.sha"
    desired = desired_root / "apcupsd-power-alerts.sha"
    installed.write_text(f"{sha_a}\n", encoding="utf-8")
    desired.write_text(f"{sha_b}\n", encoding="utf-8")
    live_dest = tmp_path / "live-apcupsd"
    live_dest.mkdir()
    live_marker = live_dest / "apcupsd.conf"
    live_marker.write_text("installed A policy\n", encoding="utf-8")

    result = subprocess.run(
        [str(INSTALLER), "--source", str(drain_dir), "--install", "--verify-live"],
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
            "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT": str(installed_root),
            "HAPAX_ROOT_REQUIRED_DESIRED_RECEIPT_ROOT": str(desired_root),
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(repo),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "superseded by desired" in result.stdout
    assert installed.read_text(encoding="utf-8").strip() == sha_a
    assert desired.read_text(encoding="utf-8").strip() == sha_b
    assert live_marker.read_text(encoding="utf-8") == "installed A policy\n"
    assert (drain_dir / "DRAINED.txt").is_file()


def test_apcupsd_squash_equivalence_rejects_newer_manifest_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "manifest-test@example.test"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Manifest Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    subprocess.run(["git", "switch", "-c", "candidate"], cwd=repo, check=True, capture_output=True)
    candidate_manifest = repo / "config/root-required/apcupsd-power-alerts.files"
    candidate_manifest.parent.mkdir(parents=True)
    candidate_manifest.write_text(
        "config/root-required/apcupsd-power-alerts.files\nscripts/install-apcupsd-power-alerts\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "candidate"], cwd=repo, check=True, capture_output=True)
    candidate_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    subprocess.run(
        ["git", "switch", "-c", "desired", base_sha], cwd=repo, check=True, capture_output=True
    )
    desired_manifest = repo / "config/root-required/apcupsd-power-alerts.files"
    desired_manifest.parent.mkdir(parents=True)
    desired_manifest.write_text(
        "config/root-required/apcupsd-power-alerts.files\nscripts/install-apcupsd-power-alerts\nconfig/apcupsd/new-policy\n",
        encoding="utf-8",
    )
    extra = repo / "config/apcupsd/new-policy"
    extra.parent.mkdir(parents=True)
    extra.write_text("new owned policy\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "desired adds owned file"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    desired_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    defer_root = tmp_path / "root-required"
    stage = defer_root / candidate_sha / "apcupsd-power-alerts"
    stage.mkdir(parents=True)
    (stage / "RUNBOOK.txt").write_text("candidate\n", encoding="utf-8")
    (stage / ".hapax-root-required-package-sha").write_text(f"{candidate_sha}\n", encoding="utf-8")
    installed_root = tmp_path / "root-state/installed-receipts"
    desired_root = tmp_path / "root-state/desired-receipts"
    installed_root.mkdir(parents=True)
    desired_root.mkdir(parents=True)
    (installed_root / "apcupsd-power-alerts.sha").write_text(f"{candidate_sha}\n", encoding="utf-8")
    desired_receipt = desired_root / "apcupsd-power-alerts.sha"
    desired_receipt.write_text(f"{desired_sha}\n", encoding="utf-8")

    result = subprocess.run(
        [str(INSTALLER), "--source", str(stage), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
            "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_root),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": candidate_sha,
            "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT": str(installed_root),
            "HAPAX_ROOT_REQUIRED_DESIRED_RECEIPT_ROOT": str(desired_root),
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(repo),
        },
    )

    assert result.returncode == 1
    assert "refusing divergent apcupsd package desired=" in result.stderr
    assert desired_receipt.read_text(encoding="utf-8").strip() == desired_sha
    assert (stage / "RUNBOOK.txt").is_file()


def test_apcupsd_installer_accepts_content_equivalent_squash_sibling(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "squash-test@example.test"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Squash Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    subprocess.run(["git", "switch", "-c", "pr"], cwd=repo, check=True, capture_output=True)
    _copy_apcupsd_package(repo)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "PR package"], cwd=repo, check=True, capture_output=True)
    pr_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    subprocess.run(
        ["git", "switch", "-c", "squash-main", base_sha],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    _copy_apcupsd_package(repo)
    (repo / "squash-marker").write_text("main sibling\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "squash package"], cwd=repo, check=True, capture_output=True
    )
    squash_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", pr_sha, squash_sha], cwd=repo, check=False
    )
    assert ancestry.returncode == 1

    receipt_root = tmp_path / "root-state" / "installed-receipts"
    receipt_root.mkdir(parents=True)
    receipt = receipt_root / "apcupsd-power-alerts.sha"
    receipt.write_text(f"{pr_sha}\n", encoding="utf-8")
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--source", str(repo), "--install", "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_APCUPSD_DEST": str(tmp_path / "apcupsd"),
            "HAPAX_APCUPSD_AUDIT_DIR": str(tmp_path / "audit"),
            "HAPAX_APCUPSD_LOGROTATE_DEST": str(tmp_path / "logrotate"),
            "HAPAX_UPOWER_CONF_DEST": str(tmp_path / "upower"),
            "HAPAX_APCUPSD_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_APCUPSD_INSTALL_SUDO": "",
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": squash_sha,
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(repo),
            "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT": str(receipt_root),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "package-content equivalent" in result.stdout
    assert receipt.read_text(encoding="utf-8").strip() == squash_sha

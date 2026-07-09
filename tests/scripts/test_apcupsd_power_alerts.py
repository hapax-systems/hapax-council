from __future__ import annotations

import json
import subprocess
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
    assert "hapax-power-event.py onbattery" in (CONFIG_DIR / "onbattery").read_text(
        encoding="utf-8"
    )
    assert "hapax-power-event.py offbattery" in (CONFIG_DIR / "offbattery").read_text(
        encoding="utf-8"
    )


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
    record = json.loads(audit.read_text(encoding="utf-8"))
    assert record["schema"] == "hapax.ups_power_event.v1"
    assert record["event"] == "onbattery"
    assert record["delivery"]["attempted"] is False
    assert record["apcaccess"]["STATUS"] == "ONLINE"


def test_installer_installs_config_hooks_and_audit_dir() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "config/apcupsd/apcupsd.conf" in text
    assert "/etc/apcupsd/hapax-power-event.py" in text
    assert "/var/log/hapax" in text
    assert "## apcupsd.conf v1.1 ##" in text

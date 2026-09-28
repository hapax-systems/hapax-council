from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/hapax-oom-seat-alert"


def _env(tmp_path: Path) -> dict[str, str]:
    vault = tmp_path / "vault"
    (vault / "30-areas/hapax/lanebus/dev1").mkdir(parents=True)
    boot = tmp_path / "boot-id"
    boot.write_text("877be5fc-b7c9-4017-91e0-2bb0d13baacd\n", encoding="ascii")
    audit = tmp_path / "audit"
    audit.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({'checks': [{'name': 'system_slice_MemoryMax', 'status': 'gap', "
        "'target': '18G', 'actual': 'infinity'}]}))\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    audit.chmod(0o755)
    return {
        **os.environ,
        "PERSONAL_VAULT_PATH": str(vault),
        "HAPAX_OOM_SEAT_ALERT_TEST_MODE": "1",
        "HAPAX_OOM_SEAT_ALERT_BOOT_ID_PATH": str(boot),
        "HAPAX_OOM_SEAT_ALERT_AUDIT": str(audit),
    }


def test_oom_failure_reaches_seat_once_per_boot(tmp_path: Path) -> None:
    env = _env(tmp_path)
    for _ in range(2):
        result = subprocess.run(
            [str(SCRIPT), "hapax-oom-policy-audit.service"],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        assert result.returncode == 0, result.stderr
    drops = list((Path(env["PERSONAL_VAULT_PATH"]) / "30-areas/hapax/lanebus/dev1").glob("*.md"))
    assert len(drops) == 1
    body = drops[0].read_text(encoding="utf-8")
    assert "system_slice_MemoryMax" in body
    assert "infinity" in body
    assert "cc-task-oom-policy-per-host-parameterization-20260809" in body


def test_oom_seat_alert_refuses_unrelated_unit(tmp_path: Path) -> None:
    env = _env(tmp_path)
    result = subprocess.run(
        [str(SCRIPT), "unrelated.service"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert result.returncode != 0
    assert not list((Path(env["PERSONAL_VAULT_PATH"]) / "30-areas/hapax/lanebus/dev1").iterdir())

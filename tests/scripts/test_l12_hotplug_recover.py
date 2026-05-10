"""Contract tests for L-12 bounded hotplug recovery."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RECOVER = REPO_ROOT / "scripts" / "hapax-l12-hotplug-recover"


def test_recover_starts_only_bounded_default_units(tmp_path: Path) -> None:
    calls = tmp_path / "calls.txt"
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "$HAPAX_TEST_CALLS"\nexit 0\n',
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    state = tmp_path / "state.json"

    result = subprocess.run(
        [str(RECOVER), "--systemctl", str(fake_systemctl), "--state-path", str(state)],
        env={"HAPAX_TEST_CALLS": str(calls)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    call_lines = calls.read_text(encoding="utf-8").splitlines()
    assert call_lines == [
        "--user start hapax-usb-topology-witness.service",
        "--user start hapax-livestream-tap-loopback.service",
        "--user start hapax-l12-mainmix-tap-loopback.service",
        "--user start hapax-audio-topology-verify.service",
    ]
    assert not any("pipewire.service" in line for line in call_lines)
    assert not any("wireplumber.service" in line for line in call_lines)
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["ok"] is True


def test_recover_refuses_default_pipewire_restart_units(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(RECOVER), "--unit", "pipewire.service", "--dry-run"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "refusing forbidden" in result.stderr

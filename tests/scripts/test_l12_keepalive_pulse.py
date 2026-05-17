"""Contract tests for scripts/hapax-l12-keepalive-pulse."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-l12-keepalive-pulse"
SERVICE = REPO_ROOT / "systemd" / "units" / "mixer-keepalive.service"
TIMER = REPO_ROOT / "systemd" / "units" / "mixer-keepalive.timer"

L12_SINK = (
    "alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40"
)


def load_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_l12_keepalive_pulse", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_choose_l12_sink_prefers_canonical_surround_sink() -> None:
    module = load_module()
    sinks = [
        "hapax-livestream",
        "alsa_output.usb-ZOOM_Corporation_L-12_x-00.analog-stereo",
        L12_SINK,
    ]

    assert module.choose_l12_sink(sinks) == L12_SINK


def test_absent_l12_records_state_without_false_failure(tmp_path: Path) -> None:
    module = load_module()
    pulse = tmp_path / "pulse.wav"
    state = tmp_path / "state.json"
    pulse.write_bytes(b"RIFFfake")

    pactl = tmp_path / "pactl"
    pactl.write_text("#!/usr/bin/env bash\nprintf '1\\thapax-livestream\\tPipeWire\\n'\n")
    pactl.chmod(0o755)
    pw_play = tmp_path / "pw-play"
    pw_play.write_text("#!/usr/bin/env bash\nexit 99\n")
    pw_play.chmod(0o755)

    rc = module.run_keepalive(
        pulse_path=pulse,
        state_path=state,
        pactl=str(pactl),
        pw_play=str(pw_play),
    )

    assert rc == 0
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["status"] == "l12_absent"
    assert payload["selected_target"] is None


def test_present_l12_sends_pulse_to_resolved_sink(tmp_path: Path) -> None:
    module = load_module()
    pulse = tmp_path / "pulse.wav"
    state = tmp_path / "state.json"
    target_log = tmp_path / "target.txt"
    pulse.write_bytes(b"RIFFfake")

    pactl = tmp_path / "pactl"
    pactl.write_text(f"#!/usr/bin/env bash\nprintf '9\\t{L12_SINK}\\tPipeWire\\n'\n")
    pactl.chmod(0o755)
    pw_play = tmp_path / "pw-play"
    pw_play.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' \"$1\" > {target_log}\nexit 0\n")
    pw_play.chmod(0o755)

    rc = module.run_keepalive(
        pulse_path=pulse,
        state_path=state,
        pactl=str(pactl),
        pw_play=str(pw_play),
    )

    assert rc == 0
    assert target_log.read_text(encoding="utf-8").strip() == f"--target={L12_SINK}"
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["status"] == "sent"
    assert payload["selected_target"] == L12_SINK


def test_script_cli_uses_env_overrides(tmp_path: Path) -> None:
    pulse = tmp_path / "pulse.wav"
    state = tmp_path / "state.json"
    pulse.write_bytes(b"RIFFfake")

    pactl = tmp_path / "pactl"
    pactl.write_text(f"#!/usr/bin/env bash\nprintf '9\\t{L12_SINK}\\tPipeWire\\n'\n")
    pactl.chmod(0o755)
    pw_play = tmp_path / "pw-play"
    pw_play.write_text("#!/usr/bin/env bash\nexit 0\n")
    pw_play.chmod(0o755)

    result = subprocess.run(
        [str(SCRIPT)],
        env={
            "PATH": "/usr/bin:/bin",
            "HAPAX_L12_KEEPALIVE_PULSE": str(pulse),
            "HAPAX_L12_KEEPALIVE_STATE": str(state),
            "HAPAX_L12_KEEPALIVE_PACTL": str(pactl),
            "HAPAX_L12_KEEPALIVE_PW_PLAY": str(pw_play),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["status"] == "sent"


def test_systemd_units_point_at_resolving_keepalive_script() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")

    assert "hapax-l12-keepalive-pulse" in service
    assert "PreSonus" not in service
    assert "OnUnitActiveSec=5min" in timer

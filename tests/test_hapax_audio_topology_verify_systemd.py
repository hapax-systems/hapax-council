"""Static checks for the boot-time topology verify systemd timer (audit A#5).

Regression pin: assert that:
  - ``systemd/units/hapax-audio-topology-verify.{service,timer}`` exist
    in the canonical install directory (so install-units.sh picks them up
    via its ``REPO_DIR/*.{service,timer}`` glob).
  - The unit + timer files parse cleanly (no broken sections / typos).
  - The timer is preset-enabled in ``systemd/user-preset.d/hapax.preset``
    so ``systemctl preset-all`` activates it.
  - The service ExecStart includes ``verify``, ``--strict``, ``--json``,
    and ``--output`` so the textfile-collector + JSON evidence file are
    actually produced on each tick.
"""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
PRESET_FILE = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"
INSTALL_SCRIPT = REPO_ROOT / "systemd" / "scripts" / "install-units.sh"


def _read_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # preserve case (systemd is case-sensitive)
    text = path.read_text(encoding="utf-8")
    # systemd ExecStart= lines may be split with trailing backslash; collapse them
    # so configparser can read the value as a single line.
    collapsed: list[str] = []
    buffer: list[str] = []
    for raw_line in text.splitlines():
        if raw_line.endswith("\\"):
            buffer.append(raw_line[:-1].strip())
            continue
        if buffer:
            buffer.append(raw_line.strip())
            collapsed.append(" ".join(buffer))
            buffer = []
        else:
            collapsed.append(raw_line)
    parser.read_string("\n".join(collapsed))
    return parser


def test_service_unit_exists_in_install_visible_path() -> None:
    """install-units.sh sweeps systemd/units/*.service so the unit must live there."""
    service = UNITS_DIR / "hapax-audio-topology-verify.service"
    assert service.exists(), f"{service} must exist in systemd/units so install-units.sh links it"


def test_timer_unit_exists_in_install_visible_path() -> None:
    timer = UNITS_DIR / "hapax-audio-topology-verify.timer"
    assert timer.exists(), (
        f"{timer} must exist in systemd/units so install-units.sh links + enables it"
    )


def test_service_unit_parses_cleanly() -> None:
    service = UNITS_DIR / "hapax-audio-topology-verify.service"
    parsed = _read_unit(service)
    assert "Unit" in parsed.sections()
    assert "Service" in parsed.sections()
    assert "Install" in parsed.sections()
    # Audit A#5 invariants
    assert parsed.get("Service", "Type") == "oneshot"
    after = parsed.get("Unit", "After", fallback="")
    assert "pipewire.service" in after
    assert "wireplumber.service" in after
    exec_start = parsed.get("Service", "ExecStart")
    assert "scripts/hapax-audio-topology" in exec_start
    assert "verify" in exec_start
    assert "--strict" in exec_start
    assert "--json" in exec_start
    assert "--output" in exec_start
    assert "/dev/shm/hapax-audio/topology-verify.json" in exec_start


def test_timer_unit_parses_cleanly() -> None:
    timer = UNITS_DIR / "hapax-audio-topology-verify.timer"
    parsed = _read_unit(timer)
    assert "Timer" in parsed.sections()
    assert "Install" in parsed.sections()
    # Cadence pin: 60s after boot, every 30s.
    # Audit A#5 originally specified 120s; cc-task
    # audio-audit-E-topology-prometheus-metrics (Auditor E, 2026-05-03)
    # tightened to 30s so Grafana drift trends + alerts on
    # `hapax_audio_topology_live_links_total{state="extra"} > 0` catch a
    # mid-run topology mutation within the same window the operator
    # uses to investigate. Single source of truth for the new value
    # also lives in tests/test_audio_topology_prometheus_metrics.py.
    assert parsed.get("Timer", "OnBootSec") == "60s"
    assert parsed.get("Timer", "OnUnitActiveSec") == "30s"
    assert parsed.get("Timer", "Unit") == "hapax-audio-topology-verify.service"
    assert parsed.get("Install", "WantedBy") == "timers.target"


def test_timer_is_preset_enabled() -> None:
    """The systemd preset file pins which audit-discovered timers are
    enabled by default; the verify timer must be in the list so a
    fresh install picks it up via ``systemctl preset-all``."""
    assert PRESET_FILE.exists()
    body = PRESET_FILE.read_text(encoding="utf-8")
    enabled_lines = {
        line.strip()
        for line in body.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "enable hapax-audio-topology-verify.timer" in enabled_lines


def test_install_script_sweeps_units_dir_so_no_explicit_auto_enable_needed() -> None:
    """install-units.sh sweeps systemd/units/*.{service,timer} unconditionally,
    so the new unit + timer ride into deployment without needing a hand-
    maintained AUTO_ENABLE list."""
    body = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert '"$REPO_DIR"/*.timer' in body
    assert '"$REPO_DIR"/*.service' in body
    # Belt + suspenders: ensure REPO_DIR resolves to systemd/units.
    assert 'REPO_DIR="$(cd "$(dirname "$0")/../units" && pwd)"' in body


def test_no_root_level_shadow_units() -> None:
    """Units placed under systemd/ root (not systemd/units/) are silently
    invisible to install-units.sh — guard against the same shape error
    other audited timers tripped over."""
    systemd_root = REPO_ROOT / "systemd"
    assert not (systemd_root / "hapax-audio-topology-verify.service").exists()
    assert not (systemd_root / "hapax-audio-topology-verify.timer").exists()

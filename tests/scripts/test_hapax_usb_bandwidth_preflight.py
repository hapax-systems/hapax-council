"""Tests for the USB bandwidth preflight checker."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-usb-bandwidth-preflight"


def _load_module() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "hapax_usb_bandwidth_preflight_under_test", str(SCRIPT)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def preflight() -> types.ModuleType:
    return _load_module()


# ---------------------------------------------------------------------------
# Sysfs fixtures
# ---------------------------------------------------------------------------


def _make_device(bus_dir: Path, name: str, *, vid: str, pid: str, speed: str) -> Path:
    dev = bus_dir / name
    dev.mkdir(parents=True)
    (dev / "idVendor").write_text(vid + "\n")
    (dev / "idProduct").write_text(pid + "\n")
    (dev / "speed").write_text(speed + "\n")
    return dev


def _make_root_hub(bdf_dir: Path, *, hub_name: str, speed: str = "480", busnum: int = 1) -> Path:
    hub = bdf_dir / hub_name
    hub.mkdir(parents=True)
    (hub / "speed").write_text(speed + "\n")
    (hub / "busnum").write_text(str(busnum) + "\n")
    return hub


def _make_pci_root(tmp_path: Path) -> Path:
    """Build a minimal /sys/bus/pci layout."""

    pci = tmp_path / "sys" / "bus" / "pci"
    (pci / "devices").mkdir(parents=True)
    return pci


def _layout_today_incident(pci: Path) -> None:
    """Reproduce the 2026-05-02 saturation pattern.

    BDF 0000:09:00.0 carries 3 BRIO + C920 + S-4 + Yeti — total ~66 Mbps,
    well under USB 2.0 480 Mbps but realistic for the front-case
    controller. BDF 0000:71:00.0 (the asmedia hub) carries the
    just-plugged L-12. The OPERATOR's plug attempt put the L-12 here.
    """

    front = pci / "devices" / "0000:09:00.0"
    front.mkdir()
    front_hub = _make_root_hub(front, hub_name="usb3", speed="480", busnum=3)
    _make_device(front_hub, "3-1", vid="046d", pid="085e", speed="480")  # BRIO
    _make_device(front_hub, "3-2", vid="046d", pid="085e", speed="480")  # BRIO
    _make_device(front_hub, "3-3", vid="046d", pid="085e", speed="480")  # BRIO
    _make_device(front_hub, "3-4", vid="046d", pid="08e5", speed="480")  # C920 PRO
    _make_device(front_hub, "3-5", vid="1fc9", pid="0104", speed="480")  # S-4
    _make_device(front_hub, "3-6", vid="b58e", pid="9e84", speed="480")  # Yeti

    back = pci / "devices" / "0000:71:00.0"
    back.mkdir()
    back_hub = _make_root_hub(back, hub_name="usb1", speed="480", busnum=1)
    _make_device(back_hub, "1-1", vid="1686", pid="03d5", speed="480")  # L-12


# ---------------------------------------------------------------------------
# Tests — sysfs walking + bandwidth summation
# ---------------------------------------------------------------------------


def test_collect_reports_finds_two_controllers(preflight: types.ModuleType, tmp_path: Path) -> None:
    pci = _make_pci_root(tmp_path)
    _layout_today_incident(pci)
    reports = preflight.collect_reports(sys_pci_root=pci)
    bdfs = sorted(r.bdf for r in reports)
    assert bdfs == ["0000:09:00.0", "0000:71:00.0"]


def test_bandwidth_summation_matches_static_table(
    preflight: types.ModuleType, tmp_path: Path
) -> None:
    pci = _make_pci_root(tmp_path)
    _layout_today_incident(pci)
    reports = {r.bdf: r for r in preflight.collect_reports(sys_pci_root=pci)}
    front = reports["0000:09:00.0"]
    # 3 * 15 (BRIO) + 10 (C920 PRO) + 8 (S-4) + 3 (Yeti) = 66
    assert front.used_mbps == pytest.approx(66.0)
    back = reports["0000:71:00.0"]
    # L-12 alone = 12 Mbps
    assert back.used_mbps == pytest.approx(12.0)


def test_unknown_device_falls_back_to_default(preflight: types.ModuleType, tmp_path: Path) -> None:
    pci = _make_pci_root(tmp_path)
    bdf = pci / "devices" / "0000:99:00.0"
    bdf.mkdir(parents=True)
    hub = _make_root_hub(bdf, hub_name="usb9", speed="480", busnum=9)
    _make_device(hub, "9-1", vid="dead", pid="beef", speed="480")
    reports = preflight.collect_reports(sys_pci_root=pci)
    assert len(reports) == 1
    dev = reports[0].devices[0]
    assert dev.is_known is False
    # synthesise_unknown returns DEFAULT_UNKNOWN_MBPS = 2.0
    assert dev.profile.bandwidth_mbps == pytest.approx(2.0)


@pytest.mark.parametrize("vid,pid", [("2886", "001a"), ("20b1", "4f00"), ("20b1", "4f01")])
def test_respeaker_xvf3800_profiles_are_known(vid: str, pid: str) -> None:
    """The array introduction must be preflightable before plug-in."""
    from shared.usb_bandwidth_table import lookup

    profile = lookup(vid, pid)
    assert profile is not None
    assert "XVF3800" in profile.name
    assert profile.bandwidth_mbps == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Tests — capacity inference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "speed,expected",
    [
        (480.0, 480.0),
        (5000.0, 5000.0),
        (10000.0, 10000.0),
        (20000.0, 20000.0),
        (12.0, 480.0),  # USB 1.1 low/full-speed devices roll up to USB 2.0
        (0.0, 480.0),  # speed unset / zero -> safe fallback
    ],
)
def test_capacity_inference_for_speed_levels(
    preflight: types.ModuleType, speed: float, expected: float
) -> None:
    from shared.usb_bandwidth_table import capacity_for_speed

    assert capacity_for_speed(speed) == expected


def test_capacity_picks_max_negotiated_speed(preflight: types.ModuleType, tmp_path: Path) -> None:
    pci = _make_pci_root(tmp_path)
    bdf = pci / "devices" / "0000:09:00.0"
    bdf.mkdir(parents=True)
    hub = _make_root_hub(bdf, hub_name="usb3", speed="480", busnum=3)
    # SuperSpeed device on the hub bumps capacity to 5G.
    _make_device(hub, "3-1", vid="046d", pid="085e", speed="5000")
    reports = preflight.collect_reports(sys_pci_root=pci)
    assert reports[0].capacity_mbps == 5000.0


# ---------------------------------------------------------------------------
# Tests — severity + exit code
# ---------------------------------------------------------------------------


def test_exit_code_ok_when_all_under_threshold(preflight: types.ModuleType, tmp_path: Path) -> None:
    pci = _make_pci_root(tmp_path)
    _layout_today_incident(pci)
    reports = preflight.collect_reports(sys_pci_root=pci)
    code = preflight.compute_exit_code(reports, warn=0.70, saturated=0.80)
    assert code == preflight.EXIT_OK


def test_exit_code_warning_at_warn_threshold(preflight: types.ModuleType, tmp_path: Path) -> None:
    pci = _make_pci_root(tmp_path)
    bdf = pci / "devices" / "0000:09:00.0"
    bdf.mkdir(parents=True)
    hub = _make_root_hub(bdf, hub_name="usb3", speed="480", busnum=3)
    # Pack 22 BRIOs * 15 = 330 / 480 = 68.75% — under default warn 70%.
    # Lower the warn threshold to make this a WARNING.
    for i in range(22):
        _make_device(hub, f"3-{i}", vid="046d", pid="085e", speed="480")
    reports = preflight.collect_reports(sys_pci_root=pci)
    code = preflight.compute_exit_code(reports, warn=0.50, saturated=0.80)
    assert code == preflight.EXIT_WARNING


def test_exit_code_saturated_at_saturated_threshold(
    preflight: types.ModuleType, tmp_path: Path
) -> None:
    pci = _make_pci_root(tmp_path)
    bdf = pci / "devices" / "0000:09:00.0"
    bdf.mkdir(parents=True)
    hub = _make_root_hub(bdf, hub_name="usb3", speed="480", busnum=3)
    # 30 BRIOs * 15 = 450 / 480 = 93.75% — over default saturated 80%.
    for i in range(30):
        _make_device(hub, f"3-{i}", vid="046d", pid="085e", speed="480")
    reports = preflight.collect_reports(sys_pci_root=pci)
    code = preflight.compute_exit_code(reports, warn=0.70, saturated=0.80)
    assert code == preflight.EXIT_SATURATED


# ---------------------------------------------------------------------------
# Tests — simulation mode
# ---------------------------------------------------------------------------


def test_parse_device_spec_basic(preflight: types.ModuleType) -> None:
    vid, pid, port = preflight.parse_device_spec("1686:03D5")
    assert vid == "1686"
    assert pid == "03d5"
    assert port is None


def test_parse_device_spec_with_port(preflight: types.ModuleType) -> None:
    vid, pid, port = preflight.parse_device_spec("1686:03d5/0000:09:00.0")
    assert vid == "1686"
    assert pid == "03d5"
    assert port == "0000:09:00.0"


def test_parse_device_spec_rejects_bad_form(preflight: types.ModuleType) -> None:
    with pytest.raises(ValueError):
        preflight.parse_device_spec("1686-03d5")


def test_apply_simulation_routes_to_target_bdf(preflight: types.ModuleType, tmp_path: Path) -> None:
    pci = _make_pci_root(tmp_path)
    _layout_today_incident(pci)
    reports = preflight.collect_reports(sys_pci_root=pci)
    target, profile = preflight.apply_simulation(reports, "1686:03d5/0000:09:00.0")
    assert target.bdf == "0000:09:00.0"
    assert profile.bandwidth_mbps == pytest.approx(12.0)
    # The simulation mutates the target in place.
    assert profile in target.simulated_added
    # Headroom decreased by the simulated device's bandwidth.
    assert target.used_mbps == pytest.approx(78.0)  # 66 + 12


def test_apply_simulation_picks_least_loaded_when_no_target(
    preflight: types.ModuleType, tmp_path: Path
) -> None:
    pci = _make_pci_root(tmp_path)
    _layout_today_incident(pci)
    reports = preflight.collect_reports(sys_pci_root=pci)
    target, _profile = preflight.apply_simulation(reports, "1686:03d5")
    # Both controllers are well below warn threshold; the simulator picks
    # the least-loaded, which is the back hub (12 Mbps).
    assert target.bdf == "0000:71:00.0"


# ---------------------------------------------------------------------------
# Tests — output formats
# ---------------------------------------------------------------------------


def test_render_json_includes_per_controller_data(
    preflight: types.ModuleType, tmp_path: Path
) -> None:
    pci = _make_pci_root(tmp_path)
    _layout_today_incident(pci)
    reports = preflight.collect_reports(sys_pci_root=pci)
    rendered = preflight.render_json(reports, warn=0.70, saturated=0.80)
    payload = json.loads(rendered)
    assert "controllers" in payload
    bdfs = sorted(c["bdf"] for c in payload["controllers"])
    assert bdfs == ["0000:09:00.0", "0000:71:00.0"]
    front = next(c for c in payload["controllers"] if c["bdf"] == "0000:09:00.0")
    assert front["used_mbps"] == pytest.approx(66.0)
    assert front["severity"] == "OK"
    assert front["headroom_mbps"] == pytest.approx(414.0)
    assert any(d["vid"] == "1686" or d["vid"] == "046d" for d in front["devices"])


def test_render_json_includes_simulation_block(preflight: types.ModuleType, tmp_path: Path) -> None:
    pci = _make_pci_root(tmp_path)
    _layout_today_incident(pci)
    reports = preflight.collect_reports(sys_pci_root=pci)
    target, profile = preflight.apply_simulation(reports, "1686:03d5/0000:09:00.0")
    rendered = preflight.render_json(
        reports,
        warn=0.70,
        saturated=0.80,
        target=target,
        simulated=profile,
    )
    payload = json.loads(rendered)
    assert "simulation" in payload
    assert payload["simulation"]["added_to"] == "0000:09:00.0"
    assert payload["simulation"]["device"]["vid"] == "1686"


def test_render_prometheus_emits_four_metric_families(
    preflight: types.ModuleType, tmp_path: Path
) -> None:
    pci = _make_pci_root(tmp_path)
    _layout_today_incident(pci)
    reports = preflight.collect_reports(sys_pci_root=pci)
    rendered = preflight.render_prometheus(reports)
    for metric in (
        "hapax_usb_bandwidth_capacity_bps",
        "hapax_usb_bandwidth_used_bps",
        "hapax_usb_bandwidth_headroom_bps",
        "hapax_usb_bandwidth_headroom_ratio",
    ):
        assert f"# TYPE {metric} gauge" in rendered
        assert f'{metric}{{bdf="0000:09:00.0",bus="3"}}' in rendered
    # Verify a value: front controller used ~66 Mbps -> 66e6 bps.
    assert "66000000" in rendered


def test_render_human_marks_severity(preflight: types.ModuleType, tmp_path: Path) -> None:
    pci = _make_pci_root(tmp_path)
    bdf = pci / "devices" / "0000:09:00.0"
    bdf.mkdir(parents=True)
    hub = _make_root_hub(bdf, hub_name="usb3", speed="480", busnum=3)
    for i in range(30):
        _make_device(hub, f"3-{i}", vid="046d", pid="085e", speed="480")
    reports = preflight.collect_reports(sys_pci_root=pci)
    out = preflight.render_human(reports, warn=0.70, saturated=0.80, use_colour=False)
    assert "SATURATED" in out
    assert "0000:09:00.0" in out


# ---------------------------------------------------------------------------
# Tests — monitor mode
# ---------------------------------------------------------------------------


def test_monitor_loop_writes_textfile_then_exits(
    preflight: types.ModuleType, tmp_path: Path
) -> None:
    pci = _make_pci_root(tmp_path)
    _layout_today_incident(pci)
    prom_path = tmp_path / "out" / "hapax-usb-bandwidth.prom"

    def no_sleep(_seconds: float) -> None:
        return None

    code = preflight.monitor_loop(
        sys_pci_root=pci,
        interval_sec=0,
        prom_path=prom_path,
        warn=0.70,
        saturated=0.80,
        iterations=2,
        sleep_fn=no_sleep,
    )
    assert code == preflight.EXIT_OK
    assert prom_path.exists()
    text = prom_path.read_text(encoding="utf-8")
    assert "hapax_usb_bandwidth_capacity_bps" in text
    assert "0000:09:00.0" in text


# ---------------------------------------------------------------------------
# Tests — main / CLI integration
# ---------------------------------------------------------------------------


def test_main_returns_zero_on_clean_topology(
    preflight: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pci = _make_pci_root(tmp_path)
    _layout_today_incident(pci)
    code = preflight.main(["--sys-pci-root", str(pci), "--no-colour"])
    captured = capsys.readouterr()
    assert code == preflight.EXIT_OK
    assert "0000:09:00.0" in captured.out


def test_main_simulation_with_json(
    preflight: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pci = _make_pci_root(tmp_path)
    _layout_today_incident(pci)
    code = preflight.main(
        [
            "--sys-pci-root",
            str(pci),
            "--device",
            "1686:03d5/0000:09:00.0",
            "--json",
        ]
    )
    assert code == preflight.EXIT_OK
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["simulation"]["added_to"] == "0000:09:00.0"
    front = next(c for c in payload["controllers"] if c["bdf"] == "0000:09:00.0")
    assert front["used_mbps"] == pytest.approx(78.0)


def test_main_rejects_bad_device_spec(
    preflight: types.ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pci = _make_pci_root(tmp_path)
    _layout_today_incident(pci)
    code = preflight.main(["--sys-pci-root", str(pci), "--device", "1686-03d5"])
    captured = capsys.readouterr()
    assert code == 64
    assert "must be vid:pid" in captured.err

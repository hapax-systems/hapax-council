"""Pin Option C target string in `scripts/hapax-private-monitor-recover`.

This regression test enforces the constitutional invariant that the private
monitor recovery script targets the S-4 USB IN multichannel-output sink (not
the Blue Yeti) per the Option C spec amendment of 2026-05-02. Pinning the
exact string at module load time prevents a silent regression where someone
flips it back to the Yeti string (which would re-introduce the L-12 leak path
because the Yeti pin lives outside the audited Track-1-fenced architecture).

Privacy invariant reference:
    feedback_l12_equals_livestream_invariant — anything entering L-12 reaches
    broadcast. Private monitor streams MUST route to a private-fenced
    destination outside L-12.

Spec amendment:
    docs/superpowers/specs/2026-05-02-hapax-private-monitor-track-fenced-via-s4.md
"""

from __future__ import annotations

import importlib.util
import sys
import types
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "hapax-private-monitor-recover"

S4_USB_SINK = "alsa_output.usb-Torso_Electronics_S-4_fedcba9876543220-03.multichannel-output"
YETI_TARGET_LEGACY = "alsa_output.usb-Blue_Microphones_Yeti_Stereo_Microphone_REV8-00.analog-stereo"


def _load_recover_script() -> types.ModuleType:
    """Load the extension-less recover script as an importable module."""
    loader = SourceFileLoader("_recover_option_c_target_pin", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def recover() -> types.ModuleType:
    return _load_recover_script()


def test_exact_target_pins_to_s4_usb_in_sink(recover: types.ModuleType) -> None:
    """`EXACT_PRIVATE_MONITOR_TARGET` must be the S-4 USB IN sink, not Yeti."""
    assert recover.EXACT_PRIVATE_MONITOR_TARGET == S4_USB_SINK, (
        f"recover script must target S-4 USB IN sink under Option C; "
        f"got {recover.EXACT_PRIVATE_MONITOR_TARGET!r}"
    )


def test_exact_target_is_not_the_legacy_yeti_string(recover: types.ModuleType) -> None:
    """Defense-in-depth: pin the negative as well so a flip back is loud."""
    assert recover.EXACT_PRIVATE_MONITOR_TARGET != YETI_TARGET_LEGACY


def test_sanitized_refs_indicate_s4_route(recover: types.ModuleType) -> None:
    """Sanitized refs in the status JSON must reflect Option C, not Yeti."""
    assert recover.ROUTE_REF == "route:private.s4_track_fenced"
    assert recover.SANITIZED_TARGET_REF == "audio.s4_private_monitor"
    # The legacy yeti_monitor refs must be GONE.
    assert "yeti_monitor" not in recover.ROUTE_REF
    assert "yeti_monitor" not in recover.SANITIZED_TARGET_REF


def test_script_source_does_not_carry_yeti_target_string() -> None:
    """The recover script source must not contain the literal Yeti sink.

    Pinning the source-level absence catches a regression in either the
    constant or in supporting helper code (e.g. validation strings).
    The Yeti pin is preserved on disk under
    `config/wireplumber/56-hapax-private-pin-yeti.conf.disabled-2026-05-02-option-c`
    for revert capability — the recover script does NOT mention it.
    """
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert YETI_TARGET_LEGACY not in text, (
        "Recover script must not carry the legacy Yeti sink string under Option C"
    )
    assert S4_USB_SINK in text


def test_script_validate_repo_bridge_requires_s4_target(
    recover: types.ModuleType, tmp_path: Path
) -> None:
    """`_validate_repo_bridge` must accept S-4 bridge content + reject pre-Option-C
    bridge content that still hardcodes the Yeti target."""
    repo_bridge = tmp_path / "hapax-private-monitor-bridge.conf"

    # Synthesize a minimally-valid Option C bridge: includes the S-4 sink
    # string AND the fail-closed pins the validator requires.
    valid_bridge = (
        f'target.object = "{S4_USB_SINK}"\n'
        "node.dont-fallback = true\n"
        "node.dont-reconnect = true\n"
        "node.dont-move = true\n"
        "node.linger = true\n"
        "state.restore = false\n"
        'target.object = "hapax-private"\n'
        'target.object = "hapax-notification-private"\n'
    )
    repo_bridge.write_text(valid_bridge, encoding="utf-8")
    # Should not raise.
    recover._validate_repo_bridge(repo_bridge)

    # Pre-Option C bridge (Yeti target only) is now invalid because
    # EXACT_PRIVATE_MONITOR_TARGET is the S-4 string.
    invalid_bridge = valid_bridge.replace(S4_USB_SINK, YETI_TARGET_LEGACY)
    repo_bridge.write_text(invalid_bridge, encoding="utf-8")
    with pytest.raises(ValueError, match="missing required fail-closed pin"):
        recover._validate_repo_bridge(repo_bridge)


# ---------------------------------------------------------------------------
# Auto-reload (PipeWire restart on bridge drift) — Option C runtime closure
# ---------------------------------------------------------------------------
#
# Background: the original Option C deploy (PR #2305) shipped the canonical
# S-4-targeting bridge conf in `config/pipewire/`. When the recover service
# detected drift it rewrote the on-disk file but did NOT restart PipeWire,
# so the daemon kept the stale `context.modules` definition (Yeti target)
# loaded in memory and the pin "did not bind". Operators had to notice and
# manually `systemctl --user restart pipewire pipewire-pulse wireplumber`.
#
# The auto-reload flag closes that loop: when drift is repaired in-place,
# the script also restarts the PipeWire stack so the new loopback target
# takes effect within seconds. Without this, post-Option-C deploys remain
# silently stale until reboot.

import shutil  # noqa: E402  — placed after fixtures by intent
import subprocess  # noqa: E402
from unittest.mock import patch  # noqa: E402


def test_install_bridge_records_pipewire_reload_metadata(
    recover: types.ModuleType, tmp_path: Path
) -> None:
    """`_install_bridge` returns the new `pipewire_reloaded` and
    `pipewire_reload_error` keys so downstream observers can tell whether
    the daemon actually got cycled."""
    repo_bridge = tmp_path / "hapax-private-monitor-bridge.conf"
    repo_bridge.write_text("# canonical S-4 bridge\n", encoding="utf-8")
    install_path = tmp_path / "deployed.conf"

    bridge = recover._install_bridge(repo_bridge, install_path, install=False)
    assert "pipewire_reloaded" in bridge
    assert "pipewire_reload_error" in bridge
    assert bridge["pipewire_reloaded"] is False
    assert bridge["pipewire_reload_error"] == ""


def test_install_bridge_no_auto_reload_does_not_invoke_systemctl(
    recover: types.ModuleType, tmp_path: Path
) -> None:
    """Default behaviour (without --auto-reload) must NEVER call systemctl —
    the script remains side-effect-free for test environments and any caller
    that is happy to handle the restart externally."""
    repo_bridge = tmp_path / "hapax-private-monitor-bridge.conf"
    repo_bridge.write_text("# canonical\n", encoding="utf-8")
    install_path = tmp_path / "deployed.conf"
    install_path.write_text("# stale\n", encoding="utf-8")

    with patch.object(recover.subprocess, "run") as run_mock:
        bridge = recover._install_bridge(repo_bridge, install_path, install=True, auto_reload=False)
        run_mock.assert_not_called()
    assert bridge["repaired"] is True
    assert bridge["requires_pipewire_reload"] is True
    assert bridge["pipewire_reloaded"] is False


def test_install_bridge_auto_reload_restarts_pipewire_stack_on_repair(
    recover: types.ModuleType, tmp_path: Path
) -> None:
    """When auto_reload=True AND the bridge is repaired in-place AND it was
    already installed, the script must invoke
    `systemctl --user restart pipewire pipewire-pulse wireplumber` so the
    PipeWire daemon reloads the loopback `context.modules` block."""
    repo_bridge = tmp_path / "hapax-private-monitor-bridge.conf"
    repo_bridge.write_text("# canonical S-4\n", encoding="utf-8")
    install_path = tmp_path / "deployed.conf"
    install_path.write_text("# stale Yeti\n", encoding="utf-8")

    with patch.object(recover.shutil, "which", return_value="/usr/bin/systemctl"):
        with patch.object(recover.subprocess, "run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess([], 0, "", "")
            bridge = recover._install_bridge(
                repo_bridge, install_path, install=True, auto_reload=True
            )
            run_mock.assert_called_once()
            call_args = run_mock.call_args
            cmd = call_args.args[0]
            assert cmd[:3] == ["systemctl", "--user", "restart"]
            for unit in recover.PIPEWIRE_RELOAD_UNITS:
                assert unit in cmd
    assert bridge["repaired"] is True
    assert bridge["pipewire_reloaded"] is True
    assert bridge["pipewire_reload_error"] == ""


def test_install_bridge_auto_reload_skips_when_no_drift(
    recover: types.ModuleType, tmp_path: Path
) -> None:
    """When the deployed conf already matches canonical, auto_reload MUST NOT
    bounce PipeWire — the daemon is already correct."""
    canonical = "# canonical S-4 bridge\n"
    repo_bridge = tmp_path / "hapax-private-monitor-bridge.conf"
    repo_bridge.write_text(canonical, encoding="utf-8")
    install_path = tmp_path / "deployed.conf"
    install_path.write_text(canonical, encoding="utf-8")

    with patch.object(recover.subprocess, "run") as run_mock:
        bridge = recover._install_bridge(repo_bridge, install_path, install=True, auto_reload=True)
        run_mock.assert_not_called()
    assert bridge["repaired"] is False
    assert bridge["requires_pipewire_reload"] is False
    assert bridge["pipewire_reloaded"] is False


def test_install_bridge_auto_reload_skips_when_first_install(
    recover: types.ModuleType, tmp_path: Path
) -> None:
    """First-install case (deployed file did not exist before): the daemon
    will pick up the new conf on its next normal restart cycle. Bouncing
    PipeWire on first install is overkill and may surprise the operator;
    only repair-in-place cases trigger auto-reload."""
    repo_bridge = tmp_path / "hapax-private-monitor-bridge.conf"
    repo_bridge.write_text("# canonical\n", encoding="utf-8")
    install_path = tmp_path / "deployed.conf"
    # NOTE: install_path does not exist — first-install case.

    with patch.object(recover.subprocess, "run") as run_mock:
        bridge = recover._install_bridge(repo_bridge, install_path, install=True, auto_reload=True)
        run_mock.assert_not_called()
    assert bridge["repaired"] is True
    assert bridge["requires_pipewire_reload"] is False  # first install
    assert bridge["pipewire_reloaded"] is False


def test_install_bridge_auto_reload_records_systemctl_failure(
    recover: types.ModuleType, tmp_path: Path
) -> None:
    """If systemctl fails (e.g. unit name typo, transient bus error), the
    error string must be captured in `pipewire_reload_error` so the witness
    JSON surfaces it. The script must NOT raise — drift recovery already
    succeeded and the operator just needs to restart manually."""
    repo_bridge = tmp_path / "hapax-private-monitor-bridge.conf"
    repo_bridge.write_text("# canonical\n", encoding="utf-8")
    install_path = tmp_path / "deployed.conf"
    install_path.write_text("# stale\n", encoding="utf-8")

    with patch.object(recover.shutil, "which", return_value="/usr/bin/systemctl"):
        with patch.object(recover.subprocess, "run") as run_mock:
            run_mock.side_effect = subprocess.CalledProcessError(
                returncode=5, cmd="systemctl", stderr="Unit not found"
            )
            bridge = recover._install_bridge(
                repo_bridge, install_path, install=True, auto_reload=True
            )
    assert bridge["repaired"] is True
    assert bridge["pipewire_reloaded"] is False
    assert "systemctl_failed" in bridge["pipewire_reload_error"]


def test_install_bridge_auto_reload_handles_missing_systemctl(
    recover: types.ModuleType, tmp_path: Path
) -> None:
    """If systemctl is not on PATH (e.g. in a CI container), record the
    failure mode and continue — do not raise."""
    repo_bridge = tmp_path / "hapax-private-monitor-bridge.conf"
    repo_bridge.write_text("# canonical\n", encoding="utf-8")
    install_path = tmp_path / "deployed.conf"
    install_path.write_text("# stale\n", encoding="utf-8")

    with patch.object(recover.shutil, "which", return_value=None):
        with patch.object(recover.subprocess, "run") as run_mock:
            bridge = recover._install_bridge(
                repo_bridge, install_path, install=True, auto_reload=True
            )
            run_mock.assert_not_called()
    assert bridge["pipewire_reloaded"] is False
    assert bridge["pipewire_reload_error"] == "systemctl_not_in_path"


def test_systemd_unit_passes_auto_reload_flag() -> None:
    """The systemd `hapax-private-monitor-recover.service` unit MUST pass
    `--auto-reload` so the timer-driven recovery actually closes the loop
    end-to-end. Without this flag the service would only update the conf
    file and the daemon would keep the stale loopback live until manual
    operator action — which is the exact failure mode the spec amendment
    intends to prevent."""
    unit_path = REPO_ROOT / "systemd" / "units" / "hapax-private-monitor-recover.service"
    body = unit_path.read_text(encoding="utf-8")
    assert "--auto-reload" in body, (
        "Service unit must pass --auto-reload so PipeWire is restarted on drift"
    )
    assert "--install" in body
    assert "hapax-private-monitor-recover" in body


def test_auto_reload_implies_install_when_only_auto_reload_passed(
    recover: types.ModuleType, tmp_path: Path
) -> None:
    """`--auto-reload` alone (without explicit `--install`) is treated as
    `--install --auto-reload` — the contract is "if you may restart
    PipeWire, you may write the file that justifies the restart"."""
    # Stand up a minimal valid bridge so `_validate_repo_bridge` passes.
    repo_bridge_dir = tmp_path / "config" / "pipewire"
    repo_bridge_dir.mkdir(parents=True)
    repo_bridge = repo_bridge_dir / "hapax-private-monitor-bridge.conf"
    valid = (
        f'target.object = "{S4_USB_SINK}"\n'
        "node.dont-fallback = true\n"
        "node.dont-reconnect = true\n"
        "node.dont-move = true\n"
        "node.linger = true\n"
        "state.restore = false\n"
        'target.object = "hapax-private"\n'
        'target.object = "hapax-notification-private"\n'
    )
    repo_bridge.write_text(valid, encoding="utf-8")
    install_path = tmp_path / "deployed.conf"
    status_path = tmp_path / "status.json"
    dump_path = tmp_path / "dump.json"
    dump_path.write_text("[]", encoding="utf-8")

    with patch.object(recover.shutil, "which", return_value="/usr/bin/systemctl"):
        with patch.object(recover.subprocess, "run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess([], 0, "", "")
            rc = recover.main(
                [
                    "--repo-root",
                    str(tmp_path),
                    "--install-path",
                    str(install_path),
                    "--status-path",
                    str(status_path),
                    "--dump-file",
                    str(dump_path),
                    "--auto-reload",
                ]
            )
    # Bridge nodes will be absent (empty pw-dump), so blocked_absent → exit 2.
    assert rc == 2
    # The conf was written because --install is auto-implied by --auto-reload.
    assert install_path.exists()
    assert install_path.read_text(encoding="utf-8") == valid


# Silence the unused-import linter for shutil — we use it via patch.object
# on `recover.shutil.which`, but ruff doesn't see that path.
_ = shutil

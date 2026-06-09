"""Integration verification for the V4L2 bridge sidecar failure-isolation contract.

Maps directly to the three failure-isolation scenarios in cc-task
``202605181733-v4l2-bridge-sidec-p3-integration-verification`` and architecture
doc ``docs/architecture/v4l2-bridge-sidecar.md`` §5 (failure modes and recovery):

1. Sidecar crash -> systemd restarts it -> video stream recovers within
   ``RestartSec`` *without* a compositor restart.
2. Compositor restart -> sidecar reconnects to the new shm segment without
   manual intervention.
3. ``v4l2loopback`` module unloaded and reloaded -> sidecar recovers gracefully.

The existing suites (``test_v4l2_shm_bridge.py``,
``test_shmsink_output_pipeline.py``, ``test_studio_compositor_visual_stack_units.py``)
cover the building blocks (fd lifecycle, property setters, the full systemd unit
contract). This module covers the *recovery cascades* that make each scenario
recover end to end -- the bus-error/EOS teardown, the socket reconnect loop, and
the ``os.write``/``os.open`` errno recovery -- which no existing test exercises.
Each scenario also asserts the single declarative systemd property that is its
recovery linchpin; the full unit contract lives in
``tests/systemd/test_studio_compositor_visual_stack_units.py``.

GStreamer is unavailable in unit context, so ``Gst``/``GLib`` are mocked as inert
collaborators (the same approach as ``test_v4l2_shm_bridge.py``). Everything that
is actually verified -- fd state, counters, return codes, errno classification,
socket parsing, the reopen cycle -- is real bridge code.
"""

from __future__ import annotations

import configparser
import errno
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.studio_compositor.v4l2_output_pipeline import _RECOVERABLE_ERRNOS
from agents.studio_compositor.v4l2_shm_bridge import (
    BridgeConfig,
    ShmToV4l2Bridge,
    socket_listening,
    wait_for_socket,
)

_MODULE = "agents.studio_compositor.v4l2_shm_bridge"
REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_UNIT = REPO_ROOT / "systemd" / "units" / "hapax-v4l2-bridge.service"
COMPOSITOR_UNIT = REPO_ROOT / "systemd" / "units" / "studio-compositor.service"


def _load_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment]
    parser.read(path, encoding="utf-8")
    return parser


def _bridge(tmp_path: Path) -> ShmToV4l2Bridge:
    config = BridgeConfig(
        device=str(tmp_path / "video42"),
        socket_path=str(tmp_path / "bridge.sock"),
        width=1280,
        height=720,
        fps=30,
        wait_seconds=3,
        metrics_path=tmp_path / "bridge.prom",
    )
    return ShmToV4l2Bridge(config, MagicMock(), MagicMock())


def _fake_sample(payload: bytes) -> MagicMock:
    """Build a GStreamer appsink that yields one buffer mapping to ``payload``."""
    map_info = MagicMock()
    map_info.data = payload
    buf = MagicMock()
    buf.map.return_value = (True, map_info)
    sample = MagicMock()
    sample.get_buffer.return_value = buf
    appsink = MagicMock()
    appsink.emit.return_value = sample
    return appsink


class TestScenario1SidecarCrash:
    """Sidecar crash -> systemd restart -> recovery without compositor restart."""

    def test_bus_error_marks_failed_and_releases_v4l2_device(self, tmp_path: Path) -> None:
        # A pipeline bus ERROR (the canonical sidecar crash signal) must mark the
        # run failed and release the loopback fd so the kernel frees the device
        # before systemd respawns the process.
        bridge = _bridge(tmp_path)
        bridge._pipeline = MagicMock()
        bridge._fd = 999
        message = MagicMock()
        err = MagicMock()
        err.message = "Internal data stream error"
        message.parse_error.return_value = (err, "debug")

        with patch("os.close") as os_close:
            bridge._on_bus_error(MagicMock(), message)

        assert bridge._failed is True
        assert bridge._stopping is True
        bridge._pipeline.set_state.assert_called_with(bridge._Gst.State.NULL)
        os_close.assert_called_once_with(999)
        assert bridge._fd == -1

    def test_run_returns_nonzero_when_pipeline_fails_so_systemd_restarts(
        self, tmp_path: Path
    ) -> None:
        # Restart=on-failure only fires on a nonzero exit. A failure observed
        # while the GLib loop runs must propagate to the process exit code.
        bridge = _bridge(tmp_path)
        loop = MagicMock()
        loop.run.side_effect = lambda: setattr(bridge, "_failed", True)
        bridge._GLib.MainLoop.return_value = loop

        with patch.object(bridge, "start", return_value=True):
            assert bridge.run() == 1

    def test_clean_shutdown_returns_zero_so_systemd_does_not_respawn(self, tmp_path: Path) -> None:
        # A SIGTERM-driven clean stop (e.g. BindsTo teardown with the compositor)
        # must exit zero so on-failure restart does not spuriously respawn it.
        bridge = _bridge(tmp_path)
        bridge._GLib.MainLoop.return_value = MagicMock()

        with patch.object(bridge, "start", return_value=True):
            assert bridge.run() == 0

    def test_startup_failure_exits_nonzero_and_flushes_metrics(self, tmp_path: Path) -> None:
        bridge = _bridge(tmp_path)

        with patch.object(bridge, "start", return_value=False):
            assert bridge.run() == 1

        assert bridge.counters.errors == 1
        assert (tmp_path / "bridge.prom").exists()

    def test_restart_contract_bounds_recovery_window(self) -> None:
        # Declarative linchpin: recovery is bounded to <2s by RestartSec=1s, and
        # the sidecar is a leaf of the compositor (BindsTo is compositor->sidecar)
        # so its crash never tears the compositor down.
        unit = _load_unit(BRIDGE_UNIT)
        assert unit.get("Service", "Restart") == "on-failure"
        assert unit.get("Service", "RestartSec") == "1s"
        assert unit.get("Unit", "BindsTo") == "studio-compositor.service"


class TestScenario2CompositorRestart:
    """Compositor restart -> sidecar reconnects to the new shm segment."""

    def test_socket_listening_detects_fresh_listening_socket(self, tmp_path: Path) -> None:
        sock = str(tmp_path / "bridge.sock")
        ss_output = (
            f"u_str LISTEN 0 128 {sock} 12345 * 0\n"
            "u_str ESTAB  0 0   /run/user/1000/other.sock 67890 * 0\n"
        )
        result = MagicMock(returncode=0, stdout=ss_output)
        with patch(f"{_MODULE}.subprocess.run", return_value=result):
            assert socket_listening(sock) is True

    def test_socket_listening_rejects_present_but_non_listening_socket(
        self, tmp_path: Path
    ) -> None:
        # A stale socket left by a crashed compositor is present but not LISTENing;
        # the bridge must not connect to it (architecture doc R2 triple-defense).
        sock = str(tmp_path / "bridge.sock")
        result = MagicMock(returncode=0, stdout=f"u_str ESTAB 0 0 {sock} 12345 * 0\n")
        with patch(f"{_MODULE}.subprocess.run", return_value=result):
            assert socket_listening(sock) is False

    def test_socket_listening_false_when_ss_unavailable(self, tmp_path: Path) -> None:
        with patch(f"{_MODULE}.subprocess.run", side_effect=OSError):
            assert socket_listening(str(tmp_path / "bridge.sock")) is False

    def test_wait_for_socket_returns_once_new_socket_starts_listening(self, tmp_path: Path) -> None:
        # After a compositor restart the shmsink socket reappears a moment later;
        # the bridge polls until it is LISTENing, then reconnects.
        sock = str(tmp_path / "bridge.sock")
        with (
            patch(f"{_MODULE}.Path.is_socket", return_value=True),
            patch(f"{_MODULE}.socket_listening", side_effect=[False, False, True]),
            patch(f"{_MODULE}.time.sleep") as sleep,
        ):
            assert wait_for_socket(sock, wait_seconds=5) is True
        assert sleep.call_count == 2

    def test_wait_for_socket_times_out_when_socket_never_returns(self, tmp_path: Path) -> None:
        sock = str(tmp_path / "bridge.sock")
        with (
            patch(f"{_MODULE}.Path.is_socket", return_value=False),
            patch(f"{_MODULE}.socket_listening", return_value=False),
            patch(f"{_MODULE}.time.sleep") as sleep,
        ):
            assert wait_for_socket(sock, wait_seconds=3) is False
        assert sleep.call_count == 3

    def test_eos_on_socket_loss_exits_so_partof_restart_reconnects(self, tmp_path: Path) -> None:
        # Compositor restart deletes the shmsink socket inode; shmsrc emits EOS.
        # The bridge must exit so systemd (PartOf) respawns it against the fresh
        # socket rather than wedging on the dead one.
        bridge = _bridge(tmp_path)
        bridge._pipeline = MagicMock()
        bridge._fd = 999
        with patch("os.close"):
            bridge._on_bus_eos(MagicMock(), MagicMock())
        assert bridge._failed is True
        assert bridge._stopping is True
        bridge._pipeline.set_state.assert_called_with(bridge._Gst.State.NULL)

    def test_partof_restart_and_socket_recreation_close_the_loop(self) -> None:
        # Declarative linchpin: PartOf makes the sidecar restart *with* the
        # compositor, and the compositor's ExecStartPre deletes the stale socket
        # so the sidecar reconnects to a genuinely new segment.
        unit = _load_unit(BRIDGE_UNIT)
        assert unit.get("Unit", "PartOf") == "studio-compositor.service"
        compositor = COMPOSITOR_UNIT.read_text(encoding="utf-8")
        # Both tokens must land on the *same* ExecStartPre entry -- the stale-
        # socket delete -- not merely co-occur somewhere in the unit file.
        cleanup_lines = [
            line for line in compositor.splitlines() if line.startswith("ExecStartPre=")
        ]
        assert any("v4l2-bridge.sock" in line and "-delete" in line for line in cleanup_lines)


class TestScenario3ModuleReload:
    """v4l2loopback unloaded and reloaded -> sidecar recovers gracefully."""

    def test_module_unload_errnos_are_classified_recoverable(self) -> None:
        # rmmod surfaces as ENODEV/ENXIO on write; these must be recoverable
        # (warn + reopen), not fatal. EAGAIN/EIO cover ring-buffer/IO stalls.
        assert errno.ENODEV in _RECOVERABLE_ERRNOS
        assert errno.ENXIO in _RECOVERABLE_ERRNOS
        assert errno.EIO in _RECOVERABLE_ERRNOS
        assert errno.EAGAIN in _RECOVERABLE_ERRNOS

    def test_write_during_unload_counts_error_without_raising(self, tmp_path: Path) -> None:
        bridge = _bridge(tmp_path)
        bridge._fd = 999
        payload = memoryview(bytearray(b"\x00" * 64))
        with patch("os.write", side_effect=OSError(errno.ENODEV, "No such device")):
            assert bridge._write_frame(payload) is False
        assert bridge.counters.errors == 1

    def test_on_sample_triggers_reopen_after_write_failure(self, tmp_path: Path) -> None:
        # The recovery cascade: a failed frame write drives a fd reopen, and the
        # mapped buffer is always released.
        bridge = _bridge(tmp_path)
        bridge._fd = 999
        appsink = _fake_sample(b"\x00" * 64)
        buf = appsink.emit.return_value.get_buffer.return_value
        map_info = buf.map.return_value[1]
        with (
            patch("os.write", side_effect=OSError(errno.ENODEV, "No such device")),
            patch.object(bridge, "_reopen_fd", return_value=True) as reopen,
        ):
            bridge._on_sample(appsink)
        reopen.assert_called_once()
        buf.unmap.assert_called_once_with(map_info)

    def test_reopen_recovers_when_device_returns_after_modprobe(self, tmp_path: Path) -> None:
        # While the module is gone os.open raises ENODEV; after modprobe the next
        # reopen succeeds and increments the reconnect counter.
        bridge = _bridge(tmp_path)
        bridge._fd = 999
        with (
            patch("os.close"),
            patch(f"{_MODULE}.time.sleep"),
            patch(f"{_MODULE}._enforce_v4l2_output_format", return_value=True),
            patch("os.open", side_effect=[OSError(errno.ENODEV, "gone"), 1234]),
        ):
            assert bridge._reopen_fd() is False
            assert bridge._reopen_fd() is True
        assert bridge.counters.reconnects == 1
        assert bridge._fd == 1234

    def test_open_fd_fails_gracefully_when_device_node_missing(self, tmp_path: Path) -> None:
        bridge = _bridge(tmp_path)
        with (
            patch(f"{_MODULE}._enforce_v4l2_output_format", return_value=True),
            patch("os.open", side_effect=FileNotFoundError(errno.ENOENT, "no node")),
        ):
            assert bridge._open_fd() is False
        assert bridge._fd == -1

    def test_open_fd_pins_format_before_opening_device(self, tmp_path: Path) -> None:
        # After a reload the format must be re-pinned before the device is opened;
        # if the guard fails the device is never opened.
        bridge = _bridge(tmp_path)
        with (
            patch(f"{_MODULE}._enforce_v4l2_output_format", return_value=False),
            patch("os.open") as os_open,
        ):
            assert bridge._open_fd() is False
        os_open.assert_not_called()

    def test_restart_storm_is_bounded_for_graceful_recovery(self) -> None:
        # Declarative linchpin: while the module is unloaded the sidecar cannot
        # open the device and exits repeatedly; StartLimit bounds that loop so the
        # recovery is graceful rather than a hot crash-spin.
        unit = _load_unit(BRIDGE_UNIT)
        assert unit.get("Unit", "StartLimitIntervalSec") == "300"
        assert unit.get("Unit", "StartLimitBurst") == "5"

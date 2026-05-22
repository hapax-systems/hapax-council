"""Tests for EvdevInputBackend — raw HID event monitoring."""

from __future__ import annotations

from unittest.mock import patch

from agents.hapax_daimonion.backends.evdev_input import EvdevInputBackend
from agents.hapax_daimonion.primitives import Behavior


class TestEvdevInputBackendProtocol:
    def test_name(self):
        with patch("agents.hapax_daimonion.backends.evdev_input.evdev") as mock_evdev:
            mock_evdev.list_devices.return_value = []
            backend = EvdevInputBackend()
            assert backend.name == "evdev_input"

    def test_provides(self):
        with patch("agents.hapax_daimonion.backends.evdev_input.evdev") as mock_evdev:
            mock_evdev.list_devices.return_value = []
            backend = EvdevInputBackend()
            assert "real_keyboard_active" in backend.provides
            assert "real_idle_seconds" in backend.provides

    def test_contribute_defaults_idle(self):
        import time

        with patch("agents.hapax_daimonion.backends.evdev_input.evdev") as mock_evdev:
            mock_evdev.list_devices.return_value = []
            backend = EvdevInputBackend()
            backend._start_ts = time.monotonic() - 15.0  # past warmup
            backend._events_received = 1  # pass disabled check
            behaviors: dict[str, Behavior] = {}
            backend.contribute(behaviors)
            assert behaviors["real_keyboard_active"].value is False
            assert behaviors["real_idle_seconds"].value > 0


class TestDeviceFiltering:
    def test_filters_virtual_devices(self):
        from agents.hapax_daimonion.backends.evdev_input import _is_physical_input

        assert _is_physical_input("Keychron  Keychron Link  Keyboard") is True
        assert _is_physical_input("Logitech USB Receiver Mouse") is True
        assert _is_physical_input("RustDesk UInput Keyboard") is False
        assert _is_physical_input("mouce-library-fake-mouse") is False
        assert _is_physical_input("ydotoold virtual device") is False


class TestIdleCalculation:
    def test_recent_event_is_active(self):
        import time

        from agents.hapax_daimonion.backends.evdev_input import _compute_idle

        now = time.monotonic()
        assert _compute_idle(now - 2.0, now) == (True, 2.0)

    def test_old_event_is_idle(self):
        import time

        from agents.hapax_daimonion.backends.evdev_input import _compute_idle

        now = time.monotonic()
        assert _compute_idle(now - 30.0, now) == (False, 30.0)

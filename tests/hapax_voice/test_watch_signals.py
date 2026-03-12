"""Tests for watch signal reading and stress detection."""
from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch

from agents.hapax_voice.presence import PresenceDetector
from agents.hapax_voice.watch_signals import (
    is_phone_connected,
    is_stress_elevated,
    is_watch_bt_nearby,
    is_watch_connected,
    read_watch_signal,
)


class TestReadWatchSignal:
    """Reading JSON files from hapax-state/watch/."""

    def test_reads_valid_file(self, tmp_path):
        """Returns parsed JSON for a valid, fresh file."""
        f = tmp_path / "heartrate.json"
        f.write_text(json.dumps({
            "current": {"bpm": 72},
            "updated_at": "2026-03-12T14:30:00-05:00",
            "window_1h": {"min": 58, "max": 95, "mean": 71, "readings": 120},
        }))
        result = read_watch_signal(f, max_age_seconds=300)
        assert result is not None
        assert result["current"]["bpm"] == 72

    def test_returns_none_for_missing_file(self, tmp_path):
        """Returns None when file does not exist."""
        result = read_watch_signal(tmp_path / "nonexistent.json", max_age_seconds=300)
        assert result is None

    def test_returns_none_for_stale_file(self, tmp_path):
        """Returns None when file is older than max_age_seconds."""
        f = tmp_path / "heartrate.json"
        f.write_text(json.dumps({"current": {"bpm": 72}}))
        old_time = time.time() - 600
        os.utime(f, (old_time, old_time))
        result = read_watch_signal(f, max_age_seconds=300)
        assert result is None


class TestStressDetection:
    """Composite stress signal from EDA + HRV."""

    def test_elevated_when_hrv_dropped(self, tmp_path):
        """Stress elevated when HRV dropped >30% from 1h mean."""
        hrv = tmp_path / "hrv.json"
        hrv.write_text(json.dumps({
            "current": {"rmssd_ms": 20},
            "window_1h": {"mean": 45},
            "updated_at": "2026-03-12T14:30:00-05:00",
        }))
        assert is_stress_elevated(watch_dir=tmp_path) is True

    def test_not_elevated_normal_hrv(self, tmp_path):
        """Stress not elevated with normal HRV."""
        hrv = tmp_path / "hrv.json"
        hrv.write_text(json.dumps({
            "current": {"rmssd_ms": 42},
            "window_1h": {"mean": 45},
            "updated_at": "2026-03-12T14:30:00-05:00",
        }))
        eda = tmp_path / "eda.json"
        eda.write_text(json.dumps({
            "current": {"eda_event": False},
            "updated_at": "2026-03-12T14:30:00-05:00",
        }))
        assert is_stress_elevated(watch_dir=tmp_path) is False

    def test_elevated_when_eda_spike(self, tmp_path):
        """Stress elevated on EDA spike event."""
        eda = tmp_path / "eda.json"
        eda.write_text(json.dumps({
            "current": {"eda_event": True, "duration_seconds": 180},
            "updated_at": "2026-03-12T14:30:00-05:00",
        }))
        hrv = tmp_path / "hrv.json"
        hrv.write_text(json.dumps({
            "current": {"rmssd_ms": 40},
            "window_1h": {"mean": 45},
            "updated_at": "2026-03-12T14:30:00-05:00",
        }))
        assert is_stress_elevated(watch_dir=tmp_path) is True

    def test_not_elevated_when_no_watch_data(self, tmp_path):
        """Returns False (graceful degradation) when no watch data."""
        assert is_stress_elevated(watch_dir=tmp_path) is False


class TestWatchPresence:
    """Haptic presence verification via watch."""

    def test_watch_connected_when_fresh_data(self, tmp_path):
        conn = tmp_path / "connection.json"
        conn.write_text(json.dumps({
            "last_seen_epoch": time.time(),
            "battery_pct": 85,
        }))
        assert is_watch_connected(watch_dir=tmp_path) is True

    def test_watch_disconnected_when_stale(self, tmp_path):
        conn = tmp_path / "connection.json"
        conn.write_text(json.dumps({
            "last_seen_epoch": time.time() - 600,
            "battery_pct": 85,
        }))
        old_time = time.time() - 600
        os.utime(conn, (old_time, old_time))
        assert is_watch_connected(watch_dir=tmp_path) is False

    def test_watch_disconnected_when_no_file(self, tmp_path):
        assert is_watch_connected(watch_dir=tmp_path) is False

    @patch("agents.hapax_voice.watch_signals.is_watch_bt_nearby", return_value=True)
    def test_watch_connected_via_bt_when_wifi_stale(self, mock_bt, tmp_path):
        """Falls back to BLE when WiFi connection.json is stale."""
        conn = tmp_path / "connection.json"
        conn.write_text(json.dumps({
            "last_seen_epoch": time.time() - 600,
            "battery_pct": 85,
        }))
        old_time = time.time() - 600
        os.utime(conn, (old_time, old_time))
        assert is_watch_connected(watch_dir=tmp_path) is True
        mock_bt.assert_called_once()

    @patch("agents.hapax_voice.watch_signals.is_watch_bt_nearby", return_value=False)
    def test_watch_disconnected_when_both_fail(self, mock_bt, tmp_path):
        """Disconnected when both WiFi and BLE fail."""
        assert is_watch_connected(watch_dir=tmp_path) is False

    @patch("agents.hapax_voice.watch_signals.is_watch_bt_nearby", return_value=None)
    def test_watch_disconnected_when_bt_unavailable(self, mock_bt, tmp_path):
        """Disconnected when WiFi stale and BT adapter unavailable."""
        assert is_watch_connected(watch_dir=tmp_path) is False


class TestPhoneConnected:
    """Phone connectivity check via phone_connection.json."""

    def test_connected_when_fresh(self, tmp_path):
        """Returns True when phone_connection.json is fresh."""
        conn = tmp_path / "phone_connection.json"
        conn.write_text(json.dumps({
            "last_seen_epoch": time.time(),
            "device_id": "pixel10",
            "battery_pct": 85,
        }))
        assert is_phone_connected(watch_dir=tmp_path) is True

    def test_disconnected_when_stale(self, tmp_path):
        """Returns False when phone_connection.json is stale (>120s)."""
        conn = tmp_path / "phone_connection.json"
        conn.write_text(json.dumps({
            "last_seen_epoch": time.time() - 300,
            "device_id": "pixel10",
            "battery_pct": 85,
        }))
        old_time = time.time() - 300
        os.utime(conn, (old_time, old_time))
        assert is_phone_connected(watch_dir=tmp_path) is False

    def test_disconnected_when_missing(self, tmp_path):
        """Returns False when no phone_connection.json exists."""
        assert is_phone_connected(watch_dir=tmp_path) is False


class TestBluetoothPresence:
    """BLE proximity detection via bluetoothctl."""

    @patch("subprocess.run")
    def test_bt_nearby_when_connected(self, mock_run, tmp_path):
        """Returns True when bluetoothctl shows Connected: yes."""
        conn = tmp_path / "connection.json"
        conn.write_text(json.dumps({"bt_mac": "AA:BB:CC:DD:EE:FF"}))
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Device AA:BB:CC:DD:EE:FF\n\tConnected: yes\n\tPaired: yes\n",
        )
        result = is_watch_bt_nearby(watch_dir=tmp_path)
        assert result is True

    @patch("subprocess.run")
    def test_bt_nearby_when_rssi_present(self, mock_run, tmp_path):
        """Returns True when device has RSSI (in range but not connected)."""
        conn = tmp_path / "connection.json"
        conn.write_text(json.dumps({"bt_mac": "AA:BB:CC:DD:EE:FF"}))
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Device AA:BB:CC:DD:EE:FF\n\tPaired: yes\n\tRSSI: -65\n",
        )
        result = is_watch_bt_nearby(watch_dir=tmp_path)
        assert result is True

    @patch("subprocess.run")
    def test_bt_not_nearby_when_no_rssi(self, mock_run, tmp_path):
        """Returns False when device paired but not in range."""
        conn = tmp_path / "connection.json"
        conn.write_text(json.dumps({"bt_mac": "AA:BB:CC:DD:EE:FF"}))
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Device AA:BB:CC:DD:EE:FF\n\tPaired: yes\n\tConnected: no\n",
        )
        result = is_watch_bt_nearby(watch_dir=tmp_path)
        assert result is False

    def test_bt_returns_none_when_no_mac(self, tmp_path):
        """Returns None when no BT MAC configured."""
        result = is_watch_bt_nearby(watch_dir=tmp_path)
        assert result is None

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_bt_returns_none_when_no_bluetoothctl(self, mock_run, tmp_path):
        """Returns None when bluetoothctl not installed."""
        conn = tmp_path / "connection.json"
        conn.write_text(json.dumps({"bt_mac": "AA:BB:CC:DD:EE:FF"}))
        result = is_watch_bt_nearby(watch_dir=tmp_path)
        assert result is None

    def test_bt_with_explicit_mac(self):
        """Accepts explicit MAC without needing connection.json."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="Connected: yes\n"
            )
            result = is_watch_bt_nearby(bt_mac="AA:BB:CC:DD:EE:FF")
            assert result is True

    @patch("agents.hapax_voice.presence.is_watch_connected", return_value=True)
    def test_watch_presence_confirmed_via_trigger_file(self, mock_conn, tmp_path):
        """Presence confirmed when trigger file appears after haptic tap."""
        detector = PresenceDetector()
        trigger = tmp_path / "voice_trigger.json"

        def write_trigger_on_tap(*args, **kwargs):
            """Simulate watch writing trigger file after receiving haptic."""
            trigger.write_text(json.dumps({"source": "watch", "ts": time.time()}))
            return True

        with patch("agents.hapax_voice.presence.send_haptic_tap", side_effect=write_trigger_on_tap) as mock_tap:
            with patch("agents.hapax_voice.presence.WATCH_STATE_DIR", tmp_path):
                result = detector.try_watch_presence_check(timeout=0.5, poll_interval=0.1)
        assert result is True
        mock_tap.assert_called_once()

    @patch("agents.hapax_voice.presence.send_haptic_tap", return_value=True)
    @patch("agents.hapax_voice.presence.is_watch_connected", return_value=True)
    def test_watch_presence_timeout_returns_none(self, mock_conn, mock_tap, tmp_path):
        """Returns None (fall through) when no trigger file appears."""
        detector = PresenceDetector()
        with patch("agents.hapax_voice.presence.WATCH_STATE_DIR", tmp_path):
            result = detector.try_watch_presence_check(timeout=0.5, poll_interval=0.1)
        assert result is None

    @patch("agents.hapax_voice.presence.is_watch_connected", return_value=False)
    def test_watch_presence_skips_when_disconnected(self, mock_conn):
        """Returns None immediately when watch not connected."""
        detector = PresenceDetector()
        result = detector.try_watch_presence_check()
        assert result is None

    @patch("agents.hapax_voice.presence.send_haptic_tap", return_value=False)
    @patch("agents.hapax_voice.presence.is_watch_connected", return_value=True)
    def test_watch_presence_falls_through_on_haptic_failure(self, mock_conn, mock_tap):
        """Returns None when haptic tap send fails."""
        detector = PresenceDetector()
        result = detector.try_watch_presence_check()
        assert result is None

    @patch("agents.hapax_voice.presence.send_haptic_tap", return_value=True)
    @patch("agents.hapax_voice.presence.is_watch_connected", return_value=True)
    def test_watch_presence_ignores_stale_trigger(self, mock_conn, mock_tap, tmp_path):
        """Ignores trigger file that predates the haptic tap."""
        detector = PresenceDetector()
        trigger = tmp_path / "voice_trigger.json"
        trigger.write_text(json.dumps({"source": "watch", "ts": time.time()}))
        # Set mtime to 10 seconds ago so it predates the haptic send
        old_time = time.time() - 10
        os.utime(trigger, (old_time, old_time))
        with patch("agents.hapax_voice.presence.WATCH_STATE_DIR", tmp_path):
            result = detector.try_watch_presence_check(timeout=0.5, poll_interval=0.1)
        assert result is None

    def test_watch_presence_returns_none_when_watch_module_unavailable(self):
        """Returns None when watch_signals module is not available."""
        detector = PresenceDetector()
        with patch("agents.hapax_voice.presence._WATCH_AVAILABLE", False):
            result = detector.try_watch_presence_check()
        assert result is None

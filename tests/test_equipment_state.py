"""Tests for scripts/equipment-state-writer — validates JSON output schema."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "equipment-state-writer"


def _load_module():
    """Import the equipment-state-writer script as a module."""
    loader = importlib.machinery.SourceFileLoader("equipment_state_writer", str(_SCRIPT))
    spec = importlib.util.spec_from_file_location("equipment_state_writer", _SCRIPT, loader=loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["equipment_state_writer"] = mod
    loader.exec_module(mod)
    return mod


esw = _load_module()


# ---------------------------------------------------------------------------
# Unit tests — probe parsers
# ---------------------------------------------------------------------------


class TestProbeUsb:
    def test_parses_lsusb_line(self) -> None:
        output = "Bus 009 Device 003: ID 1686:03d5 ZOOM Corporation LiveTrak L-12\n"
        with patch.object(esw, "_run", return_value=output):
            entries = esw.probe_usb()
        assert len(entries) == 1
        assert entries[0]["vid"] == "1686"
        assert entries[0]["pid"] == "03d5"

    def test_empty_on_failure(self) -> None:
        with patch.object(esw, "_run", return_value=""):
            assert esw.probe_usb() == []


class TestProbeAlsa:
    def test_parses_arecord_output(self) -> None:
        output = (
            "**** List of CAPTURE Hardware Devices ****\n"
            "card 1: L12 [L-12], device 0: USB Audio [USB Audio]\n"
            "  Subdevices: 0/1\n"
        )
        with patch.object(esw, "_run", return_value=output):
            cards = esw.probe_alsa()
        assert len(cards) == 1
        assert cards[0]["card_name"] == "L12"
        assert cards[0]["card_long"] == "L-12"

    def test_deduplicates_cards(self) -> None:
        output_rec = "card 1: L12 [L-12], device 0: USB Audio [USB Audio]\n"
        output_play = "card 1: L12 [L-12], device 0: USB Audio [USB Audio]\n"
        call_count = 0

        def fake_run(cmd: list[str]) -> str:
            nonlocal call_count
            call_count += 1
            return output_rec if call_count == 1 else output_play

        with patch.object(esw, "_run", side_effect=fake_run):
            cards = esw.probe_alsa()
        assert len(cards) == 1


class TestProbePipewire:
    def test_parses_pw_cli_output(self) -> None:
        output = (
            "\tid 55, type PipeWire:Interface:Node/3\n"
            ' \t\tnode.name = "hapax-livestream"\n'
            ' \t\tmedia.class = "Audio/Sink"\n'
            "\tid 71, type PipeWire:Interface:Node/3\n"
            ' \t\tnode.name = "contact_mic"\n'
            ' \t\tmedia.class = "Audio/Source"\n'
        )
        with patch.object(esw, "_run", return_value=output):
            nodes = esw.probe_pipewire()
        assert len(nodes) == 2
        assert nodes[0]["node_name"] == "hapax-livestream"
        assert nodes[0]["media_class"] == "Audio/Sink"


class TestProbeMidi:
    def test_parses_amidi_output(self) -> None:
        output = "Dir Device    Name\nIO  hw:8,0,0  MPC Live III MIDI 1\nIO  hw:12,0,0  M8 MIDI 1\n"
        with patch.object(esw, "_run", return_value=output):
            ports = esw.probe_midi()
        assert len(ports) == 2
        assert ports[0]["name"] == "MPC Live III MIDI 1"
        assert ports[1]["hw_id"] == "hw:12,0,0"


# ---------------------------------------------------------------------------
# Matching tests
# ---------------------------------------------------------------------------


_ZOOM_DEVICE: dict[str, Any] = {
    "device_id": "zoom-l12",
    "identity": {"manufacturer": "Zoom", "model": "LiveTrak L-12"},
    "specifications": {
        "usb": {"vid": "0x1686", "pid": None},
        "midi": {},
    },
}

_M8_DEVICE: dict[str, Any] = {
    "device_id": "m8-tracker",
    "identity": {"manufacturer": "Dirtywave", "model": "M8 Tracker Model:02"},
    "specifications": {
        "usb": {"vid": "0x16c0", "pid": "0x048a"},
        "midi": {"alsa_card_name_pattern": "M8"},
    },
}

_EVIL_PET: dict[str, Any] = {
    "device_id": "evil-pet",
    "identity": {"manufacturer": "Endorphin.es", "model": "Evil Pet"},
    "specifications": {
        "usb": {"class": "none"},
        "midi": {},
    },
}


class TestMatchUsb:
    def test_vid_match(self) -> None:
        entries = [{"vid": "1686", "pid": "03d5", "desc": "ZOOM Corporation LiveTrak L-12"}]
        assert esw.match_usb(_ZOOM_DEVICE, entries) is True

    def test_vid_pid_match(self) -> None:
        entries = [{"vid": "16c0", "pid": "048a", "desc": "Van Ooijen M8"}]
        assert esw.match_usb(_M8_DEVICE, entries) is True

    def test_no_usb_device(self) -> None:
        assert esw.match_usb(_EVIL_PET, []) is False


class TestMatchAlsa:
    def test_pattern_match(self) -> None:
        cards = [{"card_num": "12", "card_name": "M8", "card_long": "M8"}]
        result = esw.match_alsa(_M8_DEVICE, cards)
        assert result is not None
        assert "M8" in result

    def test_no_match(self) -> None:
        assert esw.match_alsa(_EVIL_PET, []) is None


class TestMatchPipewire:
    def test_node_name_match(self) -> None:
        nodes = [{"node_name": "hapax-l12-evilpet-capture", "media_class": "Stream/Input/Audio"}]
        result = esw.match_pipewire(_ZOOM_DEVICE, nodes)
        assert len(result) >= 1

    def test_no_match_for_unconnected(self) -> None:
        nodes = [{"node_name": "hapax-livestream", "media_class": "Audio/Sink"}]
        result = esw.match_pipewire(_EVIL_PET, nodes)
        assert result == []


class TestMatchMidi:
    def test_midi_match(self) -> None:
        ports = [{"hw_id": "hw:12,0,0", "name": "M8 MIDI 1"}]
        result = esw.match_midi(_M8_DEVICE, ports)
        assert len(result) == 1
        assert result[0] == "M8 MIDI 1"


# ---------------------------------------------------------------------------
# Integration — schema validation
# ---------------------------------------------------------------------------


class TestBuildState:
    """Validate the full output schema using mocked subsystem probes."""

    def _mock_state(self) -> dict[str, Any]:
        with (
            patch.object(
                esw,
                "probe_usb",
                return_value=[
                    {"vid": "1686", "pid": "03d5", "desc": "ZOOM Corporation LiveTrak L-12"},
                    {"vid": "16c0", "pid": "048a", "desc": "Van Ooijen M8"},
                ],
            ),
            patch.object(
                esw,
                "probe_alsa",
                return_value=[
                    {"card_num": "1", "card_name": "L12", "card_long": "L-12"},
                    {"card_num": "12", "card_name": "M8", "card_long": "M8"},
                ],
            ),
            patch.object(
                esw,
                "probe_pipewire",
                return_value=[
                    {"node_name": "hapax-l12-evilpet-capture", "media_class": "Stream/Input/Audio"},
                    {
                        "node_name": "alsa_output.usb-Dirtywave_M8_16558390-02.analog-stereo",
                        "node_description": "M8 Analog Stereo",
                        "media_class": "Audio/Sink",
                    },
                ],
            ),
            patch.object(
                esw,
                "probe_midi",
                return_value=[
                    {"hw_id": "hw:12,0,0", "name": "M8 MIDI 1"},
                ],
            ),
        ):
            return esw.build_state()

    def test_top_level_keys(self) -> None:
        state = self._mock_state()
        assert "generated_at" in state
        assert "devices" in state

    def test_generated_at_is_iso(self) -> None:
        state = self._mock_state()
        # Must parse as ISO datetime
        datetime.fromisoformat(state["generated_at"])

    def test_all_seed_devices_present(self) -> None:
        state = self._mock_state()
        expected = {
            "blue-yeti",
            "brio-operator",
            "digitakt-ii",
            "digitone-ii",
            "evil-pet",
            "m8-tracker",
            "mpc-live-iii",
            "sp404-mk2",
            "torso-s4",
            "zoom-l12",
        }
        assert expected == set(state["devices"].keys())

    def test_per_device_schema(self) -> None:
        state = self._mock_state()
        for did, ds in state["devices"].items():
            assert isinstance(ds["usb_connected"], bool), f"{did}: usb_connected not bool"
            assert ds["alsa_card"] is None or isinstance(ds["alsa_card"], str), (
                f"{did}: alsa_card not str|null"
            )
            assert isinstance(ds["pipewire_nodes"], list), f"{did}: pipewire_nodes not list"
            assert isinstance(ds["midi_ports"], list), f"{did}: midi_ports not list"
            assert ds["last_seen_at"] is None or isinstance(ds["last_seen_at"], str), (
                f"{did}: last_seen_at not str|null"
            )

    def test_connected_device_has_last_seen(self) -> None:
        state = self._mock_state()
        zoom = state["devices"]["zoom-l12"]
        assert zoom["usb_connected"] is True
        assert zoom["last_seen_at"] is not None

    def test_disconnected_device_has_no_last_seen(self) -> None:
        state = self._mock_state()
        evil = state["devices"]["evil-pet"]
        assert evil["usb_connected"] is False
        assert evil["last_seen_at"] is None

    def test_json_serializable(self) -> None:
        state = self._mock_state()
        serialized = json.dumps(state)
        roundtrip = json.loads(serialized)
        assert roundtrip == state


class TestWriteState:
    """Test actual file write to /dev/shm."""

    def test_writes_valid_json(self, tmp_path: Path) -> None:
        with (
            patch.object(esw, "_OUTPUT_DIR", tmp_path),
            patch.object(esw, "_OUTPUT_FILE", tmp_path / "state.json"),
            patch.object(
                esw,
                "probe_usb",
                return_value=[],
            ),
            patch.object(esw, "probe_alsa", return_value=[]),
            patch.object(esw, "probe_pipewire", return_value=[]),
            patch.object(esw, "probe_midi", return_value=[]),
        ):
            out = esw.write_state()
        assert out.exists()
        data = json.loads(out.read_text())
        assert "devices" in data
        assert len(data["devices"]) == 10

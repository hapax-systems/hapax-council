"""Tests for shared.s4_audio_witness — S-4 USB audio presence probing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from shared.s4_audio_witness import (
    is_s4_audio_present,
    probe_and_publish,
    update_fx_device_witness,
)


def test_is_s4_audio_present_when_device_listed(tmp_path: Path) -> None:
    fake_output = (
        "136\thapax-s4-content\tPipeWire\tfloat32le 2ch 48000Hz\tSUSPENDED\n"
        "200\talsa_output.usb-Torso_Electronics_S-4_1234-00.pro-audio\tPipeWire\ts32le 2ch 48000Hz\tIDLE\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = fake_output
        assert is_s4_audio_present() is True


def test_is_s4_audio_present_when_not_listed() -> None:
    fake_output = "136\thapax-s4-content\tPipeWire\tfloat32le 2ch 48000Hz\tSUSPENDED\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = fake_output
        assert is_s4_audio_present() is False


def test_is_s4_audio_present_when_pactl_fails() -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        assert is_s4_audio_present() is False


def test_update_fx_device_witness_creates_file(tmp_path: Path) -> None:
    witness_path = tmp_path / "fx-device-witness.json"
    with patch("shared.s4_audio_witness.FX_DEVICE_WITNESS_PATH", witness_path):
        update_fx_device_witness(s4_audio=True, s4_midi=True)
        data = json.loads(witness_path.read_text())
        assert data["s4_audio"] is True
        assert data["s4_midi"] is True
        assert "s4_audio:usb_enumerated" in data["evidence_refs"]


def test_update_fx_device_witness_merges_existing(tmp_path: Path) -> None:
    witness_path = tmp_path / "fx-device-witness.json"
    witness_path.write_text(
        json.dumps(
            {
                "evil_pet_midi": True,
                "evil_pet_sd_pack": True,
                "evil_pet_firmware_verified": True,
                "s4_audio": False,
                "s4_midi": False,
                "l12_route": True,
                "observed_at": "2026-05-16T00:00:00+00:00",
                "max_age_s": 300.0,
                "evidence_refs": ["evil_pet:verified"],
            }
        )
    )
    with patch("shared.s4_audio_witness.FX_DEVICE_WITNESS_PATH", witness_path):
        update_fx_device_witness(s4_audio=True)
        data = json.loads(witness_path.read_text())
        assert data["s4_audio"] is True
        assert data["evil_pet_midi"] is True
        assert data["l12_route"] is True


def test_probe_and_publish_integrates(tmp_path: Path) -> None:
    witness_path = tmp_path / "fx-device-witness.json"
    with (
        patch("shared.s4_audio_witness.FX_DEVICE_WITNESS_PATH", witness_path),
        patch("shared.s4_audio_witness.is_s4_audio_present", return_value=True),
        patch("shared.s4_midi.find_s4_midi_output", return_value=None),
    ):
        result = probe_and_publish()
        assert result is True
        data = json.loads(witness_path.read_text())
        assert data["s4_audio"] is True
        assert data["s4_midi"] is False

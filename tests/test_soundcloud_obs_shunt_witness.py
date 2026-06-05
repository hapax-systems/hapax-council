"""Tests for ``scripts/hapax-soundcloud-obs-shunt-witness``."""

from __future__ import annotations

import importlib.machinery
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture()
def witness_mod() -> types.ModuleType:
    script = (
        Path(__file__).resolve().parent.parent / "scripts" / "hapax-soundcloud-obs-shunt-witness"
    )
    loader = importlib.machinery.SourceFileLoader("soundcloud_obs_shunt_witness", str(script))
    mod = types.ModuleType("soundcloud_obs_shunt_witness")
    mod.__file__ = str(script)
    sys.modules["soundcloud_obs_shunt_witness"] = mod
    loader.exec_module(mod)
    return mod


def test_canonical_soundcloud_selection_requires_repo_match(witness_mod: types.ModuleType) -> None:
    selection = {
        "path": "https://soundcloud.com/oudepode/dump-disciple-8",
        "source": "soundcloud-oudepode",
    }

    assert (
        witness_mod._is_canonical_soundcloud_selection(
            selection,
            {"https://soundcloud.com/oudepode/dump-disciple-8"},
        )
        is True
    )
    assert witness_mod._is_canonical_soundcloud_selection(selection, set()) is False
    assert (
        witness_mod._is_canonical_soundcloud_selection(
            {**selection, "source": "local"},
            {"https://soundcloud.com/oudepode/dump-disciple-8"},
        )
        is False
    )


def test_canonical_soundcloud_selection_rejects_lookalike_urls(
    witness_mod: types.ModuleType,
    tmp_path: Path,
) -> None:
    canonical = {"https://soundcloud.com/oudepode/dump-disciple-8"}

    assert (
        witness_mod._is_canonical_soundcloud_selection(
            {
                "path": "https://example.com/soundcloud.com/oudepode/dump-disciple-8",
                "source": "soundcloud-oudepode",
            },
            canonical,
        )
        is False
    )
    assert (
        witness_mod._is_canonical_soundcloud_selection(
            {
                "path": "https://soundcloud.com.example/oudepode/dump-disciple-8",
                "source": "soundcloud-oudepode",
            },
            canonical,
        )
        is False
    )

    repo_path = tmp_path / "soundcloud.jsonl"
    repo_path.write_text(
        "\n".join(
            [
                json.dumps({"path": "https://example.com/soundcloud.com/oudepode/not-real"}),
                json.dumps({"path": "https://soundcloud.com.example/oudepode/not-real"}),
                json.dumps({"path": "https://www.soundcloud.com/oudepode/dump-disciple-8/"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert witness_mod._canonical_soundcloud_urls(repo_path) == {
        "https://soundcloud.com/oudepode/dump-disciple-8"
    }


def test_obs_links_complete_requires_pipewire_obs_input(witness_mod: types.ModuleType) -> None:
    graph = """
hapax-obs-broadcast-remap:capture_FL
  |-> OBS: Audio Input Capture (PipeWire):input_FL
hapax-obs-broadcast-remap:capture_FR
  |-> OBS: Audio Input Capture (PipeWire):input_FR
"""

    assert witness_mod._obs_links_complete(graph) is True
    assert witness_mod._obs_links_complete(graph.replace("(PipeWire)", "(PulseAudio)")) is False


def test_obs_consumer_present_accepts_remap_numeric_target(
    witness_mod: types.ModuleType,
) -> None:
    pw_dump = json.dumps(
        [
            {
                "id": 124,
                "info": {
                    "props": {
                        "node.name": "hapax-obs-broadcast-remap",
                        "object.serial": "124",
                    }
                },
            },
            {
                "id": 721,
                "info": {
                    "props": {
                        "node.name": "OBS: Audio Input Capture (PipeWire)",
                        "target.object": 124,
                    }
                },
            },
        ]
    )

    assert witness_mod._obs_consumer_present(pw_dump) is True


def test_build_status_accepts_canonical_soundcloud_obs_shunt(
    witness_mod: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection_path = tmp_path / "music-selection.json"
    sc_repo_path = tmp_path / "soundcloud.jsonl"
    status_path = tmp_path / "status.json"
    url = "https://soundcloud.com/oudepode/dump-disciple-8"
    selection_path.write_text(
        json.dumps(
            {
                "path": url,
                "title": "dump disciple",
                "source": "soundcloud-oudepode",
            }
        ),
        encoding="utf-8",
    )
    sc_repo_path.write_text(json.dumps({"path": url}) + "\n", encoding="utf-8")

    pw_link = """
pw-cat:output_FL
  |-> hapax-music-loudnorm:playback_FL
pw-cat:output_FR
  |-> hapax-music-loudnorm:playback_FR
hapax-music-loudnorm-playback:output_FL
  |-> hapax-livestream-tap:playback_FL
hapax-music-loudnorm-playback:output_FR
  |-> hapax-livestream-tap:playback_FR
hapax-livestream-tap:monitor_FL
  |-> hapax-broadcast-master-capture:input_FL
hapax-livestream-tap:monitor_FR
  |-> hapax-broadcast-master-capture:input_FR
hapax-broadcast-master:capture_FL
  |-> hapax-broadcast-normalized-capture:input_FL
hapax-broadcast-master:capture_FR
  |-> hapax-broadcast-normalized-capture:input_FR
hapax-broadcast-normalized:capture_FL
  |-> hapax-obs-broadcast-remap-capture:input_FL
hapax-broadcast-normalized:capture_FR
  |-> hapax-obs-broadcast-remap-capture:input_FR
hapax-obs-broadcast-remap:capture_FL
  |-> OBS: Audio Input Capture (PipeWire):input_FL
hapax-obs-broadcast-remap:capture_FR
  |-> OBS: Audio Input Capture (PipeWire):input_FR
"""
    pw_dump = json.dumps(
        [
            {
                "info": {
                    "props": {
                        "node.name": "OBS: Audio Input Capture (PipeWire)",
                        "target.object": "hapax-obs-broadcast-remap",
                    }
                }
            }
        ]
    )

    def fake_run_text(args: list[str], **_: object) -> str:
        if args == ["pactl", "get-sink-volume", "hapax-music-loudnorm"]:
            return (
                "Volume: front-left: 65536 / 100% / 0.00 dB, front-right: 65536 / 100% / 0.00 dB\n"
            )
        if args == ["pactl", "get-sink-mute", "hapax-music-loudnorm"]:
            return "Mute: no\n"
        if args[:3] == ["ps", "-eo", "args="]:
            return "pw-cat --playback --target hapax-music-loudnorm --format s16\n"
        if args == ["pw-link", "-l"]:
            return pw_link
        if args == ["pw-dump"]:
            return pw_dump
        raise AssertionError(args)

    monkeypatch.setattr(witness_mod, "_run_binder", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(witness_mod, "_systemd_unit_active", lambda _unit: True)
    monkeypatch.setattr(witness_mod, "_run_text", fake_run_text)
    monkeypatch.setattr(
        witness_mod,
        "capture_and_measure",
        lambda *_args, **_kwargs: SimpleNamespace(
            error=None,
            measurement=SimpleNamespace(rms_dbfs=-18.0, peak_dbfs=-3.0),
        ),
    )

    args = SimpleNamespace(
        selection_path=selection_path,
        sc_repo_path=sc_repo_path,
        status_path=status_path,
        repair=True,
        bind_wait_links_s=0.1,
        probe_duration_s=0.1,
        min_obs_rms_dbfs=-55.0,
    )
    status = witness_mod._build_status(args)

    assert status.ok is True
    assert status.state == "ready"
    assert status.canonical_match is True
    assert status.playback_sink == "hapax-music-loudnorm"
    assert status.music_sink_volume_ok is True
    assert status.music_sink_volume_repaired is False
    assert status.obs_links_complete is True
    assert status.obs_consumer_present is True
    assert status.obs_rms_dbfs == -18.0


def test_build_status_repairs_zero_music_sink_volume(
    witness_mod: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection_path = tmp_path / "music-selection.json"
    sc_repo_path = tmp_path / "soundcloud.jsonl"
    status_path = tmp_path / "status.json"
    url = "https://soundcloud.com/oudepode/visage-best-10"
    selection_path.write_text(
        json.dumps(
            {
                "path": url,
                "title": "visage best",
                "source": "soundcloud-oudepode",
            }
        ),
        encoding="utf-8",
    )
    sc_repo_path.write_text(json.dumps({"path": url}) + "\n", encoding="utf-8")

    volume_gets = 0
    repair_commands: list[list[str]] = []

    def fake_run_text(args: list[str], **_: object) -> str:
        nonlocal volume_gets
        if args == ["pactl", "get-sink-volume", "hapax-music-loudnorm"]:
            volume_gets += 1
            if volume_gets == 1:
                return "Volume: front-left: 0 / 0% / -inf dB, front-right: 0 / 0% / -inf dB\n"
            return (
                "Volume: front-left: 65536 / 100% / 0.00 dB, front-right: 65536 / 100% / 0.00 dB\n"
            )
        if args == ["pactl", "get-sink-mute", "hapax-music-loudnorm"]:
            return "Mute: no\n"
        if args[:3] == ["ps", "-eo", "args="]:
            return "pw-cat --playback --target hapax-music-loudnorm --format s16\n"
        if args == ["pw-link", "-l"]:
            return """
pw-cat:output_FL
  |-> hapax-music-loudnorm:playback_FL
pw-cat:output_FR
  |-> hapax-music-loudnorm:playback_FR
hapax-music-loudnorm-playback:output_FL
  |-> hapax-livestream-tap:playback_FL
hapax-music-loudnorm-playback:output_FR
  |-> hapax-livestream-tap:playback_FR
hapax-livestream-tap:monitor_FL
  |-> hapax-broadcast-master-capture:input_FL
hapax-livestream-tap:monitor_FR
  |-> hapax-broadcast-master-capture:input_FR
hapax-broadcast-master:capture_FL
  |-> hapax-broadcast-normalized-capture:input_FL
hapax-broadcast-master:capture_FR
  |-> hapax-broadcast-normalized-capture:input_FR
hapax-broadcast-normalized:capture_FL
  |-> hapax-obs-broadcast-remap-capture:input_FL
hapax-broadcast-normalized:capture_FR
  |-> hapax-obs-broadcast-remap-capture:input_FR
hapax-obs-broadcast-remap:capture_FL
  |-> OBS: Audio Input Capture (PipeWire):input_FL
hapax-obs-broadcast-remap:capture_FR
  |-> OBS: Audio Input Capture (PipeWire):input_FR
"""
        if args == ["pw-dump"]:
            return json.dumps(
                [
                    {
                        "info": {
                            "props": {
                                "node.name": "OBS: Audio Input Capture (PipeWire)",
                                "target.object": "hapax-obs-broadcast-remap",
                            }
                        }
                    }
                ]
            )
        raise AssertionError(args)

    def fake_run_command_ok(args: list[str], **_: object) -> bool:
        repair_commands.append(args)
        return True

    monkeypatch.setattr(witness_mod, "_run_binder", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(witness_mod, "_systemd_unit_active", lambda _unit: True)
    monkeypatch.setattr(witness_mod, "_run_text", fake_run_text)
    monkeypatch.setattr(witness_mod, "_run_command_ok", fake_run_command_ok)
    monkeypatch.setattr(
        witness_mod,
        "capture_and_measure",
        lambda *_args, **_kwargs: SimpleNamespace(
            error=None,
            measurement=SimpleNamespace(rms_dbfs=-22.0, peak_dbfs=-6.0),
        ),
    )

    args = SimpleNamespace(
        selection_path=selection_path,
        sc_repo_path=sc_repo_path,
        status_path=status_path,
        repair=True,
        bind_wait_links_s=0.1,
        probe_duration_s=0.1,
        min_obs_rms_dbfs=-55.0,
    )
    status = witness_mod._build_status(args)

    assert status.ok is True
    assert status.music_sink_volume_ok is True
    assert status.music_sink_volume_repaired is True
    assert ["pactl", "set-sink-volume", "hapax-music-loudnorm", "100%"] in repair_commands

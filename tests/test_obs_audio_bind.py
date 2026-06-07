"""Tests for ``scripts/hapax-obs-audio-bind``."""

from __future__ import annotations

import importlib.machinery
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def bind_mod() -> types.ModuleType:
    script = Path(__file__).resolve().parent.parent / "scripts" / "hapax-obs-audio-bind"
    loader = importlib.machinery.SourceFileLoader("obs_audio_bind", str(script))
    mod = types.ModuleType("obs_audio_bind")
    mod.__file__ = str(script)
    sys.modules["obs_audio_bind"] = mod
    loader.exec_module(mod)
    return mod


def test_find_remap_ids_use_stable_node_name_and_serial(bind_mod: types.ModuleType) -> None:
    pw_dump = json.dumps(
        [
            {"id": 7, "info": {"props": {"node.name": "other"}}},
            {
                "id": 120,
                "info": {
                    "props": {
                        "node.name": "hapax-obs-broadcast-remap",
                        "object.serial": "121",
                    }
                },
            },
        ]
    )

    assert bind_mod._find_remap_node_id(pw_dump) == 120
    assert bind_mod._find_remap_target_id(pw_dump) == 121


def test_obs_links_complete_accepts_named_pipewire_obs_ports(bind_mod: types.ModuleType) -> None:
    graph = """
hapax-obs-broadcast-remap:capture_FL
  |-> OBS: Audio Input Capture (PipeWire):input_FL
hapax-obs-broadcast-remap:capture_FR
  |-> OBS: Audio Input Capture (PipeWire):input_FR
"""

    assert bind_mod._obs_links_complete(graph) is True
    assert bind_mod._obs_pipewire_links_safe(graph) is True


def test_obs_links_complete_rejects_legacy_pulse_obs_ports(bind_mod: types.ModuleType) -> None:
    graph = """
hapax-obs-broadcast-remap:capture_FL
  |-> OBS:input_FL
hapax-obs-broadcast-remap:capture_FR
  |-> OBS:input_FR
"""

    assert bind_mod._obs_links_complete(graph) is False


def test_obs_pipewire_links_safe_rejects_direct_l12_capture(bind_mod: types.ModuleType) -> None:
    graph = """
hapax-obs-broadcast-remap:capture_FL
  |-> OBS: Audio Input Capture (PipeWire):input_FL
hapax-obs-broadcast-remap:capture_FR
  |-> OBS: Audio Input Capture (PipeWire):input_FR
alsa_input.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.pro-input-0:capture_AUX0
  |-> OBS: Audio Input Capture (PipeWire):input_FL
"""

    assert bind_mod._obs_links_complete(graph) is True
    assert bind_mod._obs_pipewire_links_safe(graph) is False


def test_obs_links_complete_requires_both_channels(bind_mod: types.ModuleType) -> None:
    graph = """
hapax-obs-broadcast-remap:capture_FL
  |-> OBS: Audio Input Capture (PipeWire):input_FL
hapax-obs-broadcast-remap:capture_FR
"""

    assert bind_mod._obs_links_complete(graph) is False


def test_bind_retargets_pipewire_input_and_disables_legacy_pulse(
    bind_mod: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.get_current_program_scene.return_value = SimpleNamespace(scene_name="Scene")
    client.get_input_list.return_value = SimpleNamespace(
        inputs=[
            {"inputName": "Audio Input Capture (PipeWire)"},
            {"inputName": "Audio Input Capture (PulseAudio)"},
        ]
    )
    client.get_scene_item_list.return_value = SimpleNamespace(
        scene_items=[
            {"sourceName": "Audio Input Capture (PulseAudio)", "sceneItemId": 369},
            {"sourceName": "Audio Input Capture (PipeWire)", "sceneItemId": 375},
        ]
    )
    client.get_input_settings.return_value = SimpleNamespace(
        input_settings={"TargetId": 121, "TargetName": "hapax-obs-broadcast-remap"}
    )
    monkeypatch.setattr(bind_mod, "_current_remap_ids", lambda: (120, 121))
    monkeypatch.setattr(bind_mod, "_connect", lambda _host, _port: client)
    monkeypatch.setattr(bind_mod, "_wait_for_obs_links", lambda _timeout: True)

    args = SimpleNamespace(
        host="localhost",
        port=4455,
        scene=None,
        input_name="Audio Input Capture (PipeWire)",
        legacy_pulse_name="Audio Input Capture (PulseAudio)",
        wait_links_s=0.0,
        require_obs=True,
        recreate_input_on_missing_links=True,
    )
    status = bind_mod._bind_obs_audio(args)

    assert status.ok is True
    assert status.state == "bound"
    assert status.recreated_input is False
    client.set_input_settings.assert_called_once()
    assert client.set_input_settings.call_args.kwargs["input_settings"] == {
        "TargetName": "hapax-obs-broadcast-remap",
        "TargetId": 121,
    }
    client.set_input_mute.assert_any_call(
        input_name="Audio Input Capture (PipeWire)", input_muted=False
    )
    client.set_input_mute.assert_any_call(
        input_name="Audio Input Capture (PulseAudio)", input_muted=True
    )
    client.set_scene_item_enabled.assert_any_call(
        scene_name="Scene", scene_item_id=375, scene_item_enabled=True
    )
    client.set_scene_item_enabled.assert_any_call(
        scene_name="Scene", scene_item_id=369, scene_item_enabled=False
    )


def test_bind_recreates_pipewire_input_when_retarget_links_stay_missing(
    bind_mod: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.get_current_program_scene.return_value = SimpleNamespace(scene_name="Scene")
    client.get_input_list.return_value = SimpleNamespace(
        inputs=[{"inputName": "Audio Input Capture (PipeWire)"}]
    )
    client.get_scene_item_list.side_effect = [
        SimpleNamespace(
            scene_items=[
                {
                    "sourceName": "Audio Input Capture (PipeWire)",
                    "sceneItemId": 375,
                    "sceneItemIndex": 1,
                }
            ]
        ),
        SimpleNamespace(
            scene_items=[
                {
                    "sourceName": "Audio Input Capture (PipeWire)",
                    "sceneItemId": 375,
                    "sceneItemIndex": 1,
                }
            ]
        ),
        SimpleNamespace(
            scene_items=[
                {
                    "sourceName": "Audio Input Capture (PipeWire)",
                    "sceneItemId": 375,
                    "sceneItemIndex": 1,
                }
            ]
        ),
        SimpleNamespace(
            scene_items=[
                {
                    "sourceName": "Audio Input Capture (PipeWire)",
                    "sceneItemId": 376,
                    "sceneItemIndex": 3,
                }
            ]
        ),
    ]
    client.get_input_settings.return_value = SimpleNamespace(
        input_settings={"TargetId": 121, "TargetName": "hapax-obs-broadcast-remap"}
    )
    waits = iter([False, True])
    monkeypatch.setattr(bind_mod, "_current_remap_ids", lambda: (120, 121))
    monkeypatch.setattr(bind_mod, "_connect", lambda _host, _port: client)
    monkeypatch.setattr(bind_mod, "_wait_for_obs_links", lambda _timeout: next(waits))

    args = SimpleNamespace(
        host="localhost",
        port=4455,
        scene=None,
        input_name="Audio Input Capture (PipeWire)",
        legacy_pulse_name="Audio Input Capture (PulseAudio)",
        wait_links_s=0.0,
        require_obs=True,
        recreate_input_on_missing_links=True,
    )
    status = bind_mod._bind_obs_audio(args)

    assert status.ok is True
    assert status.state == "bound"
    assert status.recreated_input is True
    client.remove_input.assert_called_once_with(input_name="Audio Input Capture (PipeWire)")
    client.create_input.assert_called_once()
    client.set_scene_item_index.assert_called_once_with(
        scene_name="Scene", scene_item_id=376, scene_item_index=1
    )

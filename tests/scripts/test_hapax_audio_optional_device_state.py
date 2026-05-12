"""Contract tests for optional audio device state witness."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-audio-optional-device-state"
POLICY = REPO_ROOT / "config" / "hapax" / "audio-optional-devices.yaml"


def _load_script() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_audio_optional_device_state", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise AssertionError("could not load optional-device state script")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _node(name: str) -> dict[str, object]:
    return {
        "type": "PipeWire:Interface:Node",
        "info": {"props": {"node.name": name}},
    }


def test_policy_declares_known_storm_candidates_fail_closed() -> None:
    text = POLICY.read_text(encoding="utf-8")
    for node_name in (
        "hapax-m8-instrument-capture",
        "hapax-private-playback",
        "hapax-notification-private-playback",
    ):
        assert f"node_name: {node_name}" in text
    assert text.count("fail_closed_when_absent: true") == 3
    assert text.count("autoconnect: false") == 3


def test_absent_optional_targets_emit_absent_state() -> None:
    script = _load_script()
    policy = script._load_policy(POLICY)
    state = script.build_state(
        policy,
        [
            _node("hapax-m8-instrument-capture"),
            _node("hapax-private-playback"),
            _node("hapax-notification-private-playback"),
        ],
    )

    states = {branch["node_name"]: branch["state"] for branch in state["branches"]}
    assert states == {
        "hapax-m8-instrument-capture": "absent",
        "hapax-private-playback": "absent",
        "hapax-notification-private-playback": "absent",
    }
    assert state["summary"]["absent"] == 3


def test_present_optional_target_emits_present_state(tmp_path: Path) -> None:
    script = _load_script()
    policy = script._load_policy(POLICY)
    dump = [
        _node("hapax-m8-instrument-capture"),
        _node("alsa_input.usb-Dirtywave_M8_16558390-02.analog-stereo"),
    ]
    output = tmp_path / "optional-devices.json"
    state = script.build_state(policy, dump)
    output.write_text(json.dumps(state), encoding="utf-8")

    branches = {branch["node_name"]: branch for branch in state["branches"]}
    assert branches["hapax-m8-instrument-capture"]["state"] == "present"
    assert branches["hapax-private-playback"]["state"] == "inactive"

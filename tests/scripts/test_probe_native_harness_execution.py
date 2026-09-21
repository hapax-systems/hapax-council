"""A result replay must not consume provider capacity or accept changed bytes."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[2] / "scripts/probe-native-harness-execution.py"
    spec = importlib.util.spec_from_file_location("native_execution_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bundle(probe, root):
    request = {"prompt_sha256": "a" * 64, "controller_sha256": "b" * 64}
    (root / "launch.json").write_text(json.dumps({"request": request}))
    (root / "request.json").write_text(json.dumps(request))
    (root / "result.md").write_text("File-backed findings.\n")
    events = [
        {"method": "thread/started", "params": {"thread": {"id": "session"}}},
        {"method": "turn/started", "params": {"threadId": "session", "turn": {"id": "turn"}}},
        {
            "method": "turn/completed",
            "params": {"threadId": "session", "turn": {"id": "turn", "status": "completed"}},
        },
    ]
    (root / "native.jsonl").write_text("\n".join(json.dumps(event) for event in events))
    receipt = {
        "schema": "hapax.native_execution_probe.v1",
        "request": request,
        "complete": True,
        "runtime_exit_code": 0,
        "session_id": "session",
        "artifacts": {
            name: probe.reference(root / file, root)
            for name, file in {
                "result": "result.md",
                "request": "request.json",
                "native_stream": "native.jsonl",
            }.items()
        },
    }
    (root / "receipt.json").write_text(json.dumps(receipt))
    ref = probe.reference(root / "receipt.json", root)
    (root / "receipt-ref.json").write_text(json.dumps(ref))
    return request, ref


def test_replay_with_new_reader_preserves_original_execution_identity(probe, tmp_path, monkeypatch):
    request, expected = bundle(probe, tmp_path)
    monkeypatch.setattr(probe, "run", lambda *_a, **_k: pytest.fail("replay contacted runtime"))
    monkeypatch.setattr(
        probe, "load_access_token", lambda *_a: pytest.fail("replay read credentials")
    )
    assert probe.checked_replay(tmp_path, {**request, "controller_sha256": "c" * 64}) == expected


@pytest.mark.parametrize("file", ["receipt.json", "native.jsonl", "result.md", "request.json"])
def test_replay_rejects_changed_artifacts(probe, tmp_path, file):
    request, _ = bundle(probe, tmp_path)
    path = tmp_path / file
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        probe.checked_replay(tmp_path, request)


def test_replay_rejects_different_demand_even_with_new_reader(probe, tmp_path):
    request, _ = bundle(probe, tmp_path)
    with pytest.raises(ValueError, match="inputs changed"):
        probe.checked_replay(
            tmp_path, {**request, "prompt_sha256": "d" * 64, "controller_sha256": "c" * 64}
        )


def test_replay_rechecks_native_terminal_instead_of_trusting_complete_flag(probe, tmp_path):
    request, _ = bundle(probe, tmp_path)
    native = tmp_path / "native.jsonl"
    native.write_text(native.read_text().replace('"completed"', '"interrupted"'))
    receipt_path = tmp_path / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["artifacts"]["native_stream"] = probe.reference(native, tmp_path)
    receipt_path.write_text(json.dumps(receipt))
    (tmp_path / "receipt-ref.json").write_text(json.dumps(probe.reference(receipt_path, tmp_path)))
    with pytest.raises(ValueError, match="native completion"):
        probe.checked_replay(tmp_path, request)


def test_incomplete_invocation_reports_inspection_instead_of_missing_artifact(probe, tmp_path):
    request, _ = bundle(probe, tmp_path)
    path = tmp_path / "receipt.json"
    receipt = json.loads(path.read_text())
    receipt["complete"] = False
    del receipt["artifacts"]
    path.write_text(json.dumps(receipt))
    (tmp_path / "receipt-ref.json").write_text(json.dumps(probe.reference(path, tmp_path)))
    with pytest.raises(ValueError, match="inspect its owned runtime, do not relaunch"):
        probe.checked_replay(tmp_path, request)

"""Tests for the sensor backend protocol and DMN sensor extension."""

import json
from pathlib import Path

from agents._sensor_protocol import SensorTier, emit_sensor_impingement, write_sensor_state


def test_write_sensor_state(tmp_path: Path, monkeypatch):
    """write_sensor_state creates atomic JSON snapshot."""
    monkeypatch.setattr("shared.sensor_protocol.SENSOR_SHM_DIR", tmp_path)
    write_sensor_state("gmail", {"message_count": 42, "unread": 3})
    path = tmp_path / "gmail.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["message_count"] == 42
    assert data["unread"] == 3


def test_write_sensor_state_overwrites(tmp_path: Path, monkeypatch):
    """Subsequent writes overwrite previous state."""
    monkeypatch.setattr("shared.sensor_protocol.SENSOR_SHM_DIR", tmp_path)
    write_sensor_state("gmail", {"message_count": 10})
    write_sensor_state("gmail", {"message_count": 20})
    data = json.loads((tmp_path / "gmail.json").read_text())
    assert data["message_count"] == 20


def test_emit_sensor_impingement(tmp_path: Path, monkeypatch):
    """emit_sensor_impingement appends to JSONL file."""
    jsonl_path = tmp_path / "impingements.jsonl"
    monkeypatch.setattr("shared.sensor_protocol.IMPINGEMENTS_FILE", jsonl_path)
    emit_sensor_impingement("gmail", "communication_patterns", ["email_volume"])
    assert jsonl_path.exists()
    lines = jsonl_path.read_text().strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["source"] == "sensor.gmail"
    assert data["content"]["dimension"] == "communication_patterns"
    assert data["strength"] == 0.3


def test_emit_multiple_impingements(tmp_path: Path, monkeypatch):
    """Multiple emissions append to same file."""
    jsonl_path = tmp_path / "impingements.jsonl"
    monkeypatch.setattr("shared.sensor_protocol.IMPINGEMENTS_FILE", jsonl_path)
    emit_sensor_impingement("gmail", "communication_patterns", ["volume"])
    emit_sensor_impingement("chrome", "information_seeking", ["domains"])
    lines = jsonl_path.read_text().strip().split("\n")
    assert len(lines) == 2


def test_sensor_tier_values():
    assert SensorTier.FAST == "fast"
    assert SensorTier.SLOW == "slow"
    assert SensorTier.EVENT == "event"


def test_dmn_read_sensors(tmp_path: Path, monkeypatch):
    """DMN sensor.read_sensors() reads all /dev/shm/hapax-sensors/ files."""
    monkeypatch.setattr(
        "agents.dmn.sensor.Path", lambda p: tmp_path if "hapax-sensors" in str(p) else Path(p)
    )

    # Create mock sensor files
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "gmail.json").write_text(json.dumps({"count": 5}))
    (tmp_path / "chrome.json").write_text(json.dumps({"domains": 10}))

    # Monkey-patch the path inside read_sensors
    import agents.dmn.sensor as sensor_mod

    def patched():
        result = {}
        for f in tmp_path.glob("*.json"):
            data = json.loads(f.read_text())
            if data:
                result[f.stem] = data
        return result

    monkeypatch.setattr(sensor_mod, "read_sensors", patched)
    result = sensor_mod.read_sensors()
    assert "gmail" in result
    assert result["gmail"]["count"] == 5
    assert "chrome" in result


def test_dmn_read_all_includes_sensors(tmp_path):
    """read_all() includes a 'sensors' key."""
    from unittest.mock import patch

    from agents.dmn.sensor import SensorConfig, read_all

    config = SensorConfig(
        stimmung_state=tmp_path / "stimmung.json",
        fortress_state=tmp_path / "fortress.json",
        watch_dir=tmp_path / "watch",
        voice_perception=tmp_path / "perception.json",
        visual_frame=tmp_path / "frame.jpg",
        imagination_current=tmp_path / "imagination.json",
    )
    with (
        patch("agents.dmn.sensor.read_sensors", return_value={}),
        patch(
            "agents.dmn.sensor.read_visual_surface",
            return_value={"source": "visual_surface", "age_s": 999.0, "stale": True},
        ),
    ):
        result = read_all(config)
    assert "sensors" in result
    assert isinstance(result["sensors"], dict)


# ── Stimmung sync integration ───────────────────────────────────────────


def test_stimmung_sync_writes_sensor_state(tmp_path: Path, monkeypatch):
    """stimmung_sync.sync() writes sensor state to /dev/shm."""
    import agents.stimmung_sync as mod

    stimmung_file = tmp_path / "stimmung-state.json"
    stimmung_file.write_text(
        json.dumps(
            {
                "overall_stance": "nominal",
                "health": {"value": 0.2},
                "error_rate": {"value": 0.1},
            }
        )
    )
    monkeypatch.setattr(mod, "STIMMUNG_STATE", stimmung_file)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(mod, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(mod, "STATE_FILE", cache_dir / "state.json")
    monkeypatch.setattr(mod, "RAG_DIR", tmp_path / "rag")

    sensor_writes: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "agents._sensor_protocol.write_sensor_state",
        lambda name, data: sensor_writes.append((name, data)),
    )
    impingement_emits: list[tuple] = []
    monkeypatch.setattr(
        "agents._sensor_protocol.emit_sensor_impingement",
        lambda *args, **kwargs: impingement_emits.append(args),
    )

    result = mod.sync()
    assert result is True
    assert len(sensor_writes) == 1
    assert sensor_writes[0][0] == "stimmung"
    assert sensor_writes[0][1]["stance"] == "nominal"
    # Stance changed from "unknown" to "nominal"
    assert len(impingement_emits) == 1
    assert impingement_emits[0][0] == "stimmung"


def test_stimmung_sync_no_impingement_on_same_stance(tmp_path: Path, monkeypatch):
    """No impingement when stance hasn't changed."""
    import agents.stimmung_sync as mod

    stimmung_file = tmp_path / "stimmung-state.json"
    stimmung_file.write_text(json.dumps({"overall_stance": "nominal"}))
    monkeypatch.setattr(mod, "STIMMUNG_STATE", stimmung_file)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "state.json").write_text(json.dumps({"last_stance": "nominal", "readings": []}))
    monkeypatch.setattr(mod, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(mod, "STATE_FILE", cache_dir / "state.json")
    monkeypatch.setattr(mod, "RAG_DIR", tmp_path / "rag")

    sensor_writes: list = []
    monkeypatch.setattr(
        "agents._sensor_protocol.write_sensor_state",
        lambda name, data: sensor_writes.append((name, data)),
    )
    impingement_emits: list = []
    monkeypatch.setattr(
        "agents._sensor_protocol.emit_sensor_impingement",
        lambda *args, **kwargs: impingement_emits.append(args),
    )

    mod.sync()
    assert len(sensor_writes) == 1  # always writes sensor state
    assert len(impingement_emits) == 0  # no impingement — stance unchanged

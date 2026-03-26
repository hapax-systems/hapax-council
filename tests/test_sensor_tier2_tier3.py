"""Tests for sensor protocol integration in Tier 2 + Tier 3 sync agents.

Verifies that write_sensor_state and emit_sensor_impingement are called
by each agent after successful sync operations.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Tier 2: gmail_sync ──────────────────────────────────────────────────────


def test_gmail_full_sync_writes_sensor_state(tmp_path: Path, monkeypatch):
    """gmail run_full_sync writes sensor state and emits impingement."""
    import agents.gmail_sync as mod

    # Set up minimal state
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(mod, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(mod, "STATE_FILE", cache_dir / "state.json")
    monkeypatch.setattr(mod, "GMAIL_DIR", tmp_path / "gmail")
    monkeypatch.setattr(mod, "PROFILE_FACTS_FILE", cache_dir / "facts.jsonl")
    monkeypatch.setattr(mod, "CHANGES_LOG", cache_dir / "changes.jsonl")

    # Mock Gmail API
    mock_service = MagicMock()
    mock_service.users().getProfile().execute.return_value = {
        "emailAddress": "test@test.com",
        "messagesTotal": 0,
        "threadsTotal": 0,
        "historyId": "123",
    }
    mock_service.users().messages().list().execute.return_value = {"messages": []}
    monkeypatch.setattr(mod, "_get_gmail_service", lambda: mock_service)

    sensor_writes: list[tuple[str, dict]] = []
    impingement_emits: list[tuple] = []
    monkeypatch.setattr(
        "shared.sensor_protocol.write_sensor_state",
        lambda name, data: sensor_writes.append((name, data)),
    )
    monkeypatch.setattr(
        "shared.sensor_protocol.emit_sensor_impingement",
        lambda *args, **kwargs: impingement_emits.append(args),
    )
    monkeypatch.setattr("shared.notify.send_notification", lambda *a, **kw: None)

    mod.run_full_sync()

    assert len(sensor_writes) == 1
    assert sensor_writes[0][0] == "gmail"
    assert "unread_count" in sensor_writes[0][1]
    assert "last_sync" in sensor_writes[0][1]
    assert len(impingement_emits) == 1
    assert impingement_emits[0][1] == "communication_patterns"


# ── Tier 2: gdrive_sync ─────────────────────────────────────────────────────


def test_gdrive_auto_writes_sensor_state(tmp_path: Path, monkeypatch):
    """gdrive run_auto writes sensor state on incremental sync."""
    import agents.gdrive_sync as mod

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    state_file = cache_dir / "state.json"
    # Pre-populate state with a start_page_token
    state_file.write_text(json.dumps({"start_page_token": "abc", "files": {}}))

    monkeypatch.setattr(mod, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(mod, "STATE_FILE", state_file)
    monkeypatch.setattr(mod, "GDRIVE_DIR", tmp_path / "gdrive")
    monkeypatch.setattr(mod, "META_DIR", tmp_path / "gdrive" / ".meta")
    monkeypatch.setattr(mod, "PROFILE_FACTS_FILE", cache_dir / "facts.jsonl")
    monkeypatch.setattr(mod, "DELETIONS_LOG", cache_dir / "deletions.jsonl")

    mock_service = MagicMock()
    mock_service.changes().list().execute.return_value = {
        "newStartPageToken": "def",
        "changes": [],
    }
    monkeypatch.setattr(mod, "_get_drive_service", lambda: mock_service)

    sensor_writes: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "shared.sensor_protocol.write_sensor_state",
        lambda name, data: sensor_writes.append((name, data)),
    )
    monkeypatch.setattr(
        "shared.sensor_protocol.emit_sensor_impingement",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("shared.notify.send_notification", lambda *a, **kw: None)

    mod.run_auto()

    assert len(sensor_writes) == 1
    assert sensor_writes[0][0] == "gdrive"
    assert "file_count" in sensor_writes[0][1]


# ── Tier 2: watch_receiver ───────────────────────────────────────────────────


def test_watch_receiver_sensor_protocol():
    """watch_receiver ingest_sensors endpoint calls sensor protocol."""
    from fastapi.testclient import TestClient

    import agents.watch_receiver as mod

    sensor_writes: list[tuple[str, dict]] = []
    impingement_emits: list[tuple] = []

    with patch.object(mod, "WATCH_STATE_DIR", Path("/tmp/test-watch-state")):
        with patch(
            "shared.sensor_protocol.write_sensor_state",
            lambda name, data: sensor_writes.append((name, data)),
        ):
            with patch(
                "shared.sensor_protocol.emit_sensor_impingement",
                lambda *args, **kwargs: impingement_emits.append(args),
            ):
                client = TestClient(mod.app)
                resp = client.post(
                    "/watch/sensors",
                    json={
                        "ts": int(time.time() * 1000),
                        "device_id": "pw4",
                        "readings": [
                            {"type": "heart_rate", "ts": "2026-01-01T00:00:00Z", "bpm": 72.0}
                        ],
                    },
                )
                assert resp.status_code == 200
                assert len(sensor_writes) == 1
                assert sensor_writes[0][0] == "watch"
                assert len(impingement_emits) == 1
                assert impingement_emits[0][1] == "energy_and_attention"


# ── Tier 3: weather_sync ─────────────────────────────────────────────────────


def test_weather_sync_writes_sensor_state(tmp_path: Path, monkeypatch):
    """weather sync() writes sensor state and emits impingement."""
    import agents.weather_sync as mod

    monkeypatch.setattr(mod, "RAG_DIR", tmp_path / "weather")

    mock_data = {
        "current": {
            "temperature_2m": 72.0,
            "relative_humidity_2m": 45,
            "surface_pressure": 1013.0,
            "apparent_temperature": 70.0,
            "cloud_cover": 25,
            "wind_speed_10m": 5.0,
            "weather_code": 1,
        }
    }
    monkeypatch.setattr(mod, "fetch_weather", lambda *a, **kw: mock_data)

    sensor_writes: list[tuple[str, dict]] = []
    impingement_emits: list[tuple] = []
    monkeypatch.setattr(
        "shared.sensor_protocol.write_sensor_state",
        lambda name, data: sensor_writes.append((name, data)),
    )
    monkeypatch.setattr(
        "shared.sensor_protocol.emit_sensor_impingement",
        lambda *args, **kwargs: impingement_emits.append(args),
    )

    result = mod.sync()
    assert result is True
    assert len(sensor_writes) == 1
    assert sensor_writes[0][0] == "weather"
    assert sensor_writes[0][1]["temperature_f"] == 72.0
    assert len(impingement_emits) == 1
    assert impingement_emits[0][1] == "temporal"


# ── Tier 3: git_sync ─────────────────────────────────────────────────────────


def test_git_sync_sensor_protocol_present():
    """git_sync orchestration functions contain sensor protocol calls."""
    import inspect

    import agents.git_sync as mod

    full_src = inspect.getsource(mod.run_full_sync)
    assert "write_sensor_state" in full_src
    assert "emit_sensor_impingement" in full_src

    auto_src = inspect.getsource(mod.run_auto)
    assert "write_sensor_state" in auto_src
    assert "emit_sensor_impingement" in auto_src


# ── Tier 3: youtube_sync ─────────────────────────────────────────────────────


def test_youtube_sync_sensor_protocol_present():
    """youtube_sync orchestration functions contain sensor protocol calls."""
    import inspect

    import agents.youtube_sync as mod

    src = inspect.getsource(mod.run_full_sync)
    assert "write_sensor_state" in src
    assert "emit_sensor_impingement" in src


# ── Tier 3: obsidian_sync ────────────────────────────────────────────────────


def test_obsidian_sync_sensor_protocol_present():
    """obsidian_sync orchestration functions contain sensor protocol calls."""
    import inspect

    import agents.obsidian_sync as mod

    full_src = inspect.getsource(mod.run_full_sync)
    assert "write_sensor_state" in full_src

    auto_src = inspect.getsource(mod.run_auto)
    assert "write_sensor_state" in auto_src
    assert "emit_sensor_impingement" in auto_src


# ── Tier 3: langfuse_sync ────────────────────────────────────────────────────


def test_langfuse_sync_sensor_protocol_present():
    """langfuse_sync orchestration functions contain sensor protocol calls."""
    import inspect

    import agents.langfuse_sync as mod

    full_src = inspect.getsource(mod.run_full_sync)
    assert "write_sensor_state" in full_src
    assert "emit_sensor_impingement" in full_src

    auto_src = inspect.getsource(mod.run_auto)
    assert "write_sensor_state" in auto_src


# ── Tier 3: claude_code_sync ─────────────────────────────────────────────────


def test_claude_code_sync_sensor_protocol_present():
    """claude_code_sync orchestration functions contain sensor protocol calls."""
    import inspect

    import agents.claude_code_sync as mod

    full_src = inspect.getsource(mod.run_full_sync)
    assert "write_sensor_state" in full_src
    assert "emit_sensor_impingement" in full_src

    auto_src = inspect.getsource(mod.run_auto)
    assert "write_sensor_state" in auto_src
    assert "emit_sensor_impingement" in auto_src

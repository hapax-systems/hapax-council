"""Tests for scripts/youtube-player.py VideoSlot extraction-failure signalling.

Covers A12: when yt-dlp URL extraction fails (timeout, network error, etc.),
VideoSlot.play() must emit a yt-finished-N marker so the director loop
re-dispatches with a different playlist entry instead of leaving the slot
wedged forever.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch


def _load_yt_player(tmp_shm: Path):
    """Load scripts/youtube-player.py as a module with SHM_DIR pointed at tmp_path."""
    repo_root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "yt_player_under_test", repo_root / "scripts" / "youtube-player.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["yt_player_under_test"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.SHM_DIR = tmp_shm
    return module


def test_extraction_failure_writes_finished_marker(tmp_path):
    """URL extraction timeout writes yt-finished-N with sentinel rc=-1."""
    yt = _load_yt_player(tmp_path)
    slot = yt.VideoSlot(slot_id=1)

    with patch.object(yt, "extract_urls", side_effect=RuntimeError("yt-dlp timed out")):
        slot.play("https://youtube.com/watch?v=wedged")

    marker = tmp_path / "yt-finished-1"
    assert marker.exists(), "Extraction failure must emit finished marker"
    assert marker.read_text() == "-1", "Sentinel rc must be -1 for extraction failure"


def test_extraction_failure_leaves_no_ffmpeg_process(tmp_path):
    """After extraction failure the slot must be idle (no self.process)."""
    yt = _load_yt_player(tmp_path)
    slot = yt.VideoSlot(slot_id=2)

    with patch.object(yt, "extract_urls", side_effect=RuntimeError("boom")):
        slot.play("https://youtube.com/watch?v=wedged")

    assert slot.process is None
    assert slot.url == ""


def test_signal_finished_survives_missing_shm(tmp_path):
    """_signal_finished must not raise if SHM_DIR is unwritable."""
    yt = _load_yt_player(tmp_path / "does-not-exist")
    slot = yt.VideoSlot(slot_id=0)
    slot._signal_finished(rc=-1)  # must not raise


def test_extract_urls_timeout_is_45_seconds(tmp_path):
    """All three yt-dlp subprocess calls must use a 45s timeout (was 15s)."""
    yt = _load_yt_player(tmp_path)

    captured_timeouts: list[int] = []
    stdouts = iter(["Title\nChannel", "https://video.example/v", "https://audio.example/a"])

    def fake_run(*args, **kwargs):
        captured_timeouts.append(kwargs.get("timeout"))

        class _Result:
            pass

        result = _Result()
        result.stdout = next(stdouts)
        return result

    with patch.object(yt.subprocess, "run", side_effect=fake_run):
        video_url, audio_url, title, channel = yt.extract_urls("https://youtube.com/watch?v=ok")

    assert captured_timeouts == [45, 45, 45], (
        f"Expected three 45s timeouts, got {captured_timeouts}"
    )
    assert title == "Title"
    assert channel == "Channel"
    assert video_url == "https://video.example/v"
    assert audio_url == "https://audio.example/a"


def test_slot_mute_policy_unmutes_active_slot(tmp_path, monkeypatch):
    """Active slot must clear restored Pulse mute state as well as volume."""
    yt = _load_yt_player(tmp_path)
    monkeypatch.setenv("HAPAX_YT_ACTIVE_SLOT", "1")
    pw_dump = json.dumps(
        [
            {
                "id": 101,
                "type": "PipeWire:Interface:Node",
                "info": {"props": {"media.name": "youtube-audio-0"}},
            },
            {
                "id": 102,
                "type": "PipeWire:Interface:Node",
                "info": {"props": {"media.name": "youtube-audio-1"}},
            },
        ]
    )
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)

        class _Result:
            stdout = pw_dump

        return _Result()

    with patch.object(yt.subprocess, "run", side_effect=fake_run):
        yt._apply_slot_mute_policy()

    assert ["wpctl", "set-volume", "101", "0.0"] in calls
    assert ["wpctl", "set-mute", "101", "1"] in calls
    assert ["wpctl", "set-volume", "102", "1.0"] in calls
    assert ["wpctl", "set-mute", "102", "0"] in calls

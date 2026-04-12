"""Tests for agents.studio_compositor.director_loop — YT slot cold-start path."""

from __future__ import annotations

import time
from unittest.mock import patch

from agents.studio_compositor import director_loop as dl_module
from agents.studio_compositor.director_loop import DirectorLoop


class _FakeSlot:
    """Minimal stand-in for VideoSlotStub — just the fields DirectorLoop reads."""

    def __init__(self, slot_id: int) -> None:
        self.slot_id = slot_id
        self._title = ""
        self._channel = ""
        self.is_active = False

    def check_finished(self) -> bool:
        return False


class _FakeReactor:
    def set_header(self, *args, **kwargs) -> None:
        pass

    def set_text(self, *args, **kwargs) -> None:
        pass

    def set_speaking(self, *args, **kwargs) -> None:
        pass

    def feed_pcm(self, *args, **kwargs) -> None:
        pass


def _director(slots: list[_FakeSlot]) -> DirectorLoop:
    return DirectorLoop(video_slots=slots, reactor_overlay=_FakeReactor())


def test_slots_needing_cold_start_returns_missing_ids(tmp_path, monkeypatch):
    """Slots without yt-frame-N.jpg are flagged for cold-start."""
    monkeypatch.setattr(dl_module, "SHM_DIR", tmp_path)
    (tmp_path / "yt-frame-1.jpg").write_bytes(b"\xff\xd8\xff")  # only slot 1 has a frame
    director = _director([_FakeSlot(0), _FakeSlot(1), _FakeSlot(2)])

    assert director._slots_needing_cold_start() == [0, 2]


def test_slots_needing_cold_start_empty_when_all_slots_have_frames(tmp_path, monkeypatch):
    """No slots need cold-start when every frame file exists."""
    monkeypatch.setattr(dl_module, "SHM_DIR", tmp_path)
    for i in range(3):
        (tmp_path / f"yt-frame-{i}.jpg").write_bytes(b"\xff\xd8\xff")
    director = _director([_FakeSlot(i) for i in range(3)])

    assert director._slots_needing_cold_start() == []


def test_dispatch_cold_starts_triggers_reload_for_missing_slots(tmp_path, monkeypatch):
    """_dispatch_cold_starts spawns a reload thread for each missing slot."""
    monkeypatch.setattr(dl_module, "SHM_DIR", tmp_path)
    director = _director([_FakeSlot(i) for i in range(3)])
    reloaded: list[int] = []

    def _capture(slot_id: int) -> None:
        reloaded.append(slot_id)

    with patch.object(director, "_reload_slot_from_playlist", side_effect=_capture):
        dispatched = director._dispatch_cold_starts()
        for _ in range(20):  # wait for background threads
            if len(reloaded) == 3:
                break
            time.sleep(0.05)

    assert sorted(dispatched) == [0, 1, 2]
    assert sorted(reloaded) == [0, 1, 2]


def test_dispatch_cold_starts_skips_slots_with_frames(tmp_path, monkeypatch):
    """Slots that already have a frame are not cold-started."""
    monkeypatch.setattr(dl_module, "SHM_DIR", tmp_path)
    for i in range(3):
        (tmp_path / f"yt-frame-{i}.jpg").write_bytes(b"\xff\xd8\xff")
    director = _director([_FakeSlot(i) for i in range(3)])

    with patch.object(director, "_reload_slot_from_playlist") as reload_mock:
        dispatched = director._dispatch_cold_starts()

    assert dispatched == []
    reload_mock.assert_not_called()


def test_dispatch_cold_starts_partial_missing(tmp_path, monkeypatch):
    """Mixed state: only the missing slots get a reload dispatch."""
    monkeypatch.setattr(dl_module, "SHM_DIR", tmp_path)
    (tmp_path / "yt-frame-0.jpg").write_bytes(b"\xff\xd8\xff")
    (tmp_path / "yt-frame-2.jpg").write_bytes(b"\xff\xd8\xff")
    director = _director([_FakeSlot(i) for i in range(3)])
    reloaded: list[int] = []

    with patch.object(
        director, "_reload_slot_from_playlist", side_effect=lambda sid: reloaded.append(sid)
    ):
        dispatched = director._dispatch_cold_starts()
        for _ in range(20):
            if reloaded:
                break
            time.sleep(0.05)

    assert dispatched == [1]
    assert reloaded == [1]

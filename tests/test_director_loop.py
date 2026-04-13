"""Tests for agents.studio_compositor.director_loop — YT slot cold-start path."""

from __future__ import annotations

import json
import subprocess
import time
from unittest.mock import MagicMock, patch

from agents.studio_compositor import director_loop as dl_module
from agents.studio_compositor.director_loop import DirectorLoop, _load_playlist


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


def test_slots_needing_cold_start_treats_zero_byte_as_missing(tmp_path, monkeypatch):
    """A stale 0-byte yt-frame file must still count as missing (FU-5).

    Regression: yt-player restart used to leave 0-byte files behind, which
    passed the old .exists()-only check AND then got sent to Claude as
    invalid images (HTTP 400). Observed 2026-04-12 post-A12 deploy.
    """
    monkeypatch.setattr(dl_module, "SHM_DIR", tmp_path)
    (tmp_path / "yt-frame-0.jpg").write_bytes(b"\xff\xd8\xff")
    (tmp_path / "yt-frame-1.jpg").write_bytes(b"")  # stale 0-byte
    # slot 2 has no file at all
    director = _director([_FakeSlot(i) for i in range(3)])

    assert director._slots_needing_cold_start() == [1, 2]


def test_gather_images_skips_zero_byte_frame(tmp_path, monkeypatch):
    """_gather_images must not pass 0-byte frame files to the LLM."""
    monkeypatch.setattr(dl_module, "SHM_DIR", tmp_path)
    # stale 0-byte active slot frame
    (tmp_path / "yt-frame-0.jpg").write_bytes(b"")
    # valid fx snapshot
    fx = tmp_path / "fx-snapshot.jpg"
    fx.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    monkeypatch.setattr(dl_module, "FX_SNAPSHOT", fx)
    director = _director([_FakeSlot(i) for i in range(3)])

    images = director._gather_images()

    assert str(fx) in images
    assert str(tmp_path / "yt-frame-0.jpg") not in images


def test_gather_images_includes_valid_frame(tmp_path, monkeypatch):
    """_gather_images includes a frame file with non-zero size."""
    monkeypatch.setattr(dl_module, "SHM_DIR", tmp_path)
    valid = tmp_path / "yt-frame-0.jpg"
    valid.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 200)
    fx = tmp_path / "fx-snapshot.jpg"
    fx.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 200)
    monkeypatch.setattr(dl_module, "FX_SNAPSHOT", fx)
    director = _director([_FakeSlot(i) for i in range(3)])

    images = director._gather_images()

    assert images == [str(valid), str(fx)]


# ---------------------------------------------------------------------------
# _load_playlist — restored after spirograph_reactor deletion (PR #644)
# ---------------------------------------------------------------------------


def test_load_playlist_returns_cached_when_available(tmp_path, monkeypatch):
    """If playlist.json exists, return its contents without running yt-dlp."""
    cached = [
        {"id": "abc", "title": "First", "url": "https://www.youtube.com/watch?v=abc"},
        {"id": "xyz", "title": "Second", "url": "https://www.youtube.com/watch?v=xyz"},
    ]
    playlist_file = tmp_path / "playlist.json"
    playlist_file.write_text(json.dumps(cached))
    monkeypatch.setattr(dl_module, "PLAYLIST_FILE", playlist_file)

    with patch("subprocess.run") as sp_mock:
        result = _load_playlist()

    assert result == cached
    sp_mock.assert_not_called()


def test_load_playlist_extracts_via_ytdlp_when_cache_missing(tmp_path, monkeypatch):
    """Missing cache triggers yt-dlp extraction and writes the cache."""
    playlist_file = tmp_path / "playlist.json"
    monkeypatch.setattr(dl_module, "PLAYLIST_FILE", playlist_file)
    fake_stdout = "\n".join(
        [
            json.dumps({"id": "aaa", "title": "A"}),
            json.dumps({"id": "bbb", "title": "B"}),
        ]
    )

    with patch(
        "subprocess.run",
        return_value=MagicMock(stdout=fake_stdout, returncode=0),
    ) as sp_mock:
        result = _load_playlist()

    assert len(result) == 2
    assert result[0]["id"] == "aaa"
    assert result[0]["url"] == "https://www.youtube.com/watch?v=aaa"
    sp_mock.assert_called_once()
    # Cache should have been written
    assert playlist_file.exists()
    assert json.loads(playlist_file.read_text()) == result


def test_load_playlist_returns_empty_on_ytdlp_timeout(tmp_path, monkeypatch):
    """A yt-dlp timeout must degrade to an empty list, not crash."""
    monkeypatch.setattr(dl_module, "PLAYLIST_FILE", tmp_path / "missing.json")

    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="yt-dlp", timeout=60),
    ):
        result = _load_playlist()

    assert result == []


def test_load_playlist_returns_empty_when_ytdlp_not_installed(tmp_path, monkeypatch):
    """Missing yt-dlp binary must degrade to an empty list, not crash."""
    monkeypatch.setattr(dl_module, "PLAYLIST_FILE", tmp_path / "missing.json")

    with patch("subprocess.run", side_effect=FileNotFoundError()):
        result = _load_playlist()

    assert result == []


# ---------------------------------------------------------------------------
# FINDING-G real fix: Kokoro throughput safety cap on react texts
# ---------------------------------------------------------------------------


def test_synthesize_passes_short_text_through() -> None:
    """Texts under the cap must pass through unchanged."""
    director = _director([])
    director._tts_client = MagicMock()
    director._tts_client.synthesize.return_value = b"\x00\x01" * 100
    director._synthesize("hello world")
    director._tts_client.synthesize.assert_called_once_with("hello world", "conversation")


def test_synthesize_truncates_long_text_at_word_boundary() -> None:
    """Texts over _MAX_REACT_TEXT_CHARS must be truncated at the last
    whitespace before the cap and suffixed with an ellipsis. Beta
    PR #756 queue-024 Phase 1 measured Kokoro CPU at ~6.6 chars/sec;
    a 600-char input would need ~90 s synth which blocks the speak-
    react thread. The cap keeps each synth under ~60 s.
    """
    director = _director([])
    director._tts_client = MagicMock()
    director._tts_client.synthesize.return_value = b"\x00\x01" * 100

    # Build a 600-char string made of distinct words so we can see
    # the word-boundary truncation clearly.
    long_text = " ".join(f"word{i:04d}" for i in range(100))
    assert len(long_text) > director._MAX_REACT_TEXT_CHARS

    director._synthesize(long_text)

    assert director._tts_client.synthesize.call_count == 1
    sent_text = director._tts_client.synthesize.call_args[0][0]
    assert sent_text.endswith("…"), "truncated output must end with an ellipsis"
    assert len(sent_text) <= director._MAX_REACT_TEXT_CHARS + 1  # +1 for the ellipsis
    # Word-boundary invariant: the truncated output (minus the ellipsis)
    # must end at a word boundary from the original text.
    stem = sent_text[:-1]
    assert long_text.startswith(stem)
    assert not stem.endswith("word") or stem[-4:].isdigit() or stem[-1].isalnum(), (
        "truncation should not slice a word in half"
    )


def test_synthesize_truncation_invokes_tts_client_once() -> None:
    """The truncation path must not retry synthesis — a single call
    with the capped text is enough. Prevents an accidental loop
    that would defeat the throughput guard.
    """
    director = _director([])
    director._tts_client = MagicMock()
    director._tts_client.synthesize.return_value = b""
    director._synthesize("x" * 1000)
    assert director._tts_client.synthesize.call_count == 1


def test_max_react_text_chars_is_tuned_to_kokoro_throughput() -> None:
    """The cap must correspond to a synth time under the client
    timeout. Beta's measured ~6.6 chars/sec Kokoro throughput means
    400 chars → ~60 s, which is within the 90 s client timeout from
    PR #757 follow-up.
    """
    from agents.studio_compositor.tts_client import _DEFAULT_TIMEOUT_S

    assert DirectorLoop._MAX_REACT_TEXT_CHARS == 400
    # Measured throughput ~6.6 chars/sec; 400 chars ≈ 60 s worst-case
    measured_throughput_chars_per_sec = 6.6
    worst_case_synth_s = DirectorLoop._MAX_REACT_TEXT_CHARS / measured_throughput_chars_per_sec
    assert worst_case_synth_s < _DEFAULT_TIMEOUT_S, (
        f"character cap ({DirectorLoop._MAX_REACT_TEXT_CHARS}) worst-case "
        f"synth ({worst_case_synth_s:.1f}s) must be under the client "
        f"timeout ({_DEFAULT_TIMEOUT_S}s)"
    )

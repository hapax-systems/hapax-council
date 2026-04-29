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
    # valid camera-only LLM frame (Phase 3 — replaces fx-snapshot here)
    llm_frame = tmp_path / "frame_for_llm.jpg"
    llm_frame.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    monkeypatch.setattr(dl_module, "LLM_FRAME", llm_frame)
    director = _director([_FakeSlot(i) for i in range(3)])

    images = director._gather_images()

    assert str(llm_frame) in images
    assert str(tmp_path / "yt-frame-0.jpg") not in images


def test_gather_images_includes_valid_frame(tmp_path, monkeypatch):
    """_gather_images includes a frame file with non-zero size."""
    monkeypatch.setattr(dl_module, "SHM_DIR", tmp_path)
    valid = tmp_path / "yt-frame-0.jpg"
    valid.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 200)
    llm_frame = tmp_path / "frame_for_llm.jpg"
    llm_frame.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 200)
    monkeypatch.setattr(dl_module, "LLM_FRAME", llm_frame)
    director = _director([_FakeSlot(i) for i in range(3)])

    images = director._gather_images()

    assert images == [str(valid), str(llm_frame)]


def test_gather_images_uses_llm_frame_not_fx_snapshot(tmp_path, monkeypatch):
    """Phase 3 (AUDIT-07 layer 4): the LLM-bound image set is sourced from
    the camera-only ``frame_for_llm.jpg``, never the post-cairo
    ``fx-snapshot.jpg``. If both files exist, only the camera-only one
    must reach the LLM — otherwise the model OCR's the wards it
    previously authored and recycles them as ground truth.
    """
    monkeypatch.setattr(dl_module, "SHM_DIR", tmp_path)
    fx = tmp_path / "fx-snapshot.jpg"
    fx.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 200)
    llm_frame = tmp_path / "frame_for_llm.jpg"
    llm_frame.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 200)
    monkeypatch.setattr(dl_module, "FX_SNAPSHOT", fx)
    monkeypatch.setattr(dl_module, "LLM_FRAME", llm_frame)
    director = _director([_FakeSlot(i) for i in range(3)])

    images = director._gather_images()

    assert str(llm_frame) in images
    assert str(fx) not in images


def test_llm_frame_constant_path_semantics():
    """Pin the canonical path for the LLM-bound frame.

    The compositor's ``add_llm_frame_snapshot_branch`` writes here; the
    director reads here. The shared SHM_DIR + filename are the wire
    contract.
    """
    assert dl_module.LLM_FRAME == dl_module.SHM_DIR / "frame_for_llm.jpg"


def test_capture_snapshot_b64_reads_llm_frame(tmp_path, monkeypatch):
    """``_capture_snapshot_b64`` reads the camera-only LLM frame, not FX."""
    import base64

    fx = tmp_path / "fx-snapshot.jpg"
    fx.write_bytes(b"FX-WARD-CONTAMINATED")
    llm_frame = tmp_path / "frame_for_llm.jpg"
    llm_frame.write_bytes(b"CAMERA-ONLY-CLEAN")
    monkeypatch.setattr(dl_module, "FX_SNAPSHOT", fx)
    monkeypatch.setattr(dl_module, "LLM_FRAME", llm_frame)

    encoded = dl_module._capture_snapshot_b64()

    assert encoded == base64.b64encode(b"CAMERA-ONLY-CLEAN").decode()


# ---------------------------------------------------------------------------
# _gather_director_claims — Phase 3.5 Layer C ward iteration
# ---------------------------------------------------------------------------


def _make_test_claim(name: str, posterior: float = 0.85):
    """Construct a minimal Claim for ward-binding tests."""
    from shared.claim import Claim, TemporalProfile

    return Claim(
        name=name,
        domain="activity",
        proposition=f"{name} is happening.",
        posterior=posterior,
        prior_source="empirical",
        prior_provenance_ref=name,
        evidence_sources=[],
        last_update_t=time.time(),
        temporal_profile=TemporalProfile(
            enter_threshold=0.7, exit_threshold=0.3, k_enter=3, k_exit=3
        ),
        composition=None,
        narration_floor=0.6,
        staleness_cutoff_s=60.0,
    )


def test_gather_director_claims_includes_ward_bound_claims(tmp_path, monkeypatch):
    """Phase 3.5 Layer C: active wards with bound providers contribute claims."""
    from agents.studio_compositor import active_wards, ward_claim_bindings

    monkeypatch.setattr(dl_module, "_vinyl_engine", lambda: None)
    monkeypatch.setattr(dl_module, "_music_engine", lambda: None)

    ward_claim_bindings.clear_bindings()
    monkeypatch.setattr(active_wards, "ACTIVE_WARDS_FILE", tmp_path / "active_wards.json")

    bound_claim = _make_test_claim("splat_attribution")
    ward_claim_bindings.register("splat-attribution-v1", lambda: bound_claim)
    active_wards.publish(["splat-attribution-v1"])

    claims = dl_module._gather_director_claims()

    ward_claim_bindings.clear_bindings()
    assert [c.name for c in claims] == ["splat_attribution"]


def test_gather_director_claims_skips_wards_without_bindings(tmp_path, monkeypatch):
    """Active wards with no claim provider are silently skipped."""
    from agents.studio_compositor import active_wards, ward_claim_bindings

    monkeypatch.setattr(dl_module, "_vinyl_engine", lambda: None)
    monkeypatch.setattr(dl_module, "_music_engine", lambda: None)

    ward_claim_bindings.clear_bindings()
    monkeypatch.setattr(active_wards, "ACTIVE_WARDS_FILE", tmp_path / "active_wards.json")
    active_wards.publish(["sierpinski", "homage-chrome"])

    claims = dl_module._gather_director_claims()

    assert claims == []


def test_gather_director_claims_skips_provider_returning_none(tmp_path, monkeypatch):
    """A provider returning None means the engine declined this tick."""
    from agents.studio_compositor import active_wards, ward_claim_bindings

    monkeypatch.setattr(dl_module, "_vinyl_engine", lambda: None)
    monkeypatch.setattr(dl_module, "_music_engine", lambda: None)

    ward_claim_bindings.clear_bindings()
    monkeypatch.setattr(active_wards, "ACTIVE_WARDS_FILE", tmp_path / "active_wards.json")
    ward_claim_bindings.register("album-cover", lambda: None)
    active_wards.publish(["album-cover"])

    claims = dl_module._gather_director_claims()

    ward_claim_bindings.clear_bindings()
    assert claims == []


def test_gather_director_claims_swallows_provider_exceptions(tmp_path, monkeypatch):
    """A raising provider must not break envelope assembly — Layer C is the safety net."""
    from agents.studio_compositor import active_wards, ward_claim_bindings

    monkeypatch.setattr(dl_module, "_vinyl_engine", lambda: None)
    monkeypatch.setattr(dl_module, "_music_engine", lambda: None)

    ward_claim_bindings.clear_bindings()
    monkeypatch.setattr(active_wards, "ACTIVE_WARDS_FILE", tmp_path / "active_wards.json")

    def _raising_provider():
        raise RuntimeError("provider buggy")

    good_claim = _make_test_claim("good_claim")
    ward_claim_bindings.register("buggy-ward", _raising_provider)
    ward_claim_bindings.register("good-ward", lambda: good_claim)
    active_wards.publish(["buggy-ward", "good-ward"])

    claims = dl_module._gather_director_claims()

    ward_claim_bindings.clear_bindings()
    assert [c.name for c in claims] == ["good_claim"]


def test_gather_director_claims_empty_active_wards_keeps_engine_path(tmp_path, monkeypatch):
    """No active_wards.json → ward iteration contributes nothing → engine path
    behaves identically to pre-Phase-3.5-Layer-C baseline (zero regression)."""
    from agents.studio_compositor import active_wards, ward_claim_bindings

    monkeypatch.setattr(dl_module, "_vinyl_engine", lambda: None)
    monkeypatch.setattr(dl_module, "_music_engine", lambda: None)

    ward_claim_bindings.clear_bindings()
    monkeypatch.setattr(active_wards, "ACTIVE_WARDS_FILE", tmp_path / "absent.json")

    claims = dl_module._gather_director_claims()

    assert claims == []


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
# FINDING-G follow-up: no-truncation speech contract for react texts
# ---------------------------------------------------------------------------


def test_synthesize_passes_short_text_through() -> None:
    """Texts under the cap must pass through unchanged."""
    director = _director([])
    director._tts_client = MagicMock()
    director._tts_client.synthesize.return_value = b"\x00\x01" * 100
    director._synthesize("hello world")
    director._tts_client.synthesize.assert_called_once_with("hello world", "conversation")


def test_synthesize_passes_long_text_through_without_ellipsis() -> None:
    """Long react text is a planning concern, not a transport truncation point."""
    director = _director([])
    director._tts_client = MagicMock()
    director._tts_client.synthesize.return_value = b"\x00\x01" * 100

    long_text = " ".join(f"word{i:04d}" for i in range(100))

    director._synthesize(long_text)

    assert director._tts_client.synthesize.call_count == 1
    sent_text = director._tts_client.synthesize.call_args[0][0]
    assert sent_text == long_text
    assert "..." not in sent_text
    assert "…" not in sent_text


def test_synthesize_long_text_invokes_tts_client_once() -> None:
    """Long speech still makes a single TTS request with the complete text."""
    director = _director([])
    director._tts_client = MagicMock()
    director._tts_client.synthesize.return_value = b""
    director._synthesize("x" * 1000)
    assert director._tts_client.synthesize.call_count == 1


def test_react_text_timeout_budget_scales_to_kokoro_throughput() -> None:
    """Long react speech is guarded by dynamic timeout, not audible truncation."""
    from agents.studio_compositor.tts_client import _DEFAULT_TIMEOUT_S, synthesis_timeout_s

    long_text = " ".join(f"word{i:04d}" for i in range(100))
    timeout_s = synthesis_timeout_s(long_text, minimum_s=_DEFAULT_TIMEOUT_S)

    assert timeout_s > _DEFAULT_TIMEOUT_S
    assert timeout_s > len(long_text) / 6.6

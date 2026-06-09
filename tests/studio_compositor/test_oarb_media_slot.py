"""Tests for the single OARB media-slot owner.

The OARB sphere's media is selected by one file (``youtube-video-id.txt``,
read by the live BGRA source). ``oarb_media_slot`` is the single in-process
owner through which the director cues a SPECIFIC ref to that slot: it writes
the same selector the rotator writes PLUS a director-cue lease so the rotator
can defer. No new playback path — it rides the existing YT media selector.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.studio_compositor.oarb_media_slot import (
    OarbCueResult,
    cue_from_youtube_direction,
    cue_media_to_oarb,
    oarb_is_playing,
    video_id_from_ref,
)


def test_cue_writes_selector_and_lease(tmp_path: Path) -> None:
    selector = tmp_path / "youtube-video-id.txt"
    lease = tmp_path / "oarb-director-cue.json"

    result = cue_media_to_oarb(
        "object:yt:dQw4w9WgXcQ",
        ttl_s=120.0,
        now=1000.0,
        selector_path=selector,
        cue_path=lease,
    )

    assert isinstance(result, OarbCueResult)
    assert result.cued is True
    assert result.video_id == "dQw4w9WgXcQ"
    # Selector carries only the bare id (what the BGRA source consumes).
    assert selector.read_text(encoding="utf-8").strip() == "dQw4w9WgXcQ"
    # Lease marks the slot director-owned with a bounded TTL.
    payload = json.loads(lease.read_text(encoding="utf-8"))
    assert payload["video_id"] == "dQw4w9WgXcQ"
    assert payload["owner"] == "segment_director"
    assert payload["expires_at"] == 1120.0
    assert payload["media_ref"] == "object:yt:dQw4w9WgXcQ"


def test_cue_refuses_unresolvable_ref(tmp_path: Path) -> None:
    selector = tmp_path / "sel.txt"
    lease = tmp_path / "cue.json"

    result = cue_media_to_oarb("object:image:not-a-video", selector_path=selector, cue_path=lease)

    assert result.cued is False
    assert result.video_id is None
    assert not selector.exists()
    assert not lease.exists()


def test_cue_from_youtube_direction_honors_cue_to_surface(tmp_path: Path) -> None:
    selector = tmp_path / "sel.txt"
    lease = tmp_path / "cue.json"
    data = {"action": "cue-to-surface", "ttl_s": 60.0, "media_ref": "object:yt:abc123"}

    result = cue_from_youtube_direction(data, now=10.0, selector_path=selector, cue_path=lease)

    assert result is not None and result.cued is True
    assert selector.read_text(encoding="utf-8").strip() == "abc123"


def test_cue_from_youtube_direction_ignores_other_actions(tmp_path: Path) -> None:
    selector = tmp_path / "sel.txt"
    lease = tmp_path / "cue.json"

    assert (
        cue_from_youtube_direction({"action": "cut-away"}, selector_path=selector, cue_path=lease)
        is None
    )
    assert (
        cue_from_youtube_direction(
            {"action": "cue-to-surface"}, selector_path=selector, cue_path=lease
        )
        is None
    )
    assert not selector.exists()


def test_oarb_is_playing_matches_live_selector(tmp_path: Path) -> None:
    selector = tmp_path / "youtube-video-id.txt"
    selector.write_text("abc123\n", encoding="utf-8")

    # The readback reads the ACTUAL selector — a move can't fake success.
    assert oarb_is_playing("object:yt:abc123", selector_path=selector) is True
    assert oarb_is_playing("object:yt:different", selector_path=selector) is False


def test_oarb_is_playing_false_when_selector_missing(tmp_path: Path) -> None:
    selector = tmp_path / "absent.txt"
    assert oarb_is_playing("object:yt:abc123", selector_path=selector) is False


def test_oarb_is_playing_false_for_non_youtube_ref(tmp_path: Path) -> None:
    selector = tmp_path / "youtube-video-id.txt"
    selector.write_text("abc123\n", encoding="utf-8")
    assert oarb_is_playing("object:image:x.png", selector_path=selector) is False


def test_video_id_from_ref_variants() -> None:
    assert video_id_from_ref("object:yt:abc123") == "abc123"
    assert video_id_from_ref("https://www.youtube.com/watch?v=abc123&t=10") == "abc123"
    assert video_id_from_ref("https://youtu.be/xyz789") == "xyz789"
    assert video_id_from_ref("object:image:foo.png") is None
    assert video_id_from_ref("") is None

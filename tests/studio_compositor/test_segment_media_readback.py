"""A media move counts as success only when the readback proves it rendered.

youtube → the OARB selector ACTUALLY shows the intended ref; image → the ref
appears in the layout readback's rendered_object_refs. A move that merely wrote
an intent (cued) but did not render is reported as not-rendered, so it cannot
fake-succeed.
"""

from __future__ import annotations

from pathlib import Path

from agents.studio_compositor.segment_action_materializer import MediaMove
from agents.studio_compositor.segment_media_readback import media_render_verdicts


def test_youtube_move_rendered_when_selector_matches(tmp_path: Path) -> None:
    selector = tmp_path / "youtube-video-id.txt"
    selector.write_text("abc123\n", encoding="utf-8")
    move = MediaMove(
        object_ref="object:yt:abc123", media_kind="youtube", outcome="allowed", cued=True
    )

    verdicts = media_render_verdicts([move], oarb_selector_path=selector)

    assert len(verdicts) == 1
    assert verdicts[0].rendered is True


def test_youtube_move_not_rendered_when_selector_differs(tmp_path: Path) -> None:
    selector = tmp_path / "youtube-video-id.txt"
    selector.write_text("somethingelse\n", encoding="utf-8")
    move = MediaMove(
        object_ref="object:yt:abc123", media_kind="youtube", outcome="allowed", cued=True
    )

    verdicts = media_render_verdicts([move], oarb_selector_path=selector)

    # Fake-success caught: cued, but the slot is showing a different video.
    assert verdicts[0].rendered is False


def test_image_move_rendered_when_in_readback_object_refs(tmp_path: Path) -> None:
    move = MediaMove(
        object_ref="object:image:diagram.png", media_kind="image", outcome="allowed", cued=True
    )

    verdicts = media_render_verdicts(
        [move],
        rendered_object_refs=("object:image:diagram.png",),
        oarb_selector_path=tmp_path / "absent.txt",
    )

    assert verdicts[0].rendered is True


def test_image_move_not_rendered_when_absent_from_readback(tmp_path: Path) -> None:
    move = MediaMove(
        object_ref="object:image:diagram.png", media_kind="image", outcome="allowed", cued=True
    )

    verdicts = media_render_verdicts(
        [move], rendered_object_refs=(), oarb_selector_path=tmp_path / "absent.txt"
    )

    assert verdicts[0].rendered is False


def test_non_cued_move_is_not_rendered(tmp_path: Path) -> None:
    move = MediaMove(
        object_ref="object:yt:abc123", media_kind="youtube", outcome="refused_consent", cued=False
    )

    verdicts = media_render_verdicts([move], oarb_selector_path=tmp_path / "absent.txt")

    assert verdicts[0].rendered is False

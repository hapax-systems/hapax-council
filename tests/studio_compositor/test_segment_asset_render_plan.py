"""The reveal ward plans real media per asset, never a narrating text label.

``coding_activity_reveal`` used to render authored assets as the literal
on-screen string ``[IMAGE] caption`` / ``[YOUTUBE] url`` — a show-don't-tell
breach (a label narrating the move). ``plan_asset_render`` replaces that: an
authored image is blitted, a youtube asset is left to the materializer's OARB
cue (the panel skips it — no narration), and text/url assets fall back to
plain caption text WITHOUT the ``[KIND]`` move-narration prefix.

This is a pure, per-frame-safe rendering decision: consent/fortress gating of
*recruited* media is the materializer's job (once per beat), not the ward's
(which would fire the egress metric at frame rate on operator-authored
content).
"""

from __future__ import annotations

from agents.studio_compositor.coding_activity_reveal import (
    AssetRenderAction,
    plan_asset_render,
)


def test_image_with_url_is_blitted_not_labelled() -> None:
    plan = plan_asset_render(
        {"kind": "image", "url": "/srv/a/diagram.png", "caption": "the architecture"}
    )
    assert plan.action is AssetRenderAction.BLIT
    assert plan.media_ref == "/srv/a/diagram.png"
    assert plan.label is None


def test_youtube_asset_is_skipped_by_the_panel() -> None:
    # The materializer cues YT to the OARB sphere; the panel must not narrate it.
    plan = plan_asset_render(
        {"kind": "youtube", "url": "https://youtu.be/abc", "caption": "a clip"}
    )
    assert plan.action is AssetRenderAction.SKIP


def test_text_asset_renders_plain_caption() -> None:
    plan = plan_asset_render({"kind": "text", "caption": "a spoken note"})
    assert plan.action is AssetRenderAction.LABEL
    assert plan.label == "a spoken note"


def test_url_asset_renders_plain_caption() -> None:
    plan = plan_asset_render({"kind": "url", "url": "https://example.com", "caption": "see source"})
    assert plan.action is AssetRenderAction.LABEL
    assert plan.label == "see source"


def test_image_without_url_falls_back_to_caption() -> None:
    plan = plan_asset_render({"kind": "image", "caption": "missing file"})
    assert plan.action is AssetRenderAction.LABEL
    assert plan.label == "missing file"


def test_no_asset_ever_produces_a_kind_narration_label() -> None:
    for asset in (
        {"kind": "image", "url": "/x.png", "caption": "c"},
        {"kind": "youtube", "url": "https://youtu.be/x", "caption": "c"},
        {"kind": "url", "url": "https://example.com", "caption": "c"},
        {"kind": "text", "caption": "c"},
    ):
        plan = plan_asset_render(asset)
        assert "[" not in (plan.label or "")

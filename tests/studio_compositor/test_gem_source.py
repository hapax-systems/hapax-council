"""Tests for GemCairoSource (Graffiti Emphasis Mural ward).

Spec: docs/superpowers/plans/2026-04-21-gem-ward-activation-plan.md §1.
Design: docs/research/2026-04-19-gem-ward-design.md.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from agents.studio_compositor.gem_source import (
    DEFAULT_FRAMES_PATH,
    FALLBACK_FRAME_TEXT,
    LEGACY_FRAMES_PATH,
    MIN_FRAME_HOLD_MS,
    GemCairoSource,
    GemFrame,
    GemLayer,
    build_graffiti_layers,
    contains_emoji,
)


def _write_frames(path: Path, frames: list[dict]) -> None:
    path.write_text(json.dumps({"frames": frames}), encoding="utf-8")


# ── Anti-pattern enforcement ────────────────────────────────────────────


def test_contains_emoji_detects_smileys() -> None:
    assert contains_emoji("hello 😀")
    assert contains_emoji("plain ❤️ heart")  # presentation selector


def test_contains_emoji_passes_cp437_only() -> None:
    assert not contains_emoji("» hapax «")
    assert not contains_emoji("┌─[ ACIDIC ]─┐")
    assert not contains_emoji("ASCII tree: ╱╲")
    assert not contains_emoji("plain ASCII text 12345")


def test_render_replaces_emoji_with_fallback(tmp_path: Path) -> None:
    """An emoji-containing frame triggers the fallback at render time."""
    src = GemCairoSource(frames_path=tmp_path / "absent.json")
    rendered: list[str] = []

    with patch.object(
        src,
        "_render_text_centered",
        lambda cr, w, h, text, **_kwargs: rendered.append(text),
    ):
        src.render_content(cr=None, canvas_w=1840, canvas_h=240, t=0.0, state={"text": "yo 😀"})

    assert any(FALLBACK_FRAME_TEXT in text for text in rendered)


# ── Frame loading + advancement ─────────────────────────────────────────


def test_state_falls_back_when_no_frames_file(tmp_path: Path) -> None:
    src = GemCairoSource(frames_path=tmp_path / "absent.json")
    state = src.state()
    assert state["text"] == FALLBACK_FRAME_TEXT
    assert state["frame_count"] == 0
    assert len(state["layers"]) >= 2


def test_state_loads_frames_from_file(tmp_path: Path) -> None:
    frames_path = tmp_path / "frames.json"
    _write_frames(
        frames_path,
        [
            {"text": "first", "hold_ms": 1000},
            {"text": "second", "hold_ms": 800},
        ],
    )

    src = GemCairoSource(frames_path=frames_path)
    state = src.state()

    assert state["text"] == "first"
    assert state["frame_count"] == 2
    assert state["frame_index"] == 0
    assert len(state["layers"]) >= 2


def test_state_loads_explicit_multilayer_frames(tmp_path: Path) -> None:
    frames_path = tmp_path / "frames.json"
    _write_frames(
        frames_path,
        [
            {
                "text": "first",
                "hold_ms": 1000,
                "layers": [
                    {"text": "first back", "opacity": 0.35, "offset_x_px": -20},
                    {"text": "first front", "opacity": 0.9, "offset_y_px": 12},
                ],
            }
        ],
    )

    src = GemCairoSource(frames_path=frames_path)
    state = src.state()

    assert [layer["text"] for layer in state["layers"]] == ["first back", "first front"]
    assert state["layers"][0]["opacity"] == 0.35


def test_default_source_falls_back_to_legacy_frames_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    canonical = tmp_path / "hapax-gem" / "gem-frames.json"
    legacy = tmp_path / "hapax-compositor" / "gem-frames.json"
    legacy.parent.mkdir(parents=True)
    _write_frames(legacy, [{"text": "legacy mural", "hold_ms": 1000}])

    monkeypatch.setattr(
        "agents.studio_compositor.gem_source.DEFAULT_FRAMES_PATH",
        canonical,
    )
    monkeypatch.setattr(
        "agents.studio_compositor.gem_source.LEGACY_FRAMES_PATH",
        legacy,
    )

    src = GemCairoSource()
    assert src._frames_path == canonical
    assert src._legacy_frames_path == legacy
    assert src.state()["text"] == "legacy mural"


def test_frame_advances_after_hold(tmp_path: Path) -> None:
    frames_path = tmp_path / "frames.json"
    _write_frames(
        frames_path,
        [
            {"text": "a", "hold_ms": 100},
            {"text": "b", "hold_ms": 100},
        ],
    )

    src = GemCairoSource(frames_path=frames_path)
    src.state()  # loads + lands on frame 0

    # Simulate elapsed hold by rewinding the started timestamp.
    src._frame_started_ts = time.monotonic() - 0.5  # 500ms > 100ms hold
    state = src.state()

    assert state["text"] == "b"
    assert state["frame_index"] == 1


def test_frame_wraps_to_zero(tmp_path: Path) -> None:
    frames_path = tmp_path / "frames.json"
    _write_frames(frames_path, [{"text": "only", "hold_ms": 50}])

    src = GemCairoSource(frames_path=frames_path)
    src.state()
    src._frame_started_ts = time.monotonic() - 1.0
    state = src.state()

    # Single frame loops back to itself; index stays 0.
    assert state["text"] == "only"
    assert state["frame_index"] == 0


def test_malformed_json_falls_back_safely(tmp_path: Path) -> None:
    frames_path = tmp_path / "frames.json"
    frames_path.write_text("{ this is not valid json", encoding="utf-8")

    src = GemCairoSource(frames_path=frames_path)
    state = src.state()

    assert state["text"] == FALLBACK_FRAME_TEXT
    assert state["frame_count"] == 0


def test_non_dict_frame_entries_skipped(tmp_path: Path) -> None:
    frames_path = tmp_path / "frames.json"
    frames_path.write_text(
        json.dumps({"frames": ["not a dict", {"text": "ok"}, 42]}),
        encoding="utf-8",
    )

    src = GemCairoSource(frames_path=frames_path)
    state = src.state()

    assert state["text"] == "ok"
    assert state["frame_count"] == 1


def test_space_only_frame_entries_are_ignored(tmp_path: Path) -> None:
    frames_path = tmp_path / "frames.json"
    frames_path.write_text(
        json.dumps({"frames": [{"text": " ", "hold_ms": 100}]}),
        encoding="utf-8",
    )

    src = GemCairoSource(frames_path=frames_path)
    state = src.state()

    assert state["text"] == FALLBACK_FRAME_TEXT
    assert state["frame_count"] == 0


def test_negative_hold_ms_clamped_to_minimum(tmp_path: Path) -> None:
    frames_path = tmp_path / "frames.json"
    _write_frames(frames_path, [{"text": "a", "hold_ms": -500}])

    src = GemCairoSource(frames_path=frames_path)
    src.state()
    # GemFrame should have a clamped hold_ms; short legacy frames can blink.
    assert src._frames[0].hold_ms == MIN_FRAME_HOLD_MS


def test_frames_reload_on_mtime_change(tmp_path: Path) -> None:
    frames_path = tmp_path / "frames.json"
    _write_frames(frames_path, [{"text": "v1", "hold_ms": 1000}])

    src = GemCairoSource(frames_path=frames_path)
    state = src.state()
    assert state["text"] == "v1"

    # Rewrite with new content; bump mtime.
    _write_frames(frames_path, [{"text": "v2", "hold_ms": 1000}])
    import os

    new_mtime = src._last_loaded_mtime + 10.0
    os.utime(frames_path, (new_mtime, new_mtime))
    state = src.state()
    assert state["text"] == "v2"


# ── FSM identity ─────────────────────────────────────────────────────────


def test_source_id_is_gem(tmp_path: Path) -> None:
    src = GemCairoSource(frames_path=tmp_path / "x.json")
    assert src.source_id == "gem"


def test_inherits_homage_transitional_source(tmp_path: Path) -> None:
    from agents.studio_compositor.homage.transitional_source import (
        HomageTransitionalSource,
    )

    src = GemCairoSource(frames_path=tmp_path / "x.json")
    assert isinstance(src, HomageTransitionalSource)


# ── GemFrame value type ──────────────────────────────────────────────────


def test_gem_frame_default_hold_ms() -> None:
    frame = GemFrame(text="x")
    assert frame.hold_ms == 1500


def test_gem_frame_is_hashable() -> None:
    """frozen=True dataclass — usable as dict key / set member."""
    {GemFrame(text="x"), GemFrame(text="y")}


def test_gem_frame_layers_are_hashable() -> None:
    {GemFrame(text="x", layers=(GemLayer(text="x", opacity=0.5),))}


def test_build_graffiti_layers_is_dense_not_chiron() -> None:
    layers = build_graffiti_layers("signal")
    assert len(layers) >= 2
    assert len({layer.opacity for layer in layers}) >= 2
    assert any(layer.offset_x_px or layer.offset_y_px for layer in layers)
    assert not any(layer.text.startswith(">>>") for layer in layers)


def test_default_paths_use_hapax_gem_with_legacy_compat() -> None:
    assert Path("/dev/shm/hapax-gem/gem-frames.json") == DEFAULT_FRAMES_PATH
    assert Path("/dev/shm/hapax-compositor/gem-frames.json") == LEGACY_FRAMES_PATH


# ── GEM Rooms (Layer 2) ──────────────────────────────────────────────────


def test_ensure_room_tree_caching(tmp_path: Path) -> None:
    src = GemCairoSource(frames_path=tmp_path / "x.json")
    tree1 = src._ensure_room_tree(1840, 240)
    tree2 = src._ensure_room_tree(1840, 240)
    assert tree1 is tree2
    assert len(tree1) == 13


def test_ensure_room_tree_recomputes_on_resize(tmp_path: Path) -> None:
    src = GemCairoSource(frames_path=tmp_path / "x.json")
    tree1 = src._ensure_room_tree(1840, 240)
    tree2 = src._ensure_room_tree(1000, 200)
    assert tree1 is not tree2
    assert src._room_tree_w == 1000


def test_render_rooms_handles_no_tree(tmp_path: Path) -> None:
    src = GemCairoSource(frames_path=tmp_path / "x.json")
    with patch(
        "agents.studio_compositor.gem_source.GemCairoSource._ensure_room_tree", return_value=None
    ):
        src._render_rooms(None, 1840, 240, 0.0)  # Should not crash


def test_render_rooms_is_explicit_noop(tmp_path: Path) -> None:
    src = GemCairoSource(frames_path=tmp_path / "x.json")

    class _FailOnTouch:
        def __getattr__(self, name: str):
            raise AssertionError(f"room renderer touched cairo state via {name}")

    src._render_rooms(_FailOnTouch(), 1840, 240, 0.0)

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PIL import Image

from agents.studio_compositor import director_loop as director_loop_module
from agents.studio_compositor.director_loop import DirectorLoop
from agents.studio_compositor.sierpinski_loader import SierpinskiLoader
from agents.studio_compositor.sierpinski_renderer import SierpinskiCairoSource
from agents.visual_pool.repository import LocalVisualPool


def _png(path: Path) -> Path:
    Image.new("RGB", (2, 2), color=(80, 40, 20)).save(path)
    return path


def _seed_pool(root: Path, *, tier: str = "operator-cuts") -> Path:
    src = _png(root / "source.png")
    pool = LocalVisualPool(root / "visual")
    asset = pool.ingest(
        src,
        tier_directory=tier,
        aesthetic_tags=["sierpinski", "grain"],
        motion_density=0.5,
        title="Local Frame",
    )
    return asset.path


def test_sierpinski_loader_publishes_local_visual_pool_asset(tmp_path: Path) -> None:
    frame = _seed_pool(tmp_path)
    loader = SierpinskiLoader(pool_root=tmp_path / "visual", aesthetic_tags=("grain",))
    published: list[dict] = []
    removed: list[str] = []

    def inject_jpeg(**kwargs) -> bool:
        published.append(kwargs)
        return True

    def remove_source(source_id: str) -> None:
        removed.append(source_id)

    loader._publish_sources(inject_jpeg, remove_source)

    assert removed == []
    assert len(published) == 1
    assert published[0]["source_id"] == "visual-pool-slot-0"
    assert published[0]["jpeg_path"] == frame
    assert "local-visual-pool" in published[0]["tags"]
    assert "tier_0_owned" in published[0]["tags"]


def test_sierpinski_renderer_resolves_local_pool_frame(tmp_path: Path) -> None:
    frame = _seed_pool(tmp_path)
    renderer = SierpinskiCairoSource()
    renderer._visual_pool_selector.pool = LocalVisualPool(tmp_path / "visual")
    renderer._visual_pool_selector._loaded_at = 0.0

    assert renderer._resolve_frame_path(0) == frame


def test_director_skips_playlist_cold_start_for_local_visual_slots(tmp_path: Path) -> None:
    frame = _seed_pool(tmp_path)
    loader = SierpinskiLoader(pool_root=tmp_path / "visual", aesthetic_tags=("grain",))
    assert loader.video_slots[0].current_frame_path == frame
    director = DirectorLoop(video_slots=loader.video_slots, reactor_overlay=object())

    with patch.object(director, "_reload_slot_from_playlist") as reload_slot:
        assert director._dispatch_cold_starts() == []
    reload_slot.assert_not_called()


def test_director_gathers_local_visual_frame_for_reaction_context(
    tmp_path: Path, monkeypatch
) -> None:
    frame = _seed_pool(tmp_path)
    loader = SierpinskiLoader(pool_root=tmp_path / "visual", aesthetic_tags=("grain",))
    director = DirectorLoop(video_slots=loader.video_slots, reactor_overlay=object())
    monkeypatch.setattr(director_loop_module, "LLM_FRAME", tmp_path / "absent-llm-frame.jpg")

    assert director._gather_images() == [str(frame)]

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from agents.studio_compositor.director_loop import DirectorLoop
from agents.studio_compositor.sierpinski_loader import SierpinskiLoader
from agents.visual_pool.repository import LocalVisualPool

_REPO = Path(__file__).resolve().parents[2]
_SIERPINSKI_FRAME_PATHS = [
    _REPO / "agents" / "studio_compositor" / "sierpinski_loader.py",
    _REPO / "agents" / "studio_compositor" / "sierpinski_renderer.py",
    _REPO / "agents" / "visual_pool" / "repository.py",
    _REPO / "agents" / "visual_pool" / "__main__.py",
]


def _png(path: Path) -> Path:
    Image.new("RGB", (2, 2), color=(1, 2, 3)).save(path)
    return path


def _seed_pool(root: Path) -> None:
    src = _png(root / "frame.png")
    LocalVisualPool(root / "visual").ingest(
        src,
        tier_directory="operator-cuts",
        aesthetic_tags=["sierpinski"],
        motion_density=0.4,
    )


def test_sierpinski_frame_path_does_not_reference_yt_dlp() -> None:
    for path in _SIERPINSKI_FRAME_PATHS:
        text = path.read_text(encoding="utf-8")
        assert "yt-dlp" not in text
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names]
                assert "subprocess" not in names, f"{path} imports subprocess"


def test_local_visual_pool_slots_do_not_invoke_youtube_playlist_reload(tmp_path: Path) -> None:
    _seed_pool(tmp_path)
    loader = SierpinskiLoader(pool_root=tmp_path / "visual", aesthetic_tags=("sierpinski",))
    director = DirectorLoop(video_slots=loader.video_slots, reactor_overlay=object())

    with (
        patch("agents.studio_compositor.director_loop._load_playlist") as load_playlist,
        patch("subprocess.run") as subprocess_run,
    ):
        assert director._dispatch_cold_starts() == []

    load_playlist.assert_not_called()
    subprocess_run.assert_not_called()

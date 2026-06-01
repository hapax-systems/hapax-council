from __future__ import annotations

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-obs-ffmpeg-source-ensure"


def _load_module() -> Any:
    loader = SourceFileLoader("hapax_obs_ffmpeg_source_ensure", str(SCRIPT))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


class FakeObsClient:
    def __init__(self, inputs: set[str] | None = None) -> None:
        self.inputs = set(inputs or ())
        self.item_ids = {
            "Video Capture Device (V4L2)": 10,
            "DarkPlaces Screwm": 11,
        }
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def get_input_list(self) -> SimpleNamespace:
        return SimpleNamespace(inputs=[{"inputName": name} for name in sorted(self.inputs)])

    def create_input(
        self,
        scene_name: str,
        input_name: str,
        input_kind: str,
        input_settings: dict[str, Any],
        scene_item_enabled: bool,
    ) -> None:
        self.calls.append(
            (
                "create_input",
                (scene_name, input_name, input_kind, input_settings, scene_item_enabled),
            )
        )
        self.inputs.add(input_name)
        self.item_ids[input_name] = 42

    def set_input_settings(self, name: str, settings: dict[str, Any], overlay: bool) -> None:
        self.calls.append(("set_input_settings", (name, settings, overlay)))

    def get_scene_item_id(self, scene_name: str, source_name: str) -> SimpleNamespace:
        if source_name not in self.item_ids:
            raise RuntimeError(source_name)
        return SimpleNamespace(scene_item_id=self.item_ids[source_name])

    def set_scene_item_enabled(self, scene_name: str, item_id: int, enabled: bool) -> None:
        self.calls.append(("set_scene_item_enabled", (scene_name, item_id, enabled)))

    def set_scene_item_transform(
        self,
        scene_name: str,
        item_id: int,
        transform: dict[str, Any],
    ) -> None:
        self.calls.append(("set_scene_item_transform", (scene_name, item_id, transform)))


def test_ensure_obs_ffmpeg_source_creates_media_input_and_disables_v4l2() -> None:
    mod = _load_module()
    client = FakeObsClient({"Video Capture Device (V4L2)", "DarkPlaces Screwm"})
    settings = mod.ffmpeg_source_settings("udp://127.0.0.1:30552", "mpegts", 1, 1)

    result = mod.ensure_obs_ffmpeg_source(
        client,
        scene_name="Scene",
        source_name="DarkPlaces Screwm Media",
        settings=settings,
        width=1920,
        height=1080,
        disable_sources=("Video Capture Device (V4L2)", "DarkPlaces Screwm"),
    )

    assert result["action"] == "created"
    assert tuple(result["disabled_sources"]) == ("Video Capture Device (V4L2)", "DarkPlaces Screwm")
    assert client.calls[0][0] == "create_input"
    assert client.calls[0][1][2] == "ffmpeg_source"
    assert ("set_scene_item_enabled", ("Scene", 42, True)) in client.calls
    assert ("set_scene_item_enabled", ("Scene", 10, False)) in client.calls
    assert ("set_scene_item_enabled", ("Scene", 11, False)) in client.calls
    transforms = [call[1][2] for call in client.calls if call[0] == "set_scene_item_transform"]
    assert transforms[0]["boundsType"] == "OBS_BOUNDS_STRETCH"
    assert transforms[0]["boundsWidth"] == 1920.0
    assert transforms[0]["boundsHeight"] == 1080.0


def test_ensure_obs_ffmpeg_source_updates_existing_media_input() -> None:
    mod = _load_module()
    client = FakeObsClient({"DarkPlaces Screwm Media", "Video Capture Device (V4L2)"})
    client.item_ids["DarkPlaces Screwm Media"] = 42
    settings = mod.ffmpeg_source_settings("udp://127.0.0.1:30552", "mpegts", 1, 1)

    result = mod.ensure_obs_ffmpeg_source(
        client,
        scene_name="Scene",
        source_name="DarkPlaces Screwm Media",
        settings=settings,
        width=1920,
        height=1080,
        disable_sources=("Video Capture Device (V4L2)",),
    )

    assert result["action"] == "updated"
    assert client.calls[0] == ("set_input_settings", ("DarkPlaces Screwm Media", settings, True))
    assert not any(call[0] == "create_input" for call in client.calls)

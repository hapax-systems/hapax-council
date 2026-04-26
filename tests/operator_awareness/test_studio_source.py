"""Tests for ``agents.operator_awareness.sources.studio``."""

from __future__ import annotations

from pathlib import Path

from agents.operator_awareness.sources.studio import (
    DEFAULT_SCENE_FLAG_PATH,
    collect_studio_block,
)
from agents.operator_awareness.state import StudioBlock


class TestCollectStudioBlock:
    def test_missing_flag_file_returns_inactive(self, tmp_path: Path) -> None:
        block = collect_studio_block(scene_flag_path=tmp_path / "nope")
        assert isinstance(block, StudioBlock)
        assert block.monitor_aux_c_active is False
        assert block.public is False

    def test_scene_8_flips_monitor_aux_c_active(self, tmp_path: Path) -> None:
        flag = tmp_path / "l12-scene"
        flag.write_text("8\n", encoding="utf-8")
        block = collect_studio_block(scene_flag_path=flag)
        assert block.monitor_aux_c_active is True

    def test_scene_1_keeps_inactive(self, tmp_path: Path) -> None:
        flag = tmp_path / "l12-scene"
        flag.write_text("1", encoding="utf-8")
        block = collect_studio_block(scene_flag_path=flag)
        assert block.monitor_aux_c_active is False

    def test_unknown_scene_id_keeps_inactive(self, tmp_path: Path) -> None:
        flag = tmp_path / "l12-scene"
        flag.write_text("scene-13", encoding="utf-8")
        block = collect_studio_block(scene_flag_path=flag)
        assert block.monitor_aux_c_active is False

    def test_public_false_default(self, tmp_path: Path) -> None:
        flag = tmp_path / "l12-scene"
        flag.write_text("8", encoding="utf-8")
        block = collect_studio_block(scene_flag_path=flag)
        assert block.public is False

    def test_public_true_when_caller_flips(self, tmp_path: Path) -> None:
        flag = tmp_path / "l12-scene"
        flag.write_text("8", encoding="utf-8")
        block = collect_studio_block(scene_flag_path=flag, public=True)
        assert block.public is True
        assert block.monitor_aux_c_active is True


class TestDefaultPath:
    def test_path_under_hapax_cache(self) -> None:
        assert ".cache/hapax" in str(DEFAULT_SCENE_FLAG_PATH)
        assert DEFAULT_SCENE_FLAG_PATH.name == "l12-scene"

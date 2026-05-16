from __future__ import annotations

from pathlib import Path

from scripts.hapax_layout_drift_check import check_drift


class TestLayoutDriftCheck:
    def test_no_drift_on_matching_files(self, tmp_path: Path) -> None:
        gov = tmp_path / "governed"
        dep = tmp_path / "deployed"
        gov.mkdir()
        dep.mkdir()
        (gov / "default.json").write_text('{"name": "default"}')
        (dep / "default.json").write_text('{"name": "default"}')

        result = check_drift(gov, dep)
        assert result["drift_detected"] is False
        assert result["matching"] == ["default.json"]

    def test_detects_content_mismatch(self, tmp_path: Path) -> None:
        gov = tmp_path / "governed"
        dep = tmp_path / "deployed"
        gov.mkdir()
        dep.mkdir()
        (gov / "default.json").write_text('{"name": "default", "version": 1}')
        (dep / "default.json").write_text('{"name": "default", "version": 2}')

        result = check_drift(gov, dep)
        assert result["drift_detected"] is True
        assert len(result["content_mismatch"]) == 1

    def test_detects_missing_from_deployed(self, tmp_path: Path) -> None:
        gov = tmp_path / "governed"
        dep = tmp_path / "deployed"
        gov.mkdir()
        dep.mkdir()
        (gov / "segment-detail.json").write_text('{"name": "segment-detail"}')

        result = check_drift(gov, dep)
        assert result["drift_detected"] is True
        assert "segment-detail.json" in result["missing_from_deployed"]

    def test_detects_untracked(self, tmp_path: Path) -> None:
        gov = tmp_path / "governed"
        dep = tmp_path / "deployed"
        gov.mkdir()
        dep.mkdir()
        (dep / "rogue.json").write_text('{"name": "rogue"}')

        result = check_drift(gov, dep)
        assert result["drift_detected"] is True
        assert "rogue.json" in result["untracked_in_deployed"]

    def test_empty_dirs_no_drift(self, tmp_path: Path) -> None:
        gov = tmp_path / "governed"
        dep = tmp_path / "deployed"
        gov.mkdir()
        dep.mkdir()

        result = check_drift(gov, dep)
        assert result["drift_detected"] is False

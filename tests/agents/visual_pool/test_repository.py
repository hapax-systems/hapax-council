from __future__ import annotations

from pathlib import Path

import yaml
from PIL import Image

from agents.visual_pool.__main__ import main as visual_pool_main
from agents.visual_pool.repository import LocalVisualPool


def _png(path: Path) -> Path:
    Image.new("RGB", (2, 2), color=(10, 20, 30)).save(path)
    return path


def test_ensure_layout_creates_tier_directories(tmp_path: Path) -> None:
    pool = LocalVisualPool(tmp_path / "visual")
    pool.ensure_layout()

    assert (pool.root / "README.md").is_file()
    for dirname in ("operator-cuts", "storyblocks", "internet-archive", "sample-source"):
        assert (pool.root / dirname).is_dir()


def test_ingest_writes_sidecar_and_selects_by_tag_and_risk(tmp_path: Path) -> None:
    src = _png(tmp_path / "source.png")
    pool = LocalVisualPool(tmp_path / "visual")

    asset = pool.ingest(
        src,
        tier_directory="storyblocks",
        aesthetic_tags=["Sierpinski", "film grain"],
        motion_density=0.7,
        color_palette=["cyan"],
        duration_seconds=4.0,
    )

    assert asset.path == pool.root / "storyblocks" / "source.png"
    sidecar = yaml.safe_load(asset.sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["content_risk"] == "tier_1_platform_cleared"
    assert sidecar["broadcast_safe"] is True
    selected = pool.select(
        aesthetic_tags=("film-grain",), max_content_risk="tier_1_platform_cleared"
    )
    assert selected is not None
    assert selected.path == asset.path
    assert selected.provenance_token.startswith("visual:hapax-pool:")


def test_tier_two_asset_requires_explicit_risk_ceiling(tmp_path: Path) -> None:
    src = _png(tmp_path / "archive.png")
    pool = LocalVisualPool(tmp_path / "visual")
    asset = pool.ingest(
        src,
        tier_directory="internet-archive",
        aesthetic_tags=["sierpinski", "industrial"],
        motion_density=0.3,
    )

    assert pool.select(aesthetic_tags=("industrial",)) is None
    selected = pool.select(
        aesthetic_tags=("industrial",),
        max_content_risk="tier_2_provenance_known",
    )
    assert selected is not None
    assert selected.path == asset.path


def test_missing_sidecar_fails_closed(tmp_path: Path) -> None:
    pool = LocalVisualPool(tmp_path / "visual")
    pool.ensure_layout()
    _png(pool.root / "operator-cuts" / "bare.png")

    assert pool.scan() == []
    assert pool.select(aesthetic_tags=("sierpinski",)) is None


def test_malformed_sidecar_fails_closed(tmp_path: Path) -> None:
    pool = LocalVisualPool(tmp_path / "visual")
    pool.ensure_layout()
    frame = _png(pool.root / "operator-cuts" / "blank-tags.png")
    frame.with_suffix(".yaml").write_text(
        yaml.safe_dump(
            {
                "content_risk": "tier_0_owned",
                "source": "  ",
                "broadcast_safe": True,
                "aesthetic_tags": ["  "],
                "motion_density": 0.4,
                "duration_seconds": 0.0,
            }
        ),
        encoding="utf-8",
    )

    assert pool.scan() == []
    assert pool.select(aesthetic_tags=("sierpinski",)) is None


def test_sample_source_is_never_selected(tmp_path: Path) -> None:
    src = _png(tmp_path / "sample.png")
    pool = LocalVisualPool(tmp_path / "visual")
    pool.ingest(
        src,
        tier_directory="sample-source",
        aesthetic_tags=["sierpinski"],
        motion_density=0.1,
    )

    assert len(pool.scan()) == 1
    assert pool.select(aesthetic_tags=("sierpinski",), max_content_risk="tier_4_risky") is None


def test_cli_init_and_ingest(tmp_path: Path) -> None:
    root = tmp_path / "visual"
    src = _png(tmp_path / "cli.png")

    assert visual_pool_main(["--root", str(root), "init"]) == 0
    assert (root / "operator-cuts").is_dir()
    assert (
        visual_pool_main(
            [
                "--root",
                str(root),
                "ingest",
                str(src),
                "--tier",
                "operator-cuts",
                "--tag",
                "sierpinski",
                "--motion-density",
                "0.2",
            ]
        )
        == 0
    )
    assert (root / "operator-cuts" / "cli.png").is_file()
    assert (root / "operator-cuts" / "cli.yaml").is_file()

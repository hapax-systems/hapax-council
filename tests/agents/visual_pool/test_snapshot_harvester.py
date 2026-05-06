from __future__ import annotations

from pathlib import Path

import yaml
from PIL import Image

from agents.visual_pool.repository import LocalVisualPool, VisualPoolSidecar
from agents.visual_pool.snapshot_harvester import (
    discover_snapshot_sources,
    harvest_snapshots,
)


def _jpg(path: Path, color: tuple[int, int, int] = (20, 40, 80)) -> Path:
    Image.new("RGB", (4, 4), color=color).save(path, format="JPEG")
    return path


def test_discovers_only_live_camera_snapshot_names(tmp_path: Path) -> None:
    _jpg(tmp_path / "brio-operator.jpg")
    _jpg(tmp_path / "c920-desk.jpg")
    _jpg(tmp_path / "other-camera.jpg")
    (tmp_path / "brio-note.txt").write_text("not a frame", encoding="utf-8")

    assert [path.name for path in discover_snapshot_sources(tmp_path)] == [
        "brio-operator.jpg",
        "c920-desk.jpg",
    ]


def test_harvest_copies_operator_cuts_and_writes_schema_sidecars(tmp_path: Path) -> None:
    shm_dir = tmp_path / "shm"
    shm_dir.mkdir()
    _jpg(shm_dir / "brio-room.jpg")
    _jpg(shm_dir / "c920-overhead.jpg", color=(80, 40, 20))
    pool_root = tmp_path / "visual"

    results = harvest_snapshots(shm_dir=shm_dir, pool_root=pool_root)

    assert {result.asset_path.name for result in results} == {
        "brio-room.jpg",
        "c920-overhead.jpg",
    }
    assert all(result.copied for result in results)
    assert all(result.sidecar_written for result in results)
    assert not any((pool_root / "sample-source").iterdir())

    pool = LocalVisualPool(pool_root)
    assets = pool.scan()
    assert {asset.path.name for asset in assets} == {"brio-room.jpg", "c920-overhead.jpg"}
    selected = pool.select(aesthetic_tags=("camera-snapshot",))
    assert selected is not None
    assert selected.tier_directory == "operator-cuts"

    for result in results:
        raw = yaml.safe_load(result.sidecar_path.read_text(encoding="utf-8"))
        sidecar = VisualPoolSidecar.model_validate(raw)
        assert sidecar.content_risk == "tier_0_owned"
        assert sidecar.broadcast_safe is True
        assert sidecar.public_posture == "live"
        assert sidecar.routable_destinations == ("sierpinski",)
        assert "sierpinski" in sidecar.aesthetic_tags
        assert "camera-snapshot" in sidecar.aesthetic_tags
        assert f"sha256:{result.sha256}" in sidecar.wcs_evidence_refs


def test_harvest_is_idempotent_for_unchanged_snapshots(tmp_path: Path) -> None:
    shm_dir = tmp_path / "shm"
    shm_dir.mkdir()
    _jpg(shm_dir / "brio-synths.jpg")
    pool_root = tmp_path / "visual"

    first = harvest_snapshots(shm_dir=shm_dir, pool_root=pool_root)
    second = harvest_snapshots(shm_dir=shm_dir, pool_root=pool_root)

    assert len(first) == 1
    assert first[0].copied is True
    assert first[0].sidecar_written is True
    assert len(second) == 1
    assert second[0].copied is False
    assert second[0].sidecar_written is False


def test_dry_run_does_not_create_pool_layout(tmp_path: Path) -> None:
    shm_dir = tmp_path / "shm"
    shm_dir.mkdir()
    _jpg(shm_dir / "c920-room.jpg")
    pool_root = tmp_path / "visual"

    results = harvest_snapshots(shm_dir=shm_dir, pool_root=pool_root, dry_run=True)

    assert len(results) == 1
    assert results[0].dry_run is True
    assert not pool_root.exists()

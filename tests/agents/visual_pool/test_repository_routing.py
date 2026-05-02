"""Routing-metadata tests for visual_pool.repository.

Verifies the cc-task `visual-source-pool-homage-routing` extensions:
new sidecar fields (homage_class, motion_profile, public_posture,
wcs_evidence_refs, routable_destinations) and the
`select_by_destination()` query path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from PIL import Image

from agents.visual_pool.repository import (
    LocalVisualPool,
    VisualPoolSidecar,
)


def _png(path: Path) -> Path:
    Image.new("RGB", (2, 2), color=(10, 20, 30)).save(path)
    return path


def _write_asset(
    pool: LocalVisualPool,
    *,
    name: str,
    tier_directory: str,
    sidecar: dict,
) -> Path:
    pool.ensure_layout()
    src_path = pool.root / tier_directory / f"{name}.png"
    _png(src_path)
    sidecar_path = src_path.with_suffix(".yaml")
    sidecar_path.write_text(yaml.safe_dump(sidecar), encoding="utf-8")
    return src_path


def test_sidecar_accepts_routing_metadata_fields():
    sidecar = VisualPoolSidecar.model_validate(
        {
            "content_risk": "tier_0_owned",
            "source": "operator-cuts",
            "broadcast_safe": True,
            "aesthetic_tags": ["sierpinski", "homage"],
            "motion_density": 0.4,
            "color_palette": ["cyan"],
            "duration_seconds": 0,
            "homage_class": "warholian",
            "motion_profile": "slow_drift",
            "public_posture": "candidate",
            "wcs_evidence_refs": ("wcs:abc123",),
            "routable_destinations": ("sierpinski", "homage_video"),
        }
    )
    assert sidecar.homage_class == "warholian"
    assert sidecar.motion_profile == "slow_drift"
    assert sidecar.public_posture == "candidate"
    assert sidecar.wcs_evidence_refs == ("wcs:abc123",)
    assert sidecar.routable_destinations == ("sierpinski", "homage_video")


def test_sidecar_rejects_invalid_public_posture():
    with pytest.raises(ValueError):
        VisualPoolSidecar.model_validate(
            {
                "content_risk": "tier_0_owned",
                "source": "operator-cuts",
                "broadcast_safe": True,
                "aesthetic_tags": ["sierpinski"],
                "motion_density": 0.4,
                "color_palette": [],
                "duration_seconds": 0,
                "public_posture": "not-a-valid-posture",
            }
        )


def test_sidecar_rejects_unknown_routable_destination():
    with pytest.raises(ValueError):
        VisualPoolSidecar.model_validate(
            {
                "content_risk": "tier_0_owned",
                "source": "operator-cuts",
                "broadcast_safe": True,
                "aesthetic_tags": ["sierpinski"],
                "motion_density": 0.4,
                "color_palette": [],
                "duration_seconds": 0,
                "routable_destinations": ("not-a-real-destination",),
            }
        )


def test_sidecar_defaults_routing_metadata_to_empty():
    sidecar = VisualPoolSidecar.model_validate(
        {
            "content_risk": "tier_0_owned",
            "source": "operator-cuts",
            "broadcast_safe": True,
            "aesthetic_tags": ["sierpinski"],
            "motion_density": 0.4,
            "color_palette": [],
            "duration_seconds": 0,
        }
    )
    assert sidecar.homage_class is None
    assert sidecar.motion_profile is None
    assert sidecar.public_posture is None
    assert sidecar.wcs_evidence_refs == ()
    assert sidecar.routable_destinations == ()


def test_select_by_destination_legacy_assets_default_to_sierpinski(tmp_path):
    pool = LocalVisualPool(tmp_path / "visual")
    _write_asset(
        pool,
        name="legacy",
        tier_directory="operator-cuts",
        sidecar={
            "content_risk": "tier_0_owned",
            "source": "operator-cuts",
            "broadcast_safe": True,
            "aesthetic_tags": ["sierpinski", "texture"],
            "motion_density": 0.4,
            "color_palette": [],
            "duration_seconds": 0,
        },
    )

    asset = pool.select_by_destination("sierpinski")
    assert asset is not None
    assert asset.path.stem == "legacy"

    not_routable = pool.select_by_destination("homage_video")
    assert not_routable is None


def test_select_by_destination_filters_by_explicit_routable_destinations(tmp_path):
    pool = LocalVisualPool(tmp_path / "visual")
    _write_asset(
        pool,
        name="homage_only",
        tier_directory="operator-cuts",
        sidecar={
            "content_risk": "tier_0_owned",
            "source": "operator-cuts",
            "broadcast_safe": True,
            "aesthetic_tags": ["sierpinski"],
            "motion_density": 0.4,
            "color_palette": [],
            "duration_seconds": 0,
            "routable_destinations": ("homage_video",),
        },
    )

    found = pool.select_by_destination("homage_video")
    assert found is not None
    assert found.path.stem == "homage_only"

    not_found = pool.select_by_destination("sierpinski")
    assert not_found is None


def test_select_by_destination_blocks_private_posture_from_public_dest(tmp_path):
    pool = LocalVisualPool(tmp_path / "visual")
    _write_asset(
        pool,
        name="private_clip",
        tier_directory="operator-cuts",
        sidecar={
            "content_risk": "tier_0_owned",
            "source": "operator-cuts",
            "broadcast_safe": True,
            "aesthetic_tags": ["sierpinski"],
            "motion_density": 0.4,
            "color_palette": [],
            "duration_seconds": 0,
            "public_posture": "private",
            "routable_destinations": ("sierpinski", "archive_replay"),
        },
    )

    public_dest = pool.select_by_destination("sierpinski")
    assert public_dest is None

    archive = pool.select_by_destination("archive_replay")
    assert archive is not None


def test_select_by_destination_filters_by_homage_class(tmp_path):
    pool = LocalVisualPool(tmp_path / "visual")
    for name, klass in [("warholian_clip", "warholian"), ("klein_clip", "klein")]:
        _write_asset(
            pool,
            name=name,
            tier_directory="operator-cuts",
            sidecar={
                "content_risk": "tier_0_owned",
                "source": "operator-cuts",
                "broadcast_safe": True,
                "aesthetic_tags": ["homage"],
                "motion_density": 0.4,
                "color_palette": [],
                "duration_seconds": 0,
                "homage_class": klass,
                "routable_destinations": ("homage_video",),
            },
        )

    selected = pool.select_by_destination("homage_video", homage_class="klein")
    assert selected is not None
    assert selected.path.stem == "klein_clip"


def test_select_by_destination_invalid_destination_raises(tmp_path):
    pool = LocalVisualPool(tmp_path / "visual")
    pool.ensure_layout()

    with pytest.raises(ValueError):
        pool.select_by_destination("not-a-real-destination")


def test_select_by_destination_respects_max_content_risk(tmp_path):
    pool = LocalVisualPool(tmp_path / "visual")
    _write_asset(
        pool,
        name="high_risk",
        tier_directory="internet-archive",
        sidecar={
            "content_risk": "tier_2_provenance_known",
            "source": "internet-archive",
            "broadcast_safe": True,
            "aesthetic_tags": ["homage"],
            "motion_density": 0.4,
            "color_palette": [],
            "duration_seconds": 0,
            "routable_destinations": ("homage_video",),
        },
    )

    blocked = pool.select_by_destination("homage_video", max_content_risk="tier_1_platform_cleared")
    assert blocked is None

    allowed = pool.select_by_destination("homage_video", max_content_risk="tier_2_provenance_known")
    assert allowed is not None

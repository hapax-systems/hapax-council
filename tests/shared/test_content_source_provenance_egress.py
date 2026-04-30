from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from agents.visual_pool.repository import LocalVisualPool
from shared.compositor_model import SourceSchema
from shared.content_source_provenance_egress import (
    EgressManifestGate,
    audio_asset_from_music_manifest,
    build_broadcast_manifest,
    max_content_risk_from_env,
    read_broadcast_manifest,
    visual_asset_from_source_schema,
    write_broadcast_manifest,
)
from shared.music.provenance import MusicTrackProvenance, manifest_asset_from_provenance


def _png(path: Path) -> Path:
    Image.new("RGB", (2, 2), color=(10, 20, 30)).save(path)
    return path


def test_manifest_writes_expected_schema_shape(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest = build_broadcast_manifest(
        audio_assets=(),
        visual_assets=(),
        tick_id="tick-1",
        ts=10.0,
        max_content_risk="tier_1_platform_cleared",
    )

    write_broadcast_manifest(manifest, manifest_path)

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["tick_id"] == "tick-1"
    assert payload["ts"] == 10.0
    assert payload["audio_assets"] == []
    assert payload["visual_assets"] == []
    assert payload["authority_ceiling"]["grants_public_status"] is False
    assert read_broadcast_manifest(manifest_path) == manifest


def test_music_manifest_projection_preserves_token_tier_and_safety() -> None:
    record = MusicTrackProvenance(
        track_id="/pool/direct-drive.flac",
        provenance="hapax-pool",
        license="licensed-for-broadcast",
        source="operator-owned",
    )
    music_asset = manifest_asset_from_provenance(
        record,
        content_risk="tier_1_platform_cleared",
        broadcast_safe=True,
        source="operator-owned",
    )

    asset = audio_asset_from_music_manifest(music_asset)

    assert asset.medium == "audio"
    assert asset.token == music_asset.token
    assert asset.tier == "tier_1_platform_cleared"
    assert asset.broadcast_safe is True


def test_visual_pool_asset_projects_token_and_risk_for_egress(tmp_path: Path) -> None:
    src = _png(tmp_path / "source.png")
    pool = LocalVisualPool(tmp_path / "visual")
    visual_asset = pool.ingest(
        src,
        tier_directory="storyblocks",
        aesthetic_tags=["sierpinski"],
        motion_density=0.2,
    )

    asset = visual_asset.to_broadcast_manifest_asset(source_id="visual-pool-slot-0")

    assert asset.medium == "visual"
    assert asset.source == "visual-pool-slot-0"
    assert asset.token == visual_asset.provenance_token
    assert asset.tier == "tier_1_platform_cleared"
    assert asset.broadcast_safe is True


def test_layout_generated_source_gets_stable_tier_zero_token() -> None:
    source = SourceSchema(id="sierpinski", kind="cairo", backend="cairo")

    first = visual_asset_from_source_schema(source)
    second = visual_asset_from_source_schema(source)

    assert first.token is not None
    assert first.token == second.token
    assert first.tier == "tier_0_owned"
    assert first.broadcast_safe is True


def test_media_like_layout_source_without_provenance_fails_closed() -> None:
    source = SourceSchema(id="browser-video", kind="video", backend="browser")
    asset = visual_asset_from_source_schema(source)
    manifest = build_broadcast_manifest(visual_assets=(asset,))
    gate = EgressManifestGate()

    decision = gate.evaluate(manifest)

    assert asset.token is None
    assert asset.tier == "tier_4_risky"
    assert decision.kill_switch_fired is True
    assert decision.offenders[0].reason == "missing_token"


def test_max_content_risk_env_fails_closed_on_unknown_value() -> None:
    assert max_content_risk_from_env(
        {"HAPAX_BROADCAST_MAX_CONTENT_RISK": "tier_2_provenance_known"}
    ) == ("tier_2_provenance_known")
    assert max_content_risk_from_env({"HAPAX_BROADCAST_MAX_CONTENT_RISK": "tier_99"}) == (
        "tier_1_platform_cleared"
    )

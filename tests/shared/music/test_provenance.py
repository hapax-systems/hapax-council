"""Tests for per-track music provenance schema (ef7b-165 Phase 7).

Pins the five-value Literal contract, broadcast-safety predicate, the
Hapax-pool license allowlist, and the Pydantic record's strict-mode
validation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.music.provenance import (
    HAPAX_POOL_ALLOWED_LICENSES,
    MUSIC_PROVENANCE_INVENTORY,
    RETIRED_MUSIC_PROVENANCE_COMMITMENTS,
    MusicTrackProvenance,
    build_music_provenance_token,
    classify_music_provenance,
    is_broadcast_safe,
    manifest_asset_from_provenance,
    normalize_music_license,
)

# ── broadcast-safety predicate ────────────────────────────────────────


@pytest.mark.parametrize(
    "provenance",
    ["operator-vinyl", "soundcloud-licensed", "hapax-pool"],
)
def test_broadcast_safe_provenances_pass(provenance: str) -> None:
    """The three explicitly-licensed provenance classes broadcast clean."""
    assert is_broadcast_safe(provenance) is True  # type: ignore[arg-type]


@pytest.mark.parametrize("provenance", ["youtube-react", "unknown"])
def test_broadcast_unsafe_provenances_fail_closed(provenance: str) -> None:
    """``youtube-react`` and ``unknown`` are NOT auto-broadcast-safe.

    ``unknown`` fails closed; ``youtube-react`` defers to Phase 8's
    interaction policy (audio mute by default).
    """
    assert is_broadcast_safe(provenance) is False  # type: ignore[arg-type]


def test_broadcast_safe_unknown_is_fail_closed() -> None:
    """Critical safety pin: unknown must NEVER admit to broadcast.

    Operator existential-risk constraint — see ef7b-165 task body.
    """
    assert is_broadcast_safe("unknown") is False


# ── hapax-pool license allowlist ──────────────────────────────────────


def test_hapax_pool_allows_cc_family() -> None:
    assert "cc-by" in HAPAX_POOL_ALLOWED_LICENSES
    assert "cc-by-sa" in HAPAX_POOL_ALLOWED_LICENSES


def test_hapax_pool_allows_public_domain_and_explicit_broadcast() -> None:
    assert "public-domain" in HAPAX_POOL_ALLOWED_LICENSES
    assert "licensed-for-broadcast" in HAPAX_POOL_ALLOWED_LICENSES


def test_hapax_pool_rejects_proprietary_licenses() -> None:
    """Pin: no all-rights-reserved or non-commercial slugs admitted.

    The four allowlisted slugs cover everything Hapax should ingest;
    anything else is excluded. This pin prevents a silent expansion
    of the allowlist without operator review.
    """
    forbidden = {
        "all-rights-reserved",
        "cc-by-nc",
        "cc-by-nc-sa",
        "cc-by-nd",
        "proprietary",
        "unknown",
    }
    assert HAPAX_POOL_ALLOWED_LICENSES.isdisjoint(forbidden)


def test_license_normalization_accepts_allowed_aliases() -> None:
    assert normalize_music_license("CC-BY-4.0") == "cc-by"
    assert normalize_music_license("CC0-1.0") == "public-domain"
    assert normalize_music_license("operator-owned") == "licensed-for-broadcast"


def test_license_normalization_rejects_unknown_or_noncommercial() -> None:
    assert normalize_music_license("CC-BY-NC") is None
    assert normalize_music_license("all-rights-reserved") is None
    assert normalize_music_license(None) is None


def test_soundcloud_operator_adapter_is_explicitly_operator_owned_contract() -> None:
    provenance, license_slug = classify_music_provenance(
        source="soundcloud-oudepode",
        track_id="https://soundcloud.com/oudepode/track",
        license=None,
    )
    assert provenance == "soundcloud-licensed"
    assert license_slug == "licensed-for-broadcast"


def test_non_operator_soundcloud_without_license_fails_unknown() -> None:
    provenance, license_slug = classify_music_provenance(
        source="soundcloud-other",
        track_id="https://soundcloud.com/someone/track",
        license=None,
    )
    assert provenance == "unknown"
    assert license_slug is None


def test_manifest_projection_has_token_and_tier() -> None:
    rec = MusicTrackProvenance(
        track_id="/pool/track.flac",
        provenance="hapax-pool",
        license="cc-by",
        source="hapax-pool:sidecar",
    )
    asset = manifest_asset_from_provenance(
        rec,
        content_risk="tier_3_uncertain",
        broadcast_safe=True,
        source="bandcamp-direct",
    )
    assert asset.token == build_music_provenance_token("/pool/track.flac", "hapax-pool")
    assert asset.tier == "tier_3_uncertain"
    assert asset.music_provenance == "hapax-pool"
    assert asset.broadcast_safe is True


def test_unknown_manifest_projection_missing_token_fails_closed() -> None:
    rec = MusicTrackProvenance(track_id="/pool/track.flac", provenance="unknown")
    asset = manifest_asset_from_provenance(
        rec,
        content_risk="tier_4_risky",
        broadcast_safe=True,
    )
    assert asset.token is None
    assert asset.broadcast_safe is False


def test_inventory_covers_music_provenance_surfaces_and_retirements() -> None:
    inventory = {item.surface: item for item in MUSIC_PROVENANCE_INVENTORY}
    assert set(inventory) == {"soundcloud", "local-pool", "vinyl", "overlay"}
    assert "retired" in inventory["soundcloud"].current_contract
    assert "music-provenance.json" in inventory["overlay"].fields


def test_stale_soundcloud_and_vinyl_commitments_are_explicitly_retired() -> None:
    assert (
        "credential-blocked"
        in RETIRED_MUSIC_PROVENANCE_COMMITMENTS["soundcloud_oauth_me_tracks_license_parser"]
    )
    assert (
        "operator-vinyl only"
        in RETIRED_MUSIC_PROVENANCE_COMMITMENTS["vinyl_per_record_broadcast_license_resolver"]
    )


# ── Pydantic record contract ──────────────────────────────────────────


def test_record_round_trips_with_minimum_fields() -> None:
    rec = MusicTrackProvenance(
        track_id="vinyl:operator/box-1/side-A:track-3",
        provenance="operator-vinyl",
    )
    assert rec.provenance == "operator-vinyl"
    assert rec.license is None
    assert rec.source is None


def test_record_records_license_and_source_for_pool() -> None:
    rec = MusicTrackProvenance(
        track_id="hapax-pool:track-001",
        provenance="hapax-pool",
        license="cc-by",
        source="hapax-pool:cc-by-tagged-on-ingest",
    )
    assert rec.license == "cc-by"
    assert rec.source == "hapax-pool:cc-by-tagged-on-ingest"


def test_record_rejects_unknown_extra_fields() -> None:
    """Strict-mode pin: schema is closed; unknown fields fail validation."""
    with pytest.raises(ValidationError):
        MusicTrackProvenance(
            track_id="x",
            provenance="hapax-pool",
            unknown_field="surprise",  # type: ignore[call-arg]
        )


def test_record_rejects_invalid_provenance_value() -> None:
    with pytest.raises(ValidationError):
        MusicTrackProvenance(
            track_id="x",
            provenance="some-other-value",  # type: ignore[arg-type]
        )


def test_record_ingested_at_is_timezone_aware() -> None:
    rec = MusicTrackProvenance(track_id="x", provenance="hapax-pool")
    assert rec.ingested_at.tzinfo is not None

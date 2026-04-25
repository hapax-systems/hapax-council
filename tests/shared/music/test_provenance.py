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
    MusicTrackProvenance,
    is_broadcast_safe,
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

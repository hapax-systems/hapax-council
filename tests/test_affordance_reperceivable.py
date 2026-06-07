"""Tests for the two-sided affordance (Chiasm Contract reformalization #1, PR-A)."""

from __future__ import annotations

from shared.affordance import CapabilityRecord, OperationalProperties, RePerceivableProperties


def test_domain_accepts_the_four_cns_binding_domains() -> None:
    for d in ("content", "geometry", "both", "drift", "audio", "physics"):
        op = OperationalProperties(domain=d)
        assert op.domain == d


def test_capability_is_expression_only_by_default() -> None:
    # The one-sided affordance is the degenerate two-sided one: re_perceivable defaults None.
    rec = CapabilityRecord(name="x", description="verb", daemon="d")
    assert rec.re_perceivable is None


def test_re_perceivable_surface_carries_the_get_contract() -> None:
    rp = RePerceivableProperties(
        dim_projection=("intensity", "tension", "coherence"),
        readback_source="/dev/shm/hapax-compositor/quake-drift-currency.bgra",
        provenance_ref="shm:quake-drift-currency.bgra@mtime",
    )
    rec = CapabilityRecord(name="drift", description="drifts", daemon="screwm", re_perceivable=rp)
    assert rec.re_perceivable is not None
    assert rec.re_perceivable.dim_projection == ("intensity", "tension", "coherence")
    assert "quake-drift-currency" in rec.re_perceivable.readback_source


def test_records_are_frozen() -> None:
    rp = RePerceivableProperties()
    assert rp.dim_projection == ()
    rec = CapabilityRecord(name="x", description="v", daemon="d")
    try:
        rec.re_perceivable = rp  # type: ignore[misc]
        raise AssertionError("CapabilityRecord should be frozen")
    except Exception:
        pass

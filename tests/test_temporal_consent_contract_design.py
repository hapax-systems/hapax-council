"""Public-API regression pin for the TemporalConsent interval-boundary contract.

Spec: ``docs/superpowers/specs/2026-05-01-temporal-consent-interval-boundary-design.md``.

Asserts the four-relation subset of Allen's interval algebra
(``active_at``, ``before``, ``overlaps``, ``intersect``) plus the
half-open ``[start, end)`` invariant the gate-side reasoning depends on.
A change to the public contract must update this pin in the same PR.

cc-task: ``temporal-consent-contract-interval-boundary-design``.
"""

from __future__ import annotations

import time

import pytest

from shared.governance.temporal import ConsentInterval, TemporalConsent

# ── Half-open invariant ─────────────────────────────────────────────────


class TestHalfOpenInterval:
    def test_active_at_start_inclusive(self) -> None:
        iv = ConsentInterval(start=100.0, end=200.0)
        assert iv.active_at(100.0) is True

    def test_active_at_end_exclusive(self) -> None:
        iv = ConsentInterval(start=100.0, end=200.0)
        assert iv.active_at(200.0) is False

    def test_active_just_before_end(self) -> None:
        iv = ConsentInterval(start=100.0, end=200.0)
        assert iv.active_at(199.999) is True

    def test_active_before_start(self) -> None:
        iv = ConsentInterval(start=100.0, end=200.0)
        assert iv.active_at(99.999) is False

    def test_indefinite_active_far_future(self) -> None:
        iv = ConsentInterval(start=0.0, end=None)
        assert iv.active_at(1e18) is True

    def test_concatenation_covers_each_point_once(self) -> None:
        """[t0,t1) followed by [t1,t2) covers [t0,t2) without overlap."""
        a = ConsentInterval(start=0.0, end=100.0)
        b = ConsentInterval(start=100.0, end=200.0)
        assert a.active_at(99.999) is True
        assert b.active_at(99.999) is False
        assert a.active_at(100.0) is False
        assert b.active_at(100.0) is True


# ── Allen subset ────────────────────────────────────────────────────────


class TestAllenSubset:
    def test_before_disjoint(self) -> None:
        a = ConsentInterval(start=0.0, end=100.0)
        b = ConsentInterval(start=200.0, end=300.0)
        assert a.before(b) is True
        assert b.before(a) is False

    def test_before_at_boundary_due_to_half_open(self) -> None:
        """Half-open: a.end == b.start means a precedes b strictly."""
        a = ConsentInterval(start=0.0, end=100.0)
        b = ConsentInterval(start=100.0, end=200.0)
        assert a.before(b) is True

    def test_indefinite_is_never_before(self) -> None:
        a = ConsentInterval(start=0.0, end=None)
        b = ConsentInterval(start=1000.0, end=2000.0)
        assert a.before(b) is False

    def test_overlaps_disjoint_false(self) -> None:
        a = ConsentInterval(start=0.0, end=100.0)
        b = ConsentInterval(start=100.0, end=200.0)
        assert a.overlaps(b) is False

    def test_overlaps_partial_true(self) -> None:
        a = ConsentInterval(start=0.0, end=150.0)
        b = ConsentInterval(start=100.0, end=200.0)
        assert a.overlaps(b) is True

    def test_intersect_partial(self) -> None:
        a = ConsentInterval(start=0.0, end=150.0)
        b = ConsentInterval(start=100.0, end=200.0)
        result = a.intersect(b)
        assert result is not None
        assert result.start == 100.0
        assert result.end == 150.0

    def test_intersect_disjoint_returns_none(self) -> None:
        a = ConsentInterval(start=0.0, end=100.0)
        b = ConsentInterval(start=100.0, end=200.0)
        assert a.intersect(b) is None

    def test_contains_strict_subset(self) -> None:
        outer = ConsentInterval(start=0.0, end=200.0)
        inner = ConsentInterval(start=50.0, end=150.0)
        assert outer.contains(inner) is True
        assert inner.contains(outer) is False


# ── Renewal / extension semantics ───────────────────────────────────────


class TestRenewalSemantics:
    def test_extend_pushes_end_forward(self) -> None:
        iv = ConsentInterval(start=0.0, end=100.0)
        extended = iv.extend(50.0)
        assert extended.start == 0.0
        assert extended.end == 150.0

    def test_extend_indefinite_is_noop(self) -> None:
        iv = ConsentInterval(start=0.0, end=None)
        assert iv.extend(50.0) is iv

    def test_renew_starts_from_supplied_time(self) -> None:
        iv = ConsentInterval(start=0.0, end=100.0)
        renewed = iv.renew(duration_s=300.0, from_time=500.0)
        assert renewed.start == 500.0
        assert renewed.end == 800.0

    def test_indefinite_constructor(self) -> None:
        iv = ConsentInterval.indefinite(start=42.0)
        assert iv.start == 42.0
        assert iv.end is None

    def test_fixed_constructor_uses_duration(self) -> None:
        iv = ConsentInterval.fixed(duration_s=600.0, start=100.0)
        assert iv.start == 100.0
        assert iv.end == 700.0


# ── Near-expiry warning ─────────────────────────────────────────────────


class TestNearExpiry:
    def test_within_grace_returns_true(self) -> None:
        iv = ConsentInterval(start=0.0, end=1000.0)
        assert iv.near_expiry(grace_s=100.0, t=950.0) is True

    def test_outside_grace_returns_false(self) -> None:
        iv = ConsentInterval(start=0.0, end=1000.0)
        assert iv.near_expiry(grace_s=100.0, t=500.0) is False

    def test_already_expired_still_within_grace(self) -> None:
        """remaining clamps at 0 → near_expiry remains True post-expiry."""
        iv = ConsentInterval(start=0.0, end=1000.0)
        assert iv.near_expiry(grace_s=100.0, t=2000.0) is True

    def test_indefinite_never_near_expiry(self) -> None:
        iv = ConsentInterval(start=0.0, end=None)
        assert iv.near_expiry(grace_s=100.0, t=time.time()) is False


# ── TemporalConsent wrapper ─────────────────────────────────────────────


class TestTemporalConsentWrapper:
    def test_valid_at_delegates_to_interval(self) -> None:
        iv = ConsentInterval(start=0.0, end=100.0)
        consent = TemporalConsent(contract_id="c-1", interval=iv)
        assert consent.valid_at(50.0) is True
        assert consent.valid_at(150.0) is False

    def test_needs_renewal_delegates_to_near_expiry(self) -> None:
        iv = ConsentInterval(start=0.0, end=1000.0)
        consent = TemporalConsent(contract_id="c-1", interval=iv)
        assert consent.needs_renewal(grace_s=100.0, t=950.0) is True
        assert consent.needs_renewal(grace_s=100.0, t=500.0) is False

    def test_carries_optional_person_id(self) -> None:
        iv = ConsentInterval(start=0.0, end=100.0)
        consent = TemporalConsent(contract_id="c-1", interval=iv, person_id="p-1")
        assert consent.person_id == "p-1"

    def test_default_person_id_is_empty(self) -> None:
        iv = ConsentInterval(start=0.0, end=100.0)
        consent = TemporalConsent(contract_id="c-1", interval=iv)
        assert consent.person_id == ""

    def test_frozen_immutable(self) -> None:
        iv = ConsentInterval(start=0.0, end=100.0)
        consent = TemporalConsent(contract_id="c-1", interval=iv)
        with pytest.raises((AttributeError, TypeError)):
            consent.contract_id = "c-2"  # type: ignore[misc]


# ── Out-of-scope guards ─────────────────────────────────────────────────


class TestOutOfScopeGuards:
    """Pins that the contract does NOT grow scope beyond the spec."""

    def test_module_does_not_export_meets(self) -> None:
        """Allen's full algebra is research, not contract — keep it out."""
        import shared.governance.temporal as mod

        assert not hasattr(ConsentInterval, "meets")
        assert not hasattr(ConsentInterval, "during")
        assert not hasattr(ConsentInterval, "starts")
        assert not hasattr(ConsentInterval, "finishes")
        assert "meets" not in dir(mod)

    def test_temporal_consent_carries_no_revocation_field(self) -> None:
        """Manual revocation lives in revocation.py — out of scope here."""
        iv = ConsentInterval(start=0.0, end=100.0)
        consent = TemporalConsent(contract_id="c-1", interval=iv)
        assert not hasattr(consent, "revoked_at")
        assert not hasattr(consent, "revoke")

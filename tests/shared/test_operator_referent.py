"""Tests for shared.operator_referent — equal-weight referent picker."""

from __future__ import annotations

from collections import Counter

from shared.operator_referent import REFERENTS, OperatorReferentPicker


def test_referents_are_exactly_three_canonical_forms() -> None:
    assert REFERENTS == (
        "Oudepode",
        "Oudepode The Operator",
        "OTO",
    )


def test_pick_returns_a_canonical_referent() -> None:
    for _ in range(100):
        assert OperatorReferentPicker.pick() in REFERENTS


def test_pick_with_seed_is_deterministic() -> None:
    for seed in ("foo", "bar", "tick-42", "vod-segment-0xabc", ""):
        first = OperatorReferentPicker.pick(seed)
        for _ in range(10):
            assert OperatorReferentPicker.pick(seed) == first


def test_different_seeds_can_produce_different_referents() -> None:
    # Not guaranteed for any specific pair, but over 100 varied seeds
    # at least two distinct referents must appear — otherwise the
    # distribution is broken.
    results = {OperatorReferentPicker.pick(f"seed-{i}") for i in range(100)}
    assert len(results) >= 2


def test_pick_for_tick_is_deterministic() -> None:
    for tick in (0, 1, 42, 1000, 99999):
        first = OperatorReferentPicker.pick_for_tick(tick)
        for _ in range(10):
            assert OperatorReferentPicker.pick_for_tick(tick) == first


def test_pick_for_tick_varies_across_ticks() -> None:
    seen = {OperatorReferentPicker.pick_for_tick(t) for t in range(50)}
    assert len(seen) >= 2


def test_pick_for_vod_segment_is_deterministic() -> None:
    seg = "2026-04-24T08:00Z-vod-0001"
    first = OperatorReferentPicker.pick_for_vod_segment(seg)
    for _ in range(10):
        assert OperatorReferentPicker.pick_for_vod_segment(seg) == first


def test_equal_weight_distribution_over_ten_thousand_seeds() -> None:
    """SHA-256 mod 3 should be indistinguishable from uniform over N=10_000.

    Each bucket's expected count is ~3333. We allow a generous ±333 (~10%)
    tolerance — this is a smoke test against gross bias, not a χ² proof.
    """
    counts: Counter[str] = Counter(OperatorReferentPicker.pick(f"seed-{i}") for i in range(10_000))
    assert set(counts.keys()) == set(REFERENTS)
    for referent in REFERENTS:
        assert 3000 <= counts[referent] <= 3666, (
            f"{referent}: expected ~3333, got {counts[referent]}"
        )


def test_equal_weight_distribution_over_tick_ids() -> None:
    """Tick ids should also produce uniform distribution — they seed the
    same SHA-256 path with a different prefix, so this checks that the
    prefix doesn't induce bias in the lower 2 bits of the digest.
    """
    counts: Counter[str] = Counter(OperatorReferentPicker.pick_for_tick(i) for i in range(10_000))
    for referent in REFERENTS:
        assert 3000 <= counts[referent] <= 3666


def test_empty_string_seed_is_valid() -> None:
    # Empty seed is deterministic too — same digest every time.
    assert OperatorReferentPicker.pick("") == OperatorReferentPicker.pick("")


def test_unicode_seed_works() -> None:
    # Seeds are UTF-8 encoded before hashing; non-ASCII is fine.
    result = OperatorReferentPicker.pick("ουδέποτε-tick-0")
    assert result in REFERENTS

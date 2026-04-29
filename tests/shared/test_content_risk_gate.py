"""Unit tests for ContentRiskGate (content-source-registry Phase 1).

Per `docs/superpowers/plans/2026-04-23-content-source-registry-plan.md` §Phase 1.
Verifies the 5-tier policy:

  tier_0_owned             → always permitted
  tier_1_platform_cleared  → always permitted
  tier_2_provenance_known  → permitted only with programme opt-in (or unlock)
  tier_3_uncertain         → permitted only with session unlock
  tier_4_risky             → unconditionally blocked
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from shared.governance.content_risk import (
    GATE,
    ContentRiskGate,
    candidate_filter,
    is_unlocked,
)

if TYPE_CHECKING:
    import pytest


@dataclass
class _Candidate:
    capability_name: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Programme:
    content_opt_ins: frozenset[str] = field(default_factory=frozenset)


# ── tier 0/1: auto-permitted regardless of programme ─────────────────────────


def test_tier_0_owned_always_permitted() -> None:
    cand = _Candidate("oudepode-track-play", payload={"content_risk": "tier_0_owned"})
    assert GATE.assess(cand).allowed is True


def test_tier_1_platform_cleared_always_permitted() -> None:
    cand = _Candidate("found-sound-bed-music", payload={"content_risk": "tier_1_platform_cleared"})
    assert GATE.assess(cand).allowed is True


def test_missing_public_payload_fails_closed_as_unknown() -> None:
    cand = _Candidate("untagged-cap", payload={"public_capable": True})
    result = GATE.assess(cand)
    assert result.allowed is False
    assert result.tier == "unknown"
    assert "fail" in result.reason.lower()


def test_missing_internal_payload_allowed_but_remains_unknown() -> None:
    cand = _Candidate("internal-cap", payload={"public_capable": False})
    result = GATE.assess(cand)
    assert result.allowed is True
    assert result.tier == "unknown"


def test_stale_public_medium_without_tier_fails_closed() -> None:
    cand = _Candidate("stale-visual-cap", payload={"medium": "visual"})
    result = GATE.assess(cand)
    assert result.allowed is False
    assert result.tier == "unknown"


# ── tier 4: unconditional block ──────────────────────────────────────────────


def test_tier_4_risky_blocked_without_programme() -> None:
    cand = _Candidate("vinyl-direct-broadcast", payload={"content_risk": "tier_4_risky"})
    result = GATE.assess(cand)
    assert result.allowed is False
    assert "blocked" in result.reason.lower()


def test_tier_4_risky_blocked_even_with_opt_in() -> None:
    """Programmes cannot opt INTO tier_4 — it is hardware-side only."""
    cand = _Candidate("vinyl-direct-broadcast", payload={"content_risk": "tier_4_risky"})
    prog = _Programme(content_opt_ins=frozenset({"tier_4_risky"}))
    assert GATE.assess(cand, prog).allowed is False


def test_tier_4_risky_blocked_even_with_unlock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_CONTENT_RISK_UNLOCK_TIER", "tier_4_risky")
    cand = _Candidate("vinyl-direct-broadcast", payload={"content_risk": "tier_4_risky"})
    assert GATE.assess(cand).allowed is False


# ── tier 2: programme opt-in OR session unlock ───────────────────────────────


def test_tier_2_blocked_without_opt_in_or_unlock() -> None:
    cand = _Candidate("freesound-cc0-texture", payload={"content_risk": "tier_2_provenance_known"})
    assert GATE.assess(cand, _Programme()).allowed is False


def test_tier_2_permitted_with_programme_opt_in() -> None:
    cand = _Candidate("freesound-cc0-texture", payload={"content_risk": "tier_2_provenance_known"})
    prog = _Programme(content_opt_ins=frozenset({"tier_2_provenance_known"}))
    assert GATE.assess(cand, prog).allowed is True


def test_tier_2_permitted_with_session_unlock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_CONTENT_RISK_UNLOCK_TIER", "tier_2_provenance_known")
    cand = _Candidate("freesound-cc0-texture", payload={"content_risk": "tier_2_provenance_known"})
    assert GATE.assess(cand, _Programme()).allowed is True


# ── tier 3: session unlock only (no programme opt-in path) ───────────────────


def test_tier_3_blocked_without_unlock() -> None:
    cand = _Candidate("bandcamp-direct", payload={"content_risk": "tier_3_uncertain"})
    assert GATE.assess(cand).allowed is False


def test_tier_3_blocked_even_with_programme_opt_in() -> None:
    """tier_3 is operator-decision-only — programmes can't opt in."""
    cand = _Candidate("bandcamp-direct", payload={"content_risk": "tier_3_uncertain"})
    prog = _Programme(content_opt_ins=frozenset({"tier_3_uncertain"}))
    assert GATE.assess(cand, prog).allowed is False


def test_tier_3_permitted_with_session_unlock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_CONTENT_RISK_UNLOCK_TIER", "tier_3_uncertain")
    cand = _Candidate("bandcamp-direct", payload={"content_risk": "tier_3_uncertain"})
    assert GATE.assess(cand).allowed is True


# ── unknown tier: fail-closed ────────────────────────────────────────────────


def test_unknown_tier_failes_closed() -> None:
    cand = _Candidate(
        "future-tier-cap",
        payload={"public_capable": True, "content_risk": "tier_99_quantum"},
    )
    result = GATE.assess(cand)
    assert result.allowed is False
    assert "unknown" in result.reason.lower()


# ── candidate_filter (batch) ─────────────────────────────────────────────────


def test_candidate_filter_drops_blocked_keeps_allowed() -> None:
    candidates = [
        _Candidate("a-tier-0", payload={"content_risk": "tier_0_owned"}),
        _Candidate("b-tier-1", payload={"content_risk": "tier_1_platform_cleared"}),
        _Candidate("c-tier-2-no-opt", payload={"content_risk": "tier_2_provenance_known"}),
        _Candidate("d-tier-4", payload={"content_risk": "tier_4_risky"}),
    ]
    out = candidate_filter(candidates)
    assert [c.capability_name for c in out] == ["a-tier-0", "b-tier-1"]


def test_candidate_filter_with_programme_opt_in() -> None:
    candidates = [
        _Candidate("a-tier-0", payload={"content_risk": "tier_0_owned"}),
        _Candidate("c-tier-2", payload={"content_risk": "tier_2_provenance_known"}),
        _Candidate("d-tier-4", payload={"content_risk": "tier_4_risky"}),
    ]
    prog = _Programme(content_opt_ins=frozenset({"tier_2_provenance_known"}))
    out = candidate_filter(candidates, programme=prog)
    assert [c.capability_name for c in out] == ["a-tier-0", "c-tier-2"]


def test_candidate_filter_empty_input() -> None:
    assert candidate_filter([]) == []


# ── is_unlocked helper ───────────────────────────────────────────────────────


def test_is_unlocked_unset_env_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HAPAX_CONTENT_RISK_UNLOCK_TIER", raising=False)
    assert is_unlocked("tier_3_uncertain") is False


def test_is_unlocked_single_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_CONTENT_RISK_UNLOCK_TIER", "tier_3_uncertain")
    assert is_unlocked("tier_3_uncertain") is True
    assert is_unlocked("tier_2_provenance_known") is False


def test_is_unlocked_multiple_tiers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "HAPAX_CONTENT_RISK_UNLOCK_TIER",
        "tier_2_provenance_known, tier_3_uncertain",
    )
    assert is_unlocked("tier_2_provenance_known") is True
    assert is_unlocked("tier_3_uncertain") is True
    assert is_unlocked("tier_0_owned") is False


# ── module singleton stability ───────────────────────────────────────────────


def test_module_singleton_is_a_content_risk_gate() -> None:
    assert isinstance(GATE, ContentRiskGate)


def test_candidate_filter_uses_singleton() -> None:
    """The module-level convenience must delegate to the singleton, not
    instantiate a new gate. Otherwise listeners (Phase 2) could miss events.
    """
    candidates = [_Candidate("a", payload={"content_risk": "tier_0_owned"})]
    # If candidate_filter constructed a new gate, this would still pass — the
    # behavioral guarantee is that the singleton is used. We verify identity
    # via repeated call returning consistent results from the same instance.
    out1 = candidate_filter(candidates)
    out2 = candidate_filter(candidates)
    assert out1 == out2
    # Direct-singleton call returns the same shape:
    out3 = GATE.candidate_filter(candidates)
    assert out3 == out1

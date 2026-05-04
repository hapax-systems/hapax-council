"""Tests for shared.voice_tier — 7-tier voice transformation primitive."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shared.voice_tier import (
    _ROLE_TIER_DEFAULTS,
    TIER_CATALOG,
    TIER_MONETIZATION_RISK,
    TIER_NAMES,
    TIER_RISK_REASONS,
    IntelligibilityBudget,
    RoleTierBand,
    TierProfile,
    VoiceTier,
    all_tier_capability_records,
    apply_tier,
    profile_for,
    resolve_tier,
    role_tier_band,
    stance_tier_delta,
    tier_capability_record,
    tier_from_name,
)


class TestTierEnum:
    def test_seven_tiers(self) -> None:
        assert len(list(VoiceTier)) == 7

    def test_ordinal(self) -> None:
        assert VoiceTier.UNADORNED < VoiceTier.RADIO < VoiceTier.BROADCAST_GHOST
        assert VoiceTier.BROADCAST_GHOST < VoiceTier.MEMORY < VoiceTier.UNDERWATER
        assert VoiceTier.UNDERWATER < VoiceTier.GRANULAR_WASH < VoiceTier.OBLITERATED

    def test_distance(self) -> None:
        assert abs(VoiceTier.RADIO - VoiceTier.UNADORNED) == 1
        assert abs(VoiceTier.OBLITERATED - VoiceTier.UNADORNED) == 6


class TestCatalogShape:
    def test_catalog_covers_all_tiers(self) -> None:
        assert set(TIER_CATALOG.keys()) == set(VoiceTier)

    def test_tier_names_covers_all(self) -> None:
        assert set(TIER_NAMES.keys()) == set(VoiceTier)

    def test_profile_shape(self) -> None:
        for profile in TIER_CATALOG.values():
            assert isinstance(profile, TierProfile)
            assert profile.tier in VoiceTier
            assert 0.0 <= profile.intelligibility_floor <= 1.0
            assert set(profile.dimension_vector.keys()) == {
                "intensity",
                "tension",
                "diffusion",
                "degradation",
                "depth",
                "pitch_displacement",
                "temporal_distortion",
                "spectral_color",
                "coherence",
            }
            for v in profile.dimension_vector.values():
                assert 0.0 <= v <= 1.0


class TestIntelligibilityMonotonic:
    def test_floor_decreases_with_tier(self) -> None:
        """Moving up the tier ladder never increases intelligibility.

        T0 = 1.0, T6 = 0.0; intermediate steps must be monotonically
        non-increasing. This is the load-bearing invariant for the
        budget system — a consumer that assumed "higher tier = lower
        intelligibility" must never be contradicted.
        """
        tiers_ordered = sorted(TIER_CATALOG.values(), key=lambda p: p.tier.value)
        floors = [p.intelligibility_floor for p in tiers_ordered]
        assert floors == sorted(floors, reverse=True)

    def test_unadorned_is_full_intelligibility(self) -> None:
        assert TIER_CATALOG[VoiceTier.UNADORNED].intelligibility_floor == 1.0

    def test_obliterated_is_zero_intelligibility(self) -> None:
        assert TIER_CATALOG[VoiceTier.OBLITERATED].intelligibility_floor == 0.0


class TestMutexAndDurationCap:
    def test_granular_tiers_claim_engine_mutex(self) -> None:
        for tier in (VoiceTier.GRANULAR_WASH, VoiceTier.OBLITERATED):
            assert "evil_pet_granular_engine" in TIER_CATALOG[tier].mutex_groups

    def test_non_granular_tiers_have_no_mutex(self) -> None:
        for tier in (
            VoiceTier.UNADORNED,
            VoiceTier.RADIO,
            VoiceTier.BROADCAST_GHOST,
            VoiceTier.MEMORY,
            VoiceTier.UNDERWATER,
        ):
            assert TIER_CATALOG[tier].mutex_groups == frozenset()

    def test_obliterated_has_duration_cap(self) -> None:
        assert TIER_CATALOG[VoiceTier.OBLITERATED].max_duration_s == 15.0

    def test_non_obliterated_no_duration_cap(self) -> None:
        for tier in VoiceTier:
            if tier != VoiceTier.OBLITERATED:
                assert TIER_CATALOG[tier].max_duration_s is None


class TestProfileFor:
    def test_returns_catalog_entry(self) -> None:
        assert profile_for(VoiceTier.MEMORY) is TIER_CATALOG[VoiceTier.MEMORY]

    def test_raises_on_unknown(self) -> None:
        with pytest.raises(KeyError):
            profile_for(9999)  # type: ignore[arg-type]


class TestVocalChainApplyTier:
    def test_vocal_chain_apply_tier_delegates(self) -> None:
        """VocalChainCapability.apply_tier() uses the shared helper."""
        from agents.hapax_daimonion.vocal_chain import VocalChainCapability

        midi = MagicMock()
        chain = VocalChainCapability(midi_output=midi)
        chain.apply_tier(VoiceTier.BROADCAST_GHOST, route_audio=False)
        # Each dim in the tier vector triggers a _send_dimension_cc call
        # which fires midi.send_cc; expect at least 9 calls.
        assert midi.send_cc.call_count >= 9

    def test_vocal_chain_apply_tier_resets_before_set(self) -> None:
        """Tier application deactivates prior state first."""
        from agents.hapax_daimonion.vocal_chain import VocalChainCapability

        midi = MagicMock()
        chain = VocalChainCapability(midi_output=midi)
        # Prime with a non-tier activation
        import time as _time

        from shared.impingement import Impingement as _Imp
        from shared.impingement import ImpingementType as _ImpType

        imp = _Imp(
            timestamp=_time.time(),
            source="test",
            type=_ImpType.STATISTICAL_DEVIATION,
            strength=1.0,
            content={"metric": "test"},
        )
        chain.activate_dimension("vocal_chain.intensity", imp, 0.9)
        assert chain.get_dimension_level("vocal_chain.intensity") == pytest.approx(0.9)
        chain.apply_tier(VoiceTier.UNADORNED, route_audio=False)
        # UNADORNED zeros every dim
        assert chain.get_dimension_level("vocal_chain.intensity") == 0.0


class TestApplyTier:
    def test_applies_all_nine_dims(self) -> None:
        chain = MagicMock()
        apply_tier(VoiceTier.MEMORY, chain)
        assert chain.activate_dimension.call_count == 9
        # All keys should be prefixed vocal_chain.* at the call site.
        names = [call.args[0] for call in chain.activate_dimension.call_args_list]
        for name in names:
            assert name.startswith("vocal_chain.")

    def test_emits_cc_overrides_when_midi_provided(self) -> None:
        chain = MagicMock()
        midi = MagicMock()
        apply_tier(VoiceTier.GRANULAR_WASH, chain, midi_output=midi)
        # T5 has 2 CC overrides for granular engine engagement
        assert midi.send_cc.call_count == 2

    def test_skips_cc_overrides_without_midi(self) -> None:
        chain = MagicMock()
        apply_tier(VoiceTier.OBLITERATED, chain, midi_output=None)
        # 9 dim activations, 0 CC writes (no midi)
        assert chain.activate_dimension.call_count == 9

    def test_unadorned_zeros_all_dims(self) -> None:
        chain = MagicMock()
        apply_tier(VoiceTier.UNADORNED, chain)
        for call in chain.activate_dimension.call_args_list:
            # Third positional or 'level' kwarg
            level = call.kwargs.get("level", call.args[2] if len(call.args) > 2 else None)
            assert level == 0.0


class TestRoleTierBand:
    """§2 of 2026-04-20-voice-tier-director-integration.md — per-role bands."""

    def test_all_programme_roles_covered(self) -> None:
        """Every ProgrammeRole value has a default band entry.

        This is the load-bearing invariant: ``role_tier_band`` raises
        ``KeyError`` on a missing role, so a new ProgrammeRole shipped
        without a corresponding ``_ROLE_TIER_DEFAULTS`` entry would
        crash the structural director the first time the role is
        active. The assertion is open-ended (every role, not a fixed
        count) so the count-of-roles can change with new content
        formats without forcing an unrelated test edit.
        """
        from shared.programme import ProgrammeRole

        for role in ProgrammeRole:
            assert role.value in _ROLE_TIER_DEFAULTS

    def test_all_seven_tiers_appear_somewhere(self) -> None:
        """§2.1 coverage check — no tier is unused by the role map."""
        tiers_seen: set[VoiceTier] = set()
        for band in _ROLE_TIER_DEFAULTS.values():
            low, high = band.default_band
            for t in VoiceTier:
                if int(low) <= int(t) <= int(high):
                    tiers_seen.add(t)
            tiers_seen |= band.excursion_set
        assert tiers_seen == set(VoiceTier)

    def test_bands_well_ordered(self) -> None:
        for band in _ROLE_TIER_DEFAULTS.values():
            assert int(band.default_band[0]) <= int(band.default_band[1])

    def test_role_tier_band_accepts_enum_and_string(self) -> None:
        from shared.programme import ProgrammeRole

        by_enum = role_tier_band(ProgrammeRole.TUTORIAL)
        by_str = role_tier_band("tutorial")
        assert by_enum is by_str
        assert isinstance(by_enum, RoleTierBand)

    def test_role_tier_band_raises_on_unknown(self) -> None:
        with pytest.raises(KeyError):
            role_tier_band("not-a-role")

    def test_tutorial_locked_to_t0(self) -> None:
        """TUTORIAL: default band = T0 only; excursion T1 only."""
        band = role_tier_band("tutorial")
        assert band.default_band == (VoiceTier.UNADORNED, VoiceTier.UNADORNED)
        assert band.excursion_set == frozenset({VoiceTier.RADIO})

    def test_ritual_is_non_contiguous(self) -> None:
        """RITUAL: anchor at T0, markers at T5/T6 — no middle band."""
        band = role_tier_band("ritual")
        assert band.default_band == (VoiceTier.UNADORNED, VoiceTier.UNADORNED)
        assert band.excursion_set == frozenset({VoiceTier.GRANULAR_WASH, VoiceTier.OBLITERATED})

    def test_ambient_has_no_excursions(self) -> None:
        """AMBIENT must not abruptly wake the room — no excursions."""
        assert role_tier_band("ambient").excursion_set == frozenset()

    def test_experiment_spans_all_tiers(self) -> None:
        """EXPERIMENT: structural director free across full ladder."""
        band = role_tier_band("experiment")
        assert band.default_band == (VoiceTier.UNADORNED, VoiceTier.OBLITERATED)


class TestStanceTierDelta:
    def test_seeking_biases_up(self) -> None:
        assert stance_tier_delta("seeking") == 1

    def test_nominal_zero(self) -> None:
        assert stance_tier_delta("nominal") == 0

    def test_cautious_zero(self) -> None:
        assert stance_tier_delta("cautious") == 0

    def test_degraded_returns_zero_delta(self) -> None:
        """DEGRADED is handled by resolve_tier's cap, not additive delta."""
        assert stance_tier_delta("degraded") == 0

    def test_critical_returns_zero_delta(self) -> None:
        """CRITICAL is handled by resolve_tier's clamp, not additive delta."""
        assert stance_tier_delta("critical") == 0

    def test_accepts_enum(self) -> None:
        from shared.stimmung import Stance

        assert stance_tier_delta(Stance.SEEKING) == 1
        assert stance_tier_delta(Stance.NOMINAL) == 0


class TestResolveTier:
    """§3 + §3.2 — stance × band resolver."""

    def test_nominal_picks_baseline(self) -> None:
        """NOMINAL + listening (band 0–2) → baseline = ceil((0+2)/2) = 1."""
        result = resolve_tier("listening", "nominal")
        assert result == VoiceTier.RADIO

    def test_seeking_biases_up_within_band(self) -> None:
        """SEEKING +1 from baseline 1 → tier 2, still in band (0..2)."""
        result = resolve_tier("listening", "seeking")
        assert result == VoiceTier.BROADCAST_GHOST

    def test_seeking_clamped_to_band_high(self) -> None:
        """SEEKING cannot push past band_high."""
        # Tutorial band is (0, 0), baseline 0, SEEKING +1 → clamps to 0.
        result = resolve_tier("tutorial", "seeking")
        assert result == VoiceTier.UNADORNED

    def test_critical_clamps_to_band_low(self) -> None:
        """CRITICAL → band_low regardless of role band."""
        # Hothouse_pressure band (3,5). CRITICAL forces band_low = 3.
        assert resolve_tier("hothouse_pressure", "critical") == VoiceTier.MEMORY
        # Tutorial band (0,0). CRITICAL also 0.
        assert resolve_tier("tutorial", "critical") == VoiceTier.UNADORNED

    def test_degraded_caps_at_tier_3(self) -> None:
        """DEGRADED caps at min(band_high, TIER_MEMORY)."""
        # Experiment band (0,6). DEGRADED cap min(6,3) = MEMORY.
        assert resolve_tier("experiment", "degraded") == VoiceTier.MEMORY
        # Listening band (0,2). DEGRADED cap min(2,3) = 2.
        assert resolve_tier("listening", "degraded") == VoiceTier.BROADCAST_GHOST

    def test_degraded_band_low_above_three_clamps_to_low(self) -> None:
        """If band_low > TIER_MEMORY, DEGRADED clamps to band_low."""
        # Synthetic band (4,6). DEGRADED would normally cap at 3 but
        # band_low=4 > 3, so we clamp to band_low.
        result = resolve_tier(
            "experiment",
            "degraded",
            programme_band_prior=(VoiceTier.UNDERWATER, VoiceTier.OBLITERATED),
        )
        assert result == VoiceTier.UNDERWATER

    def test_programme_override_overrides_role(self) -> None:
        """An explicit programme band prior overrides the role default."""
        # Tutorial would normally return T0 for nominal; override band
        # to (3,5) shifts baseline to 4.
        result = resolve_tier(
            "tutorial",
            "nominal",
            programme_band_prior=(VoiceTier.MEMORY, VoiceTier.GRANULAR_WASH),
        )
        assert result == VoiceTier.UNDERWATER

    def test_programme_override_rejects_inverted_band(self) -> None:
        with pytest.raises(ValueError, match="low must be"):
            resolve_tier(
                "tutorial",
                "nominal",
                programme_band_prior=(VoiceTier.MEMORY, VoiceTier.RADIO),
            )

    def test_accepts_enum_inputs(self) -> None:
        from shared.programme import ProgrammeRole
        from shared.stimmung import Stance

        result = resolve_tier(ProgrammeRole.LISTENING, Stance.NOMINAL)
        assert result == VoiceTier.RADIO

    def test_ritual_steady_tick_returns_anchor(self) -> None:
        """RITUAL: steady tick lands on the T0 anchor, not the T5-6 marker.

        Excursion to marker happens via a separate code path (§4.2), not
        via the resolver.
        """
        assert resolve_tier("ritual", "nominal") == VoiceTier.UNADORNED
        assert resolve_tier("ritual", "seeking") == VoiceTier.UNADORNED


class TestProgrammeVoiceTierBandPrior:
    """Programme envelope field validator for voice_tier_band_prior."""

    def test_accepts_well_ordered_tuple(self) -> None:
        from shared.programme import ProgrammeConstraintEnvelope

        env = ProgrammeConstraintEnvelope(voice_tier_band_prior=(1, 3))
        assert env.voice_tier_band_prior == (1, 3)

    def test_accepts_equal_bounds(self) -> None:
        from shared.programme import ProgrammeConstraintEnvelope

        env = ProgrammeConstraintEnvelope(voice_tier_band_prior=(2, 2))
        assert env.voice_tier_band_prior == (2, 2)

    def test_rejects_inverted(self) -> None:
        from pydantic import ValidationError

        from shared.programme import ProgrammeConstraintEnvelope

        with pytest.raises(ValidationError, match="low .* must be"):
            ProgrammeConstraintEnvelope(voice_tier_band_prior=(4, 1))

    def test_rejects_out_of_range(self) -> None:
        from pydantic import ValidationError

        from shared.programme import ProgrammeConstraintEnvelope

        with pytest.raises(ValidationError, match="0..6"):
            ProgrammeConstraintEnvelope(voice_tier_band_prior=(0, 7))

    def test_none_default(self) -> None:
        from shared.programme import ProgrammeConstraintEnvelope

        env = ProgrammeConstraintEnvelope()
        assert env.voice_tier_band_prior is None


class TestTierMonetizationRisk:
    """Phase 4: per-tier monetization classification."""

    def test_covers_all_tiers(self) -> None:
        assert set(TIER_MONETIZATION_RISK.keys()) == set(VoiceTier)
        assert set(TIER_RISK_REASONS.keys()) == set(VoiceTier)

    def test_risk_levels_monotonic_non_decreasing(self) -> None:
        """Moving up the tier ladder never lowers monetization risk."""
        rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
        tiers_ordered = sorted(VoiceTier)
        ranks = [rank[TIER_MONETIZATION_RISK[t]] for t in tiers_ordered]
        assert ranks == sorted(ranks)

    def test_t6_is_high_risk(self) -> None:
        assert TIER_MONETIZATION_RISK[VoiceTier.OBLITERATED] == "high"

    def test_t5_is_medium(self) -> None:
        """Granular wash needs Programme opt-in at the gate."""
        assert TIER_MONETIZATION_RISK[VoiceTier.GRANULAR_WASH] == "medium"

    def test_clear_tiers_have_no_risk_reason(self) -> None:
        for tier in (
            VoiceTier.UNADORNED,
            VoiceTier.RADIO,
            VoiceTier.BROADCAST_GHOST,
            VoiceTier.MEMORY,
        ):
            assert TIER_RISK_REASONS[tier] == ""


class TestTierCapabilityRecord:
    """Phase 4: CapabilityRecord adapter for pipeline registration."""

    def test_all_seven_records_returned(self) -> None:
        records = all_tier_capability_records()
        assert len(records) == 7
        names = {r.name for r in records}
        assert names == {f"voice.tier.{TIER_NAMES[t].replace('-', '_')}" for t in VoiceTier}

    def test_record_names_use_underscore_form(self) -> None:
        """Dashed canonical names become underscores for pipeline keys."""
        record = tier_capability_record(VoiceTier.BROADCAST_GHOST)
        assert record.name == "voice.tier.broadcast_ghost"
        record = tier_capability_record(VoiceTier.GRANULAR_WASH)
        assert record.name == "voice.tier.granular_wash"

    def test_operational_medium_is_auditory(self) -> None:
        for tier in VoiceTier:
            record = tier_capability_record(tier)
            assert record.operational.medium == "auditory"

    def test_operational_consent_not_required(self) -> None:
        """Voice tier gates emission modality, not consent-scoped capture."""
        for tier in VoiceTier:
            assert tier_capability_record(tier).operational.consent_required is False

    def test_monetization_risk_flows_through(self) -> None:
        for tier in VoiceTier:
            record = tier_capability_record(tier)
            assert record.operational.monetization_risk == TIER_MONETIZATION_RISK[tier]

    def test_risk_reason_present_for_risky_tiers(self) -> None:
        assert tier_capability_record(VoiceTier.UNADORNED).operational.risk_reason is None
        assert tier_capability_record(VoiceTier.OBLITERATED).operational.risk_reason is not None

    def test_daemon_is_daimonion(self) -> None:
        for tier in VoiceTier:
            assert tier_capability_record(tier).daemon == "hapax-daimonion"

    def test_gate_assessment_matches_risk(self) -> None:
        """Spot-check that MonetizationRiskGate blocks T6 and gates T5."""
        from shared.governance.monetization_safety import GATE, RiskAssessment

        class _Candidate:
            def __init__(self, name: str, risk: str, reason: str | None) -> None:
                self.capability_name = name
                self.payload = {"monetization_risk": risk}
                if reason is not None:
                    self.payload["risk_reason"] = reason

        # T6 — high → blocked.
        rec = tier_capability_record(VoiceTier.OBLITERATED)
        cand = _Candidate(rec.name, rec.operational.monetization_risk, rec.operational.risk_reason)
        assessment: RiskAssessment = GATE.assess(cand)
        assert assessment.allowed is False
        assert assessment.risk == "high"

        # T5 — medium with no programme → blocked (needs opt-in).
        rec = tier_capability_record(VoiceTier.GRANULAR_WASH)
        cand = _Candidate(rec.name, rec.operational.monetization_risk, rec.operational.risk_reason)
        assert GATE.assess(cand).allowed is False

        # T0 — none → allowed.
        rec = tier_capability_record(VoiceTier.UNADORNED)
        cand = _Candidate(rec.name, rec.operational.monetization_risk, rec.operational.risk_reason)
        assert GATE.assess(cand).allowed is True


class TestIntelligibilityBudget:
    """Phase 4: rolling-window unintelligibility cap."""

    def test_empty_budget_is_full(self) -> None:
        b = IntelligibilityBudget(budget_units=3.0)
        assert b.remaining(now=100.0) == 3.0
        assert b.consumed(now=100.0) == 0.0

    def test_recording_unadorned_consumes_zero(self) -> None:
        b = IntelligibilityBudget()
        b.record(0.0, 60.0, VoiceTier.UNADORNED)
        assert b.consumed(now=60.0) == 0.0

    def test_recording_obliterated_full_rate(self) -> None:
        """T6 floor=0.0 so loss=1.0/min; 60 s = 1 unit-min consumed."""
        b = IntelligibilityBudget()
        b.record(0.0, 60.0, VoiceTier.OBLITERATED)
        assert b.consumed(now=60.0) == pytest.approx(1.0)

    def test_recording_underwater_partial_rate(self) -> None:
        """T4 floor=0.40 so loss=0.60/min; 60 s = 0.6 unit-min consumed."""
        b = IntelligibilityBudget()
        b.record(0.0, 60.0, VoiceTier.UNDERWATER)
        assert b.consumed(now=60.0) == pytest.approx(0.6)

    def test_rolling_window_excludes_old_spans(self) -> None:
        """Spans older than window_s don't count toward consumed."""
        b = IntelligibilityBudget(window_s=600.0)
        b.record(0.0, 60.0, VoiceTier.OBLITERATED)
        # 1 hour later, the span is outside the 10-min window.
        assert b.consumed(now=3600.0) == 0.0

    def test_pick_allowed_true_when_budget_remains(self) -> None:
        b = IntelligibilityBudget(budget_units=3.0, lookahead_s=15.0)
        assert b.pick_allowed(VoiceTier.GRANULAR_WASH, now=100.0) is True

    def test_pick_allowed_false_when_exhausted(self) -> None:
        b = IntelligibilityBudget(budget_units=0.5, lookahead_s=15.0)
        b.record(0.0, 120.0, VoiceTier.OBLITERATED)  # consumes 2.0 unit-min
        assert b.pick_allowed(VoiceTier.OBLITERATED, now=120.0) is False

    def test_clamp_tier_downshifts_when_budget_tight(self) -> None:
        """When budget can't fit T6 lookahead, clamp_tier drops down."""
        b = IntelligibilityBudget(budget_units=0.2, lookahead_s=15.0)
        b.record(0.0, 60.0, VoiceTier.OBLITERATED)  # consumes 1.0
        # Budget is now 0.0; clamp must drop all the way to UNADORNED.
        clamped = b.clamp_tier(VoiceTier.OBLITERATED, now=60.0)
        assert clamped == VoiceTier.UNADORNED

    def test_clamp_tier_noop_when_budget_ample(self) -> None:
        b = IntelligibilityBudget(budget_units=10.0)
        assert b.clamp_tier(VoiceTier.MEMORY, now=100.0) == VoiceTier.MEMORY

    def test_unadorned_always_allowed(self) -> None:
        """Even empty budget permits UNADORNED — there's no loss to spend."""
        b = IntelligibilityBudget(budget_units=0.0)
        assert b.pick_allowed(VoiceTier.UNADORNED, now=100.0) is True
        assert b.clamp_tier(VoiceTier.OBLITERATED, now=100.0) == VoiceTier.UNADORNED

    def test_record_rejects_inverted_span(self) -> None:
        b = IntelligibilityBudget()
        with pytest.raises(ValueError, match="end_ts"):
            b.record(100.0, 50.0, VoiceTier.MEMORY)

    def test_to_dict_roundtrip(self) -> None:
        """Serialised budget reconstructs losslessly."""
        b = IntelligibilityBudget(window_s=300.0, budget_units=1.5, lookahead_s=10.0)
        b.record(0.0, 30.0, VoiceTier.MEMORY)
        b.record(60.0, 90.0, VoiceTier.UNDERWATER)
        data = b.to_dict()
        reloaded = IntelligibilityBudget.from_dict(data)
        assert reloaded.window_s == 300.0
        assert reloaded.budget_units == 1.5
        assert reloaded.lookahead_s == 10.0
        # Consumed() matches before and after round-trip.
        assert reloaded.consumed(now=100.0) == pytest.approx(b.consumed(now=100.0))

    def test_save_and_load(self, tmp_path: Path) -> None:
        """Atomic write + load yields an equivalent budget."""
        from shared.voice_tier import VoiceTier as _VT

        b = IntelligibilityBudget()
        b.record(0.0, 60.0, _VT.GRANULAR_WASH)
        path = tmp_path / "intelligibility.json"
        b.save(path)
        loaded = IntelligibilityBudget.load(path)
        assert loaded.consumed(now=60.0) == pytest.approx(b.consumed(now=60.0))

    def test_load_missing_file_returns_fresh(self, tmp_path: Path) -> None:
        path = tmp_path / "nonexistent.json"
        loaded = IntelligibilityBudget.load(path)
        assert loaded.consumed(now=100.0) == 0.0
        assert loaded.budget_units == 3.0  # default

    def test_load_corrupt_file_returns_fresh(self, tmp_path: Path) -> None:
        path = tmp_path / "corrupt.json"
        path.write_text("{not valid json")
        loaded = IntelligibilityBudget.load(path)
        assert loaded.consumed(now=100.0) == 0.0

    def test_load_non_dict_returns_fresh(self, tmp_path: Path) -> None:
        """Top-level array (wrong shape) doesn't crash."""
        path = tmp_path / "wrong-shape.json"
        path.write_text("[1, 2, 3]")
        loaded = IntelligibilityBudget.load(path)
        assert loaded.budget_units == 3.0

    def test_from_dict_drops_malformed_spans(self) -> None:
        """Corrupt span entries are filtered without rejecting the whole budget."""
        data = {
            "window_s": 600.0,
            "budget_units": 3.0,
            "lookahead_s": 15.0,
            "spans": [
                [0.0, 60.0, 3],  # valid
                "garbage",  # dropped
                [0.0, 60.0, 99],  # tier out of range, dropped
                [100.0, 50.0, 3],  # inverted, dropped
                [0.0, 60.0],  # wrong length, dropped
                [30.0, 90.0, 4],  # valid
            ],
        }
        budget = IntelligibilityBudget.from_dict(data)
        assert len(budget._spans) == 2


class TestTierFromName:
    def test_canonical_names(self) -> None:
        assert tier_from_name("unadorned") == VoiceTier.UNADORNED
        assert tier_from_name("radio") == VoiceTier.RADIO
        assert tier_from_name("broadcast-ghost") == VoiceTier.BROADCAST_GHOST
        assert tier_from_name("memory") == VoiceTier.MEMORY
        assert tier_from_name("underwater") == VoiceTier.UNDERWATER
        assert tier_from_name("granular-wash") == VoiceTier.GRANULAR_WASH
        assert tier_from_name("obliterated") == VoiceTier.OBLITERATED

    def test_tN_aliases(self) -> None:
        assert tier_from_name("t0") == VoiceTier.UNADORNED
        assert tier_from_name("T6") == VoiceTier.OBLITERATED
        assert tier_from_name("t3") == VoiceTier.MEMORY

    def test_underscore_variant(self) -> None:
        assert tier_from_name("broadcast_ghost") == VoiceTier.BROADCAST_GHOST
        assert tier_from_name("granular_wash") == VoiceTier.GRANULAR_WASH

    def test_case_insensitive(self) -> None:
        assert tier_from_name("MEMORY") == VoiceTier.MEMORY
        assert tier_from_name("Radio") == VoiceTier.RADIO

    def test_aliases(self) -> None:
        assert tier_from_name("clear") == VoiceTier.UNADORNED
        assert tier_from_name("max") == VoiceTier.OBLITERATED
        assert tier_from_name("full") == VoiceTier.OBLITERATED
        assert tier_from_name("granular") == VoiceTier.GRANULAR_WASH

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown voice tier"):
            tier_from_name("loud")

"""Tests for shared.programme — Programme primitive with soft-prior envelope.

Architectural axiom: programmes EXPAND grounding opportunities, never
REPLACE them. The Pydantic validators reject zero-bias (hard gate) at
instantiation so no downstream consumer can smuggle in a hard exclusion.
"""

from __future__ import annotations

import pytest

from shared.programme import (
    Programme,
    ProgrammeConstraintEnvelope,
    ProgrammeContent,
    ProgrammeDisplayDensity,
    ProgrammeRitual,
    ProgrammeRole,
    ProgrammeStatus,
    ProgrammeSuccessCriteria,
)
from shared.voice_tier import _ROLE_TIER_DEFAULTS

# Phase 1 vocabulary — operator-context programmes (12 roles).
_PHASE_1_ROLES: frozenset[str] = frozenset(
    {
        "listening",
        "showcase",
        "ritual",
        "interlude",
        "work_block",
        "tutorial",
        "wind_down",
        "hothouse_pressure",
        "ambient",
        "experiment",
        "repair",
        "invitation",
    }
)

# Segmented-content formats — operator outcome 2 (auto-programmed
# segmented content). Seven added in
# cc-task `segmented-content-formats-expansion` (2026-05-04).
_SEGMENTED_CONTENT_ROLES: frozenset[str] = frozenset(
    {
        "tier_list",
        "top_10",
        "rant",
        "react",
        "iceberg",
        "interview",
        "lecture",
    }
)


class TestProgrammeRole:
    def test_role_count_phase_1_plus_segmented(self) -> None:
        assert len(list(ProgrammeRole)) == 19

    def test_phase_1_roles_present(self) -> None:
        values = {r.value for r in ProgrammeRole}
        assert values >= _PHASE_1_ROLES

    def test_segmented_content_roles_present(self) -> None:
        """Operator outcome 2 — auto-programmed segmented content."""
        values = {r.value for r in ProgrammeRole}
        assert values >= _SEGMENTED_CONTENT_ROLES

    def test_segmented_content_role_names_match_snake_case(self) -> None:
        """Each new segmented-content role's str value is snake_case."""
        assert ProgrammeRole.TIER_LIST.value == "tier_list"
        assert ProgrammeRole.TOP_10.value == "top_10"
        assert ProgrammeRole.RANT.value == "rant"
        assert ProgrammeRole.REACT.value == "react"
        assert ProgrammeRole.ICEBERG.value == "iceberg"
        assert ProgrammeRole.INTERVIEW.value == "interview"
        assert ProgrammeRole.LECTURE.value == "lecture"

    def test_no_duplicate_role_values(self) -> None:
        values = [r.value for r in ProgrammeRole]
        assert len(values) == len(set(values))

    def test_roles_match_phase_1_plus_segmented_set(self) -> None:
        assert {r.value for r in ProgrammeRole} == _PHASE_1_ROLES | _SEGMENTED_CONTENT_ROLES

    def test_segmented_content_roles_have_tier_band_defaults(self) -> None:
        """Each new role must have a _ROLE_TIER_DEFAULTS entry so the
        voice-tier resolver does not raise KeyError when the structural
        director picks a tier under a segmented-content programme."""
        for value in _SEGMENTED_CONTENT_ROLES:
            assert value in _ROLE_TIER_DEFAULTS, (
                f"ProgrammeRole {value!r} missing from _ROLE_TIER_DEFAULTS"
            )


class TestProgrammeStatus:
    def test_four_statuses(self) -> None:
        assert {s.value for s in ProgrammeStatus} == {
            "pending",
            "active",
            "completed",
            "aborted",
        }


class TestConstraintEnvelopeSoftPriors:
    def test_empty_envelope_allowed(self) -> None:
        env = ProgrammeConstraintEnvelope()
        assert env.capability_bias_negative == {}
        assert env.capability_bias_positive == {}

    def test_negative_bias_accepted_in_unit_interval(self) -> None:
        env = ProgrammeConstraintEnvelope(capability_bias_negative={"cam.eyes": 0.25})
        assert env.capability_bias_negative == {"cam.eyes": 0.25}

    def test_zero_negative_bias_rejected_as_hard_gate(self) -> None:
        with pytest.raises(ValueError, match="must be in"):
            ProgrammeConstraintEnvelope(capability_bias_negative={"banned_cap": 0.0})

    def test_negative_negative_bias_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProgrammeConstraintEnvelope(capability_bias_negative={"cap": -0.1})

    def test_negative_bias_above_one_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProgrammeConstraintEnvelope(capability_bias_negative={"cap": 1.5})

    def test_positive_bias_accepted_at_one_or_above(self) -> None:
        env = ProgrammeConstraintEnvelope(capability_bias_positive={"favorite": 1.0})
        assert env.capability_bias_positive == {"favorite": 1.0}

    def test_positive_bias_below_one_rejected(self) -> None:
        with pytest.raises(ValueError, match=">= 1.0"):
            ProgrammeConstraintEnvelope(capability_bias_positive={"cap": 0.9})

    def test_infinity_bias_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProgrammeConstraintEnvelope(capability_bias_positive={"cap": float("inf")})

    def test_positive_bias_accepted_up_to_five(self) -> None:
        """Audit B3 / Medium #18: positive bias clamped to [1.0, 5.0]."""
        env = ProgrammeConstraintEnvelope(capability_bias_positive={"strong": 5.0})
        assert env.capability_bias_positive == {"strong": 5.0}

    def test_positive_bias_above_five_rejected(self) -> None:
        """Audit B3 / Medium #18: 5.1× saturates the score and reduces
        the soft prior to a de-facto whitelist."""
        with pytest.raises(ValueError, match="<= 5.0"):
            ProgrammeConstraintEnvelope(capability_bias_positive={"saturating": 5.1})

    def test_positive_bias_far_above_five_rejected(self) -> None:
        with pytest.raises(ValueError, match="<= 5.0"):
            ProgrammeConstraintEnvelope(capability_bias_positive={"saturating": 1000.0})


class TestConstraintEnvelopeOtherPriors:
    def test_ward_emphasis_rate_non_negative(self) -> None:
        ProgrammeConstraintEnvelope(ward_emphasis_target_rate_per_min=0.0)
        ProgrammeConstraintEnvelope(ward_emphasis_target_rate_per_min=12.0)
        with pytest.raises(ValueError):
            ProgrammeConstraintEnvelope(ward_emphasis_target_rate_per_min=-1.0)

    def test_cadence_priors_must_be_positive_seconds(self) -> None:
        ProgrammeConstraintEnvelope(narrative_cadence_prior_s=30.0)
        with pytest.raises(ValueError):
            ProgrammeConstraintEnvelope(narrative_cadence_prior_s=0.0)
        with pytest.raises(ValueError):
            ProgrammeConstraintEnvelope(structural_cadence_prior_s=-5.0)

    def test_unit_interval_priors(self) -> None:
        ProgrammeConstraintEnvelope(surface_threshold_prior=0.35)
        ProgrammeConstraintEnvelope(reverie_saturation_target=1.0)
        with pytest.raises(ValueError):
            ProgrammeConstraintEnvelope(surface_threshold_prior=1.1)
        with pytest.raises(ValueError):
            ProgrammeConstraintEnvelope(reverie_saturation_target=-0.01)

    def test_display_density_accepted(self) -> None:
        env = ProgrammeConstraintEnvelope(display_density=ProgrammeDisplayDensity.SPARSE)
        assert env.display_density is ProgrammeDisplayDensity.SPARSE

    def test_preset_family_priors_literal(self) -> None:
        env = ProgrammeConstraintEnvelope(preset_family_priors=["calm-textural", "warm-minimal"])
        assert env.preset_family_priors == ["calm-textural", "warm-minimal"]


class TestBiasComposition:
    def test_default_multiplier_is_unity(self) -> None:
        env = ProgrammeConstraintEnvelope()
        assert env.bias_multiplier("anything") == 1.0

    def test_positive_only(self) -> None:
        env = ProgrammeConstraintEnvelope(capability_bias_positive={"favorite": 3.0})
        assert env.bias_multiplier("favorite") == 3.0

    def test_negative_only(self) -> None:
        env = ProgrammeConstraintEnvelope(capability_bias_negative={"quiet": 0.25})
        assert env.bias_multiplier("quiet") == 0.25

    def test_positive_and_negative_compose_multiplicatively(self) -> None:
        env = ProgrammeConstraintEnvelope(
            capability_bias_positive={"cap": 4.0},
            capability_bias_negative={"cap": 0.5},
        )
        assert env.bias_multiplier("cap") == 2.0

    def test_expands_candidate_set_always_true(self) -> None:
        """The architectural axiom: no envelope can strictly exclude a capability."""
        env = ProgrammeConstraintEnvelope(
            capability_bias_negative={"rarely_used": 0.01},
            # Audit B3 / Medium #18: positive bias clamped to [1.0, 5.0]; use
            # 5.0 as the strongest legal preference.
            capability_bias_positive={"preferred": 5.0},
        )
        assert env.expands_candidate_set("rarely_used") is True
        assert env.expands_candidate_set("preferred") is True
        assert env.expands_candidate_set("not_mentioned") is True


class TestProgrammeContent:
    def test_empty_content_ok(self) -> None:
        c = ProgrammeContent()
        assert c.music_track_ids == []
        assert c.narrative_beat is None

    def test_narrative_beat_stripped(self) -> None:
        c = ProgrammeContent(narrative_beat="  direction here  ")
        assert c.narrative_beat == "direction here"

    def test_narrative_beat_whitespace_coerced_to_none(self) -> None:
        c = ProgrammeContent(narrative_beat="    ")
        assert c.narrative_beat is None

    def test_narrative_beat_overlong_rejected(self) -> None:
        """500-char cap prevents scripted utterances from sneaking in."""
        with pytest.raises(ValueError, match="not a scripted utterance"):
            ProgrammeContent(narrative_beat="x" * 501)

    def test_responsible_hosting_rejects_executable_segment_cues(self) -> None:
        with pytest.raises(ValueError, match="executable segment_cues"):
            ProgrammeContent(
                hosting_context="hapax_responsible_live",
                segment_cues=["camera.hero tight"],
            )

    def test_layout_intents_cannot_mix_with_legacy_segment_cues(self) -> None:
        with pytest.raises(ValueError, match="cannot mix"):
            ProgrammeContent(
                segment_cues=["legacy cue"],
                beat_layout_intents=[
                    {
                        "beat_id": "hook",
                        "needs": ["evidence_visible"],
                    }
                ],
            )


class TestProgrammeRitual:
    def test_default_boundary_freeze(self) -> None:
        r = ProgrammeRitual()
        assert r.boundary_freeze_s == 4.0

    def test_boundary_freeze_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProgrammeRitual(boundary_freeze_s=-1.0)

    def test_boundary_freeze_above_cap_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProgrammeRitual(boundary_freeze_s=31.0)


class TestProgrammeSuccessCriteria:
    def test_durations_default(self) -> None:
        # Defaults shifted to a 10-min floor / 2-hour cap (operator
        # hard requirement; segments target ~1 hour).
        s = ProgrammeSuccessCriteria()
        assert s.min_duration_s == 600.0
        assert s.max_duration_s == 7200.0

    def test_min_cannot_exceed_max(self) -> None:
        with pytest.raises(ValueError, match="min_duration_s"):
            ProgrammeSuccessCriteria(min_duration_s=600, max_duration_s=300)

    def test_negative_durations_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProgrammeSuccessCriteria(max_duration_s=-1.0)


class TestProgramme:
    def _minimal_kwargs(self) -> dict[str, object]:
        return {
            "programme_id": "show-1:prog-1",
            "role": ProgrammeRole.LISTENING,
            "planned_duration_s": 600.0,
            "parent_show_id": "show-1",
        }

    def test_minimal_programme_constructs(self) -> None:
        p = Programme(**self._minimal_kwargs())
        assert p.status is ProgrammeStatus.PENDING
        assert p.elapsed_s is None

    def test_empty_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            Programme(**(self._minimal_kwargs() | {"programme_id": "   "}))
        with pytest.raises(ValueError):
            Programme(**(self._minimal_kwargs() | {"parent_show_id": ""}))

    def test_planned_duration_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            Programme(**(self._minimal_kwargs() | {"planned_duration_s": 0.0}))

    def test_elapsed_s_after_start(self) -> None:
        p = Programme(
            **(self._minimal_kwargs() | {"actual_started_at": 1000.0, "actual_ended_at": 1250.0})
        )
        assert p.elapsed_s == 250.0

    def test_end_before_start_rejected(self) -> None:
        with pytest.raises(ValueError, match="precedes"):
            Programme(
                **(self._minimal_kwargs() | {"actual_started_at": 1000.0, "actual_ended_at": 999.0})
            )

    def test_bias_shortcut(self) -> None:
        env = ProgrammeConstraintEnvelope(capability_bias_positive={"narrate": 2.0})
        p = Programme(**(self._minimal_kwargs() | {"constraints": env}))
        assert p.bias_multiplier("narrate") == 2.0
        assert p.expands_candidate_set("narrate") is True

    def test_json_round_trip(self) -> None:
        env = ProgrammeConstraintEnvelope(
            capability_bias_positive={"preferred": 3.0},
            capability_bias_negative={"avoided": 0.2},
            preset_family_priors=["calm-textural"],
            homage_rotation_modes=["sequential", "weighted_by_salience"],
            homage_package="default",
            ward_emphasis_target_rate_per_min=6.0,
            narrative_cadence_prior_s=45.0,
            surface_threshold_prior=0.55,
            reverie_saturation_target=0.4,
            display_density=ProgrammeDisplayDensity.DENSE,
            consent_scope="household",
        )
        p = Programme(
            programme_id="p-42",
            role=ProgrammeRole.EXPERIMENT,
            planned_duration_s=900.0,
            constraints=env,
            content=ProgrammeContent(narrative_beat="trial variant B"),
            ritual=ProgrammeRitual(boundary_freeze_s=2.0),
            success=ProgrammeSuccessCriteria(min_duration_s=120, max_duration_s=1500),
            parent_show_id="show-42",
            parent_condition_id="condition-v2",
            notes="smoke",
        )
        serialized = p.model_dump_json()
        round_trip = Programme.model_validate_json(serialized)
        assert round_trip == p

    def test_validate_soft_priors_only_self_check(self) -> None:
        env = ProgrammeConstraintEnvelope(capability_bias_negative={"cap": 0.3})
        p = Programme(**(self._minimal_kwargs() | {"constraints": env}))
        p.validate_soft_priors_only()

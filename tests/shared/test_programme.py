"""Tests for shared.programme — Programme primitive with soft-prior envelope.

Architectural axiom: programmes EXPAND grounding opportunities, never
REPLACE them. The Pydantic validators reject zero-bias (hard gate) at
instantiation so no downstream consumer can smuggle in a hard exclusion.
"""

from __future__ import annotations

import pytest

from shared.programme import (
    SEGMENTED_CONTENT_FORMAT_SPECS,
    SEGMENTED_CONTENT_ROLE_VALUES,
    Programme,
    ProgrammeAssetAttribution,
    ProgrammeConstraintEnvelope,
    ProgrammeContent,
    ProgrammeDeliveryMode,
    ProgrammeDisplayDensity,
    ProgrammeRitual,
    ProgrammeRole,
    ProgrammeStatus,
    ProgrammeSuccessCriteria,
    segmented_content_format_spec,
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


class TestSegmentedContentFormatSpecs:
    def test_specs_cover_every_segmented_role(self) -> None:
        assert SEGMENTED_CONTENT_ROLE_VALUES == _SEGMENTED_CONTENT_ROLES
        assert set(SEGMENTED_CONTENT_FORMAT_SPECS) == _SEGMENTED_CONTENT_ROLES

    def test_each_spec_declares_template_assets_and_ward_profile(self) -> None:
        for role in _SEGMENTED_CONTENT_ROLES:
            spec = segmented_content_format_spec(role)
            assert spec is not None
            assert (
                "{topic}" in spec.narrative_beat_template
                or "{source_uri}" in (spec.narrative_beat_template)
                or "{subject}" in spec.narrative_beat_template
            )
            assert "source_packet_refs" in spec.asset_requirements
            assert spec.ward_profile
            assert spec.ward_accent_role
            assert spec.source_affordance_kinds
            assert spec.minimum_planned_duration_s >= 300.0


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
        assert c.delivery_mode is ProgrammeDeliveryMode.LIVE_PRIOR

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

    def test_role_contract_and_asset_attribution_round_trip(self) -> None:
        content = ProgrammeContent(
            declared_topic="Source-backed ranking",
            source_uri="https://example.com/source",
            subject="Alpha subject",
            narrative_beat="rank source-backed claims",
            source_refs=[" vault:alpha.md ", "vault:alpha.md", "rag:hit-1"],
            role_contract={
                "source_packet_refs": [
                    {
                        "id": "packet:alpha",
                        "source_ref": "vault:alpha.md",
                        "evidence_refs": ["vault:alpha.md"],
                    }
                ],
                "role_live_bit_mechanic": "source changes ranking",
            },
            asset_attributions=[
                {
                    "source_ref": "vault:alpha.md",
                    "asset_kind": "vault_note",
                    "title": "Alpha",
                }
            ],
        )

        assert content.source_refs == ["vault:alpha.md", "rag:hit-1"]
        assert content.declared_topic == "Source-backed ranking"
        assert content.source_uri == "https://example.com/source"
        assert content.subject == "Alpha subject"
        assert content.role_contract["source_packet_refs"][0]["source_ref"] == "vault:alpha.md"
        assert content.asset_attributions == [
            ProgrammeAssetAttribution(
                source_ref="vault:alpha.md",
                asset_kind="vault_note",
                title="Alpha",
            )
        ]

    def test_responsible_hosting_rejects_executable_segment_cues(self) -> None:
        with pytest.raises(ValueError, match="executable segment_cues"):
            ProgrammeContent(
                hosting_context="hapax_responsible_live",
                segment_cues=["camera.hero tight"],
            )

    def test_missing_hosting_context_fails_closed_for_segment_cues(self) -> None:
        with pytest.raises(ValueError, match="executable segment_cues"):
            ProgrammeContent(segment_cues=["camera.hero tight"])

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

    def test_layout_intents_reject_concrete_runtime_authority_fields(self) -> None:
        with pytest.raises(ValueError, match="concrete layout authority"):
            ProgrammeContent(
                beat_layout_intents=[
                    {
                        "beat_id": "hook",
                        "needs": ["evidence_visible"],
                        "surfaceId": "main",
                    }
                ]
            )

    def test_layout_decision_receipts_rejected_at_planner_boundary(self) -> None:
        with pytest.raises(ValueError, match="layout_decision_receipts"):
            ProgrammeContent(
                layout_decision_receipts=[
                    {
                        "receipt_id": "receipt.layout_state_rendered",
                        "source": "layout_state",
                    }
                ]
            )

    @pytest.mark.parametrize(
        "bad_value",
        [
            "surface:main",
            "layout:balanced-v2",
            "cue:camera.hero tight",
            "camera.hero tight",
            "camera:operator-subject",
            "/dev/shm/hapax-layout.json",
            "default_static",
            "config/compositor-layouts/default.json",
        ],
    )
    def test_layout_intents_reject_command_like_nested_string_values(self, bad_value: str) -> None:
        with pytest.raises(ValueError, match="command-like layout authority"):
            ProgrammeContent(
                beat_layout_intents=[
                    {
                        "beat_id": "hook",
                        "action_intent_kinds": ["show_evidence"],
                        "needs": ["evidence_visible"],
                        "proposed_postures": ["asset_front"],
                        "expected_effects": ["evidence_on_screen"],
                        "evidence_refs": ["vault:source-note-1"],
                        "source_affordances": ["asset:evidence-card", bad_value],
                        "default_static_success_allowed": False,
                    }
                ]
            )

    def test_layout_intents_accept_declarative_refs_and_evidence_ids(self) -> None:
        content = ProgrammeContent(
            beat_layout_intents=[
                {
                    "beat_id": "hook",
                    "action_intent_kinds": ["show_evidence", "cite_source"],
                    "needs": ["evidence_visible", "source_visible"],
                    "proposed_postures": ["asset_front", "camera_subject"],
                    "expected_effects": ["evidence_on_screen", "source_context_legible"],
                    "evidence_refs": ["vault:source-note-1", "rag:proof-42"],
                    "source_affordances": ["asset:evidence-card", "resolver:source-card"],
                    "default_static_success_allowed": False,
                }
            ]
        )

        assert content.beat_layout_intents[0]["evidence_refs"] == [
            "vault:source-note-1",
            "rag:proof-42",
        ]

    def test_prepared_script_defaults_to_live_prior_contract(self) -> None:
        content = ProgrammeContent(
            hosting_context="hapax_responsible_live",
            prepared_script=["Place Alpha in S-tier because the ranking makes it visible."],
            beat_cards=[
                {
                    "beat_index": 0,
                    "beat_id": "beat-1",
                    "title": "rank alpha",
                    "prior_summary": "Use Alpha as a prepared prior, then compose live.",
                    "prepared_artifact_ref": "prepared_artifact:" + "a" * 64,
                    "action_intent_kinds": ["tier_chart"],
                    "layout_needs": ["tier_visual"],
                    "expected_effects": ["tier_chart.place:Alpha:S"],
                    "evidence_refs": ["prepared_artifact:" + "a" * 64],
                }
            ],
            live_priors=[
                {
                    "prior_id": "prepared-script-beat-1",
                    "beat_index": 0,
                    "text": "Prepared excerpt used as a prior, not as TTS authority.",
                    "prepared_artifact_ref": "prepared_artifact:" + "a" * 64,
                    "evidence_refs": ["prepared_artifact:" + "a" * 64],
                }
            ],
        )

        assert content.delivery_mode is ProgrammeDeliveryMode.LIVE_PRIOR
        assert content.beat_cards[0].layout_needs == ["tier_visual"]
        assert content.live_priors[0].kind == "prepared_script_excerpt"

    def test_live_prior_cards_reject_runtime_command_fields(self) -> None:
        with pytest.raises(ValueError):
            ProgrammeContent(
                beat_cards=[
                    {
                        "beat_index": 0,
                        "title": "bad",
                        "prior_summary": "bad",
                        "surfaceId": "main",
                    }
                ]
            )

    def test_delivery_mode_accepts_explicit_legacy_value(self) -> None:
        content = ProgrammeContent(delivery_mode="verbatim_legacy")
        assert content.delivery_mode is ProgrammeDeliveryMode.VERBATIM_LEGACY

    def test_responsible_layout_intents_reject_default_static_success_true(self) -> None:
        with pytest.raises(ValueError, match="default/static layout success"):
            ProgrammeContent(
                hosting_context="hapax_responsible_live",
                beat_layout_intents=[
                    {
                        "beat_id": "hook",
                        "action_intent_kinds": ["show_evidence"],
                        "needs": ["evidence_visible"],
                        "proposed_postures": ["asset_front"],
                        "expected_effects": ["evidence_on_screen"],
                        "evidence_refs": ["vault:source-note-1"],
                        "source_affordances": ["asset:evidence-card"],
                        "default_static_success_allowed": True,
                    }
                ],
            )

    @pytest.mark.parametrize("truthy_value", ["on", "enabled", "allowed", "yes", "1", "maybe"])
    def test_responsible_layout_intents_reject_truthy_default_static_success_strings(
        self, truthy_value: str
    ) -> None:
        with pytest.raises(ValueError, match="default/static layout success"):
            ProgrammeContent(
                hosting_context="hapax_responsible_live",
                beat_layout_intents=[
                    {
                        "beat_id": "hook",
                        "action_intent_kinds": ["show_evidence"],
                        "needs": ["evidence_visible"],
                        "proposed_postures": ["asset_front"],
                        "expected_effects": ["evidence_on_screen"],
                        "evidence_refs": ["vault:source-note-1"],
                        "source_affordances": ["asset:evidence-card"],
                        "default_static_success_allowed": truthy_value,
                    }
                ],
            )

    @pytest.mark.parametrize("falsey_value", ["off", "disabled", "false", "no", "0", "none", ""])
    def test_responsible_layout_intents_accept_falsey_default_static_success_strings(
        self, falsey_value: str
    ) -> None:
        content = ProgrammeContent(
            hosting_context="hapax_responsible_live",
            beat_layout_intents=[
                {
                    "beat_id": "hook",
                    "action_intent_kinds": ["show_evidence"],
                    "needs": ["evidence_visible"],
                    "proposed_postures": ["asset_front"],
                    "expected_effects": ["evidence_on_screen"],
                    "evidence_refs": ["vault:source-note-1"],
                    "source_affordances": ["asset:evidence-card"],
                    "default_static_success_allowed": falsey_value,
                }
            ],
        )

        assert content.beat_layout_intents[0]["default_static_success_allowed"] == falsey_value


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

    def _segmented_content(self) -> ProgrammeContent:
        return ProgrammeContent(
            declared_topic="source-backed ranking",
            narrative_beat="tier list on source-backed ranking",
            segment_beats=["hook: set criteria", "item: rank alpha", "close: recap"],
            source_refs=["vault:alpha.md"],
            role_contract={
                "source_packet_refs": ["vault:alpha.md"],
                "role_live_bit_mechanic": "source evidence changes a visible ranking",
                "event_object": "tier chart",
                "audience_job": "inspect and challenge placements",
                "payoff": "final tier chart resolves opening pressure",
                "temporality_band": "evergreen",
                "tier_criteria": "source-backed placement criteria",
            },
            asset_attributions=[
                ProgrammeAssetAttribution(
                    source_ref="vault:alpha.md",
                    asset_kind="vault_note",
                    title="Alpha",
                )
            ],
        )

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

    def test_segmented_programme_requires_five_minute_planned_duration(self) -> None:
        with pytest.raises(ValueError, match="planned_duration_s"):
            Programme(
                **(
                    self._minimal_kwargs()
                    | {
                        "role": ProgrammeRole.TIER_LIST,
                        "planned_duration_s": 299.0,
                        "content": self._segmented_content(),
                    }
                )
            )

    def test_segmented_programme_requires_role_contract(self) -> None:
        content = self._segmented_content()
        content.role_contract = {}
        with pytest.raises(ValueError, match="role_contract"):
            Programme(
                **(
                    self._minimal_kwargs()
                    | {
                        "role": ProgrammeRole.TIER_LIST,
                        "planned_duration_s": 600.0,
                        "content": content,
                    }
                )
            )

    def test_segmented_programme_persists_metadata(self) -> None:
        content = self._segmented_content()
        p = Programme(
            **(
                self._minimal_kwargs()
                | {
                    "role": ProgrammeRole.TIER_LIST,
                    "planned_duration_s": 600.0,
                    "content": content,
                }
            )
        )

        round_trip = Programme.model_validate_json(p.model_dump_json())
        assert (
            round_trip.content.role_contract["tier_criteria"] == "source-backed placement criteria"
        )
        assert round_trip.content.asset_attributions[0].source_ref == "vault:alpha.md"

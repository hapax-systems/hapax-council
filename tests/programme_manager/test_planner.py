"""Tests for agents.programme_manager.planner — Phase 3 of the
programme-layer plan.

Covers:
  - Happy path: well-formed LLM response → validated ProgrammePlan
  - LLM call failure → planner returns None (caller falls through)
  - Validation failure → retry with corrective prompt
  - Retry succeeds on second attempt → returns plan
  - Retry exhausted → returns None
  - Code-fence wrapper tolerated; empty / non-JSON / non-dict responses
    rejected
  - show_id mismatch in response → retry triggered with explicit hint
  - Hard-gate attempt (zero capability_bias_negative) → validator
    rejects → retry triggered
  - Vault-outline-ignored: planner has NO code path reading vault
    programme files (negative-existence test)
  - Soft-prior strict: positive bias amplifies, never gates
  - Per-call context renders missing inputs as "(unavailable)"
  - Prompt template loaded from external markdown file
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from agents.programme_manager.planner import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_MODEL,
    ProgrammePlanner,
)
from shared.programme import ProgrammePlan, ProgrammeRole, is_segmented_content_role
from shared.segment_prep_contract import programme_source_readiness

# ── Fixtures ────────────────────────────────────────────────────────────


def _well_formed_plan_payload(
    *,
    show_id: str = "show-test-001",
    plan_id: str = "plan-001",
    role: ProgrammeRole = ProgrammeRole.LISTENING,
) -> dict:
    """Build a minimal valid ProgrammePlan dict the LLM should emit."""
    content = {
        "narrative_beat": "Sit with the music. Stay quiet.",
    }
    if is_segmented_content_role(role):
        content = {
            "declared_topic": "source-backed test topic",
            "source_uri": "https://example.com/source",
            "subject": "Test Subject",
            "narrative_beat": f"{role.value} segment on source-backed test topic",
            "source_refs": ["vault:test-source.md"],
            "asset_attributions": [
                {
                    "source_ref": "vault:test-source.md",
                    "asset_kind": "vault_note",
                    "title": "Test Source",
                }
            ],
            "role_contract": {
                "source_packet_refs": ["vault:test-source.md"],
                "role_live_bit_mechanic": "source evidence changes the segment object",
                "event_object": "source-backed segment object",
                "audience_job": "inspect the source-backed consequence",
                "payoff": "closing beat resolves the opening pressure",
                "temporality_band": "evergreen",
                "tier_criteria": "source-backed ranking criterion",
                "ordering_criterion": "source-backed ordering criterion",
                "bounded_claim": "source evidence constrains the claim",
                "receipt_flip": "receipt changes scope",
                "media_ref": "media:test-source",
                "timestamp_or_locator": "00:00",
                "claim_under_reaction": "source claim under test",
                "layer_refs": ["vault:test-source.md"],
                "bottom_payoff": "deepest source-backed payoff",
                "subject_context": "source-backed subject context",
                "question_ladder": [
                    {
                        "question_id": "q1",
                        "question_text": "What changes if the source is removed?",
                        "answer_kind": "source_bound",
                        "followup_policy": "ask one source-backed followup",
                        "what_answer_changes": "segment scope",
                        "source_refs": ["vault:test-source.md"],
                    }
                ],
                "answer_source_policy": {
                    "operator_answer_authority": "none",
                    "transcript_ref_kind": "recorded_source",
                    "no_answer_flag": "say no answer is available",
                    "refusal_policy": "do not simulate private answers",
                    "public_private_boundary": "public sources only",
                },
                "teaching_objective": "teach the source consequence",
                "demonstration_object": "demonstration source object",
                "worked_example": "worked source example",
            },
            "segment_beats": ["hook: open topic", "body: show source", "close: land"],
            "beat_layout_intents": [
                {
                    "beat_id": "hook",
                    "action_intent_kinds": ["show_evidence"],
                    "needs": ["evidence_visible"],
                    "proposed_postures": ["asset_front"],
                    "expected_effects": ["evidence_on_screen"],
                    "evidence_refs": ["vault:test-source.md"],
                    "source_affordances": ["asset:source-card"],
                    "default_static_success_allowed": False,
                }
            ],
        }
    return {
        "plan_id": plan_id,
        "show_id": show_id,
        "plan_author": "hapax-director-planner",
        "programmes": [
            {
                "programme_id": "prog-001",
                "role": role.value,
                "planned_duration_s": 600.0,
                "constraints": {
                    "capability_bias_negative": {"speech_production": 0.5},
                    "capability_bias_positive": {"recall.web_search": 1.5},
                    "preset_family_priors": ["calm-textural"],
                    "homage_rotation_modes": ["paused"],
                    "surface_threshold_prior": 0.7,
                    "reverie_saturation_target": 0.30,
                },
                "content": content,
                "success": {
                    "completion_predicates": [],
                    "abort_predicates": [],
                    "min_duration_s": 60.0,
                    "max_duration_s": 1800.0,
                },
                "parent_show_id": show_id,
                "authorship": "hapax",
            }
        ],
    }


def _stub_llm(payload: dict | str) -> Callable[[str], str]:
    """LLM stub that always returns the given payload (dict → JSON, str → as-is)."""

    def fn(prompt: str) -> str:  # noqa: ARG001
        if isinstance(payload, dict):
            return json.dumps(payload)
        return payload

    return fn


def _sequence_llm(responses: list[str]) -> Callable[[str], str]:
    """LLM stub that returns each item in sequence; raises StopIteration when exhausted."""
    idx = [0]

    def fn(prompt: str) -> str:  # noqa: ARG001
        if idx[0] >= len(responses):
            raise AssertionError(
                f"LLM stub called {idx[0] + 1} times but only {len(responses)} responses queued"
            )
        out = responses[idx[0]]
        idx[0] += 1
        return out

    return fn


# ── Happy path ──────────────────────────────────────────────────────────


class TestHappyPath:
    def test_well_formed_response_returns_plan(self) -> None:
        payload = _well_formed_plan_payload()
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id="show-test-001")
        assert plan is not None
        assert isinstance(plan, ProgrammePlan)
        assert plan.show_id == "show-test-001"
        assert plan.plan_id == "plan-001"
        assert len(plan.programmes) == 1

    def test_plan_author_is_pinned_literal(self) -> None:
        payload = _well_formed_plan_payload()
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id="show-test-001")
        assert plan is not None
        assert plan.plan_author == "hapax-director-planner"

    def test_multi_programme_plan_returned(self) -> None:
        payload = _well_formed_plan_payload()
        # Add a second programme of a different role
        second = json.loads(json.dumps(payload["programmes"][0]))
        second["programme_id"] = "prog-002"
        second["role"] = ProgrammeRole.WIND_DOWN.value
        payload["programmes"].append(second)
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id="show-test-001")
        assert plan is not None
        assert len(plan.programmes) == 2

    def test_one_programme_target_is_explicit_in_prompt(self) -> None:
        prompts: list[str] = []

        def capture(prompt: str) -> str:
            prompts.append(prompt)
            return json.dumps(_well_formed_plan_payload(role=ProgrammeRole.TIER_LIST))

        planner = ProgrammePlanner(llm_fn=capture)
        plan = planner.plan(show_id="show-test-001", target_programmes=1)

        assert plan is not None
        assert "emit exactly 1 segmented-content programme" in prompts[0]
        assert "soft-prior programme proposals" in prompts[0]

    def test_default_model_is_resident_command_r(self) -> None:
        """Pin the only production planner model.

        Programme planning is content programming, so the default route is
        resident Command-R. Non-Command-R environment overrides fail in the
        production caller instead of silently falling back through LiteLLM.
        """
        assert DEFAULT_MODEL == "command-r-08-2024-exl3-5.0bpw"

    def test_default_timeout_preserves_long_resident_generation(self) -> None:
        from agents.programme_manager import planner as planner_mod

        assert planner_mod._LLM_TIMEOUT_S >= 900

    def test_default_llm_rejects_non_resident_model_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agents.programme_manager import planner as planner_mod

        monkeypatch.setenv("HAPAX_PROGRAMME_PLANNER_MODEL", "qwen-not-allowed")

        with pytest.raises(RuntimeError, match="resident Command-R"):
            planner_mod._default_llm_fn("plan prompt")

    def test_default_llm_calls_resident_command_r_helper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agents.programme_manager import planner as planner_mod

        calls: list[tuple[str, dict]] = []

        def fake_call(prompt: str, **kwargs: object) -> str:
            calls.append((prompt, kwargs))
            return json.dumps(_well_formed_plan_payload())

        monkeypatch.delenv("HAPAX_PROGRAMME_PLANNER_MODEL", raising=False)
        monkeypatch.setenv("HAPAX_TABBY_URL", "http://tabby.test/v1/chat/completions")
        monkeypatch.setattr(planner_mod, "call_resident_command_r", fake_call)

        assert planner_mod._default_llm_fn("plan prompt")
        assert calls == [
            (
                "plan prompt",
                {
                    "chat_url": "http://tabby.test/v1/chat/completions",
                    "max_tokens": 8192,
                    "temperature": 0.7,
                    "timeout_s": planner_mod._LLM_TIMEOUT_S,
                },
            )
        ]


# ── Failure modes — first attempt ───────────────────────────────────────


class TestLLMCallFailure:
    def test_llm_raising_returns_none(self) -> None:
        def boom(prompt: str) -> str:  # noqa: ARG001
            raise RuntimeError("LLM down")

        planner = ProgrammePlanner(llm_fn=boom)
        plan = planner.plan(show_id="show-test-001")
        assert plan is None

    def test_empty_llm_response_after_retry_returns_none(self) -> None:
        planner = ProgrammePlanner(llm_fn=_stub_llm(""))
        plan = planner.plan(show_id="show-test-001")
        assert plan is None

    def test_non_json_response_after_retry_returns_none(self) -> None:
        planner = ProgrammePlanner(llm_fn=_stub_llm("just a sentence about programmes"))
        plan = planner.plan(show_id="show-test-001")
        assert plan is None

    def test_non_dict_top_level_returns_none(self) -> None:
        planner = ProgrammePlanner(llm_fn=_stub_llm("[1, 2, 3]"))
        plan = planner.plan(show_id="show-test-001")
        assert plan is None


# ── Retry path ──────────────────────────────────────────────────────────


class TestRetryPath:
    def test_validation_failure_triggers_retry(self) -> None:
        bad = {"plan_id": "bad", "show_id": "show-test-001"}  # missing programmes
        good = _well_formed_plan_payload()
        planner = ProgrammePlanner(llm_fn=_sequence_llm([json.dumps(bad), json.dumps(good)]))
        plan = planner.plan(show_id="show-test-001")
        assert plan is not None
        assert plan.plan_id == "plan-001"

    def test_retry_carries_error_into_corrective_prompt(self) -> None:
        bad = json.dumps({"not": "a plan"})
        captured_prompts: list[str] = []

        def capture_llm(prompt: str) -> str:
            captured_prompts.append(prompt)
            if len(captured_prompts) == 1:
                return bad
            return json.dumps(_well_formed_plan_payload())

        planner = ProgrammePlanner(llm_fn=capture_llm)
        planner.plan(show_id="show-test-001")
        assert len(captured_prompts) == 2
        # Retry prompt explicitly mentions soft-prior strictness
        assert "Validation error on previous attempt" in captured_prompts[1]
        assert "capability_bias_negative" in captured_prompts[1]

    def test_segment_source_readiness_failure_triggers_retry(self) -> None:
        bad = _well_formed_plan_payload(role=ProgrammeRole.TIER_LIST)
        bad["programmes"][0]["content"]["role_contract"].pop("tier_criteria")
        bad["programmes"][0]["content"]["narrative_beat"] = (
            "tier-list segment on anime. Source candidates from vault + RAG; "
            "rank against operator positions; narrate placements; invite chat reactions."
        )
        bad["programmes"][0]["content"]["segment_beats"] = [
            "hook: Introduce the topic and why it matters.",
            "item_1: Present the first S-tier item.",
            "close: Recap the tier list and invite chat.",
        ]
        good = _well_formed_plan_payload(role=ProgrammeRole.TIER_LIST)
        captured_prompts: list[str] = []

        def capture_llm(prompt: str) -> str:
            captured_prompts.append(prompt)
            if len(captured_prompts) == 1:
                return json.dumps(bad)
            return json.dumps(good)

        planner = ProgrammePlanner(llm_fn=capture_llm)
        plan = planner.plan(show_id="show-test-001", target_programmes=1)

        assert plan is not None
        assert len(captured_prompts) == 2
        assert "segment source readiness failed" in captured_prompts[1]
        assert "missing_role_contract_fields" in captured_prompts[1]
        assert "programme_narrative_beat_template_leak" in captured_prompts[1]
        assert "tier_criteria" in captured_prompts[1]

    def test_segment_source_readiness_failure_returns_none_without_retry(self) -> None:
        bad = _well_formed_plan_payload(role=ProgrammeRole.TIER_LIST)
        bad["programmes"][0]["content"]["role_contract"].pop("tier_criteria")
        bad["programmes"][0]["content"]["narrative_beat"] = (
            "tier-list segment on anime. Source candidates from vault + RAG; "
            "rank against operator positions; narrate placements; invite chat reactions."
        )
        bad["programmes"][0]["content"]["segment_beats"] = [
            "hook: Introduce the topic and why it matters.",
            "item_1: Present the first S-tier item.",
            "close: Recap the tier list and invite chat.",
        ]

        planner = ProgrammePlanner(llm_fn=_stub_llm(bad), max_retries=0)
        plan = planner.plan(show_id="show-test-001")

        assert plan is None

    def test_segment_source_readiness_accepts_structured_tier_criteria_field(self) -> None:
        payload = _well_formed_plan_payload(role=ProgrammeRole.TIER_LIST)
        payload["programmes"][0]["content"]["role_contract"]["tier_criteria"] = (
            "source impact, durability, and consequence under visible placement"
        )
        plan = ProgrammePlan.model_validate(payload)

        readiness = programme_source_readiness(plan.programmes[0])

        assert readiness["ok"] is True
        assert "tier_list_requires_ordering_criteria" not in {
            item["reason"] for item in readiness["violations"]
        }

    @pytest.mark.parametrize(
        ("role", "field_updates", "forbidden_reason"),
        [
            (
                ProgrammeRole.LECTURE,
                {
                    "teaching_objective": "explain the causal chain from the packet",
                    "demonstration_object": "packet alpha",
                    "worked_example": "packet alpha against packet beta",
                },
                "lecture_requires_demonstration_object",
            ),
            (
                ProgrammeRole.REACT,
                {
                    "media_ref": "asset alpha",
                    "timestamp_or_locator": "00:00",
                    "claim_under_reaction": "the packet changes claim scope",
                },
                "react_requires_media_locator",
            ),
        ],
    )
    def test_segment_source_readiness_accepts_structured_role_specific_fields(
        self,
        role: ProgrammeRole,
        field_updates: dict[str, str],
        forbidden_reason: str,
    ) -> None:
        payload = _well_formed_plan_payload(role=role)
        payload["programmes"][0]["content"]["role_contract"].update(field_updates)
        plan = ProgrammePlan.model_validate(payload)

        readiness = programme_source_readiness(plan.programmes[0])

        assert readiness["ok"] is True
        assert forbidden_reason not in {item["reason"] for item in readiness["violations"]}

    def test_max_retries_zero_no_retry(self) -> None:
        bad = json.dumps({"plan_id": "x", "show_id": "show-test-001"})
        calls: list[int] = []

        def counting_llm(prompt: str) -> str:  # noqa: ARG001
            calls.append(1)
            return bad

        planner = ProgrammePlanner(llm_fn=counting_llm, max_retries=0)
        plan = planner.plan(show_id="show-test-001")
        assert plan is None
        assert len(calls) == 1  # initial only, no retry

    def test_default_max_retries_is_one(self) -> None:
        assert DEFAULT_MAX_RETRIES == 1


# ── Hard-gate attempts ──────────────────────────────────────────────────


class TestHardGateRejection:
    """Soft-prior strictness — zero capability_bias_negative is rejected
    by the Programme validator. The planner sees the validation error
    and may retry with the corrective prompt.
    """

    def test_zero_negative_bias_rejected_at_validator(self) -> None:
        payload = _well_formed_plan_payload()
        payload["programmes"][0]["constraints"]["capability_bias_negative"] = {
            "speech_production": 0.0,
        }
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload), max_retries=0)
        plan = planner.plan(show_id="show-test-001")
        assert plan is None  # validator rejected; no retry; returned None

    def test_negative_negative_bias_rejected(self) -> None:
        payload = _well_formed_plan_payload()
        payload["programmes"][0]["constraints"]["capability_bias_negative"] = {
            "speech_production": -0.5,
        }
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload), max_retries=0)
        plan = planner.plan(show_id="show-test-001")
        assert plan is None

    def test_positive_bias_below_one_rejected(self) -> None:
        payload = _well_formed_plan_payload()
        payload["programmes"][0]["constraints"]["capability_bias_positive"] = {
            "speech_production": 0.8,
        }
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload), max_retries=0)
        plan = planner.plan(show_id="show-test-001")
        assert plan is None

    def test_retry_can_recover_from_hard_gate_attempt(self) -> None:
        payload_bad = _well_formed_plan_payload()
        payload_bad["programmes"][0]["constraints"]["capability_bias_negative"] = {
            "speech_production": 0.0,
        }
        payload_good = _well_formed_plan_payload()
        planner = ProgrammePlanner(
            llm_fn=_sequence_llm([json.dumps(payload_bad), json.dumps(payload_good)])
        )
        plan = planner.plan(show_id="show-test-001")
        assert plan is not None  # retry succeeded


# ── show_id cross-check ────────────────────────────────────────────────


class TestShowIdInvariant:
    def test_show_id_mismatch_triggers_retry(self) -> None:
        payload = _well_formed_plan_payload(show_id="wrong-show")
        good = _well_formed_plan_payload(show_id="show-test-001")
        planner = ProgrammePlanner(llm_fn=_sequence_llm([json.dumps(payload), json.dumps(good)]))
        plan = planner.plan(show_id="show-test-001")
        assert plan is not None
        assert plan.show_id == "show-test-001"

    def test_programme_show_id_mismatch_rejected(self) -> None:
        payload = _well_formed_plan_payload(show_id="show-test-001")
        payload["programmes"][0]["parent_show_id"] = "different-show"
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload), max_retries=0)
        plan = planner.plan(show_id="show-test-001")
        assert plan is None  # cross-check at ProgrammePlan validator


# ── Code-fence tolerance ───────────────────────────────────────────────


class TestCodeFenceTolerance:
    def test_response_wrapped_in_json_fence_parses(self) -> None:
        payload = _well_formed_plan_payload()
        wrapped = "```json\n" + json.dumps(payload) + "\n```"
        planner = ProgrammePlanner(llm_fn=_stub_llm(wrapped))
        plan = planner.plan(show_id="show-test-001")
        assert plan is not None

    def test_response_wrapped_in_bare_fence_parses(self) -> None:
        payload = _well_formed_plan_payload()
        wrapped = "```\n" + json.dumps(payload) + "\n```"
        planner = ProgrammePlanner(llm_fn=_stub_llm(wrapped))
        plan = planner.plan(show_id="show-test-001")
        assert plan is not None


# ── Vault-outline-ignored invariant ───────────────────────────────────


class TestVaultOutlineIgnored:
    """Per memory feedback_hapax_authors_programmes: even if a well-
    formed programme JSON is left in the vault, the planner ignores it.
    Asserted by negative-existence on the planner's source — there is
    no vault-read code path in the planner module.
    """

    def test_planner_source_does_not_read_vault_programme_files(self) -> None:
        """Pin: planner.py does not import or scan any vault programme
        directory. A future regression that adds vault-programme reads
        trips this test."""
        from agents.programme_manager import planner as planner_mod

        source = Path(planner_mod.__file__).read_text()
        # Vault programme paths the operator might be tempted to wire in
        forbidden_substrings = [
            "20-projects/hapax-research/programmes",
            "20-projects/hapax-cc-tasks/active/programme",
            "vault_programmes",
            "operator_programme_outline",
        ]
        for token in forbidden_substrings:
            assert token not in source, (
                f"planner.py contains vault-programme reference {token!r} — "
                "the planner is Hapax-authored only "
                "(memory feedback_hapax_authors_programmes)"
            )


# ── Per-call context rendering ────────────────────────────────────────


class TestContextRendering:
    def test_missing_inputs_render_as_unavailable(self) -> None:
        captured: list[str] = []

        def capture(prompt: str) -> str:
            captured.append(prompt)
            return json.dumps(_well_formed_plan_payload())

        planner = ProgrammePlanner(llm_fn=capture)
        planner.plan(show_id="show-test-001")  # no perception, vault, profile
        prompt = captured[0]
        assert "(unavailable)" in prompt
        # Show ID always renders
        assert "show-test-001" in prompt

    def test_provided_inputs_render_as_json(self) -> None:
        captured: list[str] = []

        def capture(prompt: str) -> str:
            captured.append(prompt)
            return json.dumps(_well_formed_plan_payload())

        planner = ProgrammePlanner(llm_fn=capture)
        planner.plan(
            show_id="show-test-001",
            perception={"operator_present": True, "stance": "nominal"},
            working_mode="research",
        )
        prompt = captured[0]
        assert "operator_present" in prompt
        assert "research" in prompt

    def test_prompt_template_loaded_from_external_file(self, tmp_path: Path) -> None:
        """The prompt template is read from a markdown file (not inline)."""
        custom_template = tmp_path / "custom_template.md"
        custom_template.write_text("CUSTOM TEMPLATE MARKER", encoding="utf-8")
        captured: list[str] = []

        def capture(prompt: str) -> str:
            captured.append(prompt)
            return json.dumps(_well_formed_plan_payload())

        planner = ProgrammePlanner(llm_fn=capture, prompt_path=custom_template)
        planner.plan(show_id="show-test-001")
        assert "CUSTOM TEMPLATE MARKER" in captured[0]

    def test_default_prompt_does_not_invite_camera_layout_authority(self) -> None:
        captured: list[str] = []

        def capture(prompt: str) -> str:
            captured.append(prompt)
            return json.dumps(_well_formed_plan_payload())

        planner = ProgrammePlanner(llm_fn=capture)
        planner.plan(show_id="show-test-001")
        prompt = captured[0]

        assert "camera_subject" not in prompt
        assert "camera:" not in prompt

    def test_default_prompt_skeleton_names_segment_role_contract_fields(self) -> None:
        captured: list[str] = []

        def capture(prompt: str) -> str:
            captured.append(prompt)
            return json.dumps(_well_formed_plan_payload(role=ProgrammeRole.TIER_LIST))

        planner = ProgrammePlanner(llm_fn=capture)
        planner.plan(show_id="show-test-001", target_programmes=1)
        prompt = captured[0]

        for key in (
            '"tier_criteria"',
            '"ordering_criterion"',
            '"bounded_claim"',
            '"receipt_flip"',
            '"media_ref"',
            '"timestamp_or_locator"',
            '"claim_under_reaction"',
            '"layer_refs"',
            '"bottom_payoff"',
            '"subject_context"',
            '"question_ladder"',
            '"answer_source_policy"',
            '"topic_selection"',
            '"operator_agency_policy"',
            '"teaching_objective"',
            '"demonstration_object"',
            '"worked_example"',
        ):
            assert key in prompt


# ── Soft-prior architectural pin ──────────────────────────────────────


class TestSoftPriorOutputInvariant:
    """Whatever the planner emits, the resulting Programme objects MUST
    have soft-prior bias values (validator-enforced). This pins the
    architectural axiom at the planner output surface.
    """

    def test_emitted_negative_biases_are_strictly_positive(self) -> None:
        payload = _well_formed_plan_payload()
        payload["programmes"][0]["constraints"]["capability_bias_negative"] = {
            "speech_production": 0.5,
            "camera.hero": 0.25,
        }
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id="show-test-001")
        assert plan is not None
        for programme in plan.programmes:
            for cap, mult in programme.constraints.capability_bias_negative.items():
                assert 0.0 < mult <= 1.0, f"emitted bias {cap!r}={mult!r} violates soft-prior axiom"

    def test_emitted_positive_biases_are_at_least_one(self) -> None:
        payload = _well_formed_plan_payload()
        payload["programmes"][0]["constraints"]["capability_bias_positive"] = {
            "recall.web_search": 1.5,
            "speech_production": 1.2,
        }
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id="show-test-001")
        assert plan is not None
        for programme in plan.programmes:
            for cap, mult in programme.constraints.capability_bias_positive.items():
                assert mult >= 1.0, f"emitted bias {cap!r}={mult!r} violates soft-prior axiom"

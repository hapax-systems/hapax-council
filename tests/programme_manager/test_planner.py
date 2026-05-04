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

from agents.programme_manager.planner import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_MODEL,
    ProgrammePlanner,
)
from shared.programme import ProgrammePlan, ProgrammeRole

# ── Fixtures ────────────────────────────────────────────────────────────


def _well_formed_plan_payload(
    *,
    show_id: str = "show-test-001",
    plan_id: str = "plan-001",
    role: ProgrammeRole = ProgrammeRole.LISTENING,
) -> dict:
    """Build a minimal valid ProgrammePlan dict the LLM should emit."""
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
                "content": {
                    "narrative_beat": "Sit with the music. Stay quiet.",
                },
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

    def test_default_model_alias_routes_through_balanced_tier(self) -> None:
        """Pin the model alias the production planner uses."""
        assert DEFAULT_MODEL in ("balanced", "claude-sonnet", "claude-opus-4-7")  # operator-tunable
        # Default before any env override
        if "HAPAX_PROGRAMME_PLANNER_MODEL" not in __import__("os").environ:
            assert DEFAULT_MODEL == "claude-opus-4-7"


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

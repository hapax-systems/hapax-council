"""Tests for Batch 4: RLHF anti-pattern monitoring and directive compliance."""

from __future__ import annotations


class TestMonologicScoring:
    def test_purely_declarative_is_monologic(self):
        from agents.hapax_voice.grounding_evaluator import _score_monologic

        response = "The system is running normally. All services are healthy."
        assert _score_monologic(response) == 1.0

    def test_question_ending_is_dialogic(self):
        from agents.hapax_voice.grounding_evaluator import _score_monologic

        response = "I set up the routing. Does that work for you?"
        assert _score_monologic(response) < 1.0

    def test_comprehension_check_is_dialogic(self):
        from agents.hapax_voice.grounding_evaluator import _score_monologic

        response = "The sidechain is on channel 12. Does that make sense?"
        assert _score_monologic(response) <= 0.3

    def test_back_reference_is_dialogic(self):
        from agents.hapax_voice.grounding_evaluator import _score_monologic

        response = (
            "Going back to what you mentioned about the beat, I think we should adjust the tempo."
        )
        assert _score_monologic(response) < 1.0

    def test_collaborative_offer_is_dialogic(self):
        from agents.hapax_voice.grounding_evaluator import _score_monologic

        response = "I could check the routing. Want me to look into it?"
        assert _score_monologic(response) <= 0.3


class TestDirectiveCompliance:
    def test_advance_always_compliant(self):
        from agents.hapax_voice.grounding_evaluator import score_directive_compliance

        assert score_directive_compliance("Anything at all", "advance") == 1.0

    def test_elaborate_with_example_compliant(self):
        from agents.hapax_voice.grounding_evaluator import score_directive_compliance

        response = "For example, think of it like a compressor sidechain."
        assert score_directive_compliance(response, "elaborate") == 1.0

    def test_elaborate_without_example_partial(self):
        from agents.hapax_voice.grounding_evaluator import score_directive_compliance

        response = "The routing sends audio to the aux bus."
        assert score_directive_compliance(response, "elaborate") < 1.0

    def test_reasoning_with_retraction_noncompliant(self):
        from agents.hapax_voice.grounding_evaluator import score_directive_compliance

        response = "You're right, I was wrong about that. I apologize."
        assert score_directive_compliance(response, "present_reasoning") == 0.0

    def test_reasoning_with_explanation_compliant(self):
        from agents.hapax_voice.grounding_evaluator import score_directive_compliance

        response = "The reason I said that is because the latency measurements showed a spike."
        assert score_directive_compliance(response, "present_reasoning") == 1.0


class TestSelectiveLockdown:
    def test_grounding_directive_not_locked(self):
        from agents.hapax_voice.conversation_pipeline import ConversationPipeline

        pipeline = ConversationPipeline.__new__(ConversationPipeline)
        pipeline.system_prompt = "You are Hapax."
        pipeline.messages = [{"role": "system", "content": "You are Hapax."}]
        pipeline._conversation_thread = []
        pipeline._experiment_flags = {
            "volatile_lockdown": True,  # old-style lockdown
            "grounding_directive": True,
        }
        pipeline._env_context_fn = None
        pipeline._policy_fn = None
        pipeline._last_env_hash = 0
        pipeline._salience_router = None
        pipeline._sentinel_line = ""
        pipeline._sentinel_number = None

        # Even with volatile_lockdown, grounding directive should inject
        # (it uses getattr, not lockdown check)
        from agents.hapax_voice.grounding_ledger import GroundingLedger

        pipeline._grounding_ledger = GroundingLedger()
        pipeline._grounding_ledger.add_du(1, "test")
        pipeline._grounding_ledger.update_from_acceptance("CLARIFY")

        pipeline._update_system_context()
        content = pipeline.messages[0]["content"]
        assert "Grounding Directive" in content
        assert "Rephrase" in content or "rephrase" in content.lower()

    def test_salience_prompt_stripped_but_router_computes(self):
        from agents.hapax_voice.conversation_pipeline import ConversationPipeline

        pipeline = ConversationPipeline.__new__(ConversationPipeline)
        pipeline.system_prompt = "You are Hapax."
        pipeline.messages = [{"role": "system", "content": "You are Hapax."}]
        pipeline._conversation_thread = []
        pipeline._experiment_flags = {"salience_context": False}
        pipeline._env_context_fn = None
        pipeline._policy_fn = None
        pipeline._last_env_hash = 0
        pipeline._salience_router = None
        pipeline._sentinel_line = ""
        pipeline._sentinel_number = None
        pipeline._grounding_ledger = None

        pipeline._update_system_context()
        content = pipeline.messages[0]["content"]
        # Salience context block should NOT be in prompt
        assert "Conversational Salience" not in content

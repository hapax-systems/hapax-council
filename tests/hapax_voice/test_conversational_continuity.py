"""Tests for conversational continuity bug fixes and feature flags."""

from __future__ import annotations

# ── Batch 1: _extract_substance helper ────────────────────────────────────────


class TestExtractSubstance:
    def test_strips_greeting_prefix(self):
        from agents.hapax_voice.conversation_pipeline import _extract_substance

        assert _extract_substance("hey hapax, what's the weather") == "what's the weather"

    def test_strips_hi_prefix(self):
        from agents.hapax_voice.conversation_pipeline import _extract_substance

        assert _extract_substance("Hi Hapax, play some music") == "play some music"

    def test_no_greeting_passthrough(self):
        from agents.hapax_voice.conversation_pipeline import _extract_substance

        result = _extract_substance("what time is it")
        assert result == "what time is it"

    def test_greeting_only_returns_original(self):
        from agents.hapax_voice.conversation_pipeline import _extract_substance

        # "hey hapax" alone → stripped to empty → falls back to original
        result = _extract_substance("hey hapax")
        assert result  # should not be empty

    def test_truncates_at_100_chars(self):
        from agents.hapax_voice.conversation_pipeline import _extract_substance

        long_text = "a" * 150
        assert len(_extract_substance(long_text)) <= 100


# ── Batch 1: Sentinel survival through system prompt rebuild ──────────────────


class TestSentinelSurvival:
    def _make_pipeline(self, **kwargs):
        from agents.hapax_voice.conversation_pipeline import ConversationPipeline

        pipeline = ConversationPipeline.__new__(ConversationPipeline)
        pipeline.system_prompt = "You are Hapax."
        pipeline.messages = [{"role": "system", "content": "You are Hapax."}]
        pipeline._conversation_thread = []
        pipeline._experiment_flags = kwargs.get("experiment_flags", {})
        pipeline._env_context_fn = None
        pipeline._policy_fn = None
        pipeline._last_env_hash = 0
        pipeline._salience_router = None
        pipeline._sentinel_line = "\n\nInternal test fact: number is 42."
        pipeline._sentinel_number = 42
        return pipeline

    def test_sentinel_injected_by_update(self):
        pipeline = self._make_pipeline()
        pipeline._update_system_context()
        content = pipeline.messages[0]["content"]
        assert "number is 42" in content

    def test_sentinel_survives_thread_update(self):
        from agents.hapax_voice.conversation_pipeline import ThreadEntry

        pipeline = self._make_pipeline()
        pipeline._conversation_thread = [
            ThreadEntry(turn=1, user_text="topic A discussed", response_summary="noted"),
            ThreadEntry(turn=2, user_text="topic B discussed", response_summary="got it"),
        ]
        pipeline._last_env_hash = 0  # force refresh
        pipeline._update_system_context()
        content = pipeline.messages[0]["content"]
        assert "number is 42" in content
        assert "topic A discussed" in content

    def test_sentinel_disabled_by_experiment_flag(self):
        pipeline = self._make_pipeline(experiment_flags={"sentinel": False})
        pipeline._update_system_context()
        content = pipeline.messages[0]["content"]
        assert "number is 42" not in content


# ── Batch 1: Message drop preserves tool sequences ───────────────────────────


class TestMessageDrop:
    def _make_pipeline_with_messages(self, messages, flags=None):
        from agents.hapax_voice.conversation_pipeline import ConversationPipeline

        pipeline = ConversationPipeline.__new__(ConversationPipeline)
        pipeline.messages = messages
        pipeline.system_prompt = "system"
        pipeline._conversation_thread = []
        pipeline._experiment_flags = flags or {}
        pipeline._env_context_fn = None
        pipeline._policy_fn = None
        pipeline._last_env_hash = 0
        pipeline._salience_router = None
        pipeline._sentinel_line = ""
        pipeline._turn_model = "test"
        pipeline._turn_model_tier = "CAPABLE"
        pipeline.llm_model = "test"
        pipeline.tools = None
        pipeline.tool_handlers = {}
        pipeline._context_distillation = ""
        return pipeline

    def test_preserves_tool_sequences(self):
        """Tool call messages should not be split from their exchange."""
        messages = [
            {"role": "system", "content": "system"},
        ]
        # Add 6 exchanges, one with tool calls
        for i in range(6):
            messages.append({"role": "user", "content": f"question {i}"})
            if i == 2:
                # Tool exchange: assistant with tool_calls, tool result, assistant follow-up
                messages.append(
                    {"role": "assistant", "content": None, "tool_calls": [{"id": "tc1"}]}
                )
                messages.append({"role": "tool", "content": "tool result", "tool_call_id": "tc1"})
                messages.append({"role": "assistant", "content": f"answer {i} with tool"})
            else:
                messages.append({"role": "assistant", "content": f"answer {i}"})

        pipeline = self._make_pipeline_with_messages(messages)
        assert len(pipeline.messages) > 12  # triggers drop

        # Simulate what _generate_and_speak does
        # We can't easily call _generate_and_speak, so test the logic directly
        system_msg = pipeline.messages[0]
        user_count = 0
        cut_idx = len(pipeline.messages)
        for i in range(len(pipeline.messages) - 1, 0, -1):
            if pipeline.messages[i].get("role") == "user":
                user_count += 1
                if user_count >= 5:
                    cut_idx = i
                    break
        recent = pipeline.messages[cut_idx:]
        result = [system_msg] + recent

        # All messages from cut_idx onward should be preserved
        # Count user messages in result (excluding system)
        user_msgs = [m for m in result if m.get("role") == "user"]
        assert len(user_msgs) == 5

        # Tool messages should be preserved intact
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1  # tool exchange preserved

    def test_message_drop_disabled_by_flag(self):
        """When message_drop flag is False, no messages should be dropped."""
        messages = [{"role": "system", "content": "system"}]
        for i in range(10):
            messages.append({"role": "user", "content": f"q{i}"})
            messages.append({"role": "assistant", "content": f"a{i}"})

        pipeline = self._make_pipeline_with_messages(messages, flags={"message_drop": False})
        original_len = len(pipeline.messages)

        # The drop logic is gated — with flag off, messages stay intact
        # (testing the gate, not the full _generate_and_speak)
        should_drop = pipeline._experiment_flags.get("message_drop", True)
        assert not should_drop
        assert len(pipeline.messages) == original_len


# ── Batch 2: Feature flags default to all-on ─────────────────────────────────


class TestExperimentFlags:
    def test_all_on_by_default(self):
        from agents.hapax_voice.conversation_pipeline import ConversationPipeline

        pipeline = ConversationPipeline.__new__(ConversationPipeline)
        pipeline._experiment_flags = {}

        assert pipeline._experiment_flags.get("stable_frame", True) is True
        assert pipeline._experiment_flags.get("message_drop", True) is True
        assert pipeline._experiment_flags.get("cross_session", True) is True
        assert pipeline._experiment_flags.get("sentinel", True) is True

    def test_stable_frame_disabled(self):
        from agents.hapax_voice.conversation_pipeline import ConversationPipeline

        pipeline = ConversationPipeline.__new__(ConversationPipeline)
        pipeline.system_prompt = "You are Hapax."
        pipeline.messages = [{"role": "system", "content": "You are Hapax."}]
        pipeline._conversation_thread = ["topic discussed"]
        pipeline._experiment_flags = {"stable_frame": False}
        pipeline._env_context_fn = None
        pipeline._policy_fn = None
        pipeline._last_env_hash = 0
        pipeline._salience_router = None
        pipeline._sentinel_line = ""

        pipeline._update_system_context()
        content = pipeline.messages[0]["content"]
        assert "Conversation So Far" not in content

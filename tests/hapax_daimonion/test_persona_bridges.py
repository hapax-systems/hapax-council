"""Tests for verbal bridge and persona instructions in system prompt."""

from agents.hapax_daimonion.persona import system_prompt


class TestBridgeInstructions:
    def test_prompt_contains_bridge_instruction(self):
        prompt = system_prompt(guest_mode=False)
        assert "brief" in prompt.lower()
        assert "bridge" in prompt.lower() or "before" in prompt.lower()

    def test_prompt_mentions_varying_phrasing(self):
        prompt = system_prompt(guest_mode=False)
        assert "vary" in prompt.lower()

    def test_guest_mode_no_per_tool_directory(self):
        """Guest mode strips per-tool identifiers from the directory.

        The original assertion was a blanket "no 'tool' substring"
        but the rewritten prompt naturally mentions tool-related
        concepts (operator-private tool boundary, bridge-before-
        tool-call instruction). What actually matters is that no
        per-tool identifier appears — the LLM in guest mode should
        not know it has access to e.g. get_calendar_today."""
        prompt = system_prompt(guest_mode=True)
        for tool_name in ("get_calendar_today", "search_emails", "send_sms"):
            assert tool_name not in prompt


class TestAppearanceResponse:
    def test_prompt_mentions_appearance_naturally(self):
        prompt = system_prompt(guest_mode=False)
        assert "appearance" in prompt.lower() or "look" in prompt.lower()
        assert "friend" in prompt.lower() or "natural" in prompt.lower()


class TestProactiveOverture:
    def test_prompt_handles_name_only_invocation(self):
        prompt = system_prompt(guest_mode=False)
        assert "without a clear request" in prompt.lower() or "just your name" in prompt.lower()

    def test_prompt_mentions_contextual_sources(self):
        prompt = system_prompt(guest_mode=False)
        assert "calendar" in prompt.lower()

    def test_prompt_frames_as_warm(self):
        prompt = system_prompt(guest_mode=False)
        assert "warm" in prompt.lower() or "friendly" in prompt.lower()


class TestImageGenInstruction:
    def test_prompt_mentions_image_generation(self):
        prompt = system_prompt(guest_mode=False)
        assert "generate" in prompt.lower() or "create" in prompt.lower()
        assert "image" in prompt.lower()

    def test_prompt_mentions_screen_display(self):
        prompt = system_prompt(guest_mode=False)
        assert "screen" in prompt.lower()

    def test_guest_mode_no_image_gen(self):
        prompt = system_prompt(guest_mode=True)
        assert "generate" not in prompt.lower() or "image" not in prompt.lower()

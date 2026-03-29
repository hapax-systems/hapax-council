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

    def test_guest_mode_no_bridge_instructions(self):
        """Guest mode has no tools, so no bridge instructions needed."""
        prompt = system_prompt(guest_mode=True)
        assert "tool" not in prompt.lower()


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

"""Tests for ThreadEntry format, tiered compression, and grounding state."""

from __future__ import annotations


class TestThreadEntry:
    def test_construction(self):
        from agents.hapax_daimonion.conversation_pipeline import ThreadEntry

        entry = ThreadEntry(
            turn=3,
            user_text="what about that beat we were working on",
            response_summary="tempo-sync explained",
            acceptance="ACCEPT",
            grounding_state="grounded",
            is_repair=False,
        )
        assert entry.turn == 3
        assert entry.user_text == "what about that beat we were working on"
        assert entry.acceptance == "ACCEPT"
        assert entry.grounding_state == "grounded"
        assert not entry.is_repair
        assert not entry.is_seeded

    def test_acceptance_to_grounding_mapping(self):
        from agents.hapax_daimonion.conversation_pipeline import ThreadEntry

        assert ThreadEntry.acceptance_to_grounding("ACCEPT") == "grounded"
        assert ThreadEntry.acceptance_to_grounding("CLARIFY") == "in-repair"
        assert ThreadEntry.acceptance_to_grounding("REJECT") == "ungrounded"
        assert ThreadEntry.acceptance_to_grounding("IGNORE") == "ungrounded"
        assert ThreadEntry.acceptance_to_grounding("UNKNOWN") == "pending"

    def test_seeded_entry(self):
        from agents.hapax_daimonion.conversation_pipeline import ThreadEntry

        entry = ThreadEntry(
            turn=0,
            user_text="prior session topic",
            response_summary="discussed",
            is_seeded=True,
        )
        assert entry.is_seeded

    def test_repair_entry(self):
        from agents.hapax_daimonion.conversation_pipeline import ThreadEntry

        entry = ThreadEntry(
            turn=5,
            user_text="no the aux send",
            response_summary="which send",
            acceptance="CLARIFY",
            grounding_state="in-repair",
            is_repair=True,
        )
        assert entry.is_repair


class TestExtractSubstanceVerbatim:
    def test_preserves_full_text(self):
        from agents.hapax_daimonion.conversation_pipeline import _extract_substance

        result = _extract_substance("what about that beat we were working on")
        assert result == "what about that beat we were working on"

    def test_strips_greeting(self):
        from agents.hapax_daimonion.conversation_pipeline import _extract_substance

        result = _extract_substance("hey hapax, what about that beat")
        assert result == "what about that beat"

    def test_no_comma_splitting(self):
        from agents.hapax_daimonion.conversation_pipeline import _extract_substance

        result = _extract_substance("I want the router, the salience one")
        assert "the salience one" in result

    def test_no_period_splitting(self):
        from agents.hapax_daimonion.conversation_pipeline import _extract_substance

        result = _extract_substance("Check the pipeline. The effects one.")
        assert "The effects one" in result

    def test_max_100_chars(self):
        from agents.hapax_daimonion.conversation_pipeline import _extract_substance

        result = _extract_substance("x" * 150)
        assert len(result) == 100


class TestThreadRendering:
    def _make_entries(self, n: int) -> list:
        from agents.hapax_daimonion.conversation_pipeline import ThreadEntry

        entries = []
        for i in range(n):
            entries.append(
                ThreadEntry(
                    turn=i + 1,
                    user_text=f"user text for turn {i + 1}",
                    response_summary=f"response for turn {i + 1}",
                    acceptance="ACCEPT" if i % 2 == 0 else "IGNORE",
                    grounding_state="grounded" if i % 2 == 0 else "ungrounded",
                    is_repair=False,
                )
            )
        return entries

    def test_recent_tier_has_quotes(self):
        from agents.hapax_daimonion.conversation_pipeline import _render_thread

        entries = self._make_entries(3)
        rendered = _render_thread(entries)
        # All 3 entries are in the recent tier (age < 3)
        assert '"user text for turn 1"' in rendered
        assert '"user text for turn 3"' in rendered

    def test_oldest_tier_no_quotes(self):
        from agents.hapax_daimonion.conversation_pipeline import _render_thread

        entries = self._make_entries(10)
        rendered = _render_thread(entries)
        lines = rendered.strip().split("\n")
        # First entry (oldest, age=9) should NOT have quotes
        assert '"' not in lines[0]

    def test_ten_entry_cap(self):
        from agents.hapax_daimonion.conversation_pipeline import _render_thread

        entries = self._make_entries(10)
        rendered = _render_thread(entries)
        lines = rendered.strip().split("\n")
        assert len(lines) == 10

    def test_repair_prefix(self):
        from agents.hapax_daimonion.conversation_pipeline import ThreadEntry, _render_thread

        entries = [
            ThreadEntry(
                turn=1,
                user_text="what about aux",
                response_summary="which aux",
                acceptance="CLARIFY",
                grounding_state="in-repair",
                is_repair=True,
            ),
        ]
        rendered = _render_thread(entries)
        assert "REPAIR:" in rendered

    def test_seeded_entry_has_prior_marker(self):
        from agents.hapax_daimonion.conversation_pipeline import ThreadEntry, _render_thread

        entries = [
            ThreadEntry(
                turn=0,
                user_text="prior session topic",
                response_summary="discussed",
                is_seeded=True,
            ),
        ]
        rendered = _render_thread(entries)
        assert "[PRIOR]" in rendered

    def test_acceptance_labels_in_output(self):
        from agents.hapax_daimonion.conversation_pipeline import ThreadEntry, _render_thread

        entries = [
            ThreadEntry(
                turn=1,
                user_text="test",
                response_summary="ok",
                acceptance="ACCEPT",
                grounding_state="grounded",
                is_repair=False,
            ),
        ]
        rendered = _render_thread(entries)
        assert "ACCEPT" in rendered


class TestExperimentPrompt:
    def test_experiment_prompt_under_250_tokens(self):
        from agents.hapax_daimonion.persona import system_prompt

        prompt = system_prompt(experiment_mode=True)
        # Rough token estimate: ~4 chars per token
        assert len(prompt) < 1000  # 250 tokens * 4 chars

    def test_experiment_prompt_no_tools(self):
        from agents.hapax_daimonion.persona import system_prompt

        prompt = system_prompt(experiment_mode=True)
        assert "get_calendar_today" not in prompt
        assert "search_emails" not in prompt
        assert "send_sms" not in prompt

    def test_experiment_prompt_has_persona(self):
        from agents.hapax_daimonion.persona import system_prompt

        prompt = system_prompt(experiment_mode=True)
        assert "Hapax" in prompt
        assert "warm" in prompt.lower()

    def test_normal_prompt_still_has_tools(self):
        from agents.hapax_daimonion.persona import system_prompt

        prompt = system_prompt(experiment_mode=False)
        assert "get_calendar_today" in prompt


class TestExperimentPolicy:
    def test_experiment_policy_minimal(self):
        from agents.hapax_daimonion.conversational_policy import get_policy

        policy = get_policy(experiment_mode=True)
        assert "truthful" in policy  # dignity floor
        assert "Dry wit" in policy  # minimal style
        assert "Socrates" not in policy  # full style stripped
        assert "phone" not in policy.lower()  # env modulation stripped

    def test_normal_policy_has_full_style(self):
        from agents.hapax_daimonion.conversational_policy import get_policy

        policy = get_policy(experiment_mode=False)
        assert "Socrates" in policy

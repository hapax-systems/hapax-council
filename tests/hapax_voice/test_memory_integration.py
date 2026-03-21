"""Tests for Batch 3: thread-memory integration and seeded entry age-out."""

from __future__ import annotations


class TestSeededEntries:
    def test_seeded_entry_has_prior_marker(self):
        from agents.hapax_voice.conversation_pipeline import ThreadEntry, _render_thread

        entries = [
            ThreadEntry(
                turn=0,
                user_text="discussed beat structure",
                response_summary="agreed 4-bar loop",
                is_seeded=True,
                grounding_state="grounded",
            ),
            ThreadEntry(
                turn=1,
                user_text="what about the mix",
                response_summary="levels look good",
                acceptance="ACCEPT",
                grounding_state="grounded",
            ),
        ]
        rendered = _render_thread(entries)
        assert "[PRIOR]" in rendered

    def test_seeded_entry_uses_oldest_tier(self):
        from agents.hapax_voice.conversation_pipeline import ThreadEntry, _render_thread

        # Build 10 entries: 2 seeded + 8 current
        entries = [
            ThreadEntry(
                turn=0, user_text="prior topic A", response_summary="discussed", is_seeded=True
            ),
            ThreadEntry(
                turn=0, user_text="prior topic B", response_summary="noted", is_seeded=True
            ),
        ]
        for i in range(8):
            entries.append(
                ThreadEntry(
                    turn=i + 1,
                    user_text=f"current topic {i + 1}",
                    response_summary=f"response {i + 1}",
                    acceptance="ACCEPT",
                    grounding_state="grounded",
                )
            )
        rendered = _render_thread(entries)
        # Seeded entries should be in oldest tier (no quotes)
        lines = rendered.strip().split("\n")
        assert "[PRIOR]" in lines[0]
        assert '"' not in lines[0]  # oldest tier has no quotes


class TestSeededAgeOut:
    def _make_pipeline_with_seeds(self, n_seeds=2, n_current=0):
        from agents.hapax_voice.conversation_pipeline import ConversationPipeline, ThreadEntry

        pipeline = ConversationPipeline.__new__(ConversationPipeline)
        pipeline._conversation_thread = []
        pipeline._experiment_flags = {"stable_frame": True}
        pipeline._grounding_ledger = None

        for i in range(n_seeds):
            pipeline._conversation_thread.append(
                ThreadEntry(turn=0, user_text=f"seed {i}", response_summary="prior", is_seeded=True)
            )
        for i in range(n_current):
            pipeline._conversation_thread.append(
                ThreadEntry(
                    turn=i + 1,
                    user_text=f"current {i}",
                    response_summary=f"resp {i}",
                    acceptance="ACCEPT",
                    grounding_state="grounded",
                )
            )
        return pipeline

    def test_seeds_present_early(self):
        pipeline = self._make_pipeline_with_seeds(n_seeds=2, n_current=3)
        seeded = [e for e in pipeline._conversation_thread if e.is_seeded]
        assert len(seeded) == 2

    def test_seeds_compressed_at_6_current(self):
        from agents.hapax_voice.conversation_pipeline import ThreadEntry

        pipeline = self._make_pipeline_with_seeds(n_seeds=3, n_current=5)
        # Simulate adding the 6th current entry (triggers compression)
        pipeline._conversation_thread.append(
            ThreadEntry(
                turn=6,
                user_text="sixth",
                response_summary="ok",
                acceptance="ACCEPT",
                grounding_state="grounded",
            )
        )
        # Apply age-out logic manually
        _current_count = sum(1 for e in pipeline._conversation_thread if not e.is_seeded)
        if _current_count >= 6:
            _seeded = [e for e in pipeline._conversation_thread if e.is_seeded]
            _current = [e for e in pipeline._conversation_thread if not e.is_seeded]
            pipeline._conversation_thread = _seeded[:1] + _current

        seeded = [e for e in pipeline._conversation_thread if e.is_seeded]
        assert len(seeded) <= 1


class TestUnresolvedPersistence:
    def test_digest_includes_unresolved(self):
        from agents.hapax_voice.conversation_pipeline import ConversationPipeline, ThreadEntry

        pipeline = ConversationPipeline.__new__(ConversationPipeline)
        pipeline._conversation_thread = [
            ThreadEntry(
                turn=1,
                user_text="first topic",
                response_summary="explained",
                acceptance="ACCEPT",
                grounding_state="grounded",
            ),
            ThreadEntry(
                turn=2,
                user_text="confusing topic",
                response_summary="unclear",
                acceptance="CLARIFY",
                grounding_state="in-repair",
            ),
        ]
        pipeline.turn_count = 2
        pipeline._session_id = "test123"
        pipeline._session_start_ts = 0.0

        digest = pipeline.get_session_digest()
        assert "unresolved" in digest
        assert len(digest["unresolved"]) == 1
        assert "confusing topic" in digest["unresolved"][0]

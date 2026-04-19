"""Music-narrative anti-repetition pins.

Operator complaint 2026-04-19: "Hapax says the same stupid thing over and over
again about the vinyl tracks. I mean: unacceptably stupid"

Three different vinyl tracks all narrated with the same template:
  - "Let's take a moment to appreciate the captivating narrative of '...'"
  - "As the vinyl spins, the subtle beats of '...' from <album>..."
  - "Let's continue to appreciate the subtle beats and melodies of '...'"

The fix in ``director_loop.py`` has three additive layers:

  1. ``BANNED OPENERS`` block in the unified prompt enumerates the
     audio-tour-narrator phrases verbatim so even a weak LLM cannot
     claim ignorance.
  2. ``_narrative_too_similar()`` tightened: Jaccard 0.60 → 0.35,
     history 5 → 15, plus a 3-shingle n-gram check that catches
     "subtle beats of <track A>" → "subtle beats of <track B>"
     template re-use even when the variable token drops Jaccard
     below threshold.
  3. ``_recent_music_narratives`` separate from the general
     narrative history so the dedup stays track-aware across
     intervening non-music ticks.

Each test pins one invariant.
"""

from __future__ import annotations

import json as _json

from agents.studio_compositor.director_loop import DirectorLoop


class _FakeSlot:
    def __init__(self, slot_id: int) -> None:
        self.slot_id = slot_id
        self._title = "test video"
        self._channel = "test channel"
        self.is_active = slot_id == 0


class _FakeReactor:
    def set_header(self, *a, **k) -> None:
        pass

    def set_text(self, *a, **k) -> None:
        pass

    def set_speaking(self, *a, **k) -> None:
        pass

    def feed_pcm(self, *a, **k) -> None:
        pass


def _director() -> DirectorLoop:
    return DirectorLoop(
        video_slots=[_FakeSlot(0), _FakeSlot(1), _FakeSlot(2)],
        reactor_overlay=_FakeReactor(),
    )


# ─── Layer 1: prompt-level ban ────────────────────────────────────────


class TestBannedOpenersInPrompt:
    """The assembled prompt must enumerate the appreciation-bot openers."""

    def test_let_us_take_a_moment_is_banned(self) -> None:
        director = _director()
        prompt = director._build_unified_prompt()
        assert "let's take a moment to appreciate" in prompt.lower()

    def test_let_us_continue_to_appreciate_is_banned(self) -> None:
        director = _director()
        prompt = director._build_unified_prompt()
        assert "let's continue to appreciate" in prompt.lower()

    def test_as_the_vinyl_spins_is_banned(self) -> None:
        director = _director()
        prompt = director._build_unified_prompt()
        assert "as the vinyl spins" in prompt.lower()

    def test_subtle_beats_template_is_banned(self) -> None:
        director = _director()
        prompt = director._build_unified_prompt()
        assert "subtle beats" in prompt.lower()

    def test_captivating_template_is_banned(self) -> None:
        director = _director()
        prompt = director._build_unified_prompt()
        assert "captivating" in prompt.lower()

    def test_music_narrative_discipline_section_present(self) -> None:
        director = _director()
        prompt = director._build_unified_prompt()
        assert "Music narrative discipline" in prompt

    def test_positive_directive_says_be_a_host_not_docent(self) -> None:
        """The positive instruction (host, concrete, named instruments,
        crunchy/blunt voice) must accompany the bans — otherwise the
        LLM has nothing to reach for after the negation."""
        director = _director()
        prompt = director._build_unified_prompt()
        low = prompt.lower()
        assert "host" in low
        # At least one of the positive verbs (concrete/crunchy/blunt) must
        # be present so the LLM reads instructions on what TO do, not just
        # what NOT to do.
        assert any(word in low for word in ("concrete", "crunchy", "blunt"))


# ─── Layer 2: tightened similarity check ─────────────────────────────


class TestJaccardThreshold:
    """The Jaccard threshold tightens from 0.60 to 0.35 against history of 15."""

    def test_class_constants_match_2026_04_19_tuning(self) -> None:
        assert DirectorLoop._NARRATIVE_DEDUP_JACCARD == 0.35
        assert DirectorLoop._NARRATIVE_DEDUP_HISTORY_LEN == 15
        assert DirectorLoop._NARRATIVE_DEDUP_SHINGLE_K == 3
        assert DirectorLoop._MUSIC_NARRATIVE_HISTORY_LEN == 10

    def test_forty_percent_word_overlap_is_rejected_at_new_threshold(self) -> None:
        """Two narratives sharing ~40% of their content tokens used to slide
        through under the 0.60 threshold; now they must reject. Test text is
        hand-tuned so Jaccard lands in [0.35, 0.60) — the new-but-not-old
        rejection window — and the dedup must trip on Jaccard alone (no
        shingle-match coincidence)."""
        director = _director()
        prior = (
            "operator just dropped sparse breakbeat heavy hihat decay "
            "bassline sitting deep under kick crack snare punch"
        )
        director._remember_narrative(prior)
        candidate = (
            "operator chose sparse breakbeat heavy snare crack bassline "
            "weaves around kick punch hard hitting steady"
        )
        # Jaccard sanity: overlap divided by union should be in (0.35, 0.60).
        cand_words = DirectorLoop._narrative_word_set(candidate)
        prior_words = DirectorLoop._narrative_word_set(prior)
        union = len(cand_words | prior_words)
        intersection = len(cand_words & prior_words)
        jaccard = intersection / union
        assert 0.35 <= jaccard < 0.60, (
            f"test setup: candidate/prior overlap drifted to {jaccard:.2f}; "
            "the test is meaningless if it doesn't sit in the new-but-not-old window"
        )
        assert director._narrative_too_similar(candidate) is True

    def test_low_overlap_narratives_pass(self) -> None:
        """Sanity: completely different content should NOT trip the dedup."""
        director = _director()
        director._remember_narrative(
            "the operator just dropped a sparse breakbeat with heavy hihat decay"
        )
        candidate = (
            "chat is asking about the patchbay routing and whether the moog "
            "sequence runs through the tape echo or straight into the desk"
        )
        assert director._narrative_too_similar(candidate) is False


class TestHistorySize:
    """The dedup history is 15 entries deep — older narratives still count."""

    def test_thirteenth_back_still_dedups(self) -> None:
        director = _director()
        target = (
            "this kick has a hollow click on the attack and a long subby tail "
            "that sits right under the snare crack on every two and four"
        )
        director._remember_narrative(target)
        for i in range(13):
            director._remember_narrative(
                f"unrelated narrative number {i} mentions completely "
                "different topics like patchbays cables routing levels"
            )
        # Target is now 14 entries back. With history=5 it would be flushed.
        # With history=15 it should still trip dedup on a near-restatement.
        candidate = (
            "this kick still has the hollow click on the attack with the "
            "long subby tail sitting under the snare crack on two and four"
        )
        assert director._narrative_too_similar(candidate) is True

    def test_sixteenth_back_does_get_flushed(self) -> None:
        """History=15 means narratives older than 15 entries ARE gone."""
        director = _director()
        target = (
            "this kick has a hollow click on the attack and a long subby tail "
            "that sits right under the snare crack on every two and four"
        )
        director._remember_narrative(target)
        for i in range(16):
            director._remember_narrative(
                f"unrelated narrative number {i} mentions completely "
                "different topics like patchbays cables routing levels"
            )
        candidate = (
            "this kick still has the hollow click on the attack with the "
            "long subby tail sitting under the snare crack on two and four"
        )
        assert director._narrative_too_similar(candidate) is False


# ─── Layer 3: shingle / bigram n-gram dedup ──────────────────────────


class TestShingleDedup:
    """3-shingle on ≥4-char tokens catches verbatim phrase re-use; a
    secondary bigram-overlap pass catches the template re-use ("subtle
    beats of <track A>" vs "subtle beats of <track B>") that the strict
    3-shingle would miss when only the variable token differs."""

    def test_verbatim_three_word_phrase_shingle_match(self) -> None:
        """A direct verbatim 3-word reuse trips shingle dedup."""
        director = _director()
        director._remember_narrative(
            "the bassline is sitting deep under the kick on this break "
            "and the operator just opened the high hat"
        )
        candidate = (
            "and now the bassline is sitting deep under the snare crack "
            "on a completely different beat with cymbals"
        )
        # "bassline sitting deep" shingle is shared verbatim.
        assert ("bassline", "sitting", "deep") in DirectorLoop._narrative_shingles(
            "the bassline is sitting deep under the kick"
        )
        assert director._narrative_too_similar(candidate) is True

    def test_template_reuse_across_two_tracks_via_bigram_overlap(self) -> None:
        """The exact failure mode the operator flagged: opener template
        re-used across DIFFERENT vinyl tracks. Two bigrams from the
        opener template ("subtle beats", "appreciate the", etc.) recur
        even when the track-specific tail differs — that multi-bigram
        overlap fingerprint is what the bigram pass catches."""
        director = _director()
        prior = (
            "let's take a moment to appreciate the captivating narrative "
            "of donuts and how dilla layered those horn loops"
        )
        director._remember_narrative(prior)
        candidate = (
            "let's take a moment to appreciate the captivating narrative "
            "of madvillainy from those organ stabs and bowed bass"
        )
        cand_bigrams = DirectorLoop._narrative_bigrams(candidate)
        prior_bigrams = DirectorLoop._narrative_bigrams(prior)
        shared = cand_bigrams & prior_bigrams
        assert len(shared) >= 2, (
            f"test setup: only {len(shared)} bigram(s) match; expected ≥2 to "
            "trip the bigram-overlap pass"
        )
        assert director._narrative_too_similar(candidate) is True

    def test_shingle_helper_extracts_three_token_windows(self) -> None:
        sh = DirectorLoop._narrative_shingles("the subtle beats of donuts are stitched together")
        # Words ≥4 chars: subtle, beats, donuts, stitched, together.
        # ("the", "are", "of") are dropped by the ≥4 filter.
        assert ("subtle", "beats", "donuts") in sh
        assert ("beats", "donuts", "stitched") in sh

    def test_bigram_helper_extracts_pairs(self) -> None:
        bg = DirectorLoop._narrative_bigrams(
            "let's take a moment to appreciate the captivating narrative"
        )
        # Words ≥4 chars: take, moment, appreciate, captivating, narrative.
        assert ("take", "moment") in bg
        assert ("moment", "appreciate") in bg
        assert ("appreciate", "captivating") in bg

    def test_shingle_handles_short_input(self) -> None:
        # Fewer than k content tokens → empty shingle set, dedup falls
        # through to Jaccard alone.
        assert DirectorLoop._narrative_shingles("hi yo") == set()

    def test_single_bigram_match_does_not_trip(self) -> None:
        """Threshold is ≥2 bigram matches — a single coincidental bigram
        share between otherwise-distinct narratives must not false-positive."""
        director = _director()
        director._remember_narrative(
            "the bassline weaves under steady kick and the snare smacks loud"
        )
        # Shares "kick snare" bigram via different surrounding context but
        # nothing else; should pass.
        candidate = (
            "chat is asking why patchbay routing matters and whether tape "
            "echo runs into the desk before the kick snare bus reaches mix"
        )
        assert director._narrative_too_similar(candidate) is False


# ─── Layer 4: music-history isolation ────────────────────────────────


class TestMusicSpecificHistory:
    """`activity='music'` rememberance populates the music-only history,
    and music-specific dedup runs against that history first."""

    def test_remember_with_music_activity_populates_music_history(self) -> None:
        director = _director()
        director._remember_narrative(
            "this break is a hard pan on the hat and a tight kick", activity="music"
        )
        assert getattr(director, "_recent_music_narratives", []) == [
            "this break is a hard pan on the hat and a tight kick"
        ]

    def test_remember_without_music_activity_skips_music_history(self) -> None:
        director = _director()
        director._remember_narrative("the operator is at the patchbay", activity="react")
        assert getattr(director, "_recent_music_narratives", []) == []

    def test_music_specific_dedup_uses_music_history(self) -> None:
        """A near-restatement should trip the music-specific check even
        if the general history would have flushed it."""
        director = _director()
        director._remember_narrative(
            "the subtle beats of donuts thread through chopped horns", activity="music"
        )
        # Push lots of unrelated entries into the GENERAL history only —
        # the music history still holds the prior music narrative.
        for i in range(20):
            director._reaction_history.append(f"[12:{i:02d}] react: unrelated text {i}")
            director._recent_narratives = (
                getattr(director, "_recent_narratives", []) + [f"unrelated react paragraph {i}"]
            )[-15:]
        candidate = "the subtle beats of madvillainy thread through chopped organ stabs"
        assert director._narrative_too_similar(candidate, music_specific=True) is True

    def test_music_history_capped_at_ten(self) -> None:
        director = _director()
        for i in range(15):
            director._remember_narrative(
                f"music narrative number {i} talks about a different track",
                activity="music",
            )
        assert len(director._recent_music_narratives) == 10
        # The most-recent 10 should be 5..14.
        assert "number 5" in director._recent_music_narratives[0]
        assert "number 14" in director._recent_music_narratives[-1]


# ─── Layer 5: track-grounded album info ──────────────────────────────


class TestAlbumInfoGrounding:
    """`_read_album_info()` surfaces concrete signal the host can ground in."""

    def test_includes_rate_and_rpm_when_rate_file_present(self, tmp_path, monkeypatch) -> None:
        from agents.studio_compositor import director_loop
        from shared import vinyl_rate as _vr

        state = tmp_path / "album-state.json"
        state.write_text(
            _json.dumps(
                {
                    "artist": "MF DOOM",
                    "title": "Mm.. Food",
                    "current_track": "Hoe Cakes",
                    "confidence": 0.9,
                }
            )
        )
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", state)
        # Force a non-1.0 vinyl rate via the float file so the extras
        # include rate/rpm regardless of host environment.
        rate_file = tmp_path / "vinyl-playback-rate.txt"
        rate_file.write_text("0.741")
        monkeypatch.setattr(_vr, "_RATE_FILE", rate_file)
        info = director_loop._read_album_info()
        assert "Mm.. Food" in info
        assert "MF DOOM" in info
        assert "Hoe Cakes" in info
        assert "rate=" in info
        assert "rpm" in info

    def test_handles_missing_state_gracefully(self, tmp_path, monkeypatch) -> None:
        from agents.studio_compositor import director_loop

        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", tmp_path / "absent.json")
        assert director_loop._read_album_info() == "unknown"

    def test_includes_track_position_when_album_state_carries_it(
        self, tmp_path, monkeypatch
    ) -> None:
        from agents.studio_compositor import director_loop

        state = tmp_path / "album-state.json"
        state.write_text(
            _json.dumps(
                {
                    "artist": "King Geedorah",
                    "title": "Take Me to Your Leader",
                    "current_track": "I Wonder",
                    "confidence": 0.9,
                    "track_elapsed_s": 100.0,
                    "track_duration_s": 242.0,
                }
            )
        )
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", state)
        info = director_loop._read_album_info()
        assert "1m40s" in info
        assert "4m02s" in info


# ─── Sanity: prompt assembles cleanly ────────────────────────────────


class TestPromptAssembly:
    def test_prompt_assembles_without_error(self) -> None:
        director = _director()
        prompt = director._build_unified_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 1000

    def test_music_signal_block_label_present_when_vinyl_playing(
        self, tmp_path, monkeypatch
    ) -> None:
        from agents.studio_compositor import director_loop

        state = tmp_path / "album-state.json"
        state.write_text(
            _json.dumps(
                {
                    "artist": "Madlib",
                    "title": "Shades of Blue",
                    "current_track": "Slim's Return",
                    "confidence": 0.9,
                }
            )
        )
        monkeypatch.setattr(director_loop, "ALBUM_STATE_FILE", state)
        director = _director()
        prompt = director._build_unified_prompt()
        assert "Current music signal:" in prompt
        assert "Shades of Blue" in prompt

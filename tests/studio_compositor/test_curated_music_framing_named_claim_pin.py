"""Regression pin: ``_curated_music_framing`` must not leak named music
claims unless audio + identification evidence both agree.

Companion to ``test_director_album_info_not_playing_guard.py`` (which
pins the album-info side of the leak) and ``test_llm_frame_album_mask.py``
(which pins the LLM-frame redaction layer). This pin closes the
4-branch decision matrix in
``agents/studio_compositor/director_loop.py::_curated_music_framing``
so a future refactor cannot regress any branch silently.

The named-music-hallucination cycle (operator-reported, recurred
multiple times in the last weeks despite earlier fixes — see cc-task
``music-named-claim-regression-pin``) shows up exactly here: this
function is the one composing the music-provenance phrase that lands
in the director-loop prompt context. Every branch must either:

  * carry named claims that are independently grounded in PANNs/YT
    queue evidence, OR
  * fall back to source-agnostic phrasing AND assert no specific
    artist/title/channel name leaks through.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agents.studio_compositor import director_loop


def _set_album_state(tmp_path: Path, *, playing: bool, artist: str, title: str) -> Path:
    """Write an album-state.json fixture and return the path."""
    state_path = tmp_path / "album-state.json"
    state_path.write_text(
        f'{{"artist": "{artist}", "title": "{title}", "current_track": "", '
        f'"playing": {"true" if playing else "false"}}}',
        encoding="utf-8",
    )
    return state_path


# ── Branch 1: vinyl_is_playing=True ──────────────────────────────────


class TestVinylBranch:
    """When the vinyl engine asserts spinning, the phrase must include a
    named claim ONLY when album-state independently confirms playing
    AND artist/title are populated. The double gate (engine + file
    state) is the structural defense against the recurring leak: a
    record sitting on the deck NOT spinning produces a stale
    cover-recognition write that must not become a public claim even
    if the engine briefly mis-fires."""

    def test_vinyl_engine_true_but_album_state_not_playing_yields_no_named_claim(
        self, tmp_path: Path
    ) -> None:
        """The most-reported leak shape: engine says spinning, file says
        not playing (cover sitting on deck). The phrase must not name
        the artist/title that album-identifier wrote."""
        state_path = _set_album_state(
            tmp_path,
            playing=False,
            artist="Metal Fingers (MF DOOM)",
            title="Special Herbs, Vols. 7 & 8",
        )
        with (
            patch.object(director_loop, "ALBUM_STATE_FILE", state_path),
            patch.object(director_loop, "_vinyl_is_playing", return_value=True),
        ):
            phrase = director_loop._curated_music_framing("", "", "Oudepode")
        assert "Metal Fingers" not in phrase
        assert "MF DOOM" not in phrase
        assert "Special Herbs" not in phrase
        # The phrase still says "spinning vinyl" because the engine
        # asserted it; the named claim is what's gated.
        assert "spinning vinyl" in phrase
        assert "no music playing" in phrase or "unknown" in phrase

    def test_vinyl_engine_true_album_state_playing_with_names_yields_named_claim(
        self, tmp_path: Path
    ) -> None:
        """The supported-named-claim shape: engine + file BOTH agree.
        This branch SHOULD include the name — pinning so a future
        over-aggressive guard doesn't blank out legitimate claims."""
        state_path = _set_album_state(
            tmp_path,
            playing=True,
            artist="Pete Rock",
            title="Soul Survivor",
        )
        with (
            patch.object(director_loop, "ALBUM_STATE_FILE", state_path),
            patch.object(director_loop, "_vinyl_is_playing", return_value=True),
        ):
            phrase = director_loop._curated_music_framing("", "", "Oudepode")
        assert "Soul Survivor" in phrase
        assert "Pete Rock" in phrase
        assert "spinning vinyl" in phrase


# ── Branch 2: vinyl=False, music_in_broadcast=True, slot_title set ──


class TestCuratedQueueBranch:
    """PANNs hears music AND a YT slot title is supplied → curated-queue
    framing carries the slot's named identity. The named claim is
    grounded in operator-curated queue state per directive 2026-04-17."""

    def test_panns_music_with_slot_yields_named_curated_queue(self, tmp_path: Path) -> None:
        with (
            patch.object(director_loop, "_vinyl_is_playing", return_value=False),
            patch.object(director_loop, "_music_is_playing_in_broadcast", return_value=True),
        ):
            phrase = director_loop._curated_music_framing(
                slot_title="Madvillainy",
                slot_channel="Madlib + MF DOOM",
                referent="Oudepode",
            )
        assert "Madvillainy" in phrase
        assert "Madlib + MF DOOM" in phrase
        assert "curated queue" in phrase


# ── Branch 3: vinyl=False, music_in_broadcast=True, slot_title="" ──


class TestPannsButNoSlotBranch:
    """PANNs heard music but the YT slot file is empty/stale —
    audio-evidence ground truth disagrees with queue-state file. The
    fallback phrase must say "curated source" without naming any
    artist/title/channel. This is the second-most-reported leak shape:
    PANNs says music, slot is stale from yesterday's queue, the older
    code naively used the stale slot_title."""

    def test_panns_music_no_slot_yields_source_agnostic_no_named_claim(
        self, tmp_path: Path
    ) -> None:
        with (
            patch.object(director_loop, "_vinyl_is_playing", return_value=False),
            patch.object(director_loop, "_music_is_playing_in_broadcast", return_value=True),
        ):
            phrase = director_loop._curated_music_framing(
                slot_title="",
                slot_channel="",
                referent="Oudepode",
            )
        # Source-agnostic phrasing — the contract.
        assert "curated source" in phrase
        # No named claim — the regression pin.
        assert "Madvillainy" not in phrase
        assert "MF DOOM" not in phrase
        assert "queue" not in phrase  # not from the queue per the schema
        # Referent is allowed (it's the operator non-formal name).
        assert "Oudepode" in phrase


# ── Branch 4: silence ────────────────────────────────────────────────


class TestSilenceBranch:
    """Neither vinyl nor PANNs music — silence is the asserted state.
    The phrase must NOT mention any music, named or otherwise. This is
    the strongest pin: silence must be visible to the LLM as silence,
    or the LLM context drifts into music-narration mode anyway."""

    def test_silence_yields_quiet_phrase_no_music_words(self) -> None:
        with (
            patch.object(director_loop, "_vinyl_is_playing", return_value=False),
            patch.object(director_loop, "_music_is_playing_in_broadcast", return_value=False),
        ):
            phrase = director_loop._curated_music_framing(
                slot_title="Madvillainy",  # even with stale slot data
                slot_channel="Madlib + MF DOOM",
                referent="Oudepode",
            )
        assert "quiet" in phrase
        # NOT silence-with-music-mention — even if slot_title is set,
        # the silence branch must take precedence and ignore it.
        assert "Madvillainy" not in phrase
        assert "MF DOOM" not in phrase
        assert "curated" not in phrase
        assert "spinning vinyl" not in phrase

    def test_silence_branch_ignores_referent_in_music_words(self) -> None:
        """Silence branch produces "the room is quiet" — the operator
        referent is NOT in the silence phrase (it would create a
        misattribution that the operator is choosing silence rather
        than describing it)."""
        with (
            patch.object(director_loop, "_vinyl_is_playing", return_value=False),
            patch.object(director_loop, "_music_is_playing_in_broadcast", return_value=False),
        ):
            phrase = director_loop._curated_music_framing("", "", "Oudepode")
        assert "Oudepode" not in phrase
        assert "quiet" in phrase


# ── Cross-branch invariant ──────────────────────────────────────────


class TestNamedClaimRequiresEvidence:
    """Cross-branch pin: any named-music token in the phrase output
    requires AT LEAST ONE of the evidence sources to be true. The
    test enumerates known artist/track names that have appeared in
    operator-reported regressions and asserts they cannot appear
    when neither vinyl nor PANNs evidence holds."""

    HISTORICAL_REGRESSION_NAMES = ("MF DOOM", "Madvillainy", "Pete Rock", "Special Herbs")

    def test_no_evidence_no_named_token(self) -> None:
        """The strongest invariant: silence + empty slot → none of
        the historical regression names appear, regardless of input."""
        with (
            patch.object(director_loop, "_vinyl_is_playing", return_value=False),
            patch.object(director_loop, "_music_is_playing_in_broadcast", return_value=False),
        ):
            phrase = director_loop._curated_music_framing("", "", "Oudepode")
        for name in self.HISTORICAL_REGRESSION_NAMES:
            assert name not in phrase, (
                f"named-claim leak: {name!r} appeared with no evidence "
                f"(silence branch). phrase={phrase!r}"
            )

    def test_panns_music_empty_slot_no_named_token(self) -> None:
        """PANNs music + no slot → fallback phrase has no named claim."""
        with (
            patch.object(director_loop, "_vinyl_is_playing", return_value=False),
            patch.object(director_loop, "_music_is_playing_in_broadcast", return_value=True),
        ):
            phrase = director_loop._curated_music_framing("", "", "Oudepode")
        for name in self.HISTORICAL_REGRESSION_NAMES:
            assert name not in phrase, (
                f"named-claim leak: {name!r} appeared with PANNs+no-slot "
                f"(source-agnostic branch). phrase={phrase!r}"
            )

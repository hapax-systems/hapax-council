"""Regression pin: BANNED NARRATION block in director's unified prompt.

Operator directive 2026-04-19: "we are in a holding pattern -- geez! I
wonder whose job it is to NOT BE IN A HOLDING PATTERN!?"

Hapax was caught narrating META-STATE (pipeline status, director state,
system pauses, silence-hold compositional directives) as if those were
audience-appropriate content — reading stage directions to viewers.

This test pins the BANNED NARRATION block + the specific banned phrases
into the assembled prompt so future prompt rewrites don't regress.
"""

from __future__ import annotations

from unittest.mock import patch

from agents.studio_compositor.director_loop import DirectorLoop


class _FakeSlot:
    """Minimal stand-in for VideoSlotStub — just the fields _build_unified_prompt reads."""

    def __init__(self, slot_id: int) -> None:
        self.slot_id = slot_id
        self._title = "test video"
        self._channel = "test channel"
        self.is_active = slot_id == 0


class _FakeReactor:
    def set_header(self, *args, **kwargs) -> None:
        pass

    def set_text(self, *args, **kwargs) -> None:
        pass

    def set_speaking(self, *args, **kwargs) -> None:
        pass

    def feed_pcm(self, *args, **kwargs) -> None:
        pass


def _director() -> DirectorLoop:
    return DirectorLoop(
        video_slots=[_FakeSlot(0), _FakeSlot(1), _FakeSlot(2)],
        reactor_overlay=_FakeReactor(),
    )


def test_prompt_contains_banned_narration_block_header() -> None:
    """The unified prompt must carry the BANNED NARRATION header verbatim."""
    director = _director()
    prompt = director._build_unified_prompt()
    assert "## BANNED NARRATION — DO NOT SPEAK THESE" in prompt
    assert "BANNED NARRATION — never speak these out loud" in prompt
    assert "operator directive 2026-04-19" in prompt


def test_prompt_contains_meta_state_banned_phrases() -> None:
    """Meta-state phrases must be enumerated so the LLM can't claim ignorance."""
    director = _director()
    prompt = director._build_unified_prompt()
    for phrase in (
        "we are in a holding pattern",
        "let me pause for a moment",
        "let's take a moment to appreciate",
        "let's continue to appreciate",
        "holding the surface",
        "silence hold",
    ):
        assert phrase in prompt, f"banned meta-state phrase missing from prompt: {phrase!r}"


def test_prompt_contains_canned_appreciation_banned_phrases() -> None:
    """Canned reverent-art-critic filler must be enumerated."""
    director = _director()
    prompt = director._build_unified_prompt()
    for phrase in (
        "the subtle beats of...",
        "the captivating rhythm of...",
        "as the vinyl spins...",
    ):
        assert phrase in prompt, f"banned appreciation phrase missing from prompt: {phrase!r}"
    # Generic adjectives line — pin the substring that must appear.
    assert '"subtle"' in prompt
    assert '"captivating"' in prompt
    assert '"intricate"' in prompt
    assert '"beautiful"' in prompt


def test_prompt_contains_stage_directions_ban() -> None:
    """Stage-directions-as-speech section must be present."""
    director = _director()
    prompt = director._build_unified_prompt()
    assert "STAGE DIRECTIONS AS SPEECH" in prompt
    assert "Do not announce what you are about to do" in prompt
    assert "Do not narrate rotation modes" in prompt


def test_prompt_contains_what_to_do_instead_block() -> None:
    """The positive instruction block must accompany the bans.

    Text updated 2026-04-22 (PR #1210) from ``host making a livestream,
    not a system announcer`` → ``ACTIVE LIVESTREAM HOST, not a dumb
    observer or a museum docent``. Subsequently retitled to ``ACTIVE
    STRUCTURAL DIRECTOR ... not a dumb observer or a museum docent`` —
    same intent (active driver, not passive narrator), reframed around
    the director's structural role over the composition. Test
    assertions follow current text.
    """
    director = _director()
    prompt = director._build_unified_prompt()
    assert "WHAT TO DO INSTEAD" in prompt
    assert "ACTIVE STRUCTURAL DIRECTOR" in prompt
    # Source text: "...DRIVE the stream. Be\n  concrete. Be crunchy. Be blunt."
    # The newline+indent between "Be" and "concrete" means a strict
    # "Be concrete. Be crunchy. Be blunt." substring match would be too
    # brittle to surface-level reflowing. Match the load-bearing fragments
    # individually so the test pins INTENT (terse, blunt directive) rather
    # than EXACT line wrapping.
    assert "Be crunchy. Be blunt." in prompt
    assert "concrete." in prompt
    assert "structural director running" in prompt


def test_silence_hold_reactions_filtered_from_recent_reactions() -> None:
    """Silence-hold compositional directives MUST NOT appear in the
    LLM's view of 'Recent Reactions'. They are stage directions for the
    visual pipeline, not prior things Hapax actually said.
    """
    director = _director()
    director._reaction_history = [
        '[12:00] react: "the kick on this one is sharper than the last"',
        (
            '[12:01] silence: "Silence hold: maintain the current surface; '
            'stance indicator breathes, chrome unchanged, no new recruitment this tick."'
        ),
        '[12:02] react: "she just panned the hat hard left"',
    ]
    prompt = director._build_unified_prompt()
    # The genuine reactions must still be present.
    assert "the kick on this one is sharper than the last" in prompt
    assert "she just panned the hat hard left" in prompt
    # The silence-hold compositional directive must NOT leak into the
    # Recent Reactions context window — that is the regression.
    assert "Silence hold: maintain the current surface" not in prompt


def test_prompt_assembly_is_safe_with_empty_reaction_history() -> None:
    """Sanity: prompt builds even when no reaction history exists."""
    director = _director()
    director._reaction_history = []
    # Should not raise; the BANNED block lives outside the reactions
    # section so it must still appear regardless of history state.
    prompt = director._build_unified_prompt()
    assert "## BANNED NARRATION — DO NOT SPEAK THESE" in prompt


def test_prompt_omits_reactions_section_when_only_silence_hold_present() -> None:
    """When the only history entries are silence-holds, the entire
    'Recent Reactions' section should be skipped — not rendered as an
    empty header."""
    director = _director()
    director._reaction_history = [
        '[12:00] silence: "Silence hold: maintain the current surface."',
        '[12:01] silence: "Silence hold: maintain the current surface."',
    ]
    prompt = director._build_unified_prompt()
    assert "## Recent Reactions" not in prompt


# Quiet unused-import warning if patch ends up unused — keep available for
# future test extensions that need to monkeypatch external readers.
_ = patch

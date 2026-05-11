"""AUDIT-18 narrative director programme-context prompt tests."""

from __future__ import annotations

import re
from unittest.mock import patch

from agents.studio_compositor.director_loop import DirectorLoop
from shared.programme import (
    Programme,
    ProgrammeConstraintEnvelope,
    ProgrammeContent,
    ProgrammeRole,
)


class _FakeSlot:
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


def _director(programme_provider=None) -> DirectorLoop:
    return DirectorLoop(
        video_slots=[_FakeSlot(0), _FakeSlot(1), _FakeSlot(2)],
        reactor_overlay=_FakeReactor(),
        programme_provider=programme_provider,
    )


def _programme() -> Programme:
    return Programme(
        programme_id="prog-work-001",
        role=ProgrammeRole.WORK_BLOCK,
        planned_duration_s=1200.0,
        parent_show_id="show-audit-18",
        parent_condition_id="condition-audit-18",
        constraints=ProgrammeConstraintEnvelope(
            capability_bias_negative={"speech_production": 0.25},
            capability_bias_positive={"ambient_texture": 2.0},
            preset_family_priors=["calm-textural", "audio-reactive"],
            homage_rotation_modes=["weighted_by_salience"],
        ),
        content=ProgrammeContent(
            narrative_beat=(
                "Hold the work block as atmosphere; keep the operator's focus "
                "legible without interrupting it."
            )
        ),
    )


def _extract_programme_block(prompt: str) -> str:
    marker = "## Programme context"
    assert marker in prompt, f"programme context marker missing from prompt:\n{prompt}"
    start = prompt.index(marker)
    next_header = prompt.find("\n## ", start + len(marker))
    if next_header == -1:
        return prompt[start:]
    return prompt[start:next_header]


def test_active_programme_renders_soft_prior_context() -> None:
    prompt = _director(lambda: _programme())._build_unified_prompt()
    block = _extract_programme_block(prompt)

    assert "prog-work-001" in block
    assert "`work_block`" in block
    assert "show-audit-18" in block
    assert "condition-audit-18" in block
    assert "Hold the work block as atmosphere" in block
    assert "calm-textural, audio-reactive" in block
    assert "weighted_by_salience" in block
    assert "ambient_texture" in block
    assert "speech_production" in block


def test_programme_context_absent_when_no_programme_or_band() -> None:
    prompt = _director(lambda: None)._build_unified_prompt()
    assert "## Programme context" not in prompt


def test_programme_band_renders_without_active_programme() -> None:
    director = _director(lambda: None)
    director._current_programme_band = (2, 4)

    block = _extract_programme_block(director._build_unified_prompt())
    assert "current programme voice tier band: 2-4" in block


def test_programme_provider_failure_preserves_legacy_prompt() -> None:
    def boom() -> Programme | None:
        raise RuntimeError("store unavailable")

    prompt = _director(boom)._build_unified_prompt()
    assert "## Programme context" not in prompt


def test_segment_binding_prompt_block_is_spliced_into_director_prompt() -> None:
    with patch(
        "agents.studio_compositor.director_segment_runner.render_director_segment_binding_prompt",
        return_value=[
            "## Segment director binding",
            "- runtime layout receipt: `held` / `default_static_layout_in_responsible_hosting` -> `segment-tier`",
        ],
    ):
        prompt = _director(lambda: _programme())._build_unified_prompt()

    assert "## Segment director binding" in prompt
    assert "segment-tier" in prompt


def test_programme_context_is_soft_prior_not_hard_gate() -> None:
    block = _extract_programme_block(_director(lambda: _programme())._build_unified_prompt())
    lower = block.lower()

    assert "soft-prior" in lower
    assert "bias toward" in lower
    assert "override posture" in lower
    assert re.search(r"\b(must|required|only|never|forbidden)\b", lower) is None

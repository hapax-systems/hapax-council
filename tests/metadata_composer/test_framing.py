"""Unit tests for agents.metadata_composer.framing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from agents.metadata_composer import framing


@dataclass
class _FakeRole:
    value: str


@dataclass
class _FakeProgramme:
    role: Any


@dataclass
class _FakeState:
    working_mode: str = "research"
    programme: Any = None
    stimmung_tone: str = "ambient"
    director_activity: str = "observe"


# ── enforce_register fallback ──────────────────────────────────────────────


def test_register_passes_neutral_prose():
    seed = "Hapax livestream — current programme role is Listening."
    out = framing.enforce_register(seed, fallback="fallback")
    assert out == seed


@pytest.mark.parametrize(
    "violation",
    [
        "Hapax feels great today.",
        "Hapax thinks about your message.",
        "Currently exploring creative new directions.",
        "Hapax dreams of new patterns.",
        "🔴 Live now!",
        "Inspired by today's session!!!",
    ],
)
def test_register_rejects_personification(violation: str) -> None:
    out = framing.enforce_register(violation, fallback="safe")
    assert out == "safe"


def test_register_handles_empty_input():
    assert framing.enforce_register("", fallback="seed") == "seed"


# ── compose_title_seed ─────────────────────────────────────────────────────


def test_title_seed_with_no_programme():
    state = _FakeState()
    title = framing.compose_title_seed(state)
    assert "Legomena Live" in title


def test_title_seed_with_programme_role():
    role = _FakeRole(value="work_block")
    programme = _FakeProgramme(role=role)
    state = _FakeState(programme=programme)
    title = framing.compose_title_seed(state)
    assert "Work Block" in title


def test_title_seed_marks_non_research_mode():
    state = _FakeState(working_mode="rnd")
    title = framing.compose_title_seed(state)
    assert "(rnd)" in title


# ── compose_description_seed ───────────────────────────────────────────────


def test_description_seed_includes_working_mode():
    state = _FakeState(working_mode="research")
    description = framing.compose_description_seed(state, scope="vod_boundary")
    assert "Working mode: research" in description


def test_description_seed_includes_programme_role():
    role = _FakeRole(value="listening")
    programme = _FakeProgramme(role=role)
    state = _FakeState(programme=programme)
    description = framing.compose_description_seed(state, scope="vod_boundary")
    assert "Listening" in description


def test_description_seed_vod_includes_research_framing():
    state = _FakeState()
    description = framing.compose_description_seed(state, scope="vod_boundary")
    assert "research instrument" in description


def test_description_seed_live_omits_research_framing():
    state = _FakeState()
    description = framing.compose_description_seed(state, scope="live_update")
    assert "research instrument" not in description


# ── compose_event_description ──────────────────────────────────────────────


def test_event_description_uses_intent_family():
    state = _FakeState()
    event = {
        "event_type": "x",
        "payload": {"intent_family": "programme.boundary", "salience": 0.85},
    }
    description = framing.compose_event_description(state, event)
    assert "programme.boundary" in description
    assert "0.85" in description


# ── compose_tags ───────────────────────────────────────────────────────────


def test_tags_contain_baseline():
    state = _FakeState()
    tags = framing.compose_tags(state)
    for required in ("legomena", "livestream", "hapax", "research-instrument"):
        assert required in tags


def test_tags_include_programme_role():
    role = _FakeRole(value="work_block")
    programme = _FakeProgramme(role=role)
    state = _FakeState(programme=programme)
    tags = framing.compose_tags(state)
    assert "work-block" in tags


def test_tags_dedupe_preserve_order():
    state = _FakeState(working_mode="research", stimmung_tone="research")
    tags = framing.compose_tags(state)
    assert tags.count("research") == 1


# ── per-surface posts ──────────────────────────────────────────────────────


def test_bluesky_cross_surface_includes_intent():
    state = _FakeState()
    event = {"payload": {"intent_family": "vinyl.side_change"}}
    post = framing.compose_bluesky_post(state, scope="cross_surface", triggering_event=event)
    assert "vinyl.side_change" in post


def test_pinned_comment_renders_chapter_scaffold():
    from agents.metadata_composer.chapters import ChapterMarker

    state = _FakeState()
    chapter_list = [
        ChapterMarker(timestamp_s=0, label="Opening"),
        ChapterMarker(timestamp_s=125, label="Beat"),
    ]
    pinned = framing.compose_pinned_comment(state, chapter_list)
    assert "00:00 Opening" in pinned
    assert "02:05 Beat" in pinned


def test_pinned_comment_empty_when_no_chapters():
    state = _FakeState()
    assert framing.compose_pinned_comment(state, []) == ""


# ── LLM prompt template ───────────────────────────────────────────────────


def test_llm_prompt_includes_seed_and_scope():
    prompt = framing.build_llm_prompt(seed="Foo", scope="live_update", kind="title")
    assert "Foo" in prompt
    assert "live_update" in prompt
    assert "title" in prompt
    assert "Hapax is a system, not a character" in prompt


def test_llm_prompt_omits_referent_clause_when_none():
    prompt = framing.build_llm_prompt(seed="Foo", scope="live_update", kind="title", referent=None)
    assert "Operator-naming rule" not in prompt
    assert "EXCLUSIVELY" not in prompt


def test_llm_prompt_includes_referent_clause_when_provided():
    prompt = framing.build_llm_prompt(
        seed="Foo", scope="live_update", kind="title", referent="Oudepode"
    )
    assert "Operator-naming rule" in prompt
    assert 'EXCLUSIVELY as: "Oudepode"' in prompt
    assert "legal name" in prompt


def test_llm_prompt_referent_blocks_legal_name_and_mixed_forms():
    prompt = framing.build_llm_prompt(
        seed="X", scope="vod_boundary", kind="description", referent="OTO"
    )
    assert "Do not use their legal name" in prompt
    assert "Do not mix other referent forms" in prompt

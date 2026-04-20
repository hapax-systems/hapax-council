"""Tests for shared.governance.ring2_prompts — per-surface prompt routing."""

from __future__ import annotations

import pytest

from shared.governance.monetization_safety import SurfaceKind
from shared.governance.ring2_prompts import (
    CAPTIONS_PROMPT,
    OVERLAY_PROMPT,
    SURFACE_IS_BROADCAST,
    TTS_PROMPT,
    WARD_PROMPT,
    Ring2Verdict,
    format_user_prompt,
    is_broadcast_surface,
    prompt_for_surface,
)


class TestBroadcastSurfaceSet:
    def test_four_broadcast_surfaces(self) -> None:
        assert (
            frozenset(
                {SurfaceKind.TTS, SurfaceKind.CAPTIONS, SurfaceKind.OVERLAY, SurfaceKind.WARD}
            )
            == SURFACE_IS_BROADCAST
        )

    def test_internal_surfaces_not_broadcast(self) -> None:
        """CHRONICLE / NOTIFICATION / LOG are internal — no LLM classification."""
        for surface in (SurfaceKind.CHRONICLE, SurfaceKind.NOTIFICATION, SurfaceKind.LOG):
            assert not is_broadcast_surface(surface)

    def test_broadcast_surfaces_true(self) -> None:
        for surface in SURFACE_IS_BROADCAST:
            assert is_broadcast_surface(surface)


class TestPromptForSurface:
    def test_tts(self) -> None:
        assert prompt_for_surface(SurfaceKind.TTS) is TTS_PROMPT

    def test_captions(self) -> None:
        assert prompt_for_surface(SurfaceKind.CAPTIONS) is CAPTIONS_PROMPT

    def test_overlay(self) -> None:
        assert prompt_for_surface(SurfaceKind.OVERLAY) is OVERLAY_PROMPT

    def test_ward(self) -> None:
        assert prompt_for_surface(SurfaceKind.WARD) is WARD_PROMPT

    def test_internal_surface_raises(self) -> None:
        """No prompt for internal surfaces — caller should gate via is_broadcast_surface."""
        with pytest.raises(KeyError):
            prompt_for_surface(SurfaceKind.CHRONICLE)
        with pytest.raises(KeyError):
            prompt_for_surface(SurfaceKind.NOTIFICATION)
        with pytest.raises(KeyError):
            prompt_for_surface(SurfaceKind.LOG)

    def test_each_broadcast_prompt_distinct(self) -> None:
        """4 distinct per-surface prompts (not a shared base)."""
        prompts = {TTS_PROMPT, CAPTIONS_PROMPT, OVERLAY_PROMPT, WARD_PROMPT}
        assert len(prompts) == 4


class TestPromptContent:
    """Each prompt must contain surface-specific risk rubric cues."""

    def test_all_prompts_mention_rubric_terms(self) -> None:
        terms = ("none", "low", "medium", "high", "JSON")
        for prompt in (TTS_PROMPT, CAPTIONS_PROMPT, OVERLAY_PROMPT, WARD_PROMPT):
            for term in terms:
                assert term in prompt, f"term {term!r} missing from prompt"

    def test_all_prompts_request_strict_json(self) -> None:
        """Parser depends on strict JSON-object output."""
        for prompt in (TTS_PROMPT, CAPTIONS_PROMPT, OVERLAY_PROMPT, WARD_PROMPT):
            assert "JSON object" in prompt

    def test_prompts_name_their_surface(self) -> None:
        assert "spoken" in TTS_PROMPT.lower() or "audio" in TTS_PROMPT.lower()
        assert "caption" in CAPTIONS_PROMPT.lower()
        assert "overlay" in OVERLAY_PROMPT.lower() or "on-screen" in OVERLAY_PROMPT.lower()
        assert "visual" in WARD_PROMPT.lower() or "image" in WARD_PROMPT.lower()


class TestRing2Verdict:
    def test_construction(self) -> None:
        v = Ring2Verdict(allowed=True, risk="low", reason="ok")
        assert v.allowed is True
        assert v.risk == "low"
        assert v.reason == "ok"

    def test_to_assessment_kwargs(self) -> None:
        v = Ring2Verdict(allowed=False, risk="high", reason="content id")
        kwargs = v.to_assessment_kwargs()
        assert kwargs == {"allowed": False, "risk": "high", "reason": "content id"}


class TestFormatUserPrompt:
    def test_includes_capability_name(self) -> None:
        prompt = format_user_prompt("knowledge.web_search", "Top result: example.com")
        assert "knowledge.web_search" in prompt
        assert "example.com" in prompt

    def test_handles_none_payload(self) -> None:
        prompt = format_user_prompt("x", None)
        assert "(empty)" in prompt

    def test_handles_dict_payload(self) -> None:
        prompt = format_user_prompt("world.news_headlines", {"title": "hi", "source": "ap"})
        # Whatever format str() chooses, it must be in the prompt.
        assert "hi" in prompt

    def test_asks_for_json_verdict(self) -> None:
        prompt = format_user_prompt("x", "y")
        assert "JSON" in prompt

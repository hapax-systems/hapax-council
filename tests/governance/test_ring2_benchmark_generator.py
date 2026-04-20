"""Tests for scripts.generate_ring2_benchmark — deterministic sample generation."""

from __future__ import annotations

from scripts.generate_ring2_benchmark import (
    NARRATIVE_TEXT_TYPICAL,
    NEGATIVE_CONTROLS,
    WEB_SEARCH_TYPICAL,
    WIKIPEDIA_TYPICAL,
    Sample,
    _is_allowed,
    build_all_samples,
)
from shared.governance.monetization_safety import SurfaceKind
from shared.governance.ring2_prompts import SURFACE_IS_BROADCAST


class TestIsAllowed:
    def test_high_blocks(self) -> None:
        assert _is_allowed("high") is False

    def test_others_admit(self) -> None:
        for risk in ("none", "low", "medium"):
            assert _is_allowed(risk) is True


class TestSampleSerialization:
    def test_round_trip(self) -> None:
        s = Sample(
            capability_name="knowledge.wikipedia",
            surface=SurfaceKind.TTS,
            rendered_payload="The Eiffel Tower was completed in 1889.",
            expected_risk="low",
            expected_allowed=True,
            exemplar_class="typical",
            notes="test",
        )
        import json as _json

        raw = _json.loads(s.to_jsonl())
        assert raw["capability_name"] == "knowledge.wikipedia"
        assert raw["surface"] == "tts"
        assert raw["expected_risk"] == "low"
        assert raw["expected_allowed"] is True
        assert raw["exemplar_class"] == "typical"


class TestBuildAllSamples:
    def test_produces_nonempty_set(self) -> None:
        samples = build_all_samples()
        assert len(samples) >= 400, f"expected ~500 samples, got {len(samples)}"

    def test_all_surfaces_broadcast(self) -> None:
        """All generated samples target broadcast surfaces (never CHRONICLE/LOG/NOTIFICATION)."""
        samples = build_all_samples()
        for s in samples:
            assert s.surface in SURFACE_IS_BROADCAST, (
                f"sample for {s.capability_name} targets non-broadcast surface {s.surface.value}"
            )

    def test_all_risks_valid(self) -> None:
        samples = build_all_samples()
        for s in samples:
            assert s.expected_risk in ("none", "low", "medium", "high")

    def test_allowed_matches_risk(self) -> None:
        """expected_allowed=False iff risk=high."""
        samples = build_all_samples()
        for s in samples:
            if s.expected_risk == "high":
                assert s.expected_allowed is False, (
                    f"{s.capability_name}: high-risk sample marked allowed"
                )
            else:
                assert s.expected_allowed is True

    def test_negative_controls_present(self) -> None:
        """At least one 'none' control per broadcast surface."""
        samples = build_all_samples()
        by_surface_class = {
            (s.surface, s.exemplar_class) for s in samples if s.exemplar_class == "negative_control"
        }
        for surface in SURFACE_IS_BROADCAST:
            assert (surface, "negative_control") in by_surface_class

    def test_all_risky_caps_have_typical(self) -> None:
        """The 6 catalog-annotated risky caps each have typical samples."""
        samples = build_all_samples()
        typical_caps = {s.capability_name for s in samples if s.exemplar_class == "typical"}
        for cap in (
            "knowledge.wikipedia",
            "knowledge.web_search",
            "knowledge.image_search",
            "world.news_headlines",
            "social.phone_media",
            "content.narrative_text",
        ):
            assert cap in typical_caps, f"missing typical exemplars for {cap}"

    def test_deterministic(self) -> None:
        """Generator output is deterministic across calls — reproducible benchmarks."""
        first = build_all_samples()
        second = build_all_samples()
        assert len(first) == len(second)
        for a, b in zip(first, second, strict=True):
            assert a == b


class TestTemplateContent:
    def test_wikipedia_typical_nonempty(self) -> None:
        assert len(WIKIPEDIA_TYPICAL) >= 5

    def test_web_search_typical_nonempty(self) -> None:
        assert len(WEB_SEARCH_TYPICAL) >= 5

    def test_narrative_text_typical_nonempty(self) -> None:
        assert len(NARRATIVE_TEXT_TYPICAL) >= 5

    def test_negative_controls_nonempty(self) -> None:
        assert len(NEGATIVE_CONTROLS) >= 10

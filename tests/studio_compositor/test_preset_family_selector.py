"""Tests for preset_family_selector — Phase 3 of the volitional-director epic."""

from __future__ import annotations

import pytest

from agents.studio_compositor import preset_family_selector as pfs


@pytest.fixture(autouse=True)
def _reset_memory():
    pfs.reset_memory()
    yield
    pfs.reset_memory()


class TestFamilyMapping:
    def test_all_documented_families_present(self):
        # The four documented families plus neutral-ambient fallback.
        names = pfs.family_names()
        assert "audio-reactive" in names
        assert "calm-textural" in names
        assert "glitch-dense" in names
        assert "warm-minimal" in names
        assert "neutral-ambient" in names

    def test_each_family_has_presets(self):
        for fam in pfs.family_names():
            presets = pfs.presets_for_family(fam)
            assert presets, f"family {fam} has no presets"
            assert all(isinstance(p, str) and p for p in presets)

    def test_unknown_family_returns_empty(self):
        assert pfs.presets_for_family("does-not-exist") == ()


class TestPickFromFamily:
    def test_returns_member_of_family(self):
        pick = pfs.pick_from_family("calm-textural")
        assert pick in pfs.presets_for_family("calm-textural")

    def test_avoids_back_to_back_repeat(self):
        # Pick twice — second pick should differ from first when the
        # family has > 1 preset.
        first = pfs.pick_from_family("glitch-dense")
        second = pfs.pick_from_family("glitch-dense")
        assert first != second, (
            "back-to-back repeat in family with multiple presets — non-repeat memory not applied"
        )

    def test_avoids_explicit_last(self):
        family_presets = pfs.presets_for_family("audio-reactive")
        # Pin "last" to first preset; pick should not return that one.
        pick = pfs.pick_from_family("audio-reactive", last=family_presets[0])
        assert pick != family_presets[0]

    def test_filters_against_available(self):
        family_presets = pfs.presets_for_family("warm-minimal")
        # Make only one family member available; selector must return that one.
        only = family_presets[0]
        pick = pfs.pick_from_family("warm-minimal", available=[only])
        assert pick == only

    def test_returns_none_when_unknown_family(self):
        assert pfs.pick_from_family("not-a-real-family") is None

    def test_returns_none_when_no_family_member_available(self):
        # All family members filtered out → None.
        result = pfs.pick_from_family("calm-textural", available=["completely-unrelated-preset"])
        assert result is None

    def test_falls_back_when_only_one_candidate_after_non_repeat(self):
        family_presets = pfs.presets_for_family("neutral-ambient")
        only = family_presets[0]
        # Force a single available candidate; non-repeat should be relaxed.
        pick = pfs.pick_from_family("neutral-ambient", available=[only], last=only)
        assert pick == only  # only candidate, returned despite being "last"


class TestMemoryReset:
    def test_reset_clears_per_family_memory(self):
        pfs.pick_from_family("glitch-dense")
        pfs.reset_memory()
        # After reset, the next pick has no last-pick anchor.
        # Just verify the memory dict is empty by checking the module attr.
        assert pfs._LAST_PICK == {}

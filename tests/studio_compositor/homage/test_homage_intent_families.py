"""Pin the 6 HOMAGE IntentFamily members + catalog entries + dispatcher routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.studio_compositor import compositional_consumer as cc
from shared.compositional_affordances import COMPOSITIONAL_CAPABILITIES, by_family
from shared.director_intent import IntentFamily


@pytest.fixture
def tmp_shm(monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "_HERO_CAMERA_OVERRIDE", tmp_path / "hero-camera-override.json")
    monkeypatch.setattr(cc, "_OVERLAY_ALPHA_OVERRIDES", tmp_path / "overlay-alpha-overrides.json")
    monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", tmp_path / "recent-recruitment.json")
    monkeypatch.setattr(cc, "_YOUTUBE_DIRECTION", tmp_path / "youtube-direction.json")
    monkeypatch.setattr(cc, "_STREAM_MODE_INTENT", tmp_path / "stream-mode-intent.json")
    monkeypatch.setattr(
        cc, "_HOMAGE_PENDING_TRANSITIONS", tmp_path / "homage-pending-transitions.json"
    )
    monkeypatch.setattr(cc, "_SEGMENT_CUE_HOLD", tmp_path / "segment-cue-hold.json")
    monkeypatch.setattr(cc, "_ACTION_RECEIPTS_JSONL", tmp_path / "action-receipts.jsonl")
    return tmp_path


HOMAGE_FAMILIES = (
    "homage.rotation",
    "homage.emergence",
    "homage.swap",
    "homage.cycle",
    "homage.recede",
    "homage.expand",
)


class TestIntentFamilyEnum:
    @pytest.mark.parametrize("family", HOMAGE_FAMILIES)
    def test_homage_family_in_literal(self, family):
        assert family in IntentFamily.__args__


class TestCatalogEntries:
    @pytest.mark.parametrize("family", HOMAGE_FAMILIES)
    def test_catalog_has_entries_for_each_family(self, family):
        entries = by_family(family)
        assert len(entries) >= 2, f"catalog missing entries for {family!r}"

    def test_catalog_total_homage_count_reasonable(self):
        homage_entries = [c for c in COMPOSITIONAL_CAPABILITIES if c.name.startswith("homage.")]
        # 2 rotation + 4 emergence + 3 swap + 3 cycle + 3 recede + 3 expand = 18
        assert len(homage_entries) >= 15

    def test_every_homage_entry_has_narrative(self):
        for c in COMPOSITIONAL_CAPABILITIES:
            if c.name.startswith("homage."):
                assert c.description and len(c.description) > 20


def _read_pending(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("transitions") or []


class TestRotationDispatcher:
    def test_rotation_writes_topic_change(self, tmp_shm):
        rec = cc.RecruitmentRecord(name="homage.rotation.signature")
        family = cc.dispatch(rec)
        assert family == "homage.rotation"
        transitions = _read_pending(tmp_shm / "homage-pending-transitions.json")
        assert any(t["transition"] == "topic-change" for t in transitions)

    def test_rotation_source_id_tags_target(self, tmp_shm):
        cc.dispatch(cc.RecruitmentRecord(name="homage.rotation.package-cycle"))
        transitions = _read_pending(tmp_shm / "homage-pending-transitions.json")
        assert any("package-cycle" in t["source_id"] for t in transitions)


class TestEmergenceDispatcher:
    def test_emergence_writes_default_entry(self, tmp_shm):
        rec = cc.RecruitmentRecord(name="homage.emergence.activity-header")
        family = cc.dispatch(rec)
        assert family == "homage.emergence"
        transitions = _read_pending(tmp_shm / "homage-pending-transitions.json")
        # BitchX default_entry is ticker-scroll-in
        assert any(t["transition"] == "ticker-scroll-in" for t in transitions)

    def test_emergence_normalises_source_id(self, tmp_shm):
        cc.dispatch(cc.RecruitmentRecord(name="homage.emergence.activity-header"))
        transitions = _read_pending(tmp_shm / "homage-pending-transitions.json")
        # Hyphens normalised to underscores so the source_id matches layout IDs
        assert any(t["source_id"] == "activity_header" for t in transitions)


class TestSwapDispatcher:
    def test_swap_emits_pair(self, tmp_shm):
        cc.dispatch(cc.RecruitmentRecord(name="homage.swap.hero-chrome"))
        transitions = _read_pending(tmp_shm / "homage-pending-transitions.json")
        kinds = {t["transition"] for t in transitions}
        assert "part-message" in kinds
        assert "join-message" in kinds


class TestCycleDispatcher:
    def test_cycle_writes_mode_change(self, tmp_shm):
        cc.dispatch(cc.RecruitmentRecord(name="homage.cycle.legibility-wards"))
        transitions = _read_pending(tmp_shm / "homage-pending-transitions.json")
        assert any(t["transition"] == "mode-change" for t in transitions)


class TestRecedeDispatcher:
    def test_recede_writes_default_exit(self, tmp_shm):
        cc.dispatch(cc.RecruitmentRecord(name="homage.recede.all-chrome"))
        transitions = _read_pending(tmp_shm / "homage-pending-transitions.json")
        # BitchX default_exit is ticker-scroll-out
        assert any(t["transition"] == "ticker-scroll-out" for t in transitions)


class TestExpandDispatcher:
    def test_expand_writes_netsplit_burst(self, tmp_shm):
        cc.dispatch(cc.RecruitmentRecord(name="homage.expand.hero"))
        transitions = _read_pending(tmp_shm / "homage-pending-transitions.json")
        assert any(t["transition"] == "netsplit-burst" for t in transitions)


class TestDispatcherMalformedNames:
    @pytest.mark.parametrize(
        "name",
        [
            "homage.rotation",  # no suffix
            "homage.emergence",
        ],
    )
    def test_no_suffix_returns_unknown(self, tmp_shm, name):
        family = cc.dispatch(cc.RecruitmentRecord(name=name))
        # Bare name without suffix — dispatch returns "unknown" (capability
        # name doesn't match any startswith clause; just "homage.rotation"
        # sans trailing dot still matches ``homage.rotation.`` prefix? no:
        # ``"homage.rotation.signature".startswith("homage.rotation.")`` is
        # True but ``"homage.rotation".startswith("homage.rotation.")`` is
        # False). So both return unknown.
        assert family == "unknown"


class TestDirectorPromptIncludesHomageSection:
    def test_prompt_text_contains_homage_composition_header(self):
        """The director's unified prompt must carry the '## Homage Composition'
        section and enumerate the 6 homage.* family members."""
        from agents.studio_compositor import director_loop

        # The prompt builder is accessed via _build_unified_prompt; we
        # spot-check its emit path by constructing a minimal scaffolding
        # that exercises the homage parts append.
        # The ACTIVITY_CAPABILITIES module-level string is a precondition;
        # the homage section is appended INSIDE _build_unified_prompt.
        # Read the source as a smoke-check that the section exists.
        src = Path(director_loop.__file__).read_text(encoding="utf-8")
        assert "## Homage Composition" in src
        for family in HOMAGE_FAMILIES:
            assert family in src, f"director prompt missing {family} mention"

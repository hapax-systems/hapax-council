"""Tests for ``agents.xprom_music_policy``."""

from __future__ import annotations

import pytest

from agents.xprom_music_policy import (
    PERMITTED_MIRROR_TARGETS,
    REFUSED_MIRROR_TARGETS,
    MirrorPlan,
    MusicTrackManifest,
    UnsupportedMirrorTarget,
    plan_mirrors_for_track,
    validate_mirror_targets,
)


class TestPermittedTargets:
    def test_permitted_targets_listed(self) -> None:
        assert "soundcloud" in PERMITTED_MIRROR_TARGETS
        assert "internet-archive" in PERMITTED_MIRROR_TARGETS
        assert "zenodo" in PERMITTED_MIRROR_TARGETS
        # Exactly three permitted music-side mirror targets per drop-5
        assert len(PERMITTED_MIRROR_TARGETS) == 3

    def test_refused_targets_listed(self) -> None:
        # Per separate REFUSED cc-tasks
        assert "bandcamp" in REFUSED_MIRROR_TARGETS
        assert "discogs" in REFUSED_MIRROR_TARGETS
        assert "rym" in REFUSED_MIRROR_TARGETS

    def test_permitted_and_refused_are_disjoint(self) -> None:
        assert PERMITTED_MIRROR_TARGETS.isdisjoint(REFUSED_MIRROR_TARGETS)


class TestValidateMirrorTargets:
    def test_all_permitted_passes(self) -> None:
        validate_mirror_targets(["soundcloud", "internet-archive"])

    def test_refused_target_raises(self) -> None:
        with pytest.raises(UnsupportedMirrorTarget) as exc_info:
            validate_mirror_targets(["soundcloud", "bandcamp"])
        assert "bandcamp" in str(exc_info.value)

    def test_unknown_target_raises(self) -> None:
        with pytest.raises(UnsupportedMirrorTarget):
            validate_mirror_targets(["soundcloud", "myspace"])

    def test_empty_list_passes(self) -> None:
        validate_mirror_targets([])


class TestPlanMirrorsForTrack:
    def test_track_with_permitted_targets_plans_all(self) -> None:
        track = MusicTrackManifest(
            slug="oudepode-001",
            mirrors=["soundcloud", "internet-archive"],
            is_research_artefact=False,
        )
        plan = plan_mirrors_for_track(track)
        assert "soundcloud" in plan.targets
        assert "internet-archive" in plan.targets
        assert "zenodo" not in plan.targets  # not a research artefact

    def test_research_artefact_includes_zenodo_when_explicit(self) -> None:
        track = MusicTrackManifest(
            slug="oudepode-research-002",
            mirrors=["soundcloud", "internet-archive", "zenodo"],
            is_research_artefact=True,
        )
        plan = plan_mirrors_for_track(track)
        assert "zenodo" in plan.targets

    def test_zenodo_dropped_when_not_research_artefact(self) -> None:
        # Per drop-5 §xprom-music-mirror: Zenodo only when track is
        # also a research artefact (e.g., release tied to a paper).
        # Even if manifest declares zenodo, drop it when flag false.
        track = MusicTrackManifest(
            slug="oudepode-bedmusic-003",
            mirrors=["soundcloud", "zenodo"],
            is_research_artefact=False,
        )
        plan = plan_mirrors_for_track(track)
        assert "soundcloud" in plan.targets
        assert "zenodo" not in plan.targets

    def test_refused_target_in_manifest_raises(self) -> None:
        track = MusicTrackManifest(
            slug="oudepode-004",
            mirrors=["soundcloud", "bandcamp"],
            is_research_artefact=False,
        )
        with pytest.raises(UnsupportedMirrorTarget):
            plan_mirrors_for_track(track)


class TestMirrorPlan:
    def test_dataclass_carries_track_slug_and_targets(self) -> None:
        plan = MirrorPlan(
            track_slug="oudepode-005",
            targets=("soundcloud", "internet-archive"),
        )
        assert plan.track_slug == "oudepode-005"
        assert "soundcloud" in plan.targets

    def test_to_attribution_dict_for_omg_lol_status_page(self) -> None:
        plan = MirrorPlan(
            track_slug="oudepode-006",
            targets=("soundcloud", "internet-archive"),
        )
        attribution = plan.to_attribution_dict()
        assert attribution["track"] == "oudepode-006"
        assert attribution["mirror_count"] == 2
        assert isinstance(attribution["mirrors"], list)


class TestMusicTrackManifest:
    def test_dataclass_required_fields(self) -> None:
        track = MusicTrackManifest(
            slug="t",
            mirrors=["soundcloud"],
            is_research_artefact=False,
        )
        assert track.slug == "t"
        assert track.is_research_artefact is False

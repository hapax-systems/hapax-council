"""Phase 3 vision integration (#150) — per_camera_person_count hero-gate.

Verifies ``dispatch_camera_hero`` rejects a candidate camera whose
YOLO-emitted person count is zero, preserves dispatch when people are
present, respects the ``HAPAX_VISION_HERO_GATE`` feature flag, and
fails open when perception data is missing or malformed.

Spec: ``docs/superpowers/specs/2026-04-18-vision-integration-design.md`` §6.
"""

from __future__ import annotations

import json

import pytest

from agents.studio_compositor import compositional_consumer as cc


@pytest.fixture
def isolated_shm(monkeypatch, tmp_path):
    """Redirect SHM paths + perception-state to tmp_path; reset history.

    Mirrors the fixture in ``test_compositional_consumer.py`` so the
    dispatcher's module-level dwell/variety history doesn't bleed
    between tests. Also isolates the perception-state read path so each
    test controls exactly what per_camera_person_count the gate sees.
    """
    monkeypatch.setattr(cc, "_HERO_CAMERA_OVERRIDE", tmp_path / "hero-camera-override.json")
    monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", tmp_path / "recent-recruitment.json")
    monkeypatch.setattr(cc, "_PERCEPTION_STATE", tmp_path / "perception-state.json")
    monkeypatch.setattr(cc, "_CAMERA_ROLE_HISTORY", [])
    # Default: flag explicitly enabled (spec default is ON; env unset still
    # reads as ON, but set it for clarity and to override any caller env).
    monkeypatch.setenv("HAPAX_VISION_HERO_GATE", "1")
    return tmp_path


def _write_perception(tmp_path, counts: dict[str, int]) -> None:
    (tmp_path / "perception-state.json").write_text(
        json.dumps({"per_camera_person_count": counts}),
        encoding="utf-8",
    )


class TestVisionHeroGate:
    def test_zero_person_count_rejects(self, isolated_shm):
        """Camera with person_count=0 is rejected; hero file not written."""
        _write_perception(isolated_shm, {"c920-overhead": 0, "brio-operator": 2})
        assert not cc.dispatch_camera_hero("cam.hero.overhead.vinyl-spinning", 30.0)
        assert not (isolated_shm / "hero-camera-override.json").exists()

    def test_nonzero_person_count_passes(self, isolated_shm):
        """Camera with people present dispatches normally."""
        _write_perception(isolated_shm, {"c920-overhead": 1, "brio-operator": 0})
        assert cc.dispatch_camera_hero("cam.hero.overhead.vinyl-spinning", 30.0)
        data = json.loads((isolated_shm / "hero-camera-override.json").read_text())
        assert data["camera_role"] == "c920-overhead"

    def test_multiple_people_passes(self, isolated_shm):
        """Person count > 1 also passes (gate is > 0)."""
        _write_perception(isolated_shm, {"brio-operator": 3})
        assert cc.dispatch_camera_hero("cam.hero.operator-brio.talking", 15.0)
        data = json.loads((isolated_shm / "hero-camera-override.json").read_text())
        assert data["camera_role"] == "brio-operator"

    def test_flag_off_bypasses_gate(self, isolated_shm, monkeypatch):
        """With HAPAX_VISION_HERO_GATE=0, an empty camera still dispatches."""
        monkeypatch.setenv("HAPAX_VISION_HERO_GATE", "0")
        _write_perception(isolated_shm, {"c920-overhead": 0})
        assert cc.dispatch_camera_hero("cam.hero.overhead.vinyl-spinning", 30.0)
        data = json.loads((isolated_shm / "hero-camera-override.json").read_text())
        assert data["camera_role"] == "c920-overhead"

    def test_flag_false_literal_bypasses_gate(self, isolated_shm, monkeypatch):
        """'false' (case-insensitive) also disables the gate."""
        monkeypatch.setenv("HAPAX_VISION_HERO_GATE", "False")
        _write_perception(isolated_shm, {"c920-overhead": 0})
        assert cc.dispatch_camera_hero("cam.hero.overhead.vinyl-spinning", 30.0)

    def test_missing_perception_file_fails_open(self, isolated_shm):
        """No perception-state.json → accept (fail-open)."""
        # Do not write the file at all.
        assert not (isolated_shm / "perception-state.json").exists()
        assert cc.dispatch_camera_hero("cam.hero.overhead.vinyl-spinning", 30.0)

    def test_missing_key_fails_open(self, isolated_shm):
        """Perception file present but lacks per_camera_person_count → accept."""
        (isolated_shm / "perception-state.json").write_text(
            json.dumps({"detected_action": "working"}), encoding="utf-8"
        )
        assert cc.dispatch_camera_hero("cam.hero.overhead.vinyl-spinning", 30.0)

    def test_empty_counts_fails_open(self, isolated_shm):
        """``per_camera_person_count`` present but empty dict → accept."""
        _write_perception(isolated_shm, {})
        assert cc.dispatch_camera_hero("cam.hero.overhead.vinyl-spinning", 30.0)

    def test_role_absent_from_counts_fails_open(self, isolated_shm):
        """Other cameras have counts but ours doesn't → accept (don't
        penalize a camera the vision stack hasn't visited yet)."""
        _write_perception(isolated_shm, {"brio-operator": 2})
        assert cc.dispatch_camera_hero("cam.hero.overhead.vinyl-spinning", 30.0)

    def test_malformed_json_fails_open(self, isolated_shm):
        """Corrupt perception-state.json → accept, don't raise."""
        (isolated_shm / "perception-state.json").write_text("{not json", encoding="utf-8")
        assert cc.dispatch_camera_hero("cam.hero.overhead.vinyl-spinning", 30.0)

    def test_non_integer_count_fails_open(self, isolated_shm):
        """Count is something weird like null/string → accept."""
        (isolated_shm / "perception-state.json").write_text(
            json.dumps({"per_camera_person_count": {"c920-overhead": None}}),
            encoding="utf-8",
        )
        assert cc.dispatch_camera_hero("cam.hero.overhead.vinyl-spinning", 30.0)

    def test_rejection_does_not_pollute_history(self, isolated_shm):
        """Vision-gate rejection must NOT update _CAMERA_ROLE_HISTORY.

        The variety fallback depends on a clean history. If the gate
        wrote to history on rejection, the next candidate for the same
        role would be variety-rejected too, masking the fallback.
        """
        _write_perception(isolated_shm, {"c920-overhead": 0})
        assert not cc.dispatch_camera_hero("cam.hero.overhead.vinyl-spinning", 30.0)
        assert cc._CAMERA_ROLE_HISTORY == []

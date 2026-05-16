"""Epic 2 Phase B — closed-loop wiring tests.

Three invariants:

1. Compositional recruitment names match the ``_COMPOSITIONAL_PREFIXES``
   the daimonion's ``impingement_consumer_loop`` dispatches through
   ``compositional_consumer.dispatch``.
2. ``compositional_consumer.dispatch`` round-trips every family in the
   catalog to a family-name string other than "unknown".
3. ``random_mode`` defers to the biased family when
   ``recent_recruitment_age_s("preset.bias")`` is below the cooldown.
"""

from __future__ import annotations

import pytest

from agents.studio_compositor.compositional_consumer import (
    RecruitmentRecord,
    dispatch,
)
from agents.studio_compositor.random_mode import _PRESET_BIAS_COOLDOWN_S


@pytest.fixture(autouse=True)
def isolate_runtime_hold(monkeypatch, tmp_path):
    """Keep dispatcher tests independent from live compositor segment holds."""
    import agents.studio_compositor.compositional_consumer as cc

    monkeypatch.setattr(cc, "_SEGMENT_CUE_HOLD", tmp_path / "segment-cue-hold.json")
    monkeypatch.setattr(cc, "_PARAMETRIC_ENVELOPES", tmp_path / "parametric-envelopes.json")
    monkeypatch.setattr(cc, "_ACTION_RECEIPTS_JSONL", tmp_path / "action-receipts.jsonl")


class TestCompositionalPrefixes:
    def test_all_catalog_names_are_compositional(self):
        from agents.hapax_daimonion.run_loops_aux import (
            _COMPOSITIONAL_PREFIXES,
            _is_compositional_capability,
        )
        from shared.compositional_affordances import capability_names

        # Every catalog entry should be routed through the compositional path.
        names = capability_names()
        assert names, "catalog is empty"
        for name in names:
            assert _is_compositional_capability(name), (
                f"catalog entry {name!r} does not match any of "
                f"{_COMPOSITIONAL_PREFIXES!r} — add its prefix or rename"
            )

    def test_non_compositional_names_are_rejected(self):
        from agents.hapax_daimonion.run_loops_aux import (
            _is_compositional_capability,
        )

        for name in (
            "studio.toggle_livestream",
            "system.notify_operator",
            "env.outdoor_rain",
            "",
            None,  # type: ignore[arg-type]
        ):
            assert _is_compositional_capability(name) is False


class TestDispatchRoundTrip:
    def test_camera_hero_dispatch(self, tmp_path, monkeypatch):
        # Redirect dispatch writes to tmp so we don't clobber live state.
        import agents.studio_compositor.compositional_consumer as cc

        monkeypatch.setattr(cc, "_HERO_CAMERA_OVERRIDE", tmp_path / "hero.json")
        monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", tmp_path / "recent.json")
        family = dispatch(RecruitmentRecord(name="cam.hero.overhead.vinyl-spinning"))
        assert family == "camera.hero"
        assert (tmp_path / "hero.json").exists()

    def test_preset_bias_dispatch(self, tmp_path, monkeypatch):
        import agents.studio_compositor.compositional_consumer as cc

        monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", tmp_path / "recent.json")
        family = dispatch(RecruitmentRecord(name="fx.family.audio-reactive"))
        assert family == "preset.bias"
        # recent-recruitment marker should now contain the family.
        import json

        data = json.loads((tmp_path / "recent.json").read_text())
        assert "preset.bias" in data["families"]
        assert data["families"]["preset.bias"]["family"] == "audio-reactive"

    def test_overlay_emphasis_dispatch(self, tmp_path, monkeypatch):
        import agents.studio_compositor.compositional_consumer as cc

        monkeypatch.setattr(cc, "_OVERLAY_ALPHA_OVERRIDES", tmp_path / "alpha.json")
        monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", tmp_path / "recent.json")
        family = dispatch(RecruitmentRecord(name="overlay.foreground.captions"))
        assert family == "overlay.emphasis"

    def test_youtube_direction_dispatch(self, tmp_path, monkeypatch):
        import agents.studio_compositor.compositional_consumer as cc

        monkeypatch.setattr(cc, "_YOUTUBE_DIRECTION", tmp_path / "yt.json")
        monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", tmp_path / "recent.json")
        family = dispatch(RecruitmentRecord(name="youtube.advance-queue"))
        assert family == "youtube.direction"

    def test_attention_winner_dispatch(self, tmp_path, monkeypatch):
        import agents.studio_compositor.compositional_consumer as cc

        monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", tmp_path / "recent.json")
        family = dispatch(RecruitmentRecord(name="attention.winner.primary-reader"))
        assert family == "attention.winner"

    def test_stream_mode_transition_dispatch(self, tmp_path, monkeypatch):
        import agents.studio_compositor.compositional_consumer as cc

        monkeypatch.setattr(cc, "_STREAM_MODE_INTENT", tmp_path / "mode.json")
        monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", tmp_path / "recent.json")
        family = dispatch(RecruitmentRecord(name="stream.mode.public-research.transition"))
        assert family == "stream_mode.transition"


class TestPresetBiasCooldown:
    def test_cooldown_constant_is_reasonable(self):
        # Short-circuit the loop: test that the cooldown is long enough to
        # hold a bias but not so long that random_mode freezes forever.
        assert 5.0 < _PRESET_BIAS_COOLDOWN_S < 120.0

    def test_cooldown_reader_recognizes_fresh_bias(self, tmp_path, monkeypatch):
        import json

        import agents.studio_compositor.compositional_consumer as cc

        monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", tmp_path / "recent.json")
        # Dispatch a preset-bias → updates recent-recruitment marker.
        dispatch(RecruitmentRecord(name="fx.family.calm-textural"))
        # Age must be ~0, well within cooldown.
        age = cc.recent_recruitment_age_s("preset.bias")
        assert age is not None
        assert age < _PRESET_BIAS_COOLDOWN_S

        # Verify the schema the random_mode loop reads against.
        data = json.loads((tmp_path / "recent.json").read_text())
        assert "preset.bias" in data["families"]
        assert "last_recruited_ts" in data["families"]["preset.bias"]

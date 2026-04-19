"""Tests for scene_classifier — Task #150 Phase 1."""

from __future__ import annotations

import json
from pathlib import Path
from random import Random

import pytest

from agents.studio_compositor import preset_family_selector as pfs
from agents.studio_compositor import scene_classifier as sc

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_shm(tmp_path: Path) -> Path:
    """Temp directory standing in for /dev/shm/hapax-compositor."""
    shm = tmp_path / "hapax-compositor"
    shm.mkdir()
    return shm


@pytest.fixture
def hero_override(tmp_shm: Path) -> Path:
    """Write a hero-camera-override.json pointing at ``c920-desk``."""
    override = tmp_shm / "hero-camera-override.json"
    override.write_text(
        json.dumps(
            {
                "camera_role": "c920-desk",
                "ttl_s": 30.0,
                "set_at": 1776564536.0,
                "source_capability": "test.hero",
            }
        )
    )
    return override


@pytest.fixture
def hero_snapshot(tmp_shm: Path) -> Path:
    """Create a minimal placeholder JPEG for the hero camera role."""
    jpeg = tmp_shm / "c920-desk.jpg"
    # Minimal bytes — the classifier only base64-encodes blindly, so a
    # non-empty payload is all we need.
    jpeg.write_bytes(b"\xff\xd8\xff\xd9not-a-real-jpeg-but-non-empty")
    return jpeg


@pytest.fixture(autouse=True)
def _reset_memory():
    """Reset the preset family selector's non-repeat memory between tests."""
    pfs.reset_memory()
    yield
    pfs.reset_memory()


# ── Classifier tests ──────────────────────────────────────────────────────


class TestClassifyOnce:
    def test_returns_classification_for_mocked_llm(
        self, tmp_shm: Path, hero_override: Path, hero_snapshot: Path
    ) -> None:
        def fake_llm(_b64: str) -> str:
            return json.dumps(
                {
                    "scene": "person-face-closeup",
                    "confidence": 0.82,
                    "evidence": "face fills frame, studio lighting",
                }
            )

        clf = sc.SceneClassifier(
            shm_dir=tmp_shm,
            override_path=hero_override,
            classification_path=tmp_shm / "scene-classification.json",
            call_llm=fake_llm,
        )
        result = clf.classify_once()
        assert result is not None
        assert result.scene == "person-face-closeup"
        assert result.confidence == pytest.approx(0.82)
        assert "face" in result.evidence

    def test_publishes_to_file(
        self, tmp_shm: Path, hero_override: Path, hero_snapshot: Path
    ) -> None:
        out = tmp_shm / "scene-classification.json"
        clf = sc.SceneClassifier(
            shm_dir=tmp_shm,
            override_path=hero_override,
            classification_path=out,
            call_llm=lambda _b64: json.dumps(
                {"scene": "turntables-playing", "confidence": 0.9, "evidence": "vinyl"}
            ),
        )
        clf.classify_once()
        assert out.exists()
        payload = json.loads(out.read_text())
        assert payload["scene"] == "turntables-playing"
        assert payload["confidence"] == pytest.approx(0.9)
        assert "ts" in payload

    def test_cache_returns_stale_within_ttl(
        self, tmp_shm: Path, hero_override: Path, hero_snapshot: Path
    ) -> None:
        calls = {"n": 0}

        def counting_llm(_b64: str) -> str:
            calls["n"] += 1
            return json.dumps({"scene": "room-wide-ambient", "confidence": 0.5, "evidence": "wide"})

        clf = sc.SceneClassifier(
            shm_dir=tmp_shm,
            override_path=hero_override,
            classification_path=tmp_shm / "scene-classification.json",
            cache_ttl_s=5.0,
            call_llm=counting_llm,
        )
        first = clf.classify_once(now=100.0)
        second = clf.classify_once(now=102.0)  # within 5s TTL
        assert first is second
        assert calls["n"] == 1

    def test_cache_refreshes_after_ttl(
        self, tmp_shm: Path, hero_override: Path, hero_snapshot: Path
    ) -> None:
        calls = {"n": 0}

        def counting_llm(_b64: str) -> str:
            calls["n"] += 1
            return json.dumps({"scene": "screen-only", "confidence": 0.7, "evidence": "monitor"})

        clf = sc.SceneClassifier(
            shm_dir=tmp_shm,
            override_path=hero_override,
            classification_path=tmp_shm / "scene-classification.json",
            cache_ttl_s=5.0,
            call_llm=counting_llm,
        )
        clf.classify_once(now=100.0)
        clf.classify_once(now=110.0)  # past 5s TTL
        assert calls["n"] == 2

    def test_malformed_json_falls_back_to_mixed_activity(
        self, tmp_shm: Path, hero_override: Path, hero_snapshot: Path, caplog
    ) -> None:
        clf = sc.SceneClassifier(
            shm_dir=tmp_shm,
            override_path=hero_override,
            classification_path=tmp_shm / "scene-classification.json",
            call_llm=lambda _b64: "this is not JSON at all{",
        )
        with caplog.at_level("ERROR"):
            result = clf.classify_once()
        assert result is not None
        assert result.scene == sc.FALLBACK_SCENE  # "mixed-activity"
        assert result.confidence == 0.0
        # Logged an error about the malformed JSON.
        assert any("malformed JSON" in rec.message for rec in caplog.records)

    def test_unknown_scene_label_falls_back(
        self, tmp_shm: Path, hero_override: Path, hero_snapshot: Path
    ) -> None:
        clf = sc.SceneClassifier(
            shm_dir=tmp_shm,
            override_path=hero_override,
            classification_path=tmp_shm / "scene-classification.json",
            call_llm=lambda _b64: json.dumps(
                {"scene": "bespoke-category-not-in-labels", "confidence": 0.5}
            ),
        )
        result = clf.classify_once()
        assert result is not None
        assert result.scene == sc.FALLBACK_SCENE

    def test_llm_exception_is_caught_and_falls_back(
        self, tmp_shm: Path, hero_override: Path, hero_snapshot: Path
    ) -> None:
        def raiser(_b64: str) -> str:
            raise RuntimeError("gateway down")

        clf = sc.SceneClassifier(
            shm_dir=tmp_shm,
            override_path=hero_override,
            classification_path=tmp_shm / "scene-classification.json",
            call_llm=raiser,
        )
        result = clf.classify_once()
        assert result is not None
        assert result.scene == sc.FALLBACK_SCENE

    def test_no_hero_override_returns_none(self, tmp_shm: Path) -> None:
        clf = sc.SceneClassifier(
            shm_dir=tmp_shm,
            override_path=tmp_shm / "does-not-exist.json",
            classification_path=tmp_shm / "scene-classification.json",
            call_llm=lambda _b64: "",
        )
        assert clf.classify_once() is None

    def test_missing_snapshot_returns_none(self, tmp_shm: Path, hero_override: Path) -> None:
        # hero_override fixture is loaded but no snapshot written.
        clf = sc.SceneClassifier(
            shm_dir=tmp_shm,
            override_path=hero_override,
            classification_path=tmp_shm / "scene-classification.json",
            call_llm=lambda _b64: "",
        )
        assert clf.classify_once() is None

    def test_json_fenced_response_is_parsed(
        self, tmp_shm: Path, hero_override: Path, hero_snapshot: Path
    ) -> None:
        fenced = (
            "```json\n"
            + json.dumps(
                {"scene": "hands-manipulating-gear", "confidence": 0.6, "evidence": "hands"}
            )
            + "\n```"
        )
        clf = sc.SceneClassifier(
            shm_dir=tmp_shm,
            override_path=hero_override,
            classification_path=tmp_shm / "scene-classification.json",
            call_llm=lambda _b64: fenced,
        )
        result = clf.classify_once()
        assert result is not None
        assert result.scene == "hands-manipulating-gear"


class TestFeatureFlag:
    def test_flag_off_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HAPAX_SCENE_CLASSIFIER_ACTIVE", raising=False)
        assert sc.classifier_active() is False

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", "", "random"])
    def test_flag_falsy_values_off(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv("HAPAX_SCENE_CLASSIFIER_ACTIVE", val)
        assert sc.classifier_active() is False

    @pytest.mark.parametrize("val", ["1", "true", "yes", "on", "True", "YES"])
    def test_flag_truthy_values_on(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv("HAPAX_SCENE_CLASSIFIER_ACTIVE", val)
        assert sc.classifier_active() is True

    def test_maybe_start_returns_none_when_inactive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HAPAX_SCENE_CLASSIFIER_ACTIVE", raising=False)
        # Should not start a thread.
        result = sc.maybe_start_scene_classifier()
        assert result is None


class TestReadPublishedScene:
    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        assert sc.read_published_scene(tmp_path / "missing.json") is None

    def test_returns_fresh_scene(self, tmp_path: Path) -> None:
        import time

        path = tmp_path / "scene-classification.json"
        path.write_text(
            json.dumps(
                {
                    "scene": "turntables-playing",
                    "confidence": 0.8,
                    "evidence": "vinyl",
                    "ts": time.time(),
                }
            )
        )
        assert sc.read_published_scene(path) == "turntables-playing"

    def test_returns_none_when_stale(self, tmp_path: Path) -> None:
        path = tmp_path / "scene-classification.json"
        path.write_text(
            json.dumps(
                {
                    "scene": "turntables-playing",
                    "confidence": 0.8,
                    "evidence": "vinyl",
                    "ts": 0.0,  # epoch 0 is definitely stale
                }
            )
        )
        assert sc.read_published_scene(path, max_age_s=30.0) is None

    def test_returns_none_when_scene_unknown(self, tmp_path: Path) -> None:
        import time

        path = tmp_path / "scene-classification.json"
        path.write_text(json.dumps({"scene": "bogus", "confidence": 0.5, "ts": time.time()}))
        assert sc.read_published_scene(path) is None


# ── Preset-family scene bias tests ────────────────────────────────────────


class TestPickWithSceneBias:
    def test_unknown_family_returns_none(self) -> None:
        assert pfs.pick_with_scene_bias("bogus-family", "person-face-closeup") is None

    def test_none_scene_falls_back_to_uniform(self) -> None:
        # With scene=None, should behave like pick_from_family — returns
        # a member of the family.
        pick = pfs.pick_with_scene_bias("glitch-dense", None, rng=Random(42))
        assert pick in pfs.presets_for_family("glitch-dense")

    def test_mixed_activity_applies_no_bias(self) -> None:
        pick = pfs.pick_with_scene_bias("calm-textural", "mixed-activity", rng=Random(42))
        assert pick in pfs.presets_for_family("calm-textural")

    def test_empty_room_applies_no_bias(self) -> None:
        pick = pfs.pick_with_scene_bias("calm-textural", "empty-room", rng=Random(42))
        assert pick in pfs.presets_for_family("calm-textural")

    def test_bias_prefers_matching_tags(self) -> None:
        # calm-textural family includes "kaleidodream" (tags: rotation,
        # spiral, geometric) and several untagged presets. With scene
        # "turntables-playing" biasing toward rotation/spiral,
        # kaleidodream should get non-trivially elevated selection.
        hits = 0
        trials = 400
        for seed in range(trials):
            pick = pfs.pick_with_scene_bias("calm-textural", "turntables-playing", rng=Random(seed))
            if pick == "kaleidodream":
                hits += 1
            # Ensure no back-to-back memory pinning across seeds.
            pfs.reset_memory()
        # Without bias, 1/6 = 16.6%; with +2 tags = 3x weight, the
        # biased share should comfortably exceed the uniform share.
        uniform_share = 1.0 / len(pfs.presets_for_family("calm-textural"))
        biased_share = hits / trials
        assert biased_share > uniform_share * 1.5, (
            f"bias not applied: hit-rate {biased_share:.3f} vs uniform {uniform_share:.3f}"
        )

    def test_bias_returns_family_member(self) -> None:
        # Even under heavy bias, the pick must come from the family.
        for seed in range(20):
            pick = pfs.pick_with_scene_bias(
                "calm-textural", "person-face-closeup", rng=Random(seed)
            )
            assert pick in pfs.presets_for_family("calm-textural")
            pfs.reset_memory()

    def test_available_filter_respected(self) -> None:
        # Limit the available pool to a single preset; bias must honor it.
        only = pfs.presets_for_family("warm-minimal")[0]
        pick = pfs.pick_with_scene_bias(
            "warm-minimal",
            "screen-only",
            rng=Random(0),
            available=[only],
        )
        assert pick == only

    def test_available_filter_with_no_match_returns_none(self) -> None:
        result = pfs.pick_with_scene_bias(
            "calm-textural",
            "person-face-closeup",
            available=["completely-unrelated"],
        )
        assert result is None

    def test_unknown_scene_falls_through_uniform(self) -> None:
        # A scene not present in SCENE_TAG_BIAS behaves as "no bias".
        pick = pfs.pick_with_scene_bias("calm-textural", "not-a-scene", rng=Random(0))
        assert pick in pfs.presets_for_family("calm-textural")


class TestPresetTags:
    def test_missing_tags_returns_empty(self) -> None:
        # datamosh.json was not given tags metadata; should return ().
        tags = pfs._preset_tags("datamosh")
        assert tags == ()

    def test_tagged_preset_returns_tags(self) -> None:
        tags = pfs._preset_tags("kaleidodream")
        assert "rotation" in tags
        assert "spiral" in tags

    def test_missing_file_returns_empty(self) -> None:
        assert pfs._preset_tags("not-a-real-preset-anywhere") == ()


# ── Compositor integration sanity ─────────────────────────────────────────


class TestMaybeStartSceneClassifier:
    def test_starts_when_flag_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_SCENE_CLASSIFIER_ACTIVE", "1")
        # We don't want it to actually poll, so immediately stop.
        thread = sc.maybe_start_scene_classifier(interval_s=60.0)
        try:
            assert thread is not None
            assert thread.is_alive()
        finally:
            if thread is not None:
                thread.stop()
                thread.join(timeout=2.0)

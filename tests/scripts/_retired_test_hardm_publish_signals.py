"""Tests for HARDM signal publisher (scripts/hardm-publish-signals.py).

Covers the three contract invariants for HOMAGE follow-on #121:

1. With realistic fixture state files present, output JSON has all
   16 primary signal keys populated with non-default values.
2. With every canonical source missing, publisher emits defaults
   (False / None / None) without raising.
3. With malformed JSON in canonical sources, publisher falls back
   to defaults without crashing.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

EXPECTED_KEYS: set[str] = {
    "midi_active",
    "vad_speech",
    "watch_hr",
    "bt_phone",
    "kde_connect",
    "screen_focus",
    "room_occupancy",
    "ir_person_detected",
    "ambient_sound",
    "director_stance",
    "stimmung_energy",
    "shader_energy",
    "reverie_pass",
    "consent_gate",
    "degraded_stream",
    "homage_package",
}


@pytest.fixture()
def publisher_mod():
    # Load the hyphenated script file as a module. Use a fresh name each
    # test invocation so module-level constants can be monkeypatched
    # per test without cross-test bleed.
    mod_name = "hardm_publish_signals"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "hardm-publish-signals.py"
    spec = importlib.util.spec_from_file_location(mod_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def _redirect_paths(monkeypatch: pytest.MonkeyPatch, publisher_mod, tmp_path: Path) -> Path:
    """Point every module-level SHM path at tmp_path; return the out dir."""
    out_dir = tmp_path / "hapax-compositor"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(publisher_mod, "OUT_FILE", out_dir / "hardm-cell-signals.json")
    monkeypatch.setattr(
        publisher_mod, "_PERCEPTION_STATE", tmp_path / "hapax-daimonion" / "perception-state.json"
    )
    monkeypatch.setattr(
        publisher_mod, "_NARRATIVE_STATE", tmp_path / "hapax-director" / "narrative-state.json"
    )
    monkeypatch.setattr(
        publisher_mod, "_STIMMUNG_STATE", tmp_path / "hapax-daimonion" / "stimmung-state.json"
    )
    monkeypatch.setattr(
        publisher_mod, "_DEGRADED_FLAG", tmp_path / "hapax-compositor" / "degraded.flag"
    )
    monkeypatch.setattr(
        publisher_mod, "_UNIFORMS_JSON", tmp_path / "hapax-imagination" / "uniforms.json"
    )
    monkeypatch.setattr(
        publisher_mod, "_HOMAGE_ACTIVE", tmp_path / "hapax-compositor" / "homage-active.json"
    )
    return out_dir


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestPublisherWithFixtures:
    def test_all_16_keys_present_with_realistic_state(
        self, publisher_mod, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        out_dir = _redirect_paths(monkeypatch, publisher_mod, tmp_path)

        _write(
            publisher_mod._PERCEPTION_STATE,
            {
                # Keys align with the live perception-state.json schema
                # (verified 2026-04-20): mixer_active / vad_confidence /
                # heart_rate_bpm / operator_present / phone_kde_connected
                # / desktop_active / person_count / ir_person_detected /
                # audio_energy_rms.
                "mixer_active": True,
                "vad_confidence": 0.82,
                "heart_rate_bpm": 82,
                "operator_present": True,
                "phone_kde_connected": True,
                "desktop_active": True,
                "person_count": 2,
                "ir_person_detected": True,
                "audio_energy_rms": 0.42,
            },
        )
        _write(publisher_mod._NARRATIVE_STATE, {"stance": "SEEKING"})
        _write(
            publisher_mod._STIMMUNG_STATE,
            {
                # Stimmung wraps each dimension as
                # ``{"value": float, "trend": str, "freshness_s": float}``.
                "overall_stance": "seeking",
                "operator_energy": {"value": 0.77, "trend": "stable", "freshness_s": 0.0},
            },
        )
        _write(
            publisher_mod._UNIFORMS_JSON,
            {"signal.homage_custom_4_0": 0.55, "signal.reverie_pass": 4.0},
        )
        _write(publisher_mod._HOMAGE_ACTIVE, {"package": "bitchx"})
        publisher_mod._DEGRADED_FLAG.parent.mkdir(parents=True, exist_ok=True)
        publisher_mod._DEGRADED_FLAG.touch()

        # Consent state is best-effort from a shared module; stub it so
        # the test is deterministic regardless of live registry contents.
        monkeypatch.setattr(publisher_mod, "_consent_state", lambda: "ok")

        assert publisher_mod.main() == 0

        out = json.loads((out_dir / "hardm-cell-signals.json").read_text(encoding="utf-8"))
        assert "generated_at" in out
        sig = out["signals"]
        assert set(sig.keys()) == EXPECTED_KEYS

        # Spot-check non-default values landed.
        assert sig["midi_active"] is True
        assert sig["vad_speech"] is True
        assert sig["watch_hr"] == 0.33  # 82 bpm → elevated band (75–95)
        assert sig["bt_phone"] is True
        assert sig["kde_connect"] is True
        assert sig["screen_focus"] is True
        assert sig["room_occupancy"] == 1.0
        assert sig["ir_person_detected"] is True
        assert sig["ambient_sound"] == pytest.approx(0.42)
        assert sig["director_stance"] == "seeking"
        assert sig["stimmung_energy"] == pytest.approx(0.77)
        assert sig["shader_energy"] == pytest.approx(0.55)
        assert sig["reverie_pass"] == pytest.approx(0.5)
        assert sig["consent_gate"] == "ok"
        assert sig["degraded_stream"] is True
        assert sig["homage_package"] == "bitchx"


class TestPublisherWithMissingState:
    def test_missing_state_defaults_without_crash(
        self, publisher_mod, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        out_dir = _redirect_paths(monkeypatch, publisher_mod, tmp_path)
        # No state files written. Stub consent to avoid live-registry flap.
        monkeypatch.setattr(publisher_mod, "_consent_state", lambda: None)

        assert publisher_mod.main() == 0

        out = json.loads((out_dir / "hardm-cell-signals.json").read_text(encoding="utf-8"))
        sig = out["signals"]
        assert set(sig.keys()) == EXPECTED_KEYS

        # Booleans default to False, scalars to None.
        assert sig["midi_active"] is False
        assert sig["vad_speech"] is False
        assert sig["watch_hr"] is None
        assert sig["bt_phone"] is False
        assert sig["kde_connect"] is False
        assert sig["screen_focus"] is False
        assert sig["room_occupancy"] is None
        assert sig["ir_person_detected"] is False
        assert sig["ambient_sound"] is None
        assert sig["director_stance"] is None
        assert sig["stimmung_energy"] is None
        assert sig["shader_energy"] is None
        assert sig["reverie_pass"] is None
        assert sig["consent_gate"] is None
        assert sig["degraded_stream"] is False
        assert sig["homage_package"] is None


class TestPublisherWithMalformedState:
    def test_malformed_json_does_not_crash_and_defaults(
        self, publisher_mod, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        out_dir = _redirect_paths(monkeypatch, publisher_mod, tmp_path)
        for p in (
            publisher_mod._PERCEPTION_STATE,
            publisher_mod._NARRATIVE_STATE,
            publisher_mod._STIMMUNG_STATE,
            publisher_mod._UNIFORMS_JSON,
            publisher_mod._HOMAGE_ACTIVE,
        ):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{not valid json", encoding="utf-8")

        monkeypatch.setattr(publisher_mod, "_consent_state", lambda: None)

        assert publisher_mod.main() == 0

        out = json.loads((out_dir / "hardm-cell-signals.json").read_text(encoding="utf-8"))
        sig = out["signals"]
        assert set(sig.keys()) == EXPECTED_KEYS
        # Everything should be default because every read failed.
        assert sig["midi_active"] is False
        assert sig["director_stance"] is None
        assert sig["stimmung_energy"] is None
        assert sig["homage_package"] is None

    def test_unexpected_shape_treated_as_empty(
        self, publisher_mod, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # JSON that parses but is a list, not a dict — publisher should
        # treat as empty and still emit all 16 keys with defaults.
        out_dir = _redirect_paths(monkeypatch, publisher_mod, tmp_path)
        _write(publisher_mod._PERCEPTION_STATE, [1, 2, 3])
        _write(publisher_mod._NARRATIVE_STATE, "not a dict")
        monkeypatch.setattr(publisher_mod, "_consent_state", lambda: None)

        assert publisher_mod.main() == 0
        sig = json.loads((out_dir / "hardm-cell-signals.json").read_text(encoding="utf-8"))[
            "signals"
        ]
        assert set(sig.keys()) == EXPECTED_KEYS
        assert sig["midi_active"] is False
        assert sig["director_stance"] is None


class TestAtomicWrite:
    def test_tmp_file_cleaned_up(
        self, publisher_mod, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        out_dir = _redirect_paths(monkeypatch, publisher_mod, tmp_path)
        monkeypatch.setattr(publisher_mod, "_consent_state", lambda: None)
        assert publisher_mod.main() == 0
        assert (out_dir / "hardm-cell-signals.json").exists()
        # No leftover .tmp file after successful rename.
        leftovers = list(out_dir.glob("*.tmp"))
        assert leftovers == []

    def test_publish_failure_surfaces(
        self, publisher_mod, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _redirect_paths(monkeypatch, publisher_mod, tmp_path)
        monkeypatch.setattr(publisher_mod, "_consent_state", lambda: None)
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                publisher_mod.main()

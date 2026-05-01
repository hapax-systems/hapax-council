"""Tests for ``_vinyl_probably_playing`` Phase 4 wiring.

Phase 4 of cc-task ``ir-perception-replace-zones-with-vlm-classification``
adds the rich-vocabulary VLM-semantics check alongside the legacy
zone / activity enums. Tests cover the corner truth-table:

- legacy-zone hits → True
- legacy-activity hits → True
- semantics-only hits → True
- both legacy and semantics negative → False
- override flag → True regardless of others
- malformed semantics dict → falls back to legacy checks safely
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def album_identifier():
    """Import ``scripts/album-identifier.py`` by file path.

    The hyphen in the filename + the script-style entrypoint mean the
    module isn't on the standard import path; we load it via
    ``importlib`` for the test.
    """
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "album-identifier.py"
    spec = importlib.util.spec_from_file_location("album_identifier_module", module_path)
    if spec is None or spec.loader is None:
        pytest.fail(f"could not load module spec at {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["album_identifier_module"] = mod
    spec.loader.exec_module(mod)
    return mod


def _seed_state(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


# ── _semantics_indicates_vinyl ─────────────────────────────────────────


class TestSemanticsIndicatesVinyl:
    @pytest.mark.parametrize(
        "surface",
        [
            "turntable platter",
            "vinyl sleeve",
            "record sleeve",
            "Turntable surface",  # case-insensitive
        ],
    )
    def test_surface_phrases_match(self, album_identifier, surface: str) -> None:
        out = album_identifier._semantics_indicates_vinyl(
            {
                "intent": "operating",
                "surface": surface,
                "hand_position": "right",
                "confidence": 0.9,
            }
        )
        assert out is True

    @pytest.mark.parametrize(
        "intent",
        [
            "scratching",
            "cueing a record on the turntable",
            "lifting needle",
            "lowering needle onto vinyl",
            "spinning the platter",
        ],
    )
    def test_intent_phrases_match(self, album_identifier, intent: str) -> None:
        out = album_identifier._semantics_indicates_vinyl(
            {
                "intent": intent,
                "surface": "ambient desk",
                "hand_position": "right",
                "confidence": 0.9,
            }
        )
        assert out is True

    def test_unrelated_semantics_no_match(self, album_identifier) -> None:
        out = album_identifier._semantics_indicates_vinyl(
            {
                "intent": "typing on keyboard",
                "surface": "laptop keyboard",
                "hand_position": "centered",
                "confidence": 0.9,
            }
        )
        assert out is False

    @pytest.mark.parametrize(
        "bad",
        [
            None,
            "not a dict",
            42,
            [],
            {"intent": None, "surface": None},
            {"intent": 5, "surface": "turntable"},  # non-string intent — surface still matches
        ],
    )
    def test_malformed_input_returns_safely(self, album_identifier, bad) -> None:
        # A non-dict input must return False (no surface or intent to read).
        # The last case is special: surface="turntable" is a valid string
        # so it should still match positive — verifying the partial-fields
        # path doesn't crash on a non-string intent.
        out = album_identifier._semantics_indicates_vinyl(bad)
        if (
            isinstance(bad, dict)
            and isinstance(bad.get("surface"), str)
            and "turntable" in bad["surface"]
        ):
            assert out is True
        else:
            assert out is False


# ── _vinyl_probably_playing truth table ─────────────────────────────────


class TestVinylProbablyPlayingTruthTable:
    def _seed(self, mod, tmp_path: Path, payload: dict) -> Path:
        state_path = tmp_path / "perception-state.json"
        _seed_state(state_path, payload)
        # Patch the module-level constants that the function reads.
        mod._PERCEPTION_STATE_FILE = state_path
        mod._VINYL_OVERRIDE_FLAG = tmp_path / "missing-override.flag"
        return state_path

    def test_zone_alone_returns_true(self, album_identifier, tmp_path: Path) -> None:
        self._seed(
            album_identifier,
            tmp_path,
            {"ir_hand_zone": "turntable", "ir_hand_activity": "idle"},
        )
        assert album_identifier._vinyl_probably_playing() is True

    def test_activity_alone_returns_true(self, album_identifier, tmp_path: Path) -> None:
        self._seed(
            album_identifier,
            tmp_path,
            {"ir_hand_zone": "desk-center", "ir_hand_activity": "scratching"},
        )
        assert album_identifier._vinyl_probably_playing() is True

    def test_semantics_alone_returns_true(self, album_identifier, tmp_path: Path) -> None:
        self._seed(
            album_identifier,
            tmp_path,
            {
                "ir_hand_zone": "desk-center",
                "ir_hand_activity": "idle",
                "ir_hand_semantics": {
                    "intent": "cueing a record on the turntable",
                    "surface": "turntable platter",
                    "hand_position": "right",
                    "confidence": 0.85,
                },
            },
        )
        assert album_identifier._vinyl_probably_playing() is True

    def test_neither_returns_false(self, album_identifier, tmp_path: Path) -> None:
        self._seed(
            album_identifier,
            tmp_path,
            {
                "ir_hand_zone": "desk-center",
                "ir_hand_activity": "idle",
                "ir_hand_semantics": {
                    "intent": "typing on keyboard",
                    "surface": "laptop keyboard",
                    "hand_position": "centered",
                    "confidence": 0.95,
                },
            },
        )
        assert album_identifier._vinyl_probably_playing() is False

    def test_override_flag_short_circuits(self, album_identifier, tmp_path: Path) -> None:
        self._seed(
            album_identifier,
            tmp_path,
            {"ir_hand_zone": "desk-center", "ir_hand_activity": "idle"},
        )
        flag = tmp_path / "vinyl-override.flag"
        flag.touch()
        album_identifier._VINYL_OVERRIDE_FLAG = flag
        assert album_identifier._vinyl_probably_playing() is True

    def test_missing_state_file_returns_false(self, album_identifier, tmp_path: Path) -> None:
        album_identifier._PERCEPTION_STATE_FILE = tmp_path / "absent.json"
        album_identifier._VINYL_OVERRIDE_FLAG = tmp_path / "no-flag"
        assert album_identifier._vinyl_probably_playing() is False

    def test_malformed_semantics_falls_back_to_legacy(
        self, album_identifier, tmp_path: Path
    ) -> None:
        """A malformed `ir_hand_semantics` field must not regress the
        legacy zone / activity gates."""
        self._seed(
            album_identifier,
            tmp_path,
            {
                "ir_hand_zone": "turntable",  # legacy hit
                "ir_hand_activity": "idle",
                "ir_hand_semantics": "garbage",  # malformed
            },
        )
        assert album_identifier._vinyl_probably_playing() is True

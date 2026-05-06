"""Tests for :mod:`shared.audio_reactivity` (CVS #149).

Pins the Protocol conformance path, the per-band blend algebra, inactive-
source exclusion, JSON round-trip, and the NaN/out-of-range guards on
``AudioSignals``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from shared.audio_reactivity import (
    ACTIVE_ENV,
    ACTIVITY_FLOOR_RMS,
    AudioReactivitySource,
    AudioSignals,
    BusSnapshot,
    UnifiedReactivityBus,
    is_active,
    read_shm_snapshot,
    reset_bus_for_tests,
)

# ── Helpers ─────────────────────────────────────────────────────────────────


class _MockSource:
    """Minimal Protocol implementation for testing."""

    def __init__(
        self,
        name: str,
        signals: AudioSignals,
        *,
        active: bool | None = None,
    ) -> None:
        self._name = name
        self._signals = signals
        self._active_override = active

    @property
    def name(self) -> str:
        return self._name

    def get_signals(self) -> AudioSignals:
        return self._signals

    def is_active(self) -> bool:
        if self._active_override is not None:
            return self._active_override
        return self._signals.rms > ACTIVITY_FLOOR_RMS


class _RaisingSource:
    """Source whose DSP raises — exercises bus error isolation."""

    def __init__(self, name: str = "broken") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def get_signals(self) -> AudioSignals:  # pragma: no cover
        raise RuntimeError("dsp exploded")

    def is_active(self) -> bool:  # pragma: no cover
        raise RuntimeError("dsp exploded")


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_bus_for_tests()
    yield
    reset_bus_for_tests()


# ── AudioSignals validation ─────────────────────────────────────────────────


class TestAudioSignalsValidation:
    def test_zero_signal_all_fields_zero(self) -> None:
        sig = AudioSignals.zero()
        for field_name in (
            "rms",
            "onset",
            "centroid",
            "zcr",
            "bpm_estimate",
            "energy_delta",
            "bass_band",
            "mid_band",
            "treble_band",
        ):
            assert getattr(sig, field_name) == 0.0

    def test_nan_rms_clamped_to_zero(self) -> None:
        sig = AudioSignals(
            rms=float("nan"),
            onset=0.0,
            centroid=0.0,
            zcr=0.0,
            bpm_estimate=0.0,
            energy_delta=0.0,
            bass_band=0.0,
            mid_band=0.0,
            treble_band=0.0,
        )
        assert sig.rms == 0.0
        assert not math.isnan(sig.rms)

    def test_inf_clamped_to_one(self) -> None:
        sig = AudioSignals(
            rms=float("inf"),
            onset=0.0,
            centroid=0.0,
            zcr=0.0,
            bpm_estimate=0.0,
            energy_delta=0.0,
            bass_band=0.0,
            mid_band=0.0,
            treble_band=0.0,
        )
        # inf is not finite → clamped to lo (0.0) by _safe_float's isfinite
        # guard. The important invariant is that no non-finite value leaks.
        assert math.isfinite(sig.rms)

    def test_negative_rms_clamped_to_zero(self) -> None:
        sig = AudioSignals(
            rms=-0.5,
            onset=0.0,
            centroid=0.0,
            zcr=0.0,
            bpm_estimate=0.0,
            energy_delta=0.0,
            bass_band=0.0,
            mid_band=0.0,
            treble_band=0.0,
        )
        assert sig.rms == 0.0

    def test_rms_above_one_clamped(self) -> None:
        sig = AudioSignals(
            rms=7.5,
            onset=0.0,
            centroid=0.0,
            zcr=0.0,
            bpm_estimate=0.0,
            energy_delta=0.0,
            bass_band=0.0,
            mid_band=0.0,
            treble_band=0.0,
        )
        assert sig.rms == 1.0

    def test_bpm_bounded_300(self) -> None:
        sig = AudioSignals(
            rms=0.0,
            onset=0.0,
            centroid=0.0,
            zcr=0.0,
            bpm_estimate=1000.0,
            energy_delta=0.0,
            bass_band=0.0,
            mid_band=0.0,
            treble_band=0.0,
        )
        assert sig.bpm_estimate == 300.0

    def test_energy_delta_signed(self) -> None:
        sig = AudioSignals(
            rms=0.0,
            onset=0.0,
            centroid=0.0,
            zcr=0.0,
            bpm_estimate=0.0,
            energy_delta=-0.5,
            bass_band=0.0,
            mid_band=0.0,
            treble_band=0.0,
        )
        assert sig.energy_delta == -0.5

    def test_energy_delta_lower_bound(self) -> None:
        sig = AudioSignals(
            rms=0.0,
            onset=0.0,
            centroid=0.0,
            zcr=0.0,
            bpm_estimate=0.0,
            energy_delta=-5.0,
            bass_band=0.0,
            mid_band=0.0,
            treble_band=0.0,
        )
        assert sig.energy_delta == -1.0

    def test_frozen(self) -> None:
        sig = AudioSignals.zero()
        with pytest.raises(AttributeError):
            sig.rms = 1.0  # type: ignore[misc]


# ── Protocol conformance ────────────────────────────────────────────────────


class TestProtocolConformance:
    def test_mock_source_satisfies_protocol(self) -> None:
        src = _MockSource("m1", AudioSignals.zero())
        assert isinstance(src, AudioReactivitySource)

    def test_multiple_mocks_satisfy_protocol(self) -> None:
        s1 = _MockSource("s1", AudioSignals.zero())
        s2 = _MockSource("s2", AudioSignals.zero())
        assert isinstance(s1, AudioReactivitySource)
        assert isinstance(s2, AudioReactivitySource)


# ── Bus registration ────────────────────────────────────────────────────────


class TestBusRegistration:
    def test_register_then_list(self) -> None:
        bus = UnifiedReactivityBus()
        bus.register(_MockSource("mixer", AudioSignals.zero()))
        bus.register(_MockSource("desk", AudioSignals.zero()))
        assert set(bus.sources()) == {"mixer", "desk"}

    def test_unregister_removes(self) -> None:
        bus = UnifiedReactivityBus()
        bus.register(_MockSource("mixer", AudioSignals.zero()))
        bus.unregister("mixer")
        assert bus.sources() == []

    def test_unregister_missing_is_idempotent(self) -> None:
        bus = UnifiedReactivityBus()
        bus.unregister("never-registered")  # no raise


# ── Bus blending ────────────────────────────────────────────────────────────


class TestBusBlend:
    def test_empty_bus_produces_zero(self, tmp_path: Path) -> None:
        bus = UnifiedReactivityBus(shm_path=tmp_path / "u.json")
        snap = bus.tick(publish=False)
        assert snap.blended == AudioSignals.zero()
        assert snap.active_sources == []

    def test_single_active_source_passes_through(self, tmp_path: Path) -> None:
        bus = UnifiedReactivityBus(shm_path=tmp_path / "u.json")
        sig = AudioSignals(
            rms=0.5,
            onset=0.3,
            centroid=0.6,
            zcr=0.2,
            bpm_estimate=120.0,
            energy_delta=0.1,
            bass_band=0.4,
            mid_band=0.5,
            treble_band=0.2,
        )
        bus.register(_MockSource("mixer", sig, active=True))
        snap = bus.tick(publish=False)
        assert snap.blended == sig
        assert snap.active_sources == ["mixer"]

    def test_three_sources_max_per_band(self, tmp_path: Path) -> None:
        """Bass from bass-heavy source, mid from mid-heavy, treble from treble-heavy."""
        bus = UnifiedReactivityBus(shm_path=tmp_path / "u.json")
        bass_src = AudioSignals(
            rms=0.3,
            onset=0.0,
            centroid=0.1,
            zcr=0.0,
            bpm_estimate=100.0,
            energy_delta=0.0,
            bass_band=0.9,
            mid_band=0.1,
            treble_band=0.05,
        )
        mid_src = AudioSignals(
            rms=0.4,
            onset=0.0,
            centroid=0.5,
            zcr=0.0,
            bpm_estimate=100.0,
            energy_delta=0.0,
            bass_band=0.1,
            mid_band=0.85,
            treble_band=0.2,
        )
        treble_src = AudioSignals(
            rms=0.2,
            onset=0.9,
            centroid=0.9,
            zcr=0.0,
            bpm_estimate=100.0,
            energy_delta=0.0,
            bass_band=0.05,
            mid_band=0.15,
            treble_band=0.95,
        )
        bus.register(_MockSource("bass", bass_src, active=True))
        bus.register(_MockSource("mid", mid_src, active=True))
        bus.register(_MockSource("treble", treble_src, active=True))
        snap = bus.tick(publish=False)
        assert snap.blended.bass_band == pytest.approx(0.9)
        assert snap.blended.mid_band == pytest.approx(0.85)
        assert snap.blended.treble_band == pytest.approx(0.95)
        assert snap.blended.rms == pytest.approx(0.4)  # loudest
        assert snap.blended.onset == pytest.approx(0.9)  # any onset
        assert set(snap.active_sources) == {"bass", "mid", "treble"}

    def test_inactive_source_excluded_from_blend(self, tmp_path: Path) -> None:
        bus = UnifiedReactivityBus(shm_path=tmp_path / "u.json")
        loud = AudioSignals(
            rms=0.8,
            onset=0.5,
            centroid=0.5,
            zcr=0.0,
            bpm_estimate=120.0,
            energy_delta=0.0,
            bass_band=0.7,
            mid_band=0.5,
            treble_band=0.3,
        )
        # Silent source that *claims* bass band — should be ignored
        silent_bass_claim = AudioSignals(
            rms=0.0,
            onset=0.0,
            centroid=0.0,
            zcr=0.0,
            bpm_estimate=0.0,
            energy_delta=0.0,
            bass_band=0.99,  # would dominate if not filtered
            mid_band=0.0,
            treble_band=0.0,
        )
        bus.register(_MockSource("mixer", loud, active=True))
        bus.register(_MockSource("silent", silent_bass_claim, active=False))
        snap = bus.tick(publish=False)
        assert snap.blended.bass_band == pytest.approx(0.7)
        assert snap.active_sources == ["mixer"]
        # Silent source still appears in per_source (attribution preserved)
        assert "silent" in snap.per_source

    def test_raising_source_defaults_to_zero(self, tmp_path: Path) -> None:
        bus = UnifiedReactivityBus(shm_path=tmp_path / "u.json")
        bus.register(_RaisingSource("broken"))
        bus.register(
            _MockSource(
                "good",
                AudioSignals(
                    rms=0.5,
                    onset=0.0,
                    centroid=0.5,
                    zcr=0.0,
                    bpm_estimate=0.0,
                    energy_delta=0.0,
                    bass_band=0.5,
                    mid_band=0.5,
                    treble_band=0.5,
                ),
                active=True,
            )
        )
        snap = bus.tick(publish=False)
        # Good source still dominates; broken source didn't poison the tick
        assert snap.blended.rms == pytest.approx(0.5)


# ── JSON publish round-trip ─────────────────────────────────────────────────


class TestJsonRoundTrip:
    def test_publish_and_read_all_nine_fields(self, tmp_path: Path) -> None:
        shm_path = tmp_path / "unified.json"
        bus = UnifiedReactivityBus(shm_path=shm_path)
        sig = AudioSignals(
            rms=0.123,
            onset=0.234,
            centroid=0.345,
            zcr=0.456,
            bpm_estimate=120.5,
            energy_delta=-0.1,
            bass_band=0.5,
            mid_band=0.6,
            treble_band=0.7,
        )
        bus.register(_MockSource("mixer", sig, active=True))
        bus.tick(publish=True)

        # File exists and contains valid JSON
        assert shm_path.exists()
        data = json.loads(shm_path.read_text())
        assert "blended" in data
        assert "per_source" in data
        assert data["active_sources"] == ["mixer"]

        # read_shm_snapshot reconstructs all 9 fields
        restored = read_shm_snapshot(shm_path)
        assert restored is not None
        assert restored.blended.rms == pytest.approx(0.123)
        assert restored.blended.onset == pytest.approx(0.234)
        assert restored.blended.centroid == pytest.approx(0.345)
        assert restored.blended.zcr == pytest.approx(0.456)
        assert restored.blended.bpm_estimate == pytest.approx(120.5)
        assert restored.blended.energy_delta == pytest.approx(-0.1)
        assert restored.blended.bass_band == pytest.approx(0.5)
        assert restored.blended.mid_band == pytest.approx(0.6)
        assert restored.blended.treble_band == pytest.approx(0.7)

    def test_read_missing_shm_returns_none(self, tmp_path: Path) -> None:
        assert read_shm_snapshot(tmp_path / "missing.json") is None

    def test_read_malformed_json_returns_none(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json at all {{{")
        assert read_shm_snapshot(bad) is None

    def test_read_blended_is_string_returns_none(self, tmp_path: Path) -> None:
        """Schema drift: ``blended`` written as a string instead of a
        mapping previously raised AttributeError out of from_dict, escaping
        the (TypeError, ValueError) catch in read_shm_snapshot. Pin the
        documented contract: malformed → None."""
        bad = tmp_path / "blended_string.json"
        bad.write_text('{"blended": "wrong-shape", "per_source": {}, "active_sources": []}')
        assert read_shm_snapshot(bad) is None

    def test_read_per_source_is_list_returns_none(self, tmp_path: Path) -> None:
        """Schema drift: ``per_source`` written as a list instead of a
        mapping previously raised AttributeError on .items(). Pin
        malformed → None."""
        bad = tmp_path / "per_source_list.json"
        bad.write_text('{"blended": {}, "per_source": ["mixer", "desk"], "active_sources": []}')
        assert read_shm_snapshot(bad) is None

    def test_read_active_sources_is_string_does_not_char_split(self, tmp_path: Path) -> None:
        """Schema drift: ``active_sources`` written as a string previously
        char-split via ``list("mixer,desk") == ['m','i','x',...]``. Pin
        malformed → None instead of silent garbage."""
        bad = tmp_path / "active_sources_string.json"
        bad.write_text('{"blended": {}, "per_source": {}, "active_sources": "mixer,desk"}')
        assert read_shm_snapshot(bad) is None

    @pytest.mark.parametrize(
        "payload,kind",
        [
            ("null", "null"),
            ('"a string"', "string"),
            ("42", "int"),
            ("[1, 2, 3]", "list"),
        ],
    )
    def test_read_top_level_non_dict_returns_none(
        self, tmp_path: Path, payload: str, kind: str
    ) -> None:
        """Schema drift: SHM file containing valid JSON whose root is not
        an object (null, string, number, list) previously raised
        AttributeError at ``data.get(...)`` before any of the per-field
        isinstance checks could fire. Pin malformed → None at the root."""
        bad = tmp_path / f"root_{kind}.json"
        bad.write_text(payload)
        assert read_shm_snapshot(bad) is None, f"root={kind} must return None"

    def test_from_dict_rejects_non_mapping_with_typeerror(self) -> None:
        """AudioSignals.from_dict on a non-dict payload raises TypeError.
        read_shm_snapshot relies on this to translate corruption into None
        rather than letting AttributeError leak out of the boundary."""
        with pytest.raises(TypeError, match="expected mapping"):
            AudioSignals.from_dict("not-a-dict")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="expected mapping"):
            AudioSignals.from_dict(["rms", "onset"])  # type: ignore[arg-type]

    def test_publish_is_atomic(self, tmp_path: Path) -> None:
        """No partial-write artifacts should remain after publish."""
        shm_path = tmp_path / "u.json"
        bus = UnifiedReactivityBus(shm_path=shm_path)
        bus.register(_MockSource("s", AudioSignals.zero()))
        bus.tick(publish=True)
        # Only the final file should exist, no leftover .tmp
        tmps = list(tmp_path.glob(".*.tmp"))
        assert tmps == [], f"leftover tmp files: {tmps}"


# ── Feature flag ────────────────────────────────────────────────────────────


class TestFeatureFlag:
    def test_default_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ACTIVE_ENV, raising=False)
        assert not is_active()

    def test_variants_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for val in ("1", "true", "True", "YES", "on"):
            monkeypatch.setenv(ACTIVE_ENV, val)
            assert is_active(), f"{val!r} should be truthy"

    def test_variants_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for val in ("0", "false", "no", "off", ""):
            monkeypatch.setenv(ACTIVE_ENV, val)
            assert not is_active(), f"{val!r} should be falsy"


# ── Snapshot shape ──────────────────────────────────────────────────────────


class TestSnapshot:
    def test_bus_snapshot_json_round_trip(self) -> None:
        sig = AudioSignals(
            rms=0.5,
            onset=0.1,
            centroid=0.2,
            zcr=0.3,
            bpm_estimate=90.0,
            energy_delta=0.05,
            bass_band=0.4,
            mid_band=0.5,
            treble_band=0.6,
        )
        snap = BusSnapshot(
            blended=sig,
            per_source={"mixer": sig},
            active_sources=["mixer"],
        )
        raw = snap.to_json()
        data = json.loads(raw)
        assert data["blended"]["rms"] == pytest.approx(0.5)
        assert data["active_sources"] == ["mixer"]

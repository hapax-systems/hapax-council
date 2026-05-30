"""Tests for narrative density audience relevance."""

from __future__ import annotations

import json

from agents import information_density_daemon


def test_narrative_relevance_combines_viewers_chat_and_concept_mastery(
    tmp_path, monkeypatch
) -> None:
    audience = tmp_path / "audience.json"
    audience.write_text(
        json.dumps(
            {
                "viewer_count": 5,
                "chat_rate_per_min": 2.0,
                "avg_watch_time_s": 180.0,
                "concept_mastery": {
                    "zpd_pressure": 0.6,
                    "unknown_pressure": 0.2,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(information_density_daemon, "AUDIENCE_SHM", audience)

    relevance = information_density_daemon.NarrativeSource([])._compute_relevance()

    assert 0.0 < relevance < 1.0


def test_narrative_relevance_uses_bkt_pressure_without_viewers(tmp_path, monkeypatch) -> None:
    audience = tmp_path / "audience.json"
    audience.write_text(
        json.dumps({"viewer_count": 0, "concept_mastery": {"unknown_pressure": 0.8}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(information_density_daemon, "AUDIENCE_SHM", audience)

    relevance = information_density_daemon.NarrativeSource([])._compute_relevance()

    assert relevance > 0.0


def test_extract_float_unwraps_stimmung_style_nested_value() -> None:
    # stimmung writes {"health": {"value": 0.205, "trend": "stable", ...}}; the
    # daemon must read the nested scalar instead of zeroing the source.
    data = {"health": {"value": 0.205, "trend": "stable"}}
    assert information_density_daemon._extract_float(data, "health") == 0.205


def test_extract_float_reads_flat_scalar() -> None:
    assert information_density_daemon._extract_float({"rms": 0.5}, "rms") == 0.5


def test_extract_float_nested_without_value_falls_back_to_default() -> None:
    data = {"health": {"trend": "stable"}}
    assert information_density_daemon._extract_float(data, "health", default=0.0) == 0.0


def test_extract_float_tries_keys_in_order() -> None:
    assert (
        information_density_daemon._extract_float({"rms_dbfs": -12.0}, "rms", "rms_dbfs") == -12.0
    )


def test_read_source_value_honors_blended_subkey(tmp_path) -> None:
    # R2 unified-reactivity.json nests signals under "blended".
    shm = tmp_path / "unified-reactivity.json"
    shm.write_text(json.dumps({"blended": {"rms": 0.18, "bass_band": 0.27}}), encoding="utf-8")
    src = {"shm": str(shm), "subkey": "blended", "keys": ["rms"]}
    assert information_density_daemon._read_source_value(src) == 0.18


def test_read_source_value_without_subkey_reads_top_level(tmp_path) -> None:
    shm = tmp_path / "state.json"
    shm.write_text(json.dumps({"rms_dbfs": -20.0}), encoding="utf-8")
    src = {"shm": str(shm), "keys": ["rms", "rms_dbfs"]}
    assert information_density_daemon._read_source_value(src) == -20.0


def test_read_source_value_missing_file_returns_zero(tmp_path) -> None:
    src = {"shm": str(tmp_path / "absent.json"), "subkey": "blended", "keys": ["rms"]}
    assert information_density_daemon._read_source_value(src) == 0.0


def test_source_registry_includes_live_reactivity_and_centroid_fix() -> None:
    registry = {s["id"]: s for s in information_density_daemon.SOURCE_REGISTRY}
    for sid in ("audio.reactivity_rms", "audio.reactivity_bass", "audio.reactivity_onset"):
        assert sid in registry, f"{sid} missing from SOURCE_REGISTRY"
        assert registry[sid]["subkey"] == "blended"
        assert registry[sid]["shm"].endswith("unified-reactivity.json")
    # spectral centroid must read the real key name the producer writes.
    assert "spectral_centroid_hz" in registry["audio.spectral_centroid"]["keys"]

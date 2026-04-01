"""Tests for eigenform convergence detection (Property 6)."""

from __future__ import annotations

import json
from pathlib import Path


def test_fixed_point_detection(tmp_path: Path):
    """Identical entries = no change = fixed point."""
    from shared.eigenform_analysis import analyze_convergence

    path = tmp_path / "log.jsonl"
    entry = {
        "presence": 0.9,
        "flow_score": 0.7,
        "audio_energy": 0.3,
        "stimmung_stance": "nominal",
        "imagination_salience": 0.3,
        "visual_brightness": 0.2,
        "heart_rate": 70,
        "operator_stress": 0.1,
        "e_mesh": 0.3,
        "consistency_radius": 0.1,
        "t": 0,
    }
    lines = [json.dumps(entry) for _ in range(12)]
    path.write_text("\n".join(lines) + "\n")

    result = analyze_convergence(path=path, window=10, threshold=0.05)
    assert result["converged"] is True
    assert result["eigenform_type"] == "fixed_point"
    assert result["mean_delta"] == 0.0


def test_divergent_detection(tmp_path: Path):
    """Monotonically increasing values = divergent."""
    from shared.eigenform_analysis import analyze_convergence

    path = tmp_path / "log.jsonl"
    entries = []
    for i in range(12):
        entries.append(
            json.dumps(
                {
                    "presence": float(i) / 10,
                    "flow_score": float(i) / 5,
                    "audio_energy": 0.0,
                    "stimmung_stance": "nominal",
                    "imagination_salience": 0.0,
                    "visual_brightness": 0.0,
                    "heart_rate": 60 + i * 5,
                    "operator_stress": 0.0,
                    "e_mesh": 0.5,
                    "consistency_radius": 0.2,
                    "t": i,
                }
            )
        )
    path.write_text("\n".join(entries) + "\n")

    result = analyze_convergence(path=path, window=10, threshold=0.05)
    assert result["converged"] is False
    assert result["eigenform_type"] == "divergent"


def test_insufficient_data(tmp_path: Path):
    """Too few entries = insufficient data."""
    from shared.eigenform_analysis import analyze_convergence

    path = tmp_path / "log.jsonl"
    path.write_text(json.dumps({"presence": 0.5, "t": 0}) + "\n")

    result = analyze_convergence(path=path, window=10)
    assert result["eigenform_type"] == "insufficient_data"


def test_missing_file(tmp_path: Path):
    """Missing file returns insufficient_data gracefully."""
    from shared.eigenform_analysis import analyze_convergence

    path = tmp_path / "nonexistent.jsonl"
    result = analyze_convergence(path=path)
    assert result["eigenform_type"] == "insufficient_data"
    assert result["entries_analyzed"] == 0


def test_stable_orbit_detection(tmp_path: Path):
    """Values oscillating in a tight band = stable orbit."""
    from shared.eigenform_analysis import analyze_convergence

    path = tmp_path / "log.jsonl"
    entries = []
    for i in range(12):
        # Oscillate presence between 0.5 and 0.52 — tight band
        p = 0.5 + 0.02 * (i % 2)
        entries.append(
            json.dumps(
                {
                    "presence": p,
                    "flow_score": 0.7,
                    "audio_energy": 0.3,
                    "stimmung_stance": "nominal",
                    "imagination_salience": 0.3,
                    "visual_brightness": 0.2,
                    "heart_rate": 70,
                    "operator_stress": 0.1,
                    "e_mesh": 0.3,
                    "consistency_radius": 0.1,
                    "t": i,
                }
            )
        )
    path.write_text("\n".join(entries) + "\n")

    result = analyze_convergence(path=path, window=10, threshold=0.05)
    # Small oscillation should be either fixed_point or stable_orbit
    assert result["converged"] is True
    assert result["eigenform_type"] in ("fixed_point", "stable_orbit")

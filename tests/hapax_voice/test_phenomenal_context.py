"""Tests for phenomenal context renderer.

Verifies progressive fidelity, faithful rendering, and orientation
(not information) across tier levels.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest as _pytest

from agents.hapax_voice.phenomenal_context import (
    _clear_cache,
    _render_impression,
    _render_self_state,
    _render_situation,
    _render_stimmung,
    _render_surprise,
    _render_temporal_depth,
    render,
)


@_pytest.fixture(autouse=True)
def _clear_phenomenal_cache():
    """Clear the temporal cache before each test."""
    _clear_cache()
    yield
    _clear_cache()


def _make_temporal_shm(
    tmp_path: Path,
    *,
    activity: str = "coding",
    flow_state: str = "active",
    flow_score: float = 0.72,
    heart_rate: int = 78,
    music_genre: str = "lo-fi",
    presence: str = "present",
    presence_probability: float = 0.9,
    surprises: list[dict] | None = None,
    retention: list[dict] | None = None,
    protention: list[dict] | None = None,
) -> Path:
    """Build a minimal temporal bands XML and write to tmp_path."""
    imp_parts = [
        f"    <flow_state>{flow_state}</flow_state>",
        f"    <flow_score>{flow_score}</flow_score>",
        f"    <activity>{activity}</activity>",
        f"    <music_genre>{music_genre}</music_genre>",
        f"    <heart_rate>{heart_rate}</heart_rate>",
    ]
    if presence:
        imp_parts.append(f"    <presence>{presence}</presence>")
        imp_parts.append(f"    <presence_probability>{presence_probability}</presence_probability>")

    # Add surprise annotations
    if surprises:
        for s in surprises:
            field = s["field"]
            # Replace the plain tag with surprised version
            imp_parts = [p for p in imp_parts if not p.strip().startswith(f"<{field}>")]
            imp_parts.append(
                f'    <{field} surprise="{s["surprise"]:.2f}" '
                f'expected="{s["expected"]}">{s["observed"]}</{field}>'
            )

    xml_parts = ["<temporal_context>", "  <impression>"]
    xml_parts.extend(imp_parts)
    xml_parts.append("  </impression>")

    if retention:
        xml_parts.append("  <retention>")
        for r in retention:
            attrs = f'age_s="{r["age_s"]}" flow="{r.get("flow", "idle")}" activity="{r.get("activity", "")}"'
            if "presence" in r:
                attrs += f' presence="{r["presence"]}"'
            xml_parts.append(f"    <memory {attrs}>{r.get('summary', 'quiet')}</memory>")
        xml_parts.append("  </retention>")

    if protention:
        xml_parts.append("  <protention>")
        for p in protention:
            xml_parts.append(
                f'    <prediction state="{p["state"]}" '
                f'confidence="{p["confidence"]:.2f}">{p.get("basis", "")}</prediction>'
            )
        xml_parts.append("  </protention>")

    xml_parts.append("</temporal_context>")
    xml = "\n".join(xml_parts)

    payload = {
        "xml": xml,
        "max_surprise": max((s.get("surprise", 0) for s in (surprises or [])), default=0.0),
        "timestamp": time.time(),
    }
    bands_file = tmp_path / "bands.json"
    bands_file.write_text(json.dumps(payload))
    return bands_file


def _make_apperception_shm(
    tmp_path: Path,
    *,
    coherence: float = 0.7,
    dimensions: dict | None = None,
    observations: list[str] | None = None,
    reflections: list[str] | None = None,
    pending_actions: list[str] | None = None,
) -> Path:
    payload = {
        "self_model": {
            "dimensions": dimensions or {},
            "recent_observations": observations or [],
            "recent_reflections": reflections or [],
            "coherence": coherence,
        },
        "pending_actions": pending_actions or [],
        "timestamp": time.time(),
    }
    band_file = tmp_path / "self-band.json"
    band_file.write_text(json.dumps(payload))
    return band_file


def _make_stimmung_shm(tmp_path: Path, *, stance: str = "nominal") -> Path:
    payload = {"overall_stance": stance, "timestamp": time.time()}
    stimmung_file = tmp_path / "state.json"
    stimmung_file.write_text(json.dumps(payload))
    return stimmung_file


# ── Progressive Fidelity Tests ───────────────────────────────────────────────


class TestProgressiveFidelity:
    def test_local_gets_layers_1_through_3(self, tmp_path):
        bands = _make_temporal_shm(tmp_path, activity="coding", flow_state="active")
        stimmung = _make_stimmung_shm(tmp_path, stance="nominal")

        with (
            patch("agents.hapax_voice.phenomenal_context._TEMPORAL_PATH", bands),
            patch("agents.hapax_voice.phenomenal_context._STIMMUNG_PATH", stimmung),
        ):
            result = render(tier="LOCAL")
            assert result  # not empty
            # Should NOT contain surprise or self-state
            assert "Surprise" not in result
            assert "Uncertain" not in result

    def test_fast_gets_through_layer_5(self, tmp_path):
        bands = _make_temporal_shm(
            tmp_path,
            activity="coding",
            surprises=[
                {"field": "flow_state", "observed": "idle", "expected": "active", "surprise": 0.6}
            ],
            retention=[
                {"age_s": 15, "flow": "active", "activity": "coding", "summary": "coding, 72bpm"}
            ],
        )
        stimmung = _make_stimmung_shm(tmp_path)

        with (
            patch("agents.hapax_voice.phenomenal_context._TEMPORAL_PATH", bands),
            patch("agents.hapax_voice.phenomenal_context._STIMMUNG_PATH", stimmung),
        ):
            result = render(tier="FAST")
            assert "Surprise" in result or "unexpected" in result
            assert "Was:" in result  # retention

    def test_capable_gets_all_layers(self, tmp_path):
        bands = _make_temporal_shm(tmp_path, activity="coding")
        stimmung = _make_stimmung_shm(tmp_path)
        apperception = _make_apperception_shm(
            tmp_path,
            coherence=0.4,
            dimensions={"activity_recognition": {"confidence": 0.2}},
        )

        with (
            patch("agents.hapax_voice.phenomenal_context._TEMPORAL_PATH", bands),
            patch("agents.hapax_voice.phenomenal_context._STIMMUNG_PATH", stimmung),
            patch("agents.hapax_voice.phenomenal_context._APPERCEPTION_PATH", apperception),
        ):
            result = render(tier="CAPABLE")
            assert "activity recognition" in result  # self-state layer


# ── Orientation Tests (not information) ──────────────────────────────────────


class TestOrientation:
    def test_situation_is_coupled(self, tmp_path):
        """Situation line couples activity + time, not lists them separately."""
        bands = _make_temporal_shm(tmp_path, activity="coding", flow_state="active")
        with patch("agents.hapax_voice.phenomenal_context._TEMPORAL_PATH", bands):
            result = _render_situation()
            # Should be something like "Evening, deep coding" not "Activity: coding. Time: evening."
            assert ":" not in result or result.count(":") <= 1  # no key:value pairs

    def test_no_xml_in_output(self, tmp_path):
        """Output is natural language, never XML."""
        bands = _make_temporal_shm(tmp_path, activity="coding")
        stimmung = _make_stimmung_shm(tmp_path)
        with (
            patch("agents.hapax_voice.phenomenal_context._TEMPORAL_PATH", bands),
            patch("agents.hapax_voice.phenomenal_context._STIMMUNG_PATH", stimmung),
        ):
            result = render(tier="CAPABLE")
            assert "<" not in result
            assert ">" not in result

    def test_no_explanatory_framing(self, tmp_path):
        """No 'retention = fading past' style explanations."""
        bands = _make_temporal_shm(tmp_path, activity="coding")
        stimmung = _make_stimmung_shm(tmp_path)
        with (
            patch("agents.hapax_voice.phenomenal_context._TEMPORAL_PATH", bands),
            patch("agents.hapax_voice.phenomenal_context._STIMMUNG_PATH", stimmung),
        ):
            result = render(tier="CAPABLE")
            assert "retention" not in result.lower()
            assert "impression" not in result.lower()
            assert "protention" not in result.lower()


# ── Self-Compression Tests ───────────────────────────────────────────────────


class TestSelfCompression:
    def test_nominal_stimmung_empty(self, tmp_path):
        stimmung = _make_stimmung_shm(tmp_path, stance="nominal")
        with patch("agents.hapax_voice.phenomenal_context._STIMMUNG_PATH", stimmung):
            result = _render_stimmung()
            assert result == ""

    def test_degraded_stimmung_present(self, tmp_path):
        stimmung = _make_stimmung_shm(tmp_path, stance="degraded")
        with patch("agents.hapax_voice.phenomenal_context._STIMMUNG_PATH", stimmung):
            result = _render_stimmung()
            assert "degraded" in result.lower()

    def test_missing_temporal_returns_empty(self):
        with patch(
            "agents.hapax_voice.phenomenal_context._TEMPORAL_PATH",
            Path("/nonexistent"),
        ):
            result = render(tier="CAPABLE")
            assert result == "" or "Self" in result  # only self-state or nothing

    def test_missing_apperception_ok(self, tmp_path):
        bands = _make_temporal_shm(tmp_path, activity="coding")
        stimmung = _make_stimmung_shm(tmp_path)
        with (
            patch("agents.hapax_voice.phenomenal_context._TEMPORAL_PATH", bands),
            patch("agents.hapax_voice.phenomenal_context._STIMMUNG_PATH", stimmung),
            patch("agents.hapax_voice.phenomenal_context._APPERCEPTION_PATH", Path("/nonexistent")),
        ):
            result = render(tier="CAPABLE")
            assert result  # temporal layers still present


# ── Direction Preservation Tests ─────────────────────────────────────────────


class TestDirectionPreservation:
    def test_protention_renders_as_arrow(self, tmp_path):
        """Protention appears as '→ state' showing direction."""
        bands = _make_temporal_shm(
            tmp_path,
            activity="coding",
            protention=[
                {"state": "entering_deep_work", "confidence": 0.72, "basis": "flow rising"}
            ],
        )
        with patch("agents.hapax_voice.phenomenal_context._TEMPORAL_PATH", bands):
            result = _render_impression()
            assert "→" in result
            assert "entering deep work" in result

    def test_operator_away_rendered(self, tmp_path):
        """Operator absence changes the situation line."""
        bands = _make_temporal_shm(
            tmp_path,
            activity="idle",
            flow_state="idle",
            presence="away",
            presence_probability=0.1,
        )
        with patch("agents.hapax_voice.phenomenal_context._TEMPORAL_PATH", bands):
            result = _render_situation()
            assert "away" in result.lower()

    def test_surprise_renders_deviation(self, tmp_path):
        """Surprise renders as prediction error, not just observation."""
        bands = _make_temporal_shm(
            tmp_path,
            surprises=[
                {
                    "field": "flow_state",
                    "observed": "idle",
                    "expected": "active",
                    "surprise": 0.7,
                }
            ],
        )
        with patch("agents.hapax_voice.phenomenal_context._TEMPORAL_PATH", bands):
            result = _render_surprise()
            assert "unexpected" in result.lower()
            assert "predicted" in result.lower()

    def test_retention_shows_temporal_arrow(self, tmp_path):
        """Retention uses → to show temporal progression."""
        bands = _make_temporal_shm(
            tmp_path,
            retention=[
                {"age_s": 40, "activity": "browsing", "summary": "browsing"},
                {"age_s": 5, "activity": "coding", "summary": "coding, 78bpm"},
            ],
        )
        with patch("agents.hapax_voice.phenomenal_context._TEMPORAL_PATH", bands):
            result = _render_temporal_depth()
            assert "→" in result
            assert "Was:" in result


# ── Self-State Tests ─────────────────────────────────────────────────────────


class TestSelfState:
    def test_low_coherence_hedging_instruction(self, tmp_path):
        apperception = _make_apperception_shm(tmp_path, coherence=0.3)
        with patch("agents.hapax_voice.phenomenal_context._APPERCEPTION_PATH", apperception):
            result = _render_self_state()
            assert "hedge" in result.lower()

    def test_high_coherence_no_output(self, tmp_path):
        apperception = _make_apperception_shm(tmp_path, coherence=0.8)
        with patch("agents.hapax_voice.phenomenal_context._APPERCEPTION_PATH", apperception):
            result = _render_self_state()
            assert result == ""

    def test_low_confidence_dimension_named(self, tmp_path):
        apperception = _make_apperception_shm(
            tmp_path,
            dimensions={"activity_recognition": {"confidence": 0.2}},
        )
        with patch("agents.hapax_voice.phenomenal_context._APPERCEPTION_PATH", apperception):
            result = _render_self_state()
            assert "activity recognition" in result

    def test_reflection_included(self, tmp_path):
        apperception = _make_apperception_shm(
            tmp_path,
            reflections=[
                "I notice a tension: accuracy trend positive but last event problematized"
            ],
        )
        with patch("agents.hapax_voice.phenomenal_context._APPERCEPTION_PATH", apperception):
            result = _render_self_state()
            assert "tension" in result

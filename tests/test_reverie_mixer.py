"""Tests for the Reverie mixer — visual expression orchestrator."""

import json
import tempfile
from pathlib import Path

from agents.reverie.mixer import ReverieMixer


def test_mixer_initializes():
    mixer = ReverieMixer()
    assert mixer is not None


def test_mixer_reads_acoustic_impulse():
    mixer = ReverieMixer()
    with tempfile.TemporaryDirectory() as tmpdir:
        impulse_path = Path(tmpdir) / "acoustic-impulse.json"
        impulse_path.write_text(
            json.dumps(
                {
                    "source": "daimonion",
                    "timestamp": 1711907400.0,
                    "signals": {"energy": 0.7, "onset": True, "pitch_hz": 185.0},
                }
            )
        )
        result = mixer._read_acoustic_impulse(impulse_path)
        assert result is not None
        assert result["signals"]["energy"] == 0.7


def test_mixer_reads_missing_acoustic_impulse():
    mixer = ReverieMixer()
    result = mixer._read_acoustic_impulse(Path("/nonexistent/path"))
    assert result is None


def test_mixer_writes_visual_salience():
    mixer = ReverieMixer()
    with tempfile.TemporaryDirectory() as tmpdir:
        salience_path = Path(tmpdir) / "visual-salience.json"
        mixer._write_visual_salience(salience_path, salience=0.6, content_density=2)
        data = json.loads(salience_path.read_text())
        assert data["source"] == "reverie"
        assert data["signals"]["salience"] == 0.6
        assert data["signals"]["content_density"] == 2


def test_mixer_has_same_interface_as_actuation_loop():
    mixer = ReverieMixer()
    assert hasattr(mixer, "pipeline")
    assert hasattr(mixer, "shader_capability")
    assert hasattr(mixer, "visual_chain")
    assert hasattr(mixer, "tick")
    assert hasattr(mixer, "dispatch_impingement")
    assert callable(mixer.tick)
    assert callable(mixer.dispatch_impingement)


def test_affordance_registration_includes_shader_nodes():
    """Pipeline should register 12 shader node + 2 content + 3 legacy affordances.

    Camera-perspective affordances moved to space.* domain in the shared registry.
    Episodic/knowledge/profile recall affordances live in knowledge.* domain.
    Content affordances are expression-only: narrative_text and waveform_viz.
    """
    from agents.reverie._affordances import (
        ALL_CONTENT_AFFORDANCES,
        LEGACY_AFFORDANCES,
        SHADER_NODE_AFFORDANCES,
    )

    assert len(SHADER_NODE_AFFORDANCES) == 12
    assert len(ALL_CONTENT_AFFORDANCES) == 2
    assert len(LEGACY_AFFORDANCES) == 3
    # All shader nodes start with "node."
    for name, _ in SHADER_NODE_AFFORDANCES:
        assert name.startswith("node."), f"{name} should start with node."
    # All content types start with "content."
    for name, _, _ops in ALL_CONTENT_AFFORDANCES:
        assert name.startswith("content."), f"{name} should start with content."


def test_slot_opacities_from_fragment_salience():
    """Slot opacities use fragment-level salience, not per-reference salience."""
    from agents.reverie._uniforms import build_slot_opacities

    imagination = {"salience": 0.6}
    opacities = build_slot_opacities(imagination, fallback_salience=0.6)
    assert opacities[0] == 0.6
    assert opacities[1] == 0.0


def test_slot_opacities_no_imagination():
    """No imagination → all zeros."""
    from agents.reverie._uniforms import build_slot_opacities

    opacities = build_slot_opacities(None, fallback_salience=0.0)
    assert opacities == [0.0, 0.0, 0.0, 0.0]


def test_dispatch_impingement_activates_visual_chain():
    """Dispatching an impingement with dimensions should activate the visual chain.

    Uses _apply_shader_impingement directly to avoid Qdrant dependency in CI.
    The pipeline.select() path is tested by affordance_pipeline tests.
    """
    from shared.impingement import Impingement, ImpingementType

    mixer = ReverieMixer()
    import time

    imp = Impingement(
        source="test",
        type=ImpingementType.SALIENCE_INTEGRATION,
        timestamp=time.time(),
        strength=0.8,
        content={"metric": "visual_modulation", "dimensions": {"intensity": 0.6}},
    )
    # Test the activation path directly (dispatch_impingement depends on Qdrant)
    mixer._apply_shader_impingement(imp)
    level = mixer.visual_chain.get_dimension_level("visual_chain.intensity")
    assert level > 0.0

"""Tests for Phase R1 — migration of existing capabilities to AffordancePipeline."""

import time

from shared.affordance import CapabilityRecord, OperationalProperties
from shared.affordance_pipeline import AffordancePipeline
from shared.impingement import Impingement, ImpingementType, render_impingement_text

# ── Function-free descriptions exist ─────────────────────────────────────────


def test_speech_description_exists():
    from agents.hapax_daimonion.capability import SPEECH_DESCRIPTION

    assert "audible" in SPEECH_DESCRIPTION
    assert "GPU" in SPEECH_DESCRIPTION
    assert len(SPEECH_DESCRIPTION) > 50


def test_fortress_description_exists():
    from agents.fortress.capability import FORTRESS_DESCRIPTION

    assert "resource" in FORTRESS_DESCRIPTION or "simulation" in FORTRESS_DESCRIPTION
    assert len(FORTRESS_DESCRIPTION) > 50


def test_rule_description_generation():
    from unittest.mock import MagicMock

    from logos.engine.rule_capability import generate_rule_description

    rule = MagicMock()
    rule.subdirectories = ["profiles", "axioms"]
    rule.phase = 0
    desc = generate_rule_description(rule)
    assert "profiles" in desc
    assert "Deterministic" in desc


def test_rule_description_phase_2():
    from unittest.mock import MagicMock

    from logos.engine.rule_capability import generate_rule_description

    rule = MagicMock()
    rule.subdirectories = []
    rule.phase = 2
    desc = generate_rule_description(rule)
    assert "Cloud LLM" in desc


# ── Pipeline interrupt token registration ────────────────────────────────────


def test_interrupt_registration_speech():
    pipeline = AffordancePipeline()
    pipeline.register_interrupt("population_critical", "speech_production", "hapax_daimonion")
    pipeline.register_interrupt("operator_distress", "speech_production", "hapax_daimonion")

    imp = Impingement(
        timestamp=time.time(),
        source="dmn",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=1.0,
        content={"metric": "extinction_risk"},
        interrupt_token="population_critical",
    )
    results = pipeline.select(imp)
    assert len(results) == 1
    assert results[0].capability_name == "speech_production"


def test_interrupt_registration_fortress():
    pipeline = AffordancePipeline()
    pipeline.register_interrupt("population_critical", "fortress_governance", "fortress")

    imp = Impingement(
        timestamp=time.time(),
        source="dmn",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=1.0,
        content={"metric": "extinction_risk"},
        interrupt_token="population_critical",
    )
    results = pipeline.select(imp)
    assert len(results) == 1
    assert results[0].capability_name == "fortress_governance"


# ── Embedding computation in converter ───────────────────────────────────────


def test_converter_produces_impingement_with_content():
    """converter.convert() produces valid impingements (embedding may or may not be present)."""

    from datetime import datetime
    from pathlib import Path

    from logos.engine.converter import convert
    from logos.engine.models import ChangeEvent

    event = ChangeEvent(
        path=Path("/tmp/profiles/test.md"),
        event_type="modified",
        doc_type=None,
        frontmatter=None,
        timestamp=datetime.now(),
        data_dir=Path("/tmp"),
    )
    imp = convert(event)
    assert imp.source == "engine.profiles"
    assert imp.content["subdirectory"] == "profiles"
    # embedding may be None if Ollama unavailable — that's fine


# ── render_impingement_text covers all fields ────────────────────────────────


def test_render_includes_all_fields():
    imp = Impingement(
        timestamp=time.time(),
        source="sensor.stimmung",
        type=ImpingementType.PATTERN_MATCH,
        strength=0.3,
        content={"metric": "profile_dimension_updated", "value": "nominal"},
        interrupt_token="profile_dimension_updated",
    )
    text = render_impingement_text(imp)
    assert "source: sensor.stimmung" in text
    assert "signal: profile_dimension_updated" in text
    assert "value: nominal" in text
    assert "critical: profile_dimension_updated" in text


# ── Pipeline outcome feedback ────────────────────────────────────────────────


def test_pipeline_learns_from_success():
    pipeline = AffordancePipeline()
    pipeline.record_success("speech_production")
    pipeline.record_success("speech_production")
    pipeline.record_success("speech_production")

    state = pipeline.get_activation_state("speech_production")
    assert state.use_count == 3
    assert state.ts_alpha > 2.0  # grown from 1.0


def test_pipeline_learns_from_failure():
    pipeline = AffordancePipeline()
    pipeline.record_failure("speech_production")
    pipeline.record_failure("speech_production")

    state = pipeline.get_activation_state("speech_production")
    assert state.use_count == 0
    assert state.ts_beta > 2.0


def test_pipeline_context_association_updates():
    pipeline = AffordancePipeline()
    pipeline.update_context_association("nominal", "speech_production", delta=0.3)
    pipeline.update_context_association("nominal", "speech_production", delta=0.3)

    boost = pipeline._compute_context_boost("speech_production", {"stance": "nominal"})
    assert boost > 0.5  # two increments of 0.3 = 0.6


# ── Capability record construction ───────────────────────────────────────────


def test_speech_capability_record():
    from agents.hapax_daimonion.capability import SPEECH_DESCRIPTION

    rec = CapabilityRecord(
        name="speech_production",
        description=SPEECH_DESCRIPTION,
        daemon="hapax_daimonion",
        operational=OperationalProperties(requires_gpu=True),
    )
    assert rec.operational.requires_gpu
    assert not rec.operational.priority_floor


def test_fortress_capability_record():
    from agents.fortress.capability import FORTRESS_DESCRIPTION

    rec = CapabilityRecord(
        name="fortress_governance",
        description=FORTRESS_DESCRIPTION,
        daemon="fortress",
    )
    assert not rec.operational.requires_gpu
    assert rec.daemon == "fortress"

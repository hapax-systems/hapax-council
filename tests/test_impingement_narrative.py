"""Test that imagination impingements carry narrative in embeddable text."""

import time

from shared.impingement import Impingement, ImpingementType, render_impingement_text


def test_render_includes_narrative_for_imagination():
    imp = Impingement(
        timestamp=time.time(),
        source="imagination",
        type=ImpingementType.SALIENCE_INTEGRATION,
        strength=0.7,
        content={"narrative": "the weight of unfinished work accumulates"},
    )
    text = render_impingement_text(imp)
    assert "unfinished work" in text


def test_render_includes_narrative_for_any_source_with_narrative():
    imp = Impingement(
        timestamp=time.time(),
        source="dmn.sensory",
        type=ImpingementType.SALIENCE_INTEGRATION,
        strength=0.5,
        content={"narrative": "something shifted", "metric": "flow_score"},
    )
    text = render_impingement_text(imp)
    assert "something shifted" in text
    assert "flow_score" in text


def test_render_still_works_without_narrative():
    imp = Impingement(
        timestamp=time.time(),
        source="sensor.weather",
        type=ImpingementType.PATTERN_MATCH,
        strength=0.3,
        content={"metric": "temperature_change", "value": 5.2},
    )
    text = render_impingement_text(imp)
    assert "source: sensor.weather" in text
    assert "signal: temperature_change" in text
    assert "5.2" in text
    assert "narrative" not in text

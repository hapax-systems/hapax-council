import time

import pytest


def test_statistical_deviation_maps_to_prediction_error():
    from agents._apperception import impingement_to_cascade_event
    from shared.impingement import Impingement, ImpingementType

    imp = Impingement(
        timestamp=time.time(),
        source="perception.vad_confidence",
        type=ImpingementType.STATISTICAL_DEVIATION,
        strength=0.6,
        content={"metric": "vad_confidence", "value": 0.2, "delta": -0.5},
    )
    event = impingement_to_cascade_event(imp)
    assert event is not None
    assert event.source == "prediction_error"
    assert event.magnitude == pytest.approx(0.6)


def test_non_statistical_deviation_ignored():
    from agents._apperception import impingement_to_cascade_event
    from shared.impingement import Impingement, ImpingementType

    imp = Impingement(
        timestamp=time.time(),
        source="dmn.resolver",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=0.6,
        content={"metric": "resolver_failures"},
    )
    event = impingement_to_cascade_event(imp)
    assert event is None

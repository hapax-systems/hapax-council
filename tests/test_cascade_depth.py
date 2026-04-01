import time

import pytest


def test_cascade_depth_root():
    from shared.impingement import Impingement, ImpingementType, cascade_depth

    root = Impingement(
        timestamp=time.time(),
        source="perception.vad",
        type=ImpingementType.STATISTICAL_DEVIATION,
        strength=0.8,
    )
    assert cascade_depth(root) == 0


def test_child_impingement_decays_strength():
    from shared.impingement import Impingement, ImpingementType, child_impingement

    parent = Impingement(
        timestamp=time.time(),
        source="perception.vad",
        type=ImpingementType.STATISTICAL_DEVIATION,
        strength=0.8,
    )
    child = child_impingement(
        parent=parent,
        source="apperception.prediction_error",
        type=ImpingementType.SALIENCE_INTEGRATION,
        content={"cascade": "test"},
        decay=0.7,
    )
    assert child is not None
    assert child.parent_id == parent.id
    assert child.strength == pytest.approx(0.56)


def test_child_blocked_at_max_depth():
    from shared.impingement import Impingement, ImpingementType, child_impingement

    parent = Impingement(
        timestamp=time.time(),
        source="test",
        type=ImpingementType.STATISTICAL_DEVIATION,
        strength=0.8,
        content={"_cascade_depth": 3},
    )
    child = child_impingement(
        parent=parent,
        source="test.child",
        type=ImpingementType.SALIENCE_INTEGRATION,
        content={},
        max_depth=3,
    )
    assert child is None

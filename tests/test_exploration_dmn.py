"""Tests for DMN boredom/curiosity escalation responses."""

from __future__ import annotations

from agents._impingement import Impingement, ImpingementType
from agents.dmn.buffer import DMNBuffer
from agents.dmn.pulse import DMNPulse


def _boredom_impingement(source: str = "test", strength: float = 0.7) -> Impingement:
    import time

    return Impingement(
        timestamp=time.time(),
        source=source,
        type=ImpingementType.BOREDOM,
        strength=strength,
        content={"boredom_index": strength},
    )


class TestDMNLevel1:
    def test_boredom_impingement_tracked(self) -> None:
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        pulse.receive_exploration_impingement(_boredom_impingement("dmn_imagination"))
        assert pulse._exploration_targets == ["dmn_imagination"]

    def test_single_component_level1(self) -> None:
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        pulse.receive_exploration_impingement(_boredom_impingement("comp_a"))
        assert pulse.exploration_level() == 1

    def test_no_boredom_level0(self) -> None:
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        assert pulse.exploration_level() == 0


class TestDMNLevel2:
    def test_multi_component_boredom_triggers_level2(self) -> None:
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        for src in ["comp_a", "comp_b", "comp_c"]:
            pulse.receive_exploration_impingement(_boredom_impingement(src))
        assert pulse.exploration_level() == 2

    def test_two_components_stays_level1(self) -> None:
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        pulse.receive_exploration_impingement(_boredom_impingement("comp_a"))
        pulse.receive_exploration_impingement(_boredom_impingement("comp_b"))
        assert pulse.exploration_level() == 1

    def test_duplicate_source_counts_once(self) -> None:
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        for _ in range(5):
            pulse.receive_exploration_impingement(_boredom_impingement("comp_a"))
        assert pulse.exploration_level() == 1

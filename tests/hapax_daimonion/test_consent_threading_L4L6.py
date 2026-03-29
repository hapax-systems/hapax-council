"""Consent threading tests for L4-L6 — label passthrough (DD-22).

L4 (Command, Schedule): Labels propagate unchanged from FusedContext.
L5 (SuppressionField, TimelineMapping): No consent semantics (domain config).
L6 (ResourceArbiter, ScheduleQueue): Inherits via Schedule.command.consent_label.
"""

from __future__ import annotations

import unittest

from agents.hapax_daimonion.commands import Command, Schedule
from agents.hapax_daimonion.governance import VetoResult
from shared.governance.consent_label import ConsentLabel


class TestCommandConsentPassthrough(unittest.TestCase):
    """Command carries consent_label unchanged from FusedContext."""

    def test_default_consent_label_is_none(self):
        """Existing code: no consent_label = None."""
        cmd = Command(action="play")
        assert cmd.consent_label is None

    def test_explicit_consent_label(self):
        """Command with explicit consent label."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        cmd = Command(action="play", consent_label=label)
        assert cmd.consent_label == label

    def test_consent_label_frozen(self):
        """consent_label is part of the frozen dataclass."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        cmd = Command(action="play", consent_label=label)
        with self.assertRaises(AttributeError):
            cmd.consent_label = ConsentLabel.bottom()  # type: ignore[misc]


class TestScheduleConsentPassthrough(unittest.TestCase):
    """Schedule inherits consent_label via its Command."""

    def test_schedule_inherits_command_label(self):
        """Schedule.command.consent_label carries the label through."""
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        cmd = Command(action="play", consent_label=label)
        sched = Schedule(command=cmd, domain="wall", target_time=1.0)
        assert sched.command.consent_label == label

    def test_schedule_with_unlabeled_command(self):
        """Schedule with unlabeled command has None label."""
        cmd = Command(action="play")
        sched = Schedule(command=cmd)
        assert sched.command.consent_label is None


class TestConsentLabelEndToEnd(unittest.TestCase):
    """End-to-end: FusedContext → Command → Schedule label propagation."""

    def test_label_preserved_through_pipeline(self):
        """Label survives FusedContext → Command → Schedule chain."""
        label = ConsentLabel(
            frozenset({("alice", frozenset({"bob"})), ("carol", frozenset({"dave"}))})
        )
        # Simulate: governance produces a Command from FusedContext
        cmd = Command(
            action="respond",
            trigger_time=1.0,
            trigger_source="vad",
            min_watermark=0.5,
            governance_result=VetoResult(allowed=True),
            selected_by="mc_fallback",
            consent_label=label,
        )
        sched = Schedule(command=cmd, domain="wall", target_time=2.0, wall_time=2.0)

        # Label survives intact through the chain
        assert sched.command.consent_label == label
        assert sched.command.consent_label is label  # same object, not copied


if __name__ == "__main__":
    unittest.main()

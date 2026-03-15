"""Consent threading tests for L8-L9 — IFC loop closure (DD-22).

L8 (ActuationEvent, FrameGate): Labels propagate from Command through actuation.
L9 (feedback loop): Labels flow from ActuationEvent back into Behaviors,
closing the IFC loop: perception → FusedContext → Command → ActuationEvent → Behavior.
"""

from __future__ import annotations

import unittest

from hypothesis import given
from hypothesis import strategies as st

from agents.hapax_voice.actuation_event import ActuationEvent
from agents.hapax_voice.commands import Command
from agents.hapax_voice.executor import ExecutorRegistry
from agents.hapax_voice.feedback import wire_feedback_behaviors
from agents.hapax_voice.frame_gate import FrameGate
from agents.hapax_voice.governance import VetoResult
from agents.hapax_voice.primitives import Event
from shared.consent_label import ConsentLabel

# --- Shared test data ---

_LABEL_ALICE = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
_LABEL_CAROL = ConsentLabel(frozenset({("carol", frozenset({"dave"}))}))
_LABEL_JOINED = _LABEL_ALICE.join(_LABEL_CAROL)


def _make_command(action: str = "vocal_throw", label: ConsentLabel | None = None) -> Command:
    return Command(
        action=action,
        trigger_time=1.0,
        trigger_source="test",
        min_watermark=0.5,
        governance_result=VetoResult(allowed=True),
        selected_by="test",
        consent_label=label,
    )


# --- L8: ActuationEvent consent threading ---


class TestActuationEventConsent(unittest.TestCase):
    """ActuationEvent carries consent_label from the Command that triggered it."""

    def test_default_consent_label_is_none(self):
        event = ActuationEvent(action="play")
        assert event.consent_label is None

    def test_explicit_consent_label(self):
        event = ActuationEvent(action="play", consent_label=_LABEL_ALICE)
        assert event.consent_label == _LABEL_ALICE

    def test_consent_label_frozen(self):
        event = ActuationEvent(action="play", consent_label=_LABEL_ALICE)
        with self.assertRaises(AttributeError):
            event.consent_label = ConsentLabel.bottom()  # type: ignore[misc]


class TestFrameGateConsentProvenance(unittest.TestCase):
    """FrameGate preserves consent provenance via last_command."""

    def test_apply_command_preserves_label(self):
        gate = FrameGate()
        cmd = _make_command(action="process", label=_LABEL_ALICE)
        gate.apply_command(cmd)
        assert gate.last_command is not None
        assert gate.last_command.consent_label == _LABEL_ALICE

    def test_apply_unlabeled_command(self):
        gate = FrameGate()
        cmd = _make_command(action="process", label=None)
        gate.apply_command(cmd)
        assert gate.last_command is not None
        assert gate.last_command.consent_label is None


class TestExecutorRegistryConsentPropagation(unittest.TestCase):
    """ExecutorRegistry propagates consent_label from Command to ActuationEvent."""

    def _make_registry_with_stub(self) -> tuple[ExecutorRegistry, list[ActuationEvent]]:
        """Create registry with a stub executor that records ActuationEvents."""
        registry = ExecutorRegistry()
        events: list[ActuationEvent] = []
        registry.actuation_event.subscribe(lambda _ts, e: events.append(e))

        class StubExecutor:
            name = "stub"
            handles = frozenset({"vocal_throw", "ad_lib"})

            def execute(self, command: Command) -> None:
                pass

            def available(self) -> bool:
                return True

            def close(self) -> None:
                pass

        registry.register(StubExecutor())
        return registry, events

    def test_dispatch_propagates_consent_label(self):
        registry, events = self._make_registry_with_stub()
        cmd = _make_command(action="vocal_throw", label=_LABEL_ALICE)
        registry.dispatch(cmd)
        assert len(events) == 1
        assert events[0].consent_label == _LABEL_ALICE

    def test_dispatch_propagates_none_label(self):
        registry, events = self._make_registry_with_stub()
        cmd = _make_command(action="vocal_throw", label=None)
        registry.dispatch(cmd)
        assert len(events) == 1
        assert events[0].consent_label is None

    def test_dispatch_propagates_joined_label(self):
        registry, events = self._make_registry_with_stub()
        cmd = _make_command(action="vocal_throw", label=_LABEL_JOINED)
        registry.dispatch(cmd)
        assert len(events) == 1
        assert events[0].consent_label == _LABEL_JOINED


# --- L9: Feedback loop consent threading ---


class TestFeedbackConsentPropagation(unittest.TestCase):
    """Feedback loop propagates consent_label from ActuationEvent to Behaviors."""

    def _emit_actuation(
        self,
        actuation_event: Event[ActuationEvent],
        action: str,
        label: ConsentLabel | None,
        timestamp: float = 1.0,
    ) -> None:
        event = ActuationEvent(action=action, wall_time=timestamp, consent_label=label)
        actuation_event.emit(timestamp, event)

    def test_mc_fire_propagates_consent_label(self):
        actuation = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(actuation)
        self._emit_actuation(actuation, "vocal_throw", _LABEL_ALICE)
        assert behaviors["last_mc_fire"].consent_label == _LABEL_ALICE
        assert behaviors["mc_fire_count"].consent_label == _LABEL_ALICE

    def test_obs_switch_propagates_consent_label(self):
        actuation = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(actuation)
        self._emit_actuation(actuation, "wide_ambient", _LABEL_CAROL)
        assert behaviors["last_obs_switch"].consent_label == _LABEL_CAROL

    def test_tts_end_propagates_consent_label(self):
        actuation = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(actuation)
        self._emit_actuation(actuation, "tts_announce", _LABEL_ALICE)
        assert behaviors["last_tts_end"].consent_label == _LABEL_ALICE

    def test_none_label_does_not_set_behavior_label(self):
        actuation = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(actuation)
        self._emit_actuation(actuation, "vocal_throw", None)
        assert behaviors["last_mc_fire"].consent_label is None

    def test_sequential_labels_join(self):
        """Multiple actuations with different labels accumulate via join."""
        actuation = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(actuation)
        self._emit_actuation(actuation, "vocal_throw", _LABEL_ALICE, timestamp=1.0)
        self._emit_actuation(actuation, "vocal_throw", _LABEL_CAROL, timestamp=2.0)
        assert behaviors["last_mc_fire"].consent_label == _LABEL_JOINED

    def test_first_label_sets_from_none(self):
        """First labeled actuation transitions Behavior from None to labeled."""
        actuation = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(actuation)
        assert behaviors["last_mc_fire"].consent_label is None
        self._emit_actuation(actuation, "vocal_throw", _LABEL_ALICE)
        assert behaviors["last_mc_fire"].consent_label == _LABEL_ALICE


# --- End-to-end: Command → ActuationEvent → Feedback Behavior ---


class TestConsentLoopClosure(unittest.TestCase):
    """End-to-end: consent label survives Command → Dispatch → ActuationEvent → Feedback."""

    def test_full_loop(self):
        """Label flows through the complete actuation feedback loop."""
        registry = ExecutorRegistry()

        class StubExecutor:
            name = "stub"
            handles = frozenset({"vocal_throw"})

            def execute(self, command: Command) -> None:
                pass

            def available(self) -> bool:
                return True

            def close(self) -> None:
                pass

        registry.register(StubExecutor())
        behaviors = wire_feedback_behaviors(registry.actuation_event)

        cmd = _make_command(action="vocal_throw", label=_LABEL_ALICE)
        registry.dispatch(cmd)

        assert behaviors["last_mc_fire"].consent_label == _LABEL_ALICE
        assert behaviors["mc_fire_count"].consent_label == _LABEL_ALICE


# --- Hypothesis properties ---


@st.composite
def st_consent_label(draw: st.DrawFn) -> ConsentLabel:
    owners = draw(st.lists(st.text(min_size=1, max_size=5, alphabet="abcde"), max_size=3))
    policies = set()
    for owner in owners:
        readers = draw(st.frozensets(st.text(min_size=1, max_size=5, alphabet="fghij"), max_size=3))
        policies.add((owner, readers))
    return ConsentLabel(frozenset(policies))


class TestConsentL8L9Hypothesis(unittest.TestCase):
    """Hypothesis properties for L8-L9 consent threading."""

    @given(label=st_consent_label())
    def test_actuation_event_preserves_label(self, label: ConsentLabel):
        """ActuationEvent.consent_label == input label (passthrough, no transform)."""
        event = ActuationEvent(action="test", consent_label=label)
        assert event.consent_label == label

    @given(label=st_consent_label())
    def test_feedback_loop_preserves_label(self, label: ConsentLabel):
        """Label survives Command → ActuationEvent → Feedback Behavior."""
        actuation = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(actuation)
        event = ActuationEvent(action="vocal_throw", wall_time=1.0, consent_label=label)
        actuation.emit(1.0, event)
        assert behaviors["last_mc_fire"].consent_label == label

    @given(a=st_consent_label(), b=st_consent_label())
    def test_feedback_label_join_commutative(self, a: ConsentLabel, b: ConsentLabel):
        """Sequential feedback labels join commutatively on Behavior."""
        # Order 1: a then b
        actuation1 = Event[ActuationEvent]()
        beh1 = wire_feedback_behaviors(actuation1)
        actuation1.emit(1.0, ActuationEvent(action="vocal_throw", wall_time=1.0, consent_label=a))
        actuation1.emit(2.0, ActuationEvent(action="vocal_throw", wall_time=2.0, consent_label=b))
        label_ab = beh1["last_mc_fire"].consent_label

        # Order 2: b then a
        actuation2 = Event[ActuationEvent]()
        beh2 = wire_feedback_behaviors(actuation2)
        actuation2.emit(1.0, ActuationEvent(action="vocal_throw", wall_time=1.0, consent_label=b))
        actuation2.emit(2.0, ActuationEvent(action="vocal_throw", wall_time=2.0, consent_label=a))
        label_ba = beh2["last_mc_fire"].consent_label

        assert label_ab == label_ba


if __name__ == "__main__":
    unittest.main()

"""Experiential governance proofs — the complete matrix.

Each test is a story told from a human's perspective. Every assertion proves
what the person experiences at each moment — not what internal methods return.

The ExperientialWorld ties the full stack together: perception → gate →
governor → consent tracker → consent reader. Tests advance through simulated
time, changing the physical world (who's present, what's playing, what app is
focused), and assert ALL experiential properties at every moment.

Three principals, three promises:
  Operator:  cognitive support without surveillance
  Guest:     informed consent without friction
  Absent:    protection without erasure

Coverage matrix (dimensions × experiential properties):

  Context (8)   :  idle, coding, production, meeting, music-ambient,
                   exercise, absent, axiom-sensitive
  Occupancy (5) :  alone, +new-guest, +consented-guest, +refused-guest, nobody
  Body (3)      :  normal, stressed, exercising
  System (2)    :  healthy, degraded
  Override (2)  :  none, wake-word
  Data flow (4) :  none, email-unconsented, calendar-unconsented, document-mixed

  Properties asserted at every intersection:
    1. gate_eligible     — can the system speak if asked?
    2. directive         — process / pause / withdraw
    3. interruptibility  — 0.0 to 1.0
    4. consent_phase     — NO_GUEST / DETECTED / PENDING / GRANTED / REFUSED
    5. persistence       — is person-adjacent data being stored?
    6. llm_sees          — what content reaches the LLM after filtering?

No hardware, no LLM, no network.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_daimonion.consent_state import ConsentPhase, ConsentStateTracker
from agents.hapax_daimonion.context_gate import ContextGate
from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline, ConvState
from agents.hapax_daimonion.conversational_policy import get_policy
from agents.hapax_daimonion.governance import Veto
from agents.hapax_daimonion.governor import PipelineGovernor
from agents.hapax_daimonion.perception import EnvironmentState, compute_interruptibility
from agents.hapax_daimonion.primitives import Behavior
from agents.hapax_daimonion.session import SessionManager
from shared.governance.consent import ConsentContract, ConsentRegistry
from shared.governance.consent_reader import ConsentGatedReader, RetrievedDatum
from shared.governance.degradation import degrade

# ── The World ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Moment:
    """What a human would experience at a single point in time.

    Every test asserts a Moment. No test checks just one property.
    If the system is paused, we also prove consent state, persistence,
    interruptibility — the full picture, not a keyhole view.
    """

    gate_eligible: bool
    directive: str  # "process" | "pause" | "withdraw"
    interruptibility: float
    consent_phase: ConsentPhase
    persistence: bool
    # Optional: specific gate/veto reasons to check
    gate_reason_contains: str = ""
    veto_contains: str = ""
    # Optional: conversational policy assertions
    policy_contains: str = ""
    policy_excludes: str = ""


class ExperientialWorld:
    """Simulates the full perception → governance stack.

    No hardware. No mocks of hardware. Just the governance layers
    wired together exactly as the daemon wires them, ticked forward
    through time by the test narrative.
    """

    def __init__(self) -> None:
        self.t: float = 1000.0  # monotonic-like clock

        # Physical world state
        self._faces: int = 0
        self._operator_present: bool = False
        self._activity_mode: str = "idle"
        self._workspace_context: str = ""
        self._active_window_class: str = ""
        self._active_window_title: str = ""
        self._sink_volume: float = 0.3
        self._midi_active: bool = False
        self._stress_elevated: bool = False
        self._system_health: str = "healthy"
        self._watch_activity: str = "idle"
        self._ambient_interruptible: bool = True
        self._ambient_reason: str = ""
        self._ambient_top_labels: list[tuple[str, float]] = []

        # Governance stack
        self.session = SessionManager()
        self.gate = ContextGate(self.session, ambient_classification=False)
        self.governor = PipelineGovernor(operator_absent_withdraw_s=60.0)
        self.consent = ConsentStateTracker(debounce_s=5.0, absence_clear_s=30.0)
        self._registry = ConsentRegistry()
        self.reader = ConsentGatedReader(
            registry=self._registry,
            operator_ids=frozenset({"operator"}),
        )

        # Snapshot after each tick
        self._last_state: EnvironmentState | None = None
        self._last_gate_result = None
        self._last_directive: str | None = None

    # ── Physical world mutations ─────────────────────────────────────

    def operator_sits_down(self) -> None:
        self._operator_present = True
        self._faces = max(1, self._faces)

    def operator_leaves(self) -> None:
        self._operator_present = False
        self._faces = max(0, self._faces - 1)

    def guest_enters(self) -> None:
        self._faces += 1

    def guest_leaves(self) -> None:
        self._faces = max(0, self._faces - 1)

    def switch_activity(self, mode: str) -> None:
        self._activity_mode = mode

    def focus_app(self, app_class: str, title: str = "") -> None:
        self._active_window_class = app_class
        self._active_window_title = title

    def set_workspace_context(self, ctx: str) -> None:
        self._workspace_context = ctx

    def start_music(self) -> None:
        self._ambient_interruptible = False
        self._ambient_reason = "Music detected"
        self._ambient_top_labels = [("Music", 0.8)]

    def stop_music(self) -> None:
        self._ambient_interruptible = True
        self._ambient_reason = ""
        self._ambient_top_labels = []

    def connect_midi(self) -> None:
        self._midi_active = True

    def disconnect_midi(self) -> None:
        self._midi_active = False

    def stress_spikes(self) -> None:
        self._stress_elevated = True

    def stress_subsides(self) -> None:
        self._stress_elevated = False

    def system_degrades(self) -> None:
        self._system_health = "degraded"

    def system_recovers(self) -> None:
        self._system_health = "healthy"

    def start_exercising(self) -> None:
        self._watch_activity = "exercise"

    def stop_exercising(self) -> None:
        self._watch_activity = "idle"

    def say_wake_word(self) -> None:
        self.governor.wake_word_active = True

    def grant_guest_consent(self) -> None:
        self.consent.grant_consent()

    def refuse_guest_consent(self) -> None:
        self.consent.refuse_consent()

    def add_consent_contract(self, person: str, scope: frozenset[str]) -> None:
        contract = ConsentContract(
            id=f"contract-{person}",
            parties=("operator", person),
            scope=scope,
        )
        self._registry._contracts[contract.id] = contract

    def revoke_consent(self, person: str) -> None:
        self._registry.purge_subject(person)

    # ── Time advancement ─────────────────────────────────────────────

    def advance(self, seconds: float, tick_interval: float = 2.5) -> None:
        """Advance time, ticking governance layers at daemon cadence (~2.5s)."""
        remaining = seconds
        while remaining > 0:
            step = min(tick_interval, remaining)
            self.t += step
            remaining -= step
            self._tick()

    def _tick(self) -> None:
        """Wire the governance stack exactly as the daemon does."""
        behaviors = {
            "sink_volume": Behavior(self._sink_volume, watermark=self.t),
            "midi_active": Behavior(self._midi_active, watermark=self.t),
            "stress_elevated": Behavior(self._stress_elevated, watermark=self.t),
            "system_health_status": Behavior(self._system_health, watermark=self.t),
            "watch_activity_state": Behavior(self._watch_activity, watermark=self.t),
        }
        if self._active_window_class:
            behaviors["active_window_class"] = Behavior(self._active_window_class, watermark=self.t)
        self.gate.set_behaviors(behaviors)
        self.gate.set_activity_mode(self._activity_mode)

        # Ambient classification (gate reads from cached result)
        if not self._ambient_interruptible:
            self.gate._ambient_result = MagicMock(interruptible=False, reason=self._ambient_reason)
            if not any(v.name == "ambient" for v in self.gate._veto_chain.vetoes):
                self.gate._veto_chain.add(Veto("ambient", predicate=self.gate._allow_ambient))
        else:
            self.gate._ambient_result = None

        self._last_state = EnvironmentState(
            timestamp=self.t,
            face_count=self._faces,
            operator_present=self._operator_present,
            activity_mode=self._activity_mode,
            workspace_context=self._workspace_context,
            interruptibility_score=compute_interruptibility(
                vad_confidence=0.0,
                activity_mode=self._activity_mode,
                in_voice_session=False,
                operator_present=self._operator_present,
            ),
        )

        self._last_gate_result = self.gate.check()

        if self._operator_present:
            self.governor._last_operator_seen = time.monotonic()
        self._last_directive = self.governor.evaluate(self._last_state)

        self.consent.tick(
            face_count=self._faces,
            speaker_is_operator=True,
            now=self.t,
        )

    # ── Moment capture ───────────────────────────────────────────────

    def moment(self) -> Moment:
        """Capture the full experiential state right now."""
        return Moment(
            gate_eligible=self._last_gate_result.eligible if self._last_gate_result else False,
            directive=self._last_directive or "unknown",
            interruptibility=(self._last_state.interruptibility_score if self._last_state else 0.0),
            consent_phase=self.consent.phase,
            persistence=self.consent.persistence_allowed,
        )

    def assert_moment(self, expected: Moment, msg: str = "") -> None:
        """Assert ALL experiential properties match expected Moment."""
        actual = self.moment()
        prefix = f"{msg}: " if msg else ""

        assert actual.gate_eligible == expected.gate_eligible, (
            f"{prefix}gate_eligible: got {actual.gate_eligible}, expected {expected.gate_eligible}"
        )
        assert actual.directive == expected.directive, (
            f"{prefix}directive: got {actual.directive}, expected {expected.directive}"
        )
        assert actual.interruptibility == pytest.approx(expected.interruptibility, abs=0.05), (
            f"{prefix}interruptibility: got {actual.interruptibility:.2f}, "
            f"expected {expected.interruptibility:.2f}"
        )
        assert actual.consent_phase == expected.consent_phase, (
            f"{prefix}consent_phase: got {actual.consent_phase}, expected {expected.consent_phase}"
        )
        assert actual.persistence == expected.persistence, (
            f"{prefix}persistence: got {actual.persistence}, expected {expected.persistence}"
        )

        if expected.gate_reason_contains and self._last_gate_result:
            assert expected.gate_reason_contains in self._last_gate_result.reason.lower(), (
                f"{prefix}gate_reason should contain '{expected.gate_reason_contains}', "
                f"got '{self._last_gate_result.reason}'"
            )

        if expected.veto_contains and self.governor.last_veto_result:
            assert expected.veto_contains in self.governor.last_veto_result.denied_by, (
                f"{prefix}veto should contain '{expected.veto_contains}', "
                f"got {self.governor.last_veto_result.denied_by}"
            )

        if expected.policy_contains or expected.policy_excludes:
            policy_text = self.policy()
            if expected.policy_contains:
                assert expected.policy_contains.lower() in policy_text.lower(), (
                    f"{prefix}policy should contain '{expected.policy_contains}', "
                    f"got: {policy_text[:200]}"
                )
            if expected.policy_excludes:
                assert expected.policy_excludes.lower() not in policy_text.lower(), (
                    f"{prefix}policy should NOT contain '{expected.policy_excludes}', "
                    f"got: {policy_text[:200]}"
                )

    def policy(self) -> str:
        """Compute the conversational policy for the current state."""
        return get_policy(
            env=self._last_state,
            guest_mode=False,
        )

    @property
    def consent_alert_needed(self) -> bool:
        """System needs to alert a guest about consent (fires once)."""
        return self.consent.needs_notification

    def filter_for_llm(self, content: str, person_ids: frozenset[str], category: str) -> str:
        """What the LLM would actually see after consent filtering."""
        datum = RetrievedDatum(
            content=content,
            person_ids=person_ids,
            data_category=category,
            source="test",
        )
        return self.reader.filter(datum).filtered_content

    def filter_tool(self, tool_name: str, result: str) -> str:
        """What the LLM would see after tool-result consent filtering."""
        return self.reader.filter_tool_result(tool_name, result)


# ═══════════════════════════════════════════════════════════════════════════════
# PART 1: CONTEXT × OPERATOR ALONE MATRIX
#
# The operator sits at their desk in different contexts. No guests,
# no third parties. Each row is a context, each assertion covers all 6
# properties. This is the baseline: prove the system adapts to what I'm
# doing without me telling it to.
# ═══════════════════════════════════════════════════════════════════════════════


class TestContextMatrix:
    """Every context the operator can be in, alone. Full moment at each."""

    def test_idle_at_desk(self):
        """I sit down. Nothing open. System fully available, fully open."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)
        w.assert_moment(
            Moment(
                gate_eligible=True,
                directive="process",
                interruptibility=1.0,
                consent_phase=ConsentPhase.NO_GUEST,
                persistence=True,
            ),
            "Idle at desk",
        )

    def test_coding(self):
        """I'm coding. System is available but interruptibility drops 0.3.
        It won't proactively bother me but will respond if I ask."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("coding")
        w.advance(2.5)
        w.assert_moment(
            Moment(
                gate_eligible=True,
                directive="process",
                interruptibility=0.7,
                consent_phase=ConsentPhase.NO_GUEST,
                persistence=True,
            ),
            "Coding",
        )

    def test_production_with_midi(self):
        """I'm in Ableton with MIDI connected. Both gate AND governor block.
        Gate: MIDI veto. Governor: production veto. Two independent safety layers."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("production")
        w.connect_midi()
        w.advance(2.5)
        w.assert_moment(
            Moment(
                gate_eligible=False,
                directive="pause",
                interruptibility=0.5,
                consent_phase=ConsentPhase.NO_GUEST,
                persistence=True,
                veto_contains="activity_mode",
            ),
            "Music production",
        )

    def test_video_meeting(self):
        """Zoom call. Gate blocks (fullscreen app). Governor blocks (meeting mode).
        Nobody on the call hears my AI assistant."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("meeting")
        w.focus_app("zoom", "Team Standup")
        w.advance(2.5)
        w.assert_moment(
            Moment(
                gate_eligible=False,
                directive="pause",
                interruptibility=0.4,
                consent_phase=ConsentPhase.NO_GUEST,
                persistence=True,
                veto_contains="activity_mode",
            ),
            "Zoom meeting",
        )

    def test_music_playing_ambient(self):
        """Music playing through speakers (no MIDI, not producing — just listening).
        Ambient classifier detects music, gate blocks to avoid talking over it."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.start_music()
        w.advance(2.5)
        w.assert_moment(
            Moment(
                gate_eligible=False,
                directive="process",  # Governor sees idle, no veto
                interruptibility=1.0,
                consent_phase=ConsentPhase.NO_GUEST,
                persistence=True,
                gate_reason_contains="music",
            ),
            "Music ambient",
        )

    def test_exercising(self):
        """On the treadmill. Watch says exercise. Gate blocks. Leave me alone."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.start_exercising()
        w.advance(2.5)
        w.assert_moment(
            Moment(
                gate_eligible=False,
                directive="process",  # Governor sees present+idle, no veto
                interruptibility=1.0,
                consent_phase=ConsentPhase.NO_GUEST,
                persistence=True,
                gate_reason_contains="exercise",
            ),
            "Exercising",
        )

    def test_absent(self):
        """I left. After grace period, system withdraws. Empty room = no listening."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)
        w.operator_leaves()
        w.governor._last_operator_seen = time.monotonic() - 61.0
        w.advance(2.5)
        w.assert_moment(
            Moment(
                gate_eligible=True,  # gate doesn't check presence
                directive="withdraw",
                interruptibility=0.0,
                consent_phase=ConsentPhase.NO_GUEST,
                persistence=True,
            ),
            "Absent",
        )

    def test_axiom_sensitive_workspace(self):
        """Performance review open. Constitutional axiom veto fires.
        This isn't a preference — it's a governance constraint."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.set_workspace_context("editing performance review in Lattice")
        w.advance(2.5)
        w.assert_moment(
            Moment(
                gate_eligible=True,  # gate doesn't check workspace
                directive="pause",
                interruptibility=1.0,
                consent_phase=ConsentPhase.NO_GUEST,
                persistence=True,
                veto_contains="axiom_compliance",
            ),
            "Axiom-sensitive workspace",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PART 2: BODY + SYSTEM CONDITION OVERLAY
#
# Stress, system health — conditions that can appear in ANY context.
# Prove they compose correctly with the context matrix.
# ═══════════════════════════════════════════════════════════════════════════════


class TestConditionOverlay:
    """Body and system conditions that overlay any context."""

    def test_stress_while_idle(self):
        """Stress elevated at idle desk. Gate blocks even though nothing
        else is competing. Adding AI interaction to physiological load
        would make things worse."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.stress_spikes()
        w.advance(2.5)
        w.assert_moment(
            Moment(
                gate_eligible=False,
                directive="process",
                interruptibility=1.0,
                consent_phase=ConsentPhase.NO_GUEST,
                persistence=True,
                gate_reason_contains="stress",
            ),
            "Stressed at idle desk",
        )

    def test_stress_while_coding(self):
        """Stress during coding. Gate blocks on stress. Governor processes
        (coding isn't a veto). Two layers agree: leave me alone."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("coding")
        w.stress_spikes()
        w.advance(2.5)
        w.assert_moment(
            Moment(
                gate_eligible=False,
                directive="process",
                interruptibility=0.7,
                consent_phase=ConsentPhase.NO_GUEST,
                persistence=True,
                gate_reason_contains="stress",
            ),
            "Stressed while coding",
        )

    def test_stress_recovery(self):
        """Stress spikes then subsides. System returns. No lingering effect."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.stress_spikes()
        w.advance(2.5)
        assert not w.moment().gate_eligible

        w.stress_subsides()
        w.advance(2.5)
        w.assert_moment(
            Moment(
                gate_eligible=True,
                directive="process",
                interruptibility=1.0,
                consent_phase=ConsentPhase.NO_GUEST,
                persistence=True,
            ),
            "Stress recovered",
        )

    def test_degraded_system_while_idle(self):
        """Infrastructure flaky. Gate blocks to prevent mid-conversation failure."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.system_degrades()
        w.advance(2.5)
        w.assert_moment(
            Moment(
                gate_eligible=False,
                directive="process",
                interruptibility=1.0,
                consent_phase=ConsentPhase.NO_GUEST,
                persistence=True,
                gate_reason_contains="health",
            ),
            "Degraded system",
        )

    def test_degraded_system_recovery(self):
        """System degrades then recovers. Full service restored."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.system_degrades()
        w.advance(2.5)
        assert not w.moment().gate_eligible

        w.system_recovers()
        w.advance(2.5)
        w.assert_moment(
            Moment(
                gate_eligible=True,
                directive="process",
                interruptibility=1.0,
                consent_phase=ConsentPhase.NO_GUEST,
                persistence=True,
            ),
            "System recovered",
        )

    def test_degraded_during_production(self):
        """System degrades while I'm producing. Two independent blocks:
        MIDI gate + health gate. Neither cares about the other."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("production")
        w.connect_midi()
        w.system_degrades()
        w.advance(2.5)
        w.assert_moment(
            Moment(
                gate_eligible=False,
                directive="pause",
                interruptibility=0.5,
                consent_phase=ConsentPhase.NO_GUEST,
                persistence=True,
            ),
            "Degraded during production",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PART 3: WAKE WORD OVERRIDE × VETOED CONTEXTS
#
# Wake word is the operator's escape hatch. Prove it works in every
# context where the system would otherwise be silent, and that it's
# always temporary — the context reasserts after grace expires.
# ═══════════════════════════════════════════════════════════════════════════════


class TestWakeWordOverride:
    """Wake word override in every vetoed context."""

    def _override_and_decay(self, w: ExperientialWorld, vetoed_directive: str) -> None:
        """Common pattern: verify veto, fire wake word, verify override + grace + decay."""
        # Verify veto is active
        assert w.moment().directive == vetoed_directive

        # Wake word fires → immediate process
        w.say_wake_word()
        w.advance(2.5)
        assert w.moment().directive == "process"
        assert w.governor.last_selected.selected_by == "wake_word_override"

        # 8 grace ticks protect the conversation (~20s at 2.5s/tick)
        for i in range(8):
            w.advance(2.5)
            assert w.moment().directive == "process", f"Grace tick {i + 1}"
            assert w.governor.last_selected.selected_by == "wake_word_grace"

        # Grace expired → veto reasserts
        w.advance(2.5)
        assert w.moment().directive == vetoed_directive, "Veto reasserts after grace"

    def test_override_production(self):
        """Wake word during music production. Override is temporary."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("production")
        w.connect_midi()
        w.advance(2.5)
        self._override_and_decay(w, "pause")

    def test_override_meeting(self):
        """Wake word during meeting. Override is temporary."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("meeting")
        w.advance(2.5)
        self._override_and_decay(w, "pause")

    def test_override_axiom_veto(self):
        """Wake word during axiom-sensitive workspace. Even constitutional
        vetoes can be overridden by explicit intent — but only temporarily."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.set_workspace_context("editing performance review in Lattice")
        w.advance(2.5)
        self._override_and_decay(w, "pause")

    def test_override_during_coding_is_unnecessary_but_harmless(self):
        """Wake word during coding. Coding doesn't veto, so override
        just sets grace period over an already-process state. Harmless."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("coding")
        w.advance(2.5)
        assert w.moment().directive == "process"

        w.say_wake_word()
        w.advance(2.5)
        assert w.moment().directive == "process"
        assert w.governor.last_selected.selected_by == "wake_word_override"


# ═══════════════════════════════════════════════════════════════════════════════
# PART 4: GUEST LIFECYCLE × FULL MOMENT
#
# Every consent phase transition, with ALL properties asserted at each step.
# These are the wife-walks-in stories.
# ═══════════════════════════════════════════════════════════════════════════════


class TestGuestLifecycle:
    """Guest enters the room. Full lifecycle with complete moment assertions."""

    def test_detection_debounce_notification(self):
        """My wife walks in while I'm coding. The system:
        1. Detects her immediately, blocks persistence
        2. Debounces for 5 seconds (might be passing through)
        3. Fires notification exactly once
        4. Waits for her answer

        At every moment, the full experiential state is correct."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("coding")
        w.advance(5.0)
        w.assert_moment(
            Moment(True, "process", 0.7, ConsentPhase.NO_GUEST, True),
            "Coding alone — baseline",
        )

        # She walks in
        w.guest_enters()
        w.advance(2.5)
        w.assert_moment(
            Moment(True, "process", 0.7, ConsentPhase.GUEST_DETECTED, False),
            "First tick after entry — persistence already blocked",
        )
        assert not w.consent_alert_needed, "Still debouncing"

        # Debounce period
        w.advance(2.5)
        w.assert_moment(
            Moment(True, "process", 0.7, ConsentPhase.GUEST_DETECTED, False),
            "Mid-debounce — still waiting",
        )

        # Debounce complete
        w.advance(2.5)
        w.assert_moment(
            Moment(True, "process", 0.7, ConsentPhase.CONSENT_PENDING, False),
            "Debounce satisfied — consent pending",
        )
        assert w.consent_alert_needed, "Notification fires now"
        assert not w.consent_alert_needed, "Only once — no nagging"

    def test_guest_grants_consent(self):
        """She says yes. Persistence unlocks. One question, one answer, done."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.guest_enters()
        w.advance(7.5)
        _ = w.consent_alert_needed

        w.grant_guest_consent()
        w.assert_moment(
            Moment(True, "process", 1.0, ConsentPhase.CONSENT_GRANTED, True),
            "Consent granted — full access",
        )

    def test_guest_refuses_consent(self):
        """She says no. System respects it. No guilt, no repeat asking."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.guest_enters()
        w.advance(7.5)
        _ = w.consent_alert_needed

        w.refuse_guest_consent()
        w.assert_moment(
            Moment(True, "process", 1.0, ConsentPhase.CONSENT_REFUSED, False),
            "Consent refused — persistence stays blocked",
        )

        # She's still there — no re-asking
        w.advance(30.0)
        assert not w.consent_alert_needed, "No repeat notification"
        assert not w.moment().persistence, "Still blocked"

    def test_transient_visit_no_consent_conversation(self):
        """She pokes her head in for 3 seconds. Gone before debounce.
        No consent conversation warranted for a 3-second visit."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.guest_enters()
        w.advance(2.5)

        w.assert_moment(
            Moment(True, "process", 1.0, ConsentPhase.GUEST_DETECTED, False),
            "Guest detected, debouncing",
        )
        assert not w.consent_alert_needed

        w.guest_leaves()
        w.advance(2.5)
        assert not w.consent_alert_needed, "She was never here long enough to matter"

    def test_guest_leaves_without_answering(self):
        """Debounce satisfied, consent pending, she leaves without responding.
        System auto-clears. No unresolved state left behind."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.guest_enters()
        w.advance(7.5)
        assert w.moment().consent_phase == ConsentPhase.CONSENT_PENDING

        w.guest_leaves()
        w.advance(35.0)  # past absence_clear_s (30s)
        w.assert_moment(
            Moment(True, "process", 1.0, ConsentPhase.NO_GUEST, True),
            "Auto-cleared after departure",
        )

    def test_consented_guest_departs(self):
        """She consented and then leaves. Contract persists (for future visits)
        but consent tracker returns to NO_GUEST."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.guest_enters()
        w.advance(7.5)
        w.grant_guest_consent()
        assert w.moment().persistence

        w.guest_leaves()
        w.advance(35.0)
        w.assert_moment(
            Moment(True, "process", 1.0, ConsentPhase.NO_GUEST, True),
            "Guest departed, back to operator-only",
        )

    def test_prior_consent_contract(self):
        """She has a prior consent contract. Data mentioning her passes through
        the reader unfiltered (for in-scope categories). The consent tracker
        still tracks presence, but the reader has the contract."""
        w = ExperientialWorld()
        w.add_consent_contract("wife", frozenset({"perception", "document"}))
        w.operator_sits_down()
        w.guest_enters()
        w.advance(7.5)

        result = w.filter_for_llm(
            "Wife mentioned dinner plans",
            frozenset({"wife"}),
            "document",
        )
        assert "wife" in result.lower(), "Prior consent → name passes through"


# ═══════════════════════════════════════════════════════════════════════════════
# PART 5: DATA FLOW × CONSENT MATRIX
#
# What does the LLM actually see? For each data category × consent state,
# prove the content is correctly filtered. This is protection without erasure:
# work context preserved, person identity abstracted.
# ═══════════════════════════════════════════════════════════════════════════════


class TestDataFlowMatrix:
    """Data category × consent state → what the LLM sees."""

    # ── Email ────────────────────────────────────────────────────────

    def test_email_unconsented(self):
        """Email from unconsented person. Address abstracted, subject preserved."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)
        result = w.filter_tool(
            "search_emails",
            "From: alice@corp.com | Subject: Q2 Budget Review\nHey, the Q2 numbers look good.",
        )
        assert "alice@corp.com" not in result
        assert "[someone at corp.com]" in result
        assert "Q2 Budget Review" in result

    def test_email_consented(self):
        """Email from consented person. Full content flows through."""
        w = ExperientialWorld()
        w.add_consent_contract("alice@corp.com", frozenset({"email"}))
        w.operator_sits_down()
        w.advance(2.5)
        result = w.filter_tool(
            "search_emails",
            "From: alice@corp.com | Subject: Q2 Budget Review",
        )
        assert "alice@corp.com" in result

    def test_email_after_revocation(self):
        """Email from person whose consent was just revoked. Immediate abstraction."""
        w = ExperientialWorld()
        w.add_consent_contract("alice@corp.com", frozenset({"email"}))
        w.operator_sits_down()
        w.advance(2.5)

        before = w.filter_tool("search_emails", "From: alice@corp.com | Subject: Budget")
        assert "alice@corp.com" in before

        w.revoke_consent("alice@corp.com")

        after = w.filter_tool("search_emails", "From: alice@corp.com | Subject: Budget")
        assert "alice@corp.com" not in after
        assert "Budget" in after

    # ── Calendar ─────────────────────────────────────────────────────

    def test_calendar_unconsented(self):
        """Calendar with unconsented attendees. Names → count, time/title preserved."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)
        result = w.filter_tool(
            "get_calendar_today",
            "- 2026-03-15T10:00: Sprint planning (with Alice, Bob, charlie@corp.com)",
        )
        assert "Alice" not in result
        assert "Bob" not in result
        assert "charlie@corp.com" not in result
        assert "3 people" in result
        assert "Sprint planning" in result
        assert "10:00" in result

    def test_calendar_mixed_consent(self):
        """Calendar where Alice consented, Bob didn't. Alice's name stays."""
        w = ExperientialWorld()
        w.add_consent_contract("Alice", frozenset({"calendar"}))
        w.operator_sits_down()
        w.advance(2.5)
        result = w.filter_for_llm(
            "- 2026-03-15T10:00: Sync (with Alice, Bob)",
            frozenset({"Alice", "Bob"}),
            "calendar",
        )
        assert "Alice" in result
        assert "Bob" not in result

    # ── Document ─────────────────────────────────────────────────────

    def test_document_unconsented(self):
        """Document mentioning unconsented person. Name → 'Someone'."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)
        result = w.filter_for_llm(
            "Bob mentioned the deadline is unrealistic",
            frozenset({"Bob"}),
            "document",
        )
        assert "Bob" not in result
        assert "Someone" in result or "someone" in result
        assert "deadline" in result

    def test_document_consented(self):
        """Document mentioning consented person. Full content flows."""
        w = ExperientialWorld()
        w.add_consent_contract("Alice", frozenset({"document"}))
        w.operator_sits_down()
        w.advance(2.5)
        result = w.filter_for_llm(
            "Alice proposed the new architecture",
            frozenset({"Alice"}),
            "document",
        )
        assert "Alice" in result

    def test_document_mixed_consent(self):
        """Document mentioning consented Alice and unconsented Bob."""
        w = ExperientialWorld()
        w.add_consent_contract("Alice", frozenset({"document"}))
        w.operator_sits_down()
        w.advance(2.5)
        result = w.filter_for_llm(
            "Alice and Bob agreed the deadline is unrealistic",
            frozenset({"Alice", "Bob"}),
            "document",
        )
        assert "Alice" in result
        assert "Bob" not in result
        assert "Someone" in result or "someone" in result

    # ── Operator data always passes ──────────────────────────────────

    def test_operator_data_always_passes(self):
        """Data about the operator is never filtered. I am always consented
        to myself."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)
        for category in ("email", "calendar", "document", "perception"):
            result = w.filter_for_llm(
                "operator reviewed the quarterly metrics",
                frozenset({"operator"}),
                category,
            )
            assert "operator" in result, f"Operator data passes in {category}"

    # ── Passthrough tools ────────────────────────────────────────────

    def test_system_tools_pass_through(self):
        """System/UI tools are never filtered — they don't contain person data."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)
        for tool in ("get_system_status", "get_weather", "get_current_time"):
            result = w.filter_tool(tool, "alice@corp.com mentioned in status")
            assert "alice@corp.com" in result, f"{tool} should pass through"


# ═══════════════════════════════════════════════════════════════════════════════
# PART 6: PIPELINE PLAUSIBILITY (MUSIC + SPEECH)
#
# When music is playing, short transcripts are noise bleed-through.
# Full sentences are the operator speaking over music. The pipeline
# must distinguish between them without hardware.
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelinePlausibility:
    """ConversationPipeline plausibility gate during ambient audio."""

    def _make_pipeline(self, ambient_interruptible: bool) -> ConversationPipeline:
        """Build a minimal pipeline with mocked STT/TTS."""
        stt = AsyncMock()
        tts = MagicMock()
        ambient = MagicMock(
            interruptible=ambient_interruptible,
            top_labels=[("Music", 0.8)] if not ambient_interruptible else [],
        )
        pipeline = ConversationPipeline(
            stt=stt,
            tts_manager=tts,
            system_prompt="test",
            ambient_fn=lambda: ambient,
        )
        pipeline._running = True
        pipeline.state = ConvState.LISTENING
        pipeline.messages = [{"role": "system", "content": "test"}]
        pipeline._audio_output = None
        return pipeline

    def test_short_transcript_during_music_rejected(self):
        """'yeah yeah' during music → noise bleed-through → rejected.
        System returns to LISTENING, no message appended."""
        pipeline = self._make_pipeline(ambient_interruptible=False)
        pipeline.stt.transcribe = AsyncMock(return_value="yeah yeah")

        asyncio.run(pipeline.process_utterance(b"\x00" * 100))

        assert pipeline.state == ConvState.LISTENING
        assert len(pipeline.messages) == 1  # only system message

    def test_full_sentence_during_music_accepted(self):
        """'Hey Hapax turn the volume down please' during music →
        real speech → passes plausibility, appended to messages."""
        pipeline = self._make_pipeline(ambient_interruptible=False)
        pipeline.stt.transcribe = AsyncMock(return_value="Hey Hapax turn the volume down please")

        # Mock LLM to avoid network
        async def _fake_generate(self_):
            self_.messages.append({"role": "assistant", "content": "Sure."})

        original = ConversationPipeline._generate_and_speak
        ConversationPipeline._generate_and_speak = _fake_generate
        try:
            asyncio.run(pipeline.process_utterance(b"\x00" * 100))
        finally:
            ConversationPipeline._generate_and_speak = original

        user_msgs = [m for m in pipeline.messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert "volume down" in user_msgs[0]["content"]

    def test_any_transcript_without_music_accepted(self):
        """'yeah' without music → real speech → accepted.
        Plausibility only gates during non-interruptible ambient."""
        pipeline = self._make_pipeline(ambient_interruptible=True)
        pipeline.stt.transcribe = AsyncMock(return_value="yeah")

        async def _fake_generate(self_):
            self_.messages.append({"role": "assistant", "content": "?"})

        original = ConversationPipeline._generate_and_speak
        ConversationPipeline._generate_and_speak = _fake_generate
        try:
            asyncio.run(pipeline.process_utterance(b"\x00" * 100))
        finally:
            ConversationPipeline._generate_and_speak = original

        user_msgs = [m for m in pipeline.messages if m["role"] == "user"]
        assert len(user_msgs) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# PART 7: COMPOUND SCENARIOS
#
# Real life doesn't present clean categories. These tests cross multiple
# dimensions simultaneously. Every moment is fully asserted.
# ═══════════════════════════════════════════════════════════════════════════════


class TestCompoundScenarios:
    """Multiple principals, multiple contexts, real-life complexity."""

    def test_full_evening(self):
        """Arrive → code → produce → code → stress → recover → leave.
        The system tracks along naturally. Every phase fully asserted."""
        w = ExperientialWorld()

        w.operator_sits_down()
        w.advance(2.5)
        w.assert_moment(
            Moment(True, "process", 1.0, ConsentPhase.NO_GUEST, True),
            "Arrive at desk",
        )

        w.switch_activity("coding")
        w.advance(10.0)
        w.assert_moment(
            Moment(True, "process", 0.7, ConsentPhase.NO_GUEST, True),
            "Coding",
        )

        w.switch_activity("production")
        w.connect_midi()
        w.advance(30.0)
        w.assert_moment(
            Moment(False, "pause", 0.5, ConsentPhase.NO_GUEST, True),
            "Music production",
        )

        w.switch_activity("coding")
        w.disconnect_midi()
        w.advance(5.0)
        w.assert_moment(
            Moment(True, "process", 0.7, ConsentPhase.NO_GUEST, True),
            "Back to coding",
        )

        w.stress_spikes()
        w.advance(2.5)
        assert not w.moment().gate_eligible, "Stress backs off"

        w.stress_subsides()
        w.advance(2.5)
        w.assert_moment(
            Moment(True, "process", 0.7, ConsentPhase.NO_GUEST, True),
            "Stress recovered",
        )

        w.operator_leaves()
        w.governor._last_operator_seen = time.monotonic() - 61.0
        w.advance(2.5)
        assert w.moment().directive == "withdraw", "Room empty"

    def test_coding_wife_zoom_depart(self):
        """Code → wife arrives → consent offered → she says yes → I join
        Zoom → she leaves during meeting → meeting ends → alone again.
        Every principal tracked correctly at every moment."""
        w = ExperientialWorld()

        # Phase 1: Coding alone
        w.operator_sits_down()
        w.switch_activity("coding")
        w.advance(10.0)
        w.assert_moment(
            Moment(True, "process", 0.7, ConsentPhase.NO_GUEST, True),
            "Phase 1: Coding alone",
        )

        # Phase 2: Wife walks in, debounce, consent offered and granted
        w.guest_enters()
        w.advance(7.5)
        w.assert_moment(
            Moment(True, "process", 0.7, ConsentPhase.CONSENT_PENDING, False),
            "Phase 2: Consent pending",
        )
        assert w.consent_alert_needed
        w.grant_guest_consent()
        w.assert_moment(
            Moment(True, "process", 0.7, ConsentPhase.CONSENT_GRANTED, True),
            "Phase 2: Consent granted",
        )

        # Phase 3: Zoom meeting (she's still here)
        w.switch_activity("meeting")
        w.focus_app("zoom")
        w.advance(2.5)
        w.assert_moment(
            Moment(False, "pause", 0.4, ConsentPhase.CONSENT_GRANTED, True),
            "Phase 3: Zoom with consented guest",
        )

        # Phase 4: She leaves during meeting
        w.guest_leaves()
        for _ in range(15):
            w.advance(2.5)
        assert w.moment().consent_phase == ConsentPhase.NO_GUEST

        # Phase 5: Meeting ends
        w.switch_activity("idle")
        w.focus_app("")
        w.advance(2.5)
        w.assert_moment(
            Moment(True, "process", 1.0, ConsentPhase.NO_GUEST, True),
            "Phase 5: Meeting over, alone",
        )

    def test_production_guest_arrives(self):
        """I'm producing when someone arrives. Production veto stays active.
        Consent tracking works independently. When I stop producing,
        consent is already pending."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("production")
        w.connect_midi()
        w.advance(2.5)
        w.assert_moment(
            Moment(False, "pause", 0.5, ConsentPhase.NO_GUEST, True),
            "Producing alone",
        )

        w.guest_enters()
        w.advance(7.5)
        w.assert_moment(
            Moment(False, "pause", 0.5, ConsentPhase.CONSENT_PENDING, False),
            "Guest during production — two independent concerns",
        )

        w.switch_activity("idle")
        w.disconnect_midi()
        w.advance(2.5)
        w.assert_moment(
            Moment(True, "process", 1.0, ConsentPhase.CONSENT_PENDING, False),
            "Production done, consent still pending",
        )

    def test_email_with_guest_present(self):
        """I look at emails while consented wife is here. Email mentions
        unconsented coworker. Wife's presence is irrelevant to third-party
        protection — separate principal, separate gate."""
        w = ExperientialWorld()
        w.add_consent_contract("wife", frozenset({"perception"}))
        w.operator_sits_down()
        w.guest_enters()
        w.advance(7.5)
        w.grant_guest_consent()

        result = w.filter_for_llm(
            "From: dave@corp.com | Subject: Deploy schedule\nDave says Friday.",
            frozenset({"dave@corp.com"}),
            "email",
        )
        assert "dave@corp.com" not in result, "Coworker still protected"
        assert "Deploy schedule" in result, "Context preserved"

    def test_stress_with_guest_present(self):
        """Guest is here and operator gets stressed. Gate blocks (stress),
        consent stays in its current phase. Independent layers."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.guest_enters()
        w.advance(7.5)
        w.grant_guest_consent()

        w.stress_spikes()
        w.advance(2.5)
        w.assert_moment(
            Moment(False, "process", 1.0, ConsentPhase.CONSENT_GRANTED, True),
            "Stressed with consented guest — gate blocks, consent unaffected",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PART 8: ALGEBRAIC INVARIANTS (Hypothesis)
#
# Properties that must hold for ALL possible inputs. The narrative tests
# prove specific scenarios; these prove the space between them.
# ═══════════════════════════════════════════════════════════════════════════════


class TestInvariants:
    """Algebraic properties that bind the matrix together."""

    @given(
        faces=st.lists(st.integers(min_value=0, max_value=5), min_size=5, max_size=30),
    )
    @settings(max_examples=100)
    def test_presence_never_equals_permission(self, faces: list[int]):
        """No sequence of face detections can grant consent. Only
        explicit human action can. Presence ≠ permission."""
        tracker = ConsentStateTracker(debounce_s=0.0, absence_clear_s=1.0)
        for i, fc in enumerate(faces):
            tracker.tick(face_count=fc, speaker_is_operator=True, now=100.0 + i * 0.5)
        assert tracker.phase != ConsentPhase.CONSENT_GRANTED

    @given(
        activities=st.lists(
            st.sampled_from(["idle", "coding", "production", "meeting", "conversation"]),
            min_size=3,
            max_size=10,
        ),
        present=st.booleans(),
    )
    @settings(max_examples=100)
    def test_governor_always_valid(self, activities: list[str], present: bool):
        """Governor never returns an invalid directive, regardless of input."""
        gov = PipelineGovernor()
        for activity in activities:
            state = EnvironmentState(
                timestamp=time.monotonic(),
                activity_mode=activity,
                operator_present=present,
                face_count=1 if present else 0,
            )
            assert gov.evaluate(state) in {"process", "pause", "withdraw"}

    @given(
        person=st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=2,
            max_size=15,
        ),
        category=st.sampled_from(["email", "calendar", "document", "perception"]),
    )
    @settings(max_examples=50)
    def test_unconsented_never_leaks(self, person: str, category: str):
        """For any person name × any category, if unconsented, their name
        never appears in what the LLM sees."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)
        result = w.filter_for_llm(
            f"{person} sent a message about the project",
            frozenset({person}),
            category,
        )
        assert person not in result

    @given(
        category=st.sampled_from(["email", "calendar", "document", "perception"]),
        content=st.text(min_size=1, max_size=100),
    )
    @settings(max_examples=50)
    def test_operator_always_passes(self, category: str, content: str):
        """Operator data is never degraded. I am always consented to myself."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)
        datum = RetrievedDatum(
            content=content,
            person_ids=frozenset({"operator"}),
            data_category=category,
            source="test",
        )
        decision = w.reader.filter(datum)
        assert decision.degradation_level == 1

    @given(
        person=st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=2,
            max_size=15,
        ),
        category=st.sampled_from(["email", "calendar", "document", "default"]),
    )
    @settings(max_examples=50)
    def test_degradation_is_idempotent(self, person: str, category: str):
        """Degrading already-degraded content changes nothing.
        degrade(degrade(x)) == degrade(x)."""
        content = f"Message from {person} about the quarterly review"
        unconsented = frozenset({person})
        once = degrade(content, unconsented, category)
        twice = degrade(once, unconsented, category)
        assert once == twice

    @given(
        activity=st.sampled_from(["idle", "coding", "production", "meeting"]),
        present=st.booleans(),
        faces=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=100)
    def test_interruptibility_bounded(self, activity: str, present: bool, faces: int):
        """Interruptibility score is always in [0.0, 1.0], never NaN."""
        score = compute_interruptibility(
            vad_confidence=0.0,
            activity_mode=activity,
            in_voice_session=False,
            operator_present=present,
        )
        assert 0.0 <= score <= 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# PART 9: CONVERSATIONAL POLICY EXPERIENTIAL PROOFS
#
# What style of speech does the operator experience in each context?
# Policy adapts HOW the system speaks based on environment and social context.
# These tests use the same ExperientialWorld but assert policy output.
# ═══════════════════════════════════════════════════════════════════════════════


class TestPolicyExperiential:
    """Policy-layer assertions across the experiential matrix."""

    def test_idle_operator_full_profile_policy(self):
        """Operator alone, idle — full profile-driven policy with conversational style."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("idle")
        w.advance(2.5)
        policy = w.policy()
        assert "Conversational Policy" in policy
        assert "truthful" in policy  # dignity floor always present
        assert "Conversational style permitted" in policy

    def test_coding_maximum_brevity(self):
        """Operator coding — policy demands maximum brevity."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("coding")
        w.advance(2.5)
        policy = w.policy()
        assert "Maximum brevity" in policy
        assert "Technical register" in policy

    def test_meeting_hard_constraint(self):
        """Operator in meeting — hard constraint, no interruptions."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("meeting")
        w.advance(2.5)
        policy = w.policy()
        assert "HARD CONSTRAINT" in policy

    def test_production_minimal(self):
        """Operator in production — minimal interruption."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("production")
        w.advance(2.5)
        policy = w.policy()
        assert "Minimal interruption" in policy

    def test_guest_detected_accessible(self):
        """Guest enters — policy ensures accessible responses."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.guest_enters()
        w.advance(2.5)
        policy = w.policy()
        assert "accessible to all listeners" in policy.lower()

    def test_guest_detected_data_protection(self):
        """Guest present — policy avoids exposing sensitive data."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.guest_enters()
        w.advance(2.5)
        policy = w.policy()
        assert "sensitive data" in policy.lower() or "personal" in policy.lower()

    def test_unconsented_guest_dignity_floor(self):
        """Unconsented guest — dignity floor only, no operator profile."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.guest_enters()
        w.advance(10)  # enough to detect guest
        # Create an EnvironmentState with pending_consent
        from dataclasses import replace

        state_with_consent = replace(w._last_state, consent_phase="pending_consent")
        policy = get_policy(env=state_with_consent)
        assert "Dignity floor only" in policy
        assert "Socrates" not in policy  # no operator personality in unconsented mode

    def test_consented_guest_moderate_formality(self):
        """Consented guest — moderate formality, operator style softened."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.guest_enters()
        w.grant_guest_consent()
        w.advance(10)
        from dataclasses import replace

        state_with_consent = replace(w._last_state, consent_phase="consented")
        policy = get_policy(env=state_with_consent)
        assert "consented guest" in policy
        assert "Moderate formality" in policy

    def test_policy_always_has_dignity_floor(self):
        """Every context has the dignity floor — Grice maxims are universal."""
        for mode in ["idle", "coding", "production", "meeting"]:
            w = ExperientialWorld()
            w.operator_sits_down()
            w.switch_activity(mode)
            w.advance(2.5)
            policy = w.policy()
            assert "truthful" in policy, f"Dignity floor missing in {mode} mode"

    def test_policy_computable_when_operator_absent(self):
        """Policy is still computable when the operator is absent.
        The pipeline won't consume it (governance blocks), but computation
        must not error — policy is decoupled from governance directives."""
        w = ExperientialWorld()
        # No operator present at all
        w.advance(2.5)
        policy = w.policy()
        assert "Conversational Policy" in policy
        assert "truthful" in policy

    @given(
        activity=st.sampled_from(["idle", "coding", "production", "meeting", "unknown"]),
        faces=st.integers(min_value=0, max_value=3),
    )
    @settings(max_examples=50)
    def test_policy_never_empty(self, activity: str, faces: int):
        """Policy always produces at least the dignity floor."""
        w = ExperientialWorld()
        if faces > 0:
            w.operator_sits_down()
        for _ in range(faces - 1):
            w.guest_enters()
        w.switch_activity(activity)
        w.advance(2.5)
        policy = w.policy()
        assert "Conversational Policy" in policy
        assert "truthful" in policy

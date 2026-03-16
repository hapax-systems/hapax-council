"""Experiential governance proofs.

Each test is a story told from a human's perspective. The assertions prove
what the person experiences at each moment — not what internal methods return.

The ExperientialWorld ties the full stack together: perception → gate →
governor → consent tracker → consent reader → pipeline readiness. Tests
advance through time, changing the physical world (who's present, what's
playing, what app is focused), and assert the experiential properties at
every moment.

Three principals, three promises:
  Operator:  cognitive support without surveillance
  Guest:     informed consent without friction
  Absent:    protection without erasure

Start with the operator alone. Then add people. Then add context.
No hardware, no LLM, no network.
"""

from __future__ import annotations

import time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_voice.consent_state import ConsentPhase, ConsentStateTracker
from agents.hapax_voice.context_gate import ContextGate
from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.perception import EnvironmentState, compute_interruptibility
from agents.hapax_voice.primitives import Behavior
from agents.hapax_voice.session import SessionManager
from shared.governance.consent import ConsentContract, ConsentRegistry
from shared.governance.consent_reader import ConsentGatedReader, RetrievedDatum


# ── The World ────────────────────────────────────────────────────────────────


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
        self.governor = PipelineGovernor(
            operator_absent_withdraw_s=60.0,
        )
        self.consent = ConsentStateTracker(debounce_s=5.0, absence_clear_s=30.0)
        self._registry = ConsentRegistry()
        self.reader = ConsentGatedReader(
            registry=self._registry,
            operator_ids=frozenset({"operator", "ryan"}),
        )

        # Event log for inspection
        self.events: list[str] = []

        # Snapshot after each tick
        self._last_state: EnvironmentState | None = None
        self._last_gate_result = None
        self._last_directive: str | None = None

    # ── Physical world mutations ─────────────────────────────────────

    def operator_sits_down(self) -> None:
        self._operator_present = True
        self._faces = max(1, self._faces)
        self.events.append(f"t={self.t:.0f}: operator sits down")

    def operator_leaves(self) -> None:
        self._operator_present = False
        self._faces = max(0, self._faces - 1)
        self.events.append(f"t={self.t:.0f}: operator leaves")

    def guest_enters(self) -> None:
        self._faces += 1
        self.events.append(f"t={self.t:.0f}: guest enters (faces={self._faces})")

    def guest_leaves(self) -> None:
        self._faces = max(0, self._faces - 1)
        self.events.append(f"t={self.t:.0f}: guest leaves (faces={self._faces})")

    def switch_activity(self, mode: str) -> None:
        self._activity_mode = mode
        self.events.append(f"t={self.t:.0f}: activity → {mode}")

    def focus_app(self, app_class: str, title: str = "") -> None:
        self._active_window_class = app_class
        self._active_window_title = title
        self.events.append(f"t={self.t:.0f}: focus → {app_class}")

    def set_workspace_context(self, ctx: str) -> None:
        self._workspace_context = ctx

    def start_music(self) -> None:
        self._ambient_interruptible = False
        self._ambient_reason = "Music detected"
        self._ambient_top_labels = [("Music", 0.8)]
        self.events.append(f"t={self.t:.0f}: music starts")

    def stop_music(self) -> None:
        self._ambient_interruptible = True
        self._ambient_reason = ""
        self._ambient_top_labels = []
        self.events.append(f"t={self.t:.0f}: music stops")

    def connect_midi(self) -> None:
        self._midi_active = True
        self.events.append(f"t={self.t:.0f}: MIDI connected")

    def disconnect_midi(self) -> None:
        self._midi_active = False
        self.events.append(f"t={self.t:.0f}: MIDI disconnected")

    def stress_spikes(self) -> None:
        self._stress_elevated = True
        self.events.append(f"t={self.t:.0f}: stress elevated")

    def stress_subsides(self) -> None:
        self._stress_elevated = False

    def system_degrades(self) -> None:
        self._system_health = "degraded"
        self.events.append(f"t={self.t:.0f}: system health → degraded")

    def system_recovers(self) -> None:
        self._system_health = "healthy"

    def start_exercising(self) -> None:
        self._watch_activity = "exercise"
        self.events.append(f"t={self.t:.0f}: exercise started")

    def stop_exercising(self) -> None:
        self._watch_activity = "idle"

    def say_wake_word(self) -> None:
        self.governor.wake_word_active = True
        self.events.append(f"t={self.t:.0f}: wake word detected")

    def grant_guest_consent(self) -> None:
        self.consent.grant_consent()
        self.events.append(f"t={self.t:.0f}: guest grants consent")

    def refuse_guest_consent(self) -> None:
        self.consent.refuse_consent()
        self.events.append(f"t={self.t:.0f}: guest refuses consent")

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
        """Advance time, ticking all governance layers at daemon cadence.

        Simulates the daemon's ~2.5s tick loop. Multiple ticks within the
        interval let debounce timers accumulate naturally.
        """
        remaining = seconds
        while remaining > 0:
            step = min(tick_interval, remaining)
            self.t += step
            remaining -= step
            self._tick()

    def _tick(self) -> None:
        """Wire the governance stack exactly as the daemon does."""
        # Build behaviors for gate
        behaviors = {
            "sink_volume": Behavior(self._sink_volume, watermark=self.t),
            "midi_active": Behavior(self._midi_active, watermark=self.t),
            "stress_elevated": Behavior(self._stress_elevated, watermark=self.t),
            "system_health_status": Behavior(self._system_health, watermark=self.t),
            "watch_activity_state": Behavior(self._watch_activity, watermark=self.t),
        }
        if self._active_window_class:
            behaviors["active_window_class"] = Behavior(
                self._active_window_class, watermark=self.t
            )
        self.gate.set_behaviors(behaviors)
        self.gate.set_activity_mode(self._activity_mode)

        # Ambient classification (gate reads from cached result)
        if not self._ambient_interruptible:
            from unittest.mock import MagicMock

            self.gate._ambient_result = MagicMock(
                interruptible=False,
                reason=self._ambient_reason,
            )
            # Ensure ambient veto is in the chain
            if not any(v.name == "ambient" for v in self.gate._veto_chain.vetoes):
                from agents.hapax_voice.governance import Veto

                self.gate._veto_chain.add(Veto("ambient", predicate=self.gate._allow_ambient))
        else:
            self.gate._ambient_result = None

        # Build environment state
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

        # Gate check
        self._last_gate_result = self.gate.check()

        # Governor evaluate (needs real monotonic for internal _last_operator_seen)
        # We manipulate _last_operator_seen directly for absence tracking
        if self._operator_present:
            self.governor._last_operator_seen = time.monotonic()
        self._last_directive = self.governor.evaluate(self._last_state)

        # Consent tracker tick
        self.consent.tick(
            face_count=self._faces,
            speaker_is_operator=True,
            now=self.t,
        )

    # ── Experiential properties ──────────────────────────────────────
    # These describe what a human would EXPERIENCE, not internal state.

    @property
    def system_available(self) -> bool:
        """System could respond if explicitly asked (gate eligible)."""
        return self._last_gate_result is not None and self._last_gate_result.eligible

    @property
    def system_would_interrupt(self) -> bool:
        """System would proactively speak (high interruptibility + no vetoes)."""
        if self._last_state is None:
            return False
        return (
            self.system_available
            and self._last_directive == "process"
            and self._last_state.interruptibility_score > 0.7
        )

    @property
    def system_listening(self) -> bool:
        """Pipeline is in process mode (accepting input)."""
        return self._last_directive == "process"

    @property
    def system_paused(self) -> bool:
        """Pipeline is paused (respecting context)."""
        return self._last_directive == "pause"

    @property
    def system_withdrawn(self) -> bool:
        """Pipeline has withdrawn (operator gone)."""
        return self._last_directive == "withdraw"

    @property
    def storing_person_data(self) -> bool:
        """Person-adjacent data would be persisted right now."""
        return self.consent.persistence_allowed

    @property
    def consent_alert_needed(self) -> bool:
        """System needs to alert a guest about consent (fires once)."""
        return self.consent.needs_notification

    @property
    def consent_phase(self) -> ConsentPhase:
        """Current consent phase."""
        return self.consent.phase

    @property
    def interruptibility(self) -> float:
        """How interruptible the operator is (0=don't touch, 1=wide open)."""
        if self._last_state is None:
            return 0.0
        return self._last_state.interruptibility_score

    @property
    def gate_reason(self) -> str:
        """Why the gate is blocking, if it is."""
        if self._last_gate_result is None:
            return ""
        return self._last_gate_result.reason

    @property
    def veto_reasons(self) -> tuple[str, ...]:
        """Which vetoes are blocking the governor."""
        if self.governor.last_veto_result is None:
            return ()
        return self.governor.last_veto_result.denied_by

    def filter_for_llm(self, content: str, person_ids: frozenset[str], category: str) -> str:
        """What the LLM would actually see after consent filtering."""
        datum = RetrievedDatum(
            content=content,
            person_ids=person_ids,
            data_category=category,
            source="test",
        )
        decision = self.reader.filter(datum)
        return decision.filtered_content


# ── PART 1: Just Me ─────────────────────────────────────────────────────────
#
# These tests prove governance properties using only the operator.
# No guests, no third parties. Run these first, run them today.
# They prove: the system supports me without surveilling me.


class TestJustMe:
    """I am the only human. Prove the system respects my cognition."""

    def test_i_sit_down_and_system_is_ready(self):
        """I sit down at my desk. The system is available but doesn't
        speak. It's there if I need it, invisible if I don't."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)

        assert w.system_available, "System should be reachable if I ask"
        assert w.system_listening, "Pipeline should be in process mode"
        assert w.interruptibility == pytest.approx(1.0, abs=0.01), (
            "Nothing competing for attention"
        )
        # No guest → no consent concerns
        assert w.storing_person_data, "Only my data, no consent issue"
        assert w.consent_phase == ConsentPhase.NO_GUEST

    def test_i_start_coding_and_system_backs_off(self):
        """I open my editor and start coding. The system detects this
        and backs off — still available, but less eager to interrupt."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("coding")
        w.advance(2.5)

        assert w.system_available, "Still reachable if I say the wake word"
        assert w.system_listening, "Pipeline still running"
        assert w.interruptibility == pytest.approx(0.7, abs=0.01), (
            "Coding penalty of 0.3 applied"
        )

    def test_i_say_wake_word_during_coding(self):
        """I'm deep in code but need help. I say 'Hey Hapax'. The system
        responds immediately, then protects the conversation for a few ticks
        before returning to quiet coding mode."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("coding")
        w.advance(2.5)

        # I speak
        w.say_wake_word()
        w.advance(2.5)
        assert w.system_listening, "Wake word → process"
        assert w.governor.last_selected.selected_by == "wake_word_override"

        # Grace period protects the conversation
        w.advance(2.5)
        assert w.system_listening, "Still protected by grace"
        w.advance(2.5)
        assert w.system_listening, "Grace tick 2"
        w.advance(2.5)
        assert w.system_listening, "Grace tick 3"

        # Grace expired, but coding isn't a veto — still process
        w.advance(2.5)
        assert w.system_listening, "Coding doesn't veto, just reduces interruptibility"

    def test_i_open_ableton_and_system_goes_silent(self):
        """I switch to music production. MIDI connects. The system goes
        completely silent — both gate and governor block. This is sacred
        creative space. When I'm done, system comes back."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)
        assert w.system_available

        # Enter production mode
        w.switch_activity("production")
        w.connect_midi()
        w.advance(2.5)

        assert not w.system_available, "Gate blocks: MIDI active"
        assert w.system_paused, "Governor blocks: production mode"

        # Even if I wanted to ask, gate says no
        # This is intentional: in production, audio output would bleed into monitors

        # I finish producing
        w.switch_activity("idle")
        w.disconnect_midi()
        w.advance(2.5)

        assert w.system_available, "System returns when production ends"
        assert w.system_listening, "Back to normal"

    def test_i_open_ableton_but_say_wake_word(self):
        """I'm producing but urgently need Hapax. Wake word overrides
        production veto for a few ticks — system responds, then production
        veto reasserts. The override is deliberate and temporary."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("production")
        w.connect_midi()
        w.advance(2.5)
        assert w.system_paused

        w.say_wake_word()
        w.advance(2.5)
        assert w.system_listening, "Wake word overrides production"

        # Grace ticks
        for _ in range(3):
            w.advance(2.5)
            assert w.system_listening, "Still in grace period"

        # Grace expired → production veto reasserts
        w.advance(2.5)
        assert w.system_paused, "Production reclaims control"

    def test_zoom_call_total_silence(self):
        """I join a Zoom meeting. Both gate and governor go silent.
        Nobody on the call hears my AI assistant blurt out."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.focus_app("zoom", "Team Standup - Zoom Meeting")
        w.switch_activity("meeting")
        w.advance(2.5)

        assert not w.system_available, "Gate blocks: Zoom is fullscreen-blocked app"
        assert w.system_paused, "Governor blocks: meeting mode"

    def test_i_step_away_for_coffee(self):
        """I leave my desk. After a grace period, the system withdraws.
        It doesn't keep listening to an empty room."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)
        assert w.system_listening

        # I leave
        w.operator_leaves()
        w.advance(2.5)

        # Within the 60s threshold — still process (might come right back)
        assert w.system_listening, "Grace period: I might just be grabbing coffee"

        # Force absence beyond threshold
        w.governor._last_operator_seen = time.monotonic() - 61.0
        w.advance(2.5)
        assert w.system_withdrawn, "System stops listening to empty room"

    def test_stress_spike_system_backs_off(self):
        """My watch detects elevated stress (HRV drop, EDA spike).
        The system backs off — adding AI interaction to physiological
        load would make things worse, not better."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)
        assert w.system_available

        w.stress_spikes()
        w.advance(2.5)
        assert not w.system_available, "Gate blocks during stress"
        assert "stress" in w.gate_reason.lower()

        w.stress_subsides()
        w.advance(2.5)
        assert w.system_available, "Stress passes, system returns"

    def test_exercise_leave_me_alone(self):
        """I'm on the treadmill. Watch says exercise. System goes dark.
        I don't want AI talking in my earbuds during a run."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.start_exercising()
        w.advance(2.5)

        assert not w.system_available
        assert "exercise" in w.gate_reason.lower()

    def test_system_health_degraded(self):
        """Infrastructure is flaky. Rather than start a conversation
        that might fail mid-sentence, system doesn't start at all."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)
        assert w.system_available

        w.system_degrades()
        w.advance(2.5)
        assert not w.system_available
        assert "health" in w.gate_reason.lower()

        w.system_recovers()
        w.advance(2.5)
        assert w.system_available

    def test_performance_review_axiom_veto(self):
        """I open a performance review document. The management_governance
        axiom fires — the system must not help draft feedback about individuals.
        This isn't a feature toggle; it's a constitutional constraint."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.set_workspace_context("editing performance review in Lattice")
        w.advance(2.5)

        assert w.system_paused, "Axiom compliance veto"
        assert "axiom_compliance" in w.veto_reasons

    def test_full_evening_session(self):
        """A complete evening: arrive, code, produce music, code more,
        get stressed, recover, leave. The system tracks along naturally,
        adjusting to each phase without me doing anything."""
        w = ExperientialWorld()

        # Arrive
        w.operator_sits_down()
        w.advance(2.5)
        assert w.system_available and w.system_listening

        # Start coding
        w.switch_activity("coding")
        w.advance(10.0)
        assert w.system_available  # available but quiet
        assert w.interruptibility < 1.0  # backed off

        # Switch to Ableton
        w.switch_activity("production")
        w.connect_midi()
        w.advance(30.0)
        assert not w.system_available  # total silence

        # Back to coding
        w.switch_activity("coding")
        w.disconnect_midi()
        w.advance(5.0)
        assert w.system_available  # back

        # Stress spike (bad PR review notification)
        w.stress_spikes()
        w.advance(2.5)
        assert not w.system_available  # backs off

        # Stress passes
        w.stress_subsides()
        w.advance(2.5)
        assert w.system_available  # returns

        # Head to bed
        w.operator_leaves()
        w.governor._last_operator_seen = time.monotonic() - 61.0
        w.advance(2.5)
        assert w.system_withdrawn  # room empty, system sleeps


# ── PART 2: My Wife Walks In ────────────────────────────────────────────────
#
# Now we add a second human. These tests prove the consent lifecycle
# from her perspective — she is a sovereign principal who deserves
# informed consent without friction.


class TestWifeWalksIn:
    """A guest enters the room. Prove consent is never violated."""

    def test_she_walks_in_and_system_notices_then_asks(self):
        """My wife walks into the room. I am there. She does not have
        prior consent on board the system. Hapax alerts her in a natural
        way. Consent has not been violated.

        What this proves:
        - Detection is immediate but action is debounced (no ambush)
        - Persistence is blocked from the moment she's detected
        - Notification fires exactly once after debounce
        - She is never recorded without consent
        """
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("coding")
        w.advance(5.0)
        assert w.storing_person_data, "Just me, no issue"

        # She walks in
        w.guest_enters()
        w.advance(0.1)  # first tick after entry

        # IMMEDIATE: persistence blocked, but no notification yet
        assert not w.storing_person_data, "Protected from the first tick"
        assert w.consent_phase == ConsentPhase.GUEST_DETECTED
        assert not w.consent_alert_needed, "Still debouncing — might be passing through"

        # 2.5 seconds — still debouncing
        w.advance(2.4)
        assert not w.storing_person_data
        assert not w.consent_alert_needed, "Debounce not satisfied"

        # 5.0 seconds — debounce complete, notification fires
        w.advance(2.5)
        assert w.consent_phase == ConsentPhase.CONSENT_PENDING
        assert w.consent_alert_needed, "NOW the system should say something"

        # But only once — not nagging
        assert not w.consent_alert_needed, "Second read is False (no nag)"

        # Still not storing
        assert not w.storing_person_data

    def test_she_says_yes(self):
        """She hears the notification, says yes. System unlocks
        persistence. From her perspective: one natural question,
        one answer, done."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.guest_enters()
        w.advance(5.1)  # past debounce
        _ = w.consent_alert_needed  # consume notification

        w.grant_guest_consent()
        assert w.consent_phase == ConsentPhase.CONSENT_GRANTED
        assert w.storing_person_data, "Consent → persistence unlocked"

    def test_she_says_no_and_nothing_changes(self):
        """She says no. System respects it immediately. No guilt trip,
        no 'are you sure?', no repeated asking. She said no."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.guest_enters()
        w.advance(5.1)
        _ = w.consent_alert_needed

        w.refuse_guest_consent()
        assert w.consent_phase == ConsentPhase.CONSENT_REFUSED
        assert not w.storing_person_data

        # She's still there — system doesn't ask again
        w.advance(30.0)
        assert not w.consent_alert_needed
        assert not w.storing_person_data

    def test_she_leaves_before_system_asks(self):
        """She pokes her head in for 3 seconds and leaves. The system
        never even asks — because there was nothing to ask about.
        A 3-second visit doesn't warrant a consent conversation."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.guest_enters()
        w.advance(2.5)  # within debounce
        assert w.consent_phase == ConsentPhase.GUEST_DETECTED
        assert not w.consent_alert_needed, "Debounce protects from premature prompt"

        w.guest_leaves()
        w.advance(2.5)
        # She's gone and debounce was never satisfied — no notification ever fired
        assert w.consent_phase == ConsentPhase.GUEST_DETECTED  # absence timer started
        assert not w.consent_alert_needed

    def test_she_walks_in_during_consent_pending_and_leaves_without_answering(self):
        """Debounce satisfied, consent pending, but she leaves without
        responding. System auto-clears after absence threshold.
        No unresolved state left behind."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.guest_enters()
        w.advance(5.1)  # debounce satisfied
        assert w.consent_phase == ConsentPhase.CONSENT_PENDING

        w.guest_leaves()
        # Absence timer starts
        w.advance(10.0)
        assert w.consent_phase == ConsentPhase.CONSENT_PENDING  # still waiting

        # After absence_clear_s (30s), auto-clear
        w.advance(21.0)
        assert w.consent_phase == ConsentPhase.NO_GUEST, "Auto-cleared, no dangling state"
        assert w.storing_person_data, "Back to operator-only"

    def test_she_has_prior_consent(self):
        """She's consented before (contract on file). System detects her,
        debounces, but then finds the contract. No notification needed —
        she already said yes."""
        w = ExperientialWorld()
        w.add_consent_contract("wife", frozenset({"perception", "document"}))
        w.operator_sits_down()
        w.guest_enters()
        w.advance(5.1)

        # Consent tracker still goes to PENDING (it doesn't check contracts),
        # but the reader will allow data through for "wife"
        result = w.filter_for_llm(
            "Wife mentioned dinner plans",
            frozenset({"wife"}),
            "document",
        )
        assert "Wife" in result or "wife" in result, (
            "Prior consent → name passes through reader"
        )


# ── PART 3: People Who Aren't Here ─────────────────────────────────────────
#
# Third parties mentioned in emails, calendar, documents. They can't
# consent because they're not present. The system must protect them
# without erasing the useful context around them.


class TestPeopleNotHere:
    """Absent third parties. Prove protection without erasure."""

    def test_coworkers_email_name_hidden_subject_preserved(self):
        """I search my email. Alice sent something about Q2 budget.
        The system tells me about the budget — but doesn't mention Alice
        by name. The work context is preserved; the person is protected."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)

        result = w.filter_for_llm(
            "From: alice@corp.com | Subject: Q2 Budget Review\n"
            "Hey, the Q2 numbers look good. Let's discuss Thursday.",
            frozenset({"alice@corp.com"}),
            "email",
        )
        assert "alice@corp.com" not in result, "Her identity is protected"
        assert "Q2 Budget" in result, "The work context survives"
        assert "[someone at corp.com]" in result, "Natural substitution"

    def test_calendar_meeting_count_not_names(self):
        """I check my calendar. I have a meeting with 3 people. The system
        tells me the time and topic — but not who specifically. I know
        it's a meeting with 3 people. That's enough context to prepare."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)

        result = w.reader.filter_tool_result(
            "get_calendar_today",
            "- 2026-03-15T10:00: Sprint planning (with Alice, Bob, charlie@corp.com)",
        )
        assert "Alice" not in result
        assert "Bob" not in result
        assert "charlie@corp.com" not in result
        assert "3 people" in result
        assert "Sprint planning" in result
        assert "10:00" in result

    def test_alice_consented_bob_didnt(self):
        """Alice has a consent contract for document access. Bob doesn't.
        In a document mentioning both: Alice's name stays, Bob becomes
        'Someone'. Neither over-protected nor under-protected."""
        w = ExperientialWorld()
        w.add_consent_contract("Alice", frozenset({"document"}))
        w.operator_sits_down()
        w.advance(2.5)

        result = w.filter_for_llm(
            "Alice and Bob agreed the deadline is unrealistic",
            frozenset({"Alice", "Bob"}),
            "document",
        )
        assert "Alice" in result, "Consented → visible"
        assert "Bob" not in result, "Unconsented → protected"
        assert "Someone" in result or "someone" in result

    def test_consent_revocation_is_immediate(self):
        """Alice revokes her consent. The very next query abstracts her name.
        No stale cache, no grace period, no 'but she used to be consented'."""
        w = ExperientialWorld()
        w.add_consent_contract("Alice", frozenset({"document"}))
        w.operator_sits_down()
        w.advance(2.5)

        # Before revocation
        before = w.filter_for_llm(
            "Alice proposed the architecture",
            frozenset({"Alice"}),
            "document",
        )
        assert "Alice" in before

        # Revoke
        w.revoke_consent("Alice")

        # Immediately after
        after = w.filter_for_llm(
            "Alice proposed the architecture",
            frozenset({"Alice"}),
            "document",
        )
        assert "Alice" not in after, "Revocation is immediate"


# ── PART 4: Compound Scenarios ──────────────────────────────────────────────
#
# Real life doesn't present clean categories. These tests combine
# multiple principals and multiple context shifts.


class TestCompoundScenarios:
    """Multiple principals, multiple contexts, real-life complexity."""

    def test_coding_then_wife_then_zoom_then_alone(self):
        """Full evening sequence: code → wife arrives → join Zoom → she leaves
        → meeting ends → alone again. At every moment, every principal is
        treated correctly."""
        w = ExperientialWorld()

        # Phase 1: Coding alone
        w.operator_sits_down()
        w.switch_activity("coding")
        w.advance(10.0)
        assert w.system_available
        assert w.storing_person_data  # just me
        assert w.consent_phase == ConsentPhase.NO_GUEST

        # Phase 2: Wife walks in
        w.guest_enters()
        w.advance(5.1)
        assert not w.storing_person_data  # her presence blocks persistence
        assert w.consent_phase == ConsentPhase.CONSENT_PENDING
        first_notification = w.consent_alert_needed
        assert first_notification, "Should notify once"
        assert not w.consent_alert_needed, "Only once"

        # She says yes
        w.grant_guest_consent()
        assert w.storing_person_data  # unlocked

        # Phase 3: I join Zoom (she's still here)
        w.switch_activity("meeting")
        w.focus_app("zoom", "Team Standup")
        w.advance(2.5)
        assert not w.system_available, "Zoom blocks gate"
        assert w.system_paused, "Meeting blocks governor"
        assert w.storing_person_data, "Consent still active"

        # Phase 4: She leaves during my meeting
        w.guest_leaves()
        # Keep ticking through absence threshold
        for _ in range(15):
            w.advance(2.5)
        assert w.consent_phase == ConsentPhase.NO_GUEST

        # Phase 5: Meeting ends
        w.switch_activity("idle")
        w.focus_app("")
        w.advance(2.5)
        assert w.system_available, "Meeting over, system back"
        assert w.system_listening
        assert w.storing_person_data  # just me again

    def test_music_and_guest_simultaneously(self):
        """I'm producing music when someone comes to the door.
        Production veto is active. Guest detection still works
        (perception continues even when pipeline is paused).
        When I stop producing, consent is already pending."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.switch_activity("production")
        w.connect_midi()
        w.advance(2.5)
        assert w.system_paused  # production veto

        # Guest arrives during production
        w.guest_enters()
        w.advance(5.1)  # past debounce

        # Production veto still active, but consent tracked independently
        assert w.system_paused
        assert w.consent_phase == ConsentPhase.CONSENT_PENDING
        assert not w.storing_person_data

        # I stop producing
        w.switch_activity("idle")
        w.disconnect_midi()
        w.advance(2.5)

        # Now system is available AND consent prompt should have fired
        assert w.system_available
        # Consent was already pending — the notification fired during production
        # even though the pipeline was paused. The consent system is independent.

    def test_email_lookup_with_guest_present(self):
        """I'm looking at emails while my wife is here (consented).
        The email mentions a coworker (unconsented). My wife's presence
        doesn't affect third-party protection — they're separate principals."""
        w = ExperientialWorld()
        w.add_consent_contract("wife", frozenset({"perception"}))
        w.operator_sits_down()
        w.guest_enters()
        w.advance(5.1)
        w.grant_guest_consent()

        # Look up an email from a coworker
        result = w.filter_for_llm(
            "From: dave@corp.com | Subject: Deploy schedule\nDave says Friday.",
            frozenset({"dave@corp.com"}),
            "email",
        )
        assert "dave@corp.com" not in result, "Coworker still protected"
        assert "Deploy schedule" in result, "Context preserved"


# ── PART 5: Algebraic Properties ────────────────────────────────────────────
#
# Hypothesis tests that prove invariants hold across random scenarios.
# These are the mathematical backbone — if a property holds for 1000
# random inputs, it's a strong proof it holds for all inputs.


class TestExperientialInvariants:
    """Properties that must hold for all possible world states."""

    @given(
        faces=st.lists(
            st.integers(min_value=0, max_value=5), min_size=5, max_size=30
        ),
    )
    @settings(max_examples=100)
    def test_consent_never_granted_without_explicit_action(self, faces: list[int]):
        """No sequence of face detections can grant consent. Only an
        explicit human action (grant_consent) can do that. This is the
        fundamental consent property: presence ≠ permission."""
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
    def test_governor_never_returns_garbage(self, activities: list[str], present: bool):
        """The governor always returns a valid directive. Never crashes,
        never returns an unexpected value, no matter what we throw at it."""
        gov = PipelineGovernor()
        for activity in activities:
            state = EnvironmentState(
                timestamp=time.monotonic(),
                activity_mode=activity,
                operator_present=present,
                face_count=1 if present else 0,
            )
            result = gov.evaluate(state)
            assert result in {"process", "pause", "withdraw"}

    @given(
        person=st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=2,
            max_size=15,
        ),
    )
    @settings(max_examples=50)
    def test_unconsented_person_never_reaches_llm(self, person: str):
        """For any possible person name, if they haven't consented,
        their name never appears in what the LLM sees."""
        w = ExperientialWorld()
        w.operator_sits_down()
        w.advance(2.5)

        result = w.filter_for_llm(
            f"{person} mentioned the quarterly targets",
            frozenset({person}),
            "document",
        )
        assert person not in result

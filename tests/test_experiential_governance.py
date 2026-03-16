"""Experiential governance test suite.

Validates that layers 1-6 (pre-LLM gates, system prompt construction,
perception→LLM pipeline, behavioral modulation, post-LLM filters, history
compression) meet the experiential goals of the system philosophy.

Every human the system touches is a sovereign principal:
- The operator deserves cognitive support without surveillance
- Guests deserve informed consent without friction
- Absent third parties deserve protection without erasure

No hardware, LLM, or network required.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_voice.consent_state import ConsentPhase, ConsentStateTracker
from agents.hapax_voice.context_gate import ContextGate
from agents.hapax_voice.conversation_pipeline import ConversationPipeline, ConvState
from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.perception import EnvironmentState
from agents.hapax_voice.primitives import Behavior
from agents.hapax_voice.session import SessionManager
from shared.governance.consent import ConsentContract, ConsentRegistry
from shared.governance.consent_reader import ConsentGatedReader, RetrievedDatum
from shared.governance.degradation import degrade
from shared.hyprland import WindowInfo

# ── Helpers ──────────────────────────────────────────────────────────────────


def _state(**overrides) -> EnvironmentState:
    """Build a frozen EnvironmentState with sensible defaults."""
    defaults = dict(
        timestamp=time.monotonic(),
        speech_detected=False,
        vad_confidence=0.0,
        face_count=1,
        operator_present=True,
        activity_mode="idle",
    )
    defaults.update(overrides)
    return EnvironmentState(**defaults)


def _gate_with(**behaviors) -> ContextGate:
    """Build a ContextGate with Behavior-injected reads (no subprocess).

    Values can be raw (wrapped in Behavior) or already Behavior instances.
    """
    session = SessionManager()
    gate = ContextGate(session, ambient_classification=False)
    b = {}
    for name, value in behaviors.items():
        b[name] = value if isinstance(value, Behavior) else Behavior(value)
    # Always provide sink_volume and midi_active to avoid subprocess fallback
    b.setdefault("sink_volume", Behavior(0.3))
    b.setdefault("midi_active", Behavior(False))
    gate.set_behaviors(b)
    return gate


def _registry_with(*contracts: ConsentContract) -> ConsentRegistry:
    """Build an in-memory ConsentRegistry with given contracts."""
    registry = ConsentRegistry()
    for c in contracts:
        registry._contracts[c.id] = c
    return registry


def _contract(cid: str, person: str, scope: frozenset[str]) -> ConsentContract:
    """Build a ConsentContract."""
    return ConsentContract(
        id=cid,
        parties=("operator", person),
        scope=scope,
    )


def _reader(registry: ConsentRegistry) -> ConsentGatedReader:
    """Build a ConsentGatedReader with operator IDs."""
    return ConsentGatedReader(
        registry=registry,
        operator_ids=frozenset({"operator", "operator"}),
    )


def _governor(**kwargs) -> PipelineGovernor:
    """Build a PipelineGovernor with optional overrides."""
    return PipelineGovernor(**kwargs)


def _window(title: str, app_class: str = "unknown") -> WindowInfo:
    """Build a minimal WindowInfo."""
    return WindowInfo(
        address="0x0",
        app_class=app_class,
        title=title,
        workspace_id=1,
        pid=1,
        x=0,
        y=0,
        width=1920,
        height=1080,
        floating=False,
        fullscreen=False,
    )


# ── A. The Operator — cognitive support without surveillance ─────────────────


class TestOperatorCognitiveSupport:
    """A1-A3: coding, music production, video meeting."""

    def test_a1_deep_coding_available_but_quiet(self):
        """System is available if asked, but interruptibility is penalized."""
        gate = _gate_with()
        gate.set_activity_mode("coding")
        result = gate.check()
        # Gate eligible — system can respond IF asked
        assert result.eligible

        gov = _governor()
        state = _state(activity_mode="coding", operator_present=True, face_count=1)
        directive = gov.evaluate(state)
        assert directive == "process"

        # Interruptibility is penalized by 0.3 for coding
        from agents.hapax_voice.perception import compute_interruptibility

        score = compute_interruptibility(
            vad_confidence=0.0,
            activity_mode="coding",
            in_voice_session=False,
            operator_present=True,
        )
        assert score == pytest.approx(0.7, abs=0.01)

    def test_a2_music_production_absolute_silence(self):
        """MIDI veto on gate + production veto on governor — two independent blocks."""
        gate = _gate_with(midi_active=True)
        gate.set_activity_mode("production")
        result = gate.check()
        assert not result.eligible

        gov = _governor()
        state = _state(activity_mode="production", operator_present=True)
        directive = gov.evaluate(state)
        assert directive == "pause"
        assert not gov.last_veto_result.allowed
        assert "activity_mode" in gov.last_veto_result.denied_by

    def test_a3_video_meeting_zero_sound(self):
        """Fullscreen app veto on gate + meeting veto on governor."""
        gate = _gate_with(active_window_class="zoom")
        gate.set_activity_mode("meeting")
        result = gate.check()
        assert not result.eligible

        gov = _governor()
        state = _state(activity_mode="meeting", operator_present=True)
        directive = gov.evaluate(state)
        assert directive == "pause"
        assert "activity_mode" in gov.last_veto_result.denied_by


class TestOperatorPresenceAndBody:
    """A4, A5, A8: absence, stress, exercise."""

    def test_a4_steps_away_graceful_withdraw(self):
        """Returns process during grace, then withdraw after timeout."""
        gov = _governor(operator_absent_withdraw_s=2.0)
        # Operator present initially
        gov._last_operator_seen = time.monotonic()
        state_present = _state(operator_present=True, face_count=1)
        assert gov.evaluate(state_present) == "process"

        # Operator absent but within grace
        time.sleep(0.1)
        state_absent = _state(operator_present=False, face_count=0)
        result = gov.evaluate(state_absent)
        assert result == "process"

        # Force absence beyond threshold
        gov._last_operator_seen = time.monotonic() - 3.0
        result = gov.evaluate(state_absent)
        assert result == "withdraw"

    def test_a5_stress_elevated_back_off(self):
        """Gate ineligible when stress is elevated."""
        gate = _gate_with(stress_elevated=True)
        result = gate.check()
        assert not result.eligible
        assert "stress" in result.reason.lower()

    def test_a8_exercising_leave_alone(self):
        """Gate ineligible when watch says exercise."""
        gate = _gate_with(watch_activity_state="exercise")
        result = gate.check()
        assert not result.eligible
        assert "exercise" in result.reason.lower()


class TestOperatorOverridesAndHealth:
    """A6, A7, A9: wake word override, system health, axiom veto."""

    def test_a6_wake_word_during_production_override(self):
        """Wake word overrides production veto with 3-tick grace, then veto reasserts."""
        gov = _governor()
        prod_state = _state(activity_mode="production", operator_present=True)

        # Production mode → pause
        assert gov.evaluate(prod_state) == "pause"

        # Wake word fires → immediate process
        gov.wake_word_active = True
        assert gov.evaluate(prod_state) == "process"
        assert gov._wake_word_grace_remaining == 3

        # Grace ticks protect the session
        assert gov.evaluate(prod_state) == "process"
        assert gov._wake_word_grace_remaining == 2
        assert gov.evaluate(prod_state) == "process"
        assert gov._wake_word_grace_remaining == 1
        assert gov.evaluate(prod_state) == "process"
        assert gov._wake_word_grace_remaining == 0

        # Grace expired → production veto reasserts
        assert gov.evaluate(prod_state) == "pause"

    def test_a7_system_degraded_no_broken_tools(self):
        """Gate ineligible when system health is degraded."""
        gate = _gate_with(system_health_status="degraded")
        result = gate.check()
        assert not result.eligible
        assert "health" in result.reason.lower()

    def test_a9_performance_review_axiom_veto(self):
        """Governor pauses when workspace suggests performance review."""
        gov = _governor()
        state = _state(
            activity_mode="idle",
            operator_present=True,
            workspace_context="editing performance review in Lattice",
        )
        directive = gov.evaluate(state)
        assert directive == "pause"
        assert not gov.last_veto_result.allowed
        assert "axiom_compliance" in gov.last_veto_result.denied_by


# ── B. Guests — informed consent without friction ────────────────────────────


class TestGuestConsentLifecycle:
    """B1-B4: detection → grant/refuse/departure."""

    def test_b1_wife_walks_in_debounce_then_offer(self):
        """Debounce prevents premature consent prompt. One notification fires."""
        tracker = ConsentStateTracker(debounce_s=5.0)
        t = 100.0

        # t=0: guest detected, debouncing
        phase = tracker.tick(face_count=2, speaker_is_operator=True, now=t)
        assert phase == ConsentPhase.GUEST_DETECTED
        assert not tracker.persistence_allowed
        assert not tracker.needs_notification

        # t=2.5: still debouncing
        phase = tracker.tick(face_count=2, speaker_is_operator=True, now=t + 2.5)
        assert phase == ConsentPhase.GUEST_DETECTED

        # t=5.0: debounce satisfied → CONSENT_PENDING
        phase = tracker.tick(face_count=2, speaker_is_operator=True, now=t + 5.0)
        assert phase == ConsentPhase.CONSENT_PENDING
        assert not tracker.persistence_allowed

        # needs_notification fires exactly once
        assert tracker.needs_notification is True
        assert tracker.needs_notification is False  # second read returns False

        # t=7.5: still pending
        phase = tracker.tick(face_count=2, speaker_is_operator=True, now=t + 7.5)
        assert phase == ConsentPhase.CONSENT_PENDING
        assert not tracker.needs_notification  # no duplicate

    def test_b2_guest_grants_consent_unlock(self):
        """Consent granted → persistence allowed."""
        tracker = ConsentStateTracker(debounce_s=0.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=100.0)
        assert tracker.phase == ConsentPhase.CONSENT_PENDING

        tracker.grant_consent()
        assert tracker.phase == ConsentPhase.CONSENT_GRANTED
        assert tracker.persistence_allowed is True

    def test_b3_guest_says_no_immediate_no_guilt(self):
        """Consent refused → no persistence, no further notifications."""
        tracker = ConsentStateTracker(debounce_s=0.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=100.0)
        _ = tracker.needs_notification  # consume

        tracker.refuse_consent()
        assert tracker.phase == ConsentPhase.CONSENT_REFUSED
        assert not tracker.persistence_allowed
        # No further notifications
        assert not tracker.needs_notification

    def test_b4_guest_leaves_before_answering_auto_clear(self):
        """Guest departs during CONSENT_PENDING → auto-clear to NO_GUEST."""
        tracker = ConsentStateTracker(debounce_s=0.0, absence_clear_s=5.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=100.0)
        assert tracker.phase == ConsentPhase.CONSENT_PENDING

        # Guest leaves
        tracker.tick(face_count=1, speaker_is_operator=True, now=101.0)
        assert tracker.phase == ConsentPhase.CONSENT_PENDING  # absence timer started

        # Enough absence time passes
        tracker.tick(face_count=1, speaker_is_operator=True, now=106.0)
        assert tracker.phase == ConsentPhase.NO_GUEST


class TestGuestProtection:
    """B5-B6: children, transient presence."""

    def test_b5_child_present_heightened_protection(self):
        """Child name absent from output, persistence denied."""
        registry = _registry_with()  # empty — no contracts
        reader = _reader(registry)

        datum = RetrievedDatum(
            content="Timmy said he wants ice cream after school",
            person_ids=frozenset({"Timmy"}),
            data_category="perception",
            source="analyze_scene",
        )
        decision = reader.filter(datum)
        assert decision.degradation_level == 2
        assert "Timmy" not in decision.filtered_content

    def test_b6_delivery_person_transient_no_consent_needed(self):
        """Face appears and disappears before debounce — no consent prompt."""
        tracker = ConsentStateTracker(debounce_s=5.0)
        t = 100.0

        # Delivery person shows up
        tracker.tick(face_count=2, speaker_is_operator=True, now=t)
        assert tracker.phase == ConsentPhase.GUEST_DETECTED

        # Gone before debounce (t=2.5 < 5.0)
        tracker.tick(face_count=1, speaker_is_operator=True, now=t + 2.5)
        # Still in GUEST_DETECTED but absence timer started — NOT CONSENT_PENDING
        assert tracker.phase == ConsentPhase.GUEST_DETECTED
        assert not tracker.needs_notification


# ── C. Absent Third Parties — protection without erasure ─────────────────────


class TestAbsentThirdPartyProtection:
    """C1-C4: email, calendar, mixed consent, revocation."""

    def test_c1_coworker_in_email_name_abstracted(self):
        """Email address replaced, subject preserved."""
        registry = _registry_with()
        reader = _reader(registry)

        result = reader.filter_tool_result(
            "search_emails",
            "From: alice@corp.com | Subject: Q2 Budget Review",
        )
        assert "alice@corp.com" not in result
        assert "[someone at corp.com]" in result
        assert "Q2 Budget Review" in result

    def test_c2_calendar_participants_count_preserved_names_removed(self):
        """Participants abstracted to count, time/title preserved."""
        registry = _registry_with()
        reader = _reader(registry)

        result = reader.filter_tool_result(
            "get_calendar_today",
            "- 2026-03-15T10:00: Team sync (with Alice, Bob, charlie@corp.com)",
        )
        assert "Alice" not in result
        assert "Bob" not in result
        assert "charlie@corp.com" not in result
        assert "3 people" in result
        assert "Team sync" in result
        assert "10:00" in result

    def test_c3_mixed_consent_partial_access(self):
        """Alice consented stays, Bob unconsented is abstracted."""
        alice_contract = _contract("c-alice", "Alice", frozenset({"document"}))
        registry = _registry_with(alice_contract)
        reader = _reader(registry)

        datum = RetrievedDatum(
            content="Alice and Bob discussed the roadmap",
            person_ids=frozenset({"Alice", "Bob"}),
            data_category="document",
            source="search_documents",
        )
        decision = reader.filter(datum)
        assert decision.degradation_level == 2
        assert "Alice" in decision.filtered_content
        assert "Bob" not in decision.filtered_content
        assert "Someone" in decision.filtered_content or "someone" in decision.filtered_content

    def test_c4_revoked_consent_immediate_effect(self):
        """Revocation immediately changes degradation level."""
        alice_contract = _contract("c-alice", "Alice", frozenset({"document"}))
        registry = _registry_with(alice_contract)
        reader = _reader(registry)

        datum = RetrievedDatum(
            content="Alice proposed the new architecture",
            person_ids=frozenset({"Alice"}),
            data_category="document",
            source="search_documents",
        )

        # Before revocation — full access
        decision_before = reader.filter(datum)
        assert decision_before.degradation_level == 1
        assert "Alice" in decision_before.filtered_content

        # Revoke
        registry.purge_subject("Alice")

        # After revocation — abstracted
        decision_after = reader.filter(datum)
        assert decision_after.degradation_level == 2
        assert "Alice" not in decision_after.filtered_content


# ── D. Environmental Conditions ──────────────────────────────────────────────


class TestEnvironmentalAwareness:
    """D1-D3: music gate, plausibility rejection, operator override."""

    def test_d1_music_playing_dont_interrupt(self):
        """Gate ineligible when ambient detects music."""
        gate = _gate_with()
        # Simulate cached ambient result
        gate._ambient_result = MagicMock(interruptible=False, reason="Music detected")
        # Re-add ambient veto (we disabled it in _gate_with)
        from agents.hapax_voice.governance import Veto

        gate._veto_chain.add(Veto("ambient", predicate=gate._allow_ambient))
        result = gate.check()
        assert not result.eligible
        assert "music" in result.reason.lower()

    def test_d2_short_transcript_during_music_plausibility_rejection(self):
        """Short transcript during music is rejected as noise bleed-through."""
        # Build a minimal pipeline with mocked STT/TTS
        stt = AsyncMock()
        stt.transcribe = AsyncMock(return_value="yeah yeah")
        tts = MagicMock()

        ambient_result = MagicMock(
            interruptible=False,
            top_labels=[("Music", 0.8)],
        )

        pipeline = ConversationPipeline(
            stt=stt,
            tts_manager=tts,
            system_prompt="test",
            ambient_fn=lambda: ambient_result,
        )
        pipeline._running = True
        pipeline.state = ConvState.LISTENING
        pipeline.messages = [{"role": "system", "content": "test"}]
        # Prevent audio output attempts
        pipeline._audio_output = None

        asyncio.run(pipeline.process_utterance(b"\x00" * 100))
        # Should return to LISTENING without appending a message
        assert pipeline.state == ConvState.LISTENING
        assert len(pipeline.messages) == 1  # only system message

    def test_d3_full_sentence_during_music_operator_override(self):
        """Full sentence passes plausibility even during music."""
        stt = AsyncMock()
        stt.transcribe = AsyncMock(return_value="Hey Hapax turn the volume down please")
        tts = MagicMock()
        tts.synthesize = MagicMock(return_value=b"\x00" * 100)

        ambient_result = MagicMock(
            interruptible=False,
            top_labels=[("Music", 0.8)],
        )

        pipeline = ConversationPipeline(
            stt=stt,
            tts_manager=tts,
            system_prompt="test",
            ambient_fn=lambda: ambient_result,
        )
        pipeline._running = True
        pipeline.state = ConvState.LISTENING
        pipeline.messages = [{"role": "system", "content": "test"}]
        pipeline._audio_output = None

        # Mock the LLM call to avoid network

        async def _fake_generate(self_):
            self_.messages.append({"role": "assistant", "content": "Sure thing."})

        original = ConversationPipeline._generate_and_speak
        ConversationPipeline._generate_and_speak = _fake_generate
        try:
            asyncio.run(pipeline.process_utterance(b"\x00" * 100))
        finally:
            ConversationPipeline._generate_and_speak = original

        # Transcript should have been appended (plausibility passed: 7 words >= 4)
        user_msgs = [m for m in pipeline.messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert "volume down" in user_msgs[0]["content"]


# ── H. Hypothesis Properties (algebraic invariants) ──────────────────────────


class TestExperientialProperties:
    """H1-H5: algebraic invariants for governance properties."""

    @given(
        face_counts=st.lists(
            st.integers(min_value=0, max_value=5), min_size=5, max_size=20
        )
    )
    @settings(max_examples=50)
    def test_h1_consent_never_skips_pending(self, face_counts: list[int]):
        """CONSENT_GRANTED is unreachable from tick() alone."""
        tracker = ConsentStateTracker(debounce_s=0.0, absence_clear_s=1.0)
        t = 100.0
        for i, fc in enumerate(face_counts):
            tracker.tick(face_count=fc, speaker_is_operator=True, now=t + i * 0.5)
        # Without explicit grant_consent(), GRANTED should never appear
        assert tracker.phase != ConsentPhase.CONSENT_GRANTED

    @given(
        person=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=3,
            max_size=20,
        ),
        category=st.sampled_from(["email", "calendar", "document", "perception"]),
    )
    @settings(max_examples=50)
    def test_h2_unconsented_names_never_leak(self, person: str, category: str):
        """Unconsented person never appears in filtered content."""
        registry = _registry_with()
        reader = _reader(registry)
        content = f"{person} sent a message about the project"
        datum = RetrievedDatum(
            content=content,
            person_ids=frozenset({person}),
            data_category=category,
            source="test",
        )
        decision = reader.filter(datum)
        assert person not in decision.filtered_content

    @given(
        category=st.sampled_from(["email", "calendar", "document", "perception"]),
        content=st.text(min_size=1, max_size=100),
    )
    @settings(max_examples=50)
    def test_h3_operator_always_passes(self, category: str, content: str):
        """Operator person_ids always get degradation_level=1."""
        registry = _registry_with()
        reader = _reader(registry)
        datum = RetrievedDatum(
            content=content,
            person_ids=frozenset({"operator"}),
            data_category=category,
            source="test",
        )
        decision = reader.filter(datum)
        assert decision.degradation_level == 1

    @given(
        activity_mode=st.sampled_from(
            ["idle", "coding", "production", "meeting", "conversation", "unknown"]
        ),
        operator_present=st.booleans(),
        face_count=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=100)
    def test_h4_governor_always_valid_directive(
        self, activity_mode: str, operator_present: bool, face_count: int
    ):
        """Governor always returns one of the three valid directives."""
        gov = _governor()
        state = _state(
            activity_mode=activity_mode,
            operator_present=operator_present,
            face_count=face_count,
        )
        result = gov.evaluate(state)
        assert result in {"process", "pause", "withdraw"}

    @given(
        person=st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=2,
            max_size=15,
        ),
        category=st.sampled_from(["email", "calendar", "document", "default"]),
    )
    @settings(max_examples=50)
    def test_h5_degradation_is_idempotent(self, person: str, category: str):
        """Applying degradation twice yields the same result as once."""
        content = f"Message from {person} about the quarterly review"
        unconsented = frozenset({person})
        once = degrade(content, unconsented, category)
        twice = degrade(once, unconsented, category)
        assert once == twice

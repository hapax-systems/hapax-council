"""Consent state tracking for the voice daemon perception loop.

Tracks whether non-operator persons are present and whether consent
has been obtained. Composes into PipelineGovernor via a Veto that
blocks data persistence (not perception) when consent is unresolved.

State machine:
    NO_GUEST → GUEST_DETECTED (face_count >1 OR speaker_id != operator)
    GUEST_DETECTED → CONSENT_PENDING (sustained for debounce_s)
    CONSENT_PENDING → CONSENT_GRANTED (contract created)
    CONSENT_PENDING → CONSENT_REFUSED (guest declined)
    CONSENT_PENDING → NO_GUEST (guest left before resolution)
    CONSENT_GRANTED → NO_GUEST (guest left, contract persists)
    CONSENT_REFUSED → NO_GUEST (guest left)

The Veto fires during GUEST_DETECTED and CONSENT_PENDING states,
blocking persistence of person-adjacent data. Perception (face
detection, VAD, classification) continues — only storage is gated.

Uses existing composition primitives: Behavior[T], Veto, EventLog.
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class ConsentPhase(enum.Enum):
    """Current consent state for the perception session."""

    NO_GUEST = "no_guest"
    GUEST_DETECTED = "guest_detected"  # debouncing — transient presence
    CONSENT_PENDING = "consent_pending"  # sustained presence, awaiting consent
    CONSENT_GRANTED = "consent_granted"  # contract active
    CONSENT_REFUSED = "consent_refused"  # guest declined


@dataclass
class ConsentStateTracker:
    """Tracks non-operator presence and consent resolution.

    Called every perception tick (~2.5s). Manages debounce, state
    transitions, and event emission. Does NOT handle the consent
    offering itself — that's the channel system's job. This only
    tracks the state.

    The persistence_allowed property is the Veto predicate:
    True when persistence is safe, False when curtailment required.
    """

    debounce_s: float = 5.0  # sustained presence before triggering
    absence_clear_s: float = 30.0  # how long guest must be absent to clear

    # Internal state
    _phase: ConsentPhase = field(default=ConsentPhase.NO_GUEST)
    _guest_first_seen: float | None = field(default=None, repr=False)
    _guest_last_seen: float | None = field(default=None, repr=False)
    _guest_absent_since: float | None = field(default=None, repr=False)
    _event_log: object | None = field(default=None, repr=False)
    _notification_sent: bool = field(default=False, repr=False)

    @property
    def phase(self) -> ConsentPhase:
        return self._phase

    @property
    def persistence_allowed(self) -> bool:
        """True when person-adjacent data may be persisted.

        This is the Veto predicate for PipelineGovernor:
        - NO_GUEST: allowed (only operator data)
        - GUEST_DETECTED: denied (debouncing, might be transient)
        - CONSENT_PENDING: denied (waiting for consent)
        - CONSENT_GRANTED: allowed (contract active)
        - CONSENT_REFUSED: denied (guest present, no consent)
        """
        return self._phase in (ConsentPhase.NO_GUEST, ConsentPhase.CONSENT_GRANTED)

    def tick(
        self,
        face_count: int,
        speaker_is_operator: bool,
        *,
        now: float | None = None,
    ) -> ConsentPhase:
        """Update state based on current perception tick.

        Args:
            face_count: Number of faces detected this tick.
            speaker_is_operator: True if current speaker is identified as operator.
            now: Monotonic timestamp (for testing).

        Returns:
            Current consent phase after update.
        """
        t = now if now is not None else time.monotonic()
        guest_present = face_count > 1 or (not speaker_is_operator and face_count >= 1)

        if self._phase == ConsentPhase.NO_GUEST:
            if guest_present:
                self._guest_first_seen = t
                self._guest_last_seen = t
                self._guest_absent_since = None
                self._notification_sent = False
                # Check if debounce is already satisfied (e.g., debounce_s=0)
                if self.debounce_s <= 0:
                    self._phase = ConsentPhase.CONSENT_PENDING
                    self._emit("consent_pending", face_count=face_count)
                else:
                    self._phase = ConsentPhase.GUEST_DETECTED

        elif self._phase == ConsentPhase.GUEST_DETECTED:
            if guest_present:
                self._guest_last_seen = t
                self._guest_absent_since = None
                # Check debounce: sustained presence → pending
                if (
                    self._guest_first_seen is not None
                    and (t - self._guest_first_seen) >= self.debounce_s
                ):
                    self._phase = ConsentPhase.CONSENT_PENDING
                    self._emit("consent_pending", face_count=face_count)
            else:
                # Guest may have left — start absence timer
                if self._guest_absent_since is None:
                    self._guest_absent_since = t
                elif (t - self._guest_absent_since) >= self.absence_clear_s:
                    self._clear()

        elif self._phase == ConsentPhase.CONSENT_PENDING:
            if guest_present:
                self._guest_last_seen = t
                self._guest_absent_since = None
            else:
                if self._guest_absent_since is None:
                    self._guest_absent_since = t
                elif (t - self._guest_absent_since) >= self.absence_clear_s:
                    self._emit("guest_left_without_consent")
                    self._clear()

        elif self._phase == ConsentPhase.CONSENT_GRANTED:
            if not guest_present:
                if self._guest_absent_since is None:
                    self._guest_absent_since = t
                elif (t - self._guest_absent_since) >= self.absence_clear_s:
                    self._emit("guest_departed", phase="granted")
                    self._clear()
            else:
                self._guest_absent_since = None

        elif self._phase == ConsentPhase.CONSENT_REFUSED:
            if not guest_present:
                if self._guest_absent_since is None:
                    self._guest_absent_since = t
                elif (t - self._guest_absent_since) >= self.absence_clear_s:
                    self._emit("guest_departed", phase="refused")
                    self._clear()
            else:
                self._guest_absent_since = None

        return self._phase

    def grant_consent(self) -> None:
        """Called when consent is granted (contract created)."""
        if self._phase in (ConsentPhase.CONSENT_PENDING, ConsentPhase.GUEST_DETECTED):
            self._phase = ConsentPhase.CONSENT_GRANTED
            self._emit("consent_granted")

    def refuse_consent(self) -> None:
        """Called when consent is refused."""
        if self._phase in (ConsentPhase.CONSENT_PENDING, ConsentPhase.GUEST_DETECTED):
            self._phase = ConsentPhase.CONSENT_REFUSED
            self._emit("consent_refused")

    @property
    def needs_notification(self) -> bool:
        """True when the consent offering should be triggered.

        Returns True exactly once per consent-pending transition.
        """
        if self._phase == ConsentPhase.CONSENT_PENDING and not self._notification_sent:
            self._notification_sent = True
            return True
        return False

    def set_event_log(self, event_log: object) -> None:
        """Set event log for consent state change emissions."""
        self._event_log = event_log

    def _clear(self) -> None:
        """Reset to NO_GUEST."""
        self._phase = ConsentPhase.NO_GUEST
        self._guest_first_seen = None
        self._guest_last_seen = None
        self._guest_absent_since = None
        self._notification_sent = False

    def _emit(self, event_type: str, **kwargs) -> None:
        """Emit event to the voice daemon event log."""
        if self._event_log is not None:
            try:
                self._event_log.emit(event_type, **kwargs)
            except Exception:
                pass

"""Context gate for determining interrupt eligibility.

Uses VetoChain internally — each check is a Veto in a deny-wins chain.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from agents.hapax_voice.governance import Veto, VetoChain
from agents.hapax_voice.session import SessionManager

log = logging.getLogger(__name__)


@dataclass
class GateResult:
    """Result of a context gate check."""

    eligible: bool
    reason: str = ""


class ContextGate:
    """Layered gate that checks whether voice interrupts are appropriate.

    Checks (as vetoes, deny-wins):
        1. Active session
        2. Activity mode (production/meeting/conversation)
        3. Audio volume (wpctl)
        4. Studio MIDI activity (aconnect)
        5. Ambient audio classification (PANNs)
    """

    def __init__(
        self,
        session: SessionManager,
        volume_threshold: float = 0.7,
        ambient_classification: bool = True,
        ambient_block_threshold: float = 0.15,
    ) -> None:
        self.session = session
        self.volume_threshold = volume_threshold
        self.ambient_classification = ambient_classification
        self.ambient_block_threshold = ambient_block_threshold
        self._activity_mode: str = "unknown"
        self._event_log = None
        self._environment_state = None

        # Denial reasons stored during predicate evaluation
        self._denial_reasons: dict[str, str] = {}

        # Build veto chain
        self._veto_chain: VetoChain[None] = VetoChain(
            [
                Veto("session_active", predicate=self._allow_no_session),
                Veto("activity_mode", predicate=self._allow_activity_mode),
                Veto("volume", predicate=self._allow_volume),
                Veto("studio_midi", predicate=self._allow_studio),
            ]
        )
        if self.ambient_classification:
            self._veto_chain.add(Veto("ambient", predicate=self._allow_ambient))

    def set_activity_mode(self, mode: str) -> None:
        self._activity_mode = mode

    def set_event_log(self, event_log) -> None:
        self._event_log = event_log

    def set_environment_state(self, state) -> None:
        """Accept latest EnvironmentState from perception engine."""
        self._environment_state = state

    def check(self) -> GateResult:
        """Run layered checks and return eligibility result."""
        result = self._check_inner()
        if self._event_log is not None:
            self._event_log.emit(
                "gate_decision",
                eligible=result.eligible,
                reason=result.reason,
                activity_mode=self._activity_mode,
            )
        return result

    def _check_inner(self) -> GateResult:
        """Evaluate all vetoes and return gate result."""
        self._denial_reasons.clear()
        result = self._veto_chain.evaluate(None)
        if result.allowed:
            return GateResult(eligible=True)
        # Use the first denial's reason
        reason = self._denial_reasons.get(result.denied_by[0], result.denied_by[0])
        return GateResult(eligible=False, reason=reason)

    # ------------------------------------------------------------------
    # Veto predicates (True=allow, False=deny)
    # ------------------------------------------------------------------

    def _allow_no_session(self, _: None) -> bool:
        if self.session.is_active:
            self._denial_reasons["session_active"] = "Session active"
            return False
        return True

    def _allow_activity_mode(self, _: None) -> bool:
        if self._activity_mode in ("production", "meeting", "conversation"):
            self._denial_reasons["activity_mode"] = f"Blocked: {self._activity_mode} mode active"
            return False
        return True

    def _allow_volume(self, _: None) -> bool:
        volume = self._get_sink_volume()
        if volume is None:
            self._denial_reasons["volume"] = "Volume check unavailable (wpctl failed)"
            return False
        if volume >= self.volume_threshold:
            self._denial_reasons["volume"] = (
                f"Volume too high ({volume:.2f} >= {self.volume_threshold:.2f})"
            )
            return False
        return True

    def _allow_studio(self, _: None) -> bool:
        ok, reason = self._check_studio()
        if not ok:
            self._denial_reasons["studio_midi"] = reason
            return False
        return True

    def _allow_ambient(self, _: None) -> bool:
        ok, reason = self._check_ambient()
        if not ok:
            self._denial_reasons["ambient"] = reason
            return False
        return True

    # ------------------------------------------------------------------
    # Underlying checks (preserved from original implementation)
    # ------------------------------------------------------------------

    def _get_sink_volume(self) -> float | None:
        """Get default audio sink volume via wpctl.

        Returns None if wpctl is unavailable or fails, signalling the
        gate should block (fail-closed).
        """
        try:
            result = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Output format: "Volume: 0.50" or "Volume: 0.50 [MUTED]"
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                return float(parts[1])
        except Exception as exc:
            log.warning("Failed to get sink volume: %s", exc)
            if self._event_log is not None:
                self._event_log.emit("subprocess_failed", command="wpctl", error=str(exc))
        return None

    def _check_studio(self) -> tuple[bool, str]:
        """Check for active MIDI connections indicating studio use.

        Fails closed — if aconnect is unavailable, blocks interrupts.
        """
        try:
            result = subprocess.run(
                ["aconnect", "-l"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if stripped.startswith("Connecting To:") or stripped.startswith("Connected From:"):
                    if "Through" not in stripped:
                        return False, "MIDI connections active"
        except Exception as exc:
            log.warning("Failed to check MIDI connections: %s", exc)
            if self._event_log is not None:
                self._event_log.emit("subprocess_failed", command="aconnect", error=str(exc))
            return False, "MIDI check unavailable (aconnect failed)"
        return True, ""

    def _check_ambient(self) -> tuple[bool, str]:
        """Check ambient audio for music, speech, or other non-interruptible sounds.

        Uses PANNs (Pre-trained Audio Neural Networks) for AudioSet classification.
        Fails closed — if the model is unavailable or inference fails, blocks.
        """
        try:
            from agents.hapax_voice.ambient_classifier import classify

            result = classify(block_threshold=self.ambient_block_threshold)
            if not result.interruptible:
                return False, result.reason
            return True, ""
        except Exception as exc:
            log.warning("Ambient classification failed: %s", exc)
            return False, "Ambient classification unavailable (fail-closed)"

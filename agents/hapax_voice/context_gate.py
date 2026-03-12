"""Context gate for determining interrupt eligibility.

Uses VetoChain internally — each check is a Veto in a deny-wins chain.
Reads from Behaviors (via PerceptionEngine) instead of subprocess calls
where possible. Falls back to direct subprocess for backends not yet
registered.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from agents.hapax_voice.governance import Veto, VetoChain
from agents.hapax_voice.primitives import Behavior
from agents.hapax_voice.session import SessionManager

try:
    from agents.hapax_voice.watch_signals import is_stress_elevated
except ImportError:
    is_stress_elevated = None  # type: ignore[assignment]

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
        3. Audio volume (from Behavior or wpctl fallback)
        4. Studio MIDI activity (from Behavior or aconnect fallback)
        5. Ambient audio classification (PANNs)
        6. Stress elevated (watch EDA + HRV signals)

    Prefers reading from Behaviors (set via set_behaviors()) over
    subprocess calls. When no Behavior is available, falls back to
    direct subprocess (legacy path).
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

        # Behavior references (set by PerceptionEngine backends)
        self._behaviors: dict[str, Behavior] = {}

        # Denial reasons stored during predicate evaluation
        self._denial_reasons: dict[str, str] = {}

        # Known fullscreen/meeting apps where interrupts are inappropriate
        self._fullscreen_block_classes: set[str] = {
            "zoom",
            "us.zoom.xos",
            "microsoft teams",
            "org.jitsi.jitsi-meet",
            "discord",
            "slack huddle",
        }

        # Build veto chain
        self._veto_chain: VetoChain[None] = VetoChain(
            [
                Veto("session_active", predicate=self._allow_no_session),
                Veto("activity_mode", predicate=self._allow_activity_mode),
                Veto("fullscreen_app", predicate=self._allow_fullscreen_app),
                Veto("volume", predicate=self._allow_volume),
                Veto("studio_midi", predicate=self._allow_studio),
            ]
        )
        if self.ambient_classification:
            self._veto_chain.add(Veto("ambient", predicate=self._allow_ambient))
        if is_stress_elevated is not None:
            self._veto_chain.add(Veto("stress_elevated", predicate=self._allow_stress))

    def set_activity_mode(self, mode: str) -> None:
        self._activity_mode = mode

    def set_event_log(self, event_log) -> None:
        self._event_log = event_log

    def set_environment_state(self, state) -> None:
        """Accept latest EnvironmentState from perception engine."""
        self._environment_state = state

    def set_behaviors(self, behaviors: dict[str, Behavior]) -> None:
        """Set Behavior references from PerceptionEngine backends.

        When set, volume and MIDI checks read from Behaviors instead
        of calling subprocess directly.
        """
        self._behaviors = behaviors

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

    def _allow_fullscreen_app(self, _: None) -> bool:
        b = self._behaviors.get("active_window_class")
        if b is None:
            return True  # fail-open: activity_mode catches meetings via slow-tick
        window_class = str(b.value).lower()
        if window_class in self._fullscreen_block_classes:
            self._denial_reasons["fullscreen_app"] = (
                f"Blocked: fullscreen app '{b.value}'"
            )
            return False
        return True

    def _allow_volume(self, _: None) -> bool:
        volume = self._read_volume()
        if volume is None:
            self._denial_reasons["volume"] = "Volume check unavailable"
            return False
        if volume >= self.volume_threshold:
            self._denial_reasons["volume"] = (
                f"Volume too high ({volume:.2f} >= {self.volume_threshold:.2f})"
            )
            return False
        return True

    def _allow_studio(self, _: None) -> bool:
        midi_active = self._read_midi_active()
        if midi_active is None:
            self._denial_reasons["studio_midi"] = "MIDI check unavailable (fail-closed)"
            return False
        if midi_active:
            self._denial_reasons["studio_midi"] = "MIDI connections active"
            return False
        return True

    def _allow_ambient(self, _: None) -> bool:
        ok, reason = self._check_ambient()
        if not ok:
            self._denial_reasons["ambient"] = reason
            return False
        return True

    def _allow_stress(self, _: None) -> bool:
        if is_stress_elevated is not None and is_stress_elevated():
            self._denial_reasons["stress_elevated"] = "Stress elevated (HRV/EDA)"
            return False
        return True

    # ------------------------------------------------------------------
    # Behavior-first reads with subprocess fallback
    # ------------------------------------------------------------------

    def _read_volume(self) -> float | None:
        """Read sink volume from Behavior if available, else subprocess."""
        b = self._behaviors.get("sink_volume")
        if b is not None:
            return b.value

        # Fallback: direct subprocess
        try:
            result = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                return float(parts[1])
        except Exception as exc:
            log.warning("Failed to get sink volume: %s", exc)
            if self._event_log is not None:
                self._event_log.emit("subprocess_failed", command="wpctl", error=str(exc))
        return None

    def _read_midi_active(self) -> bool | None:
        """Read MIDI active state from Behavior if available, else subprocess."""
        b = self._behaviors.get("midi_active")
        if b is not None:
            return b.value

        # Fallback: direct subprocess
        try:
            result = subprocess.run(
                ["aconnect", "-l"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if stripped.startswith(("Connecting To:", "Connected From:")):
                    if "Through" not in stripped:
                        return True
            return False
        except Exception as exc:
            log.warning("Failed to check MIDI connections: %s", exc)
            if self._event_log is not None:
                self._event_log.emit("subprocess_failed", command="aconnect", error=str(exc))
        return None

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

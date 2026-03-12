"""Circadian perception backend — productive window alignment.

Reads energy_and_attention facts from the operator profile to determine
whether the current time falls within a peak productivity window, a
transition period, or a non-productive time.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior
from shared.config import PROFILES_DIR

log = logging.getLogger(__name__)

_OPERATOR_PROFILE_PATH = PROFILES_DIR / "operator-profile.json"


def _hour_in_range(hour: int, start: int, end: int) -> bool:
    """Check if hour is in [start, end) range, wrapping at midnight."""
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


class CircadianBackend:
    """PerceptionBackend that provides circadian alignment from operator profile.

    Provides:
      - circadian_alignment: float (0.1=peak, 0.3=transition, 0.8=non-productive)

    Default 0.5 (neutral) when no profile data is available.
    """

    def __init__(self, profile_path: Path | None = None) -> None:
        self._path = profile_path or _OPERATOR_PROFILE_PATH
        self._b_alignment: Behavior[float] = Behavior(0.5)
        self._peak_hours: list[int] = []
        self._transition_hours: list[int] = []
        self._loaded = False

    @property
    def name(self) -> str:
        return "circadian"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"circadian_alignment"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        return True  # Graceful degradation

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()
        if not self._loaded:
            self._load_profile()
        alignment = self._compute_alignment()
        self._b_alignment.update(alignment, now)
        behaviors["circadian_alignment"] = self._b_alignment

    def start(self) -> None:
        log.info("Circadian backend started (path=%s)", self._path)

    def stop(self) -> None:
        log.info("Circadian backend stopped")

    def _load_profile(self) -> None:
        """Load peak/transition hours from operator profile."""
        self._loaded = True
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            facts = data.get("facts", [])
            for fact in facts:
                if fact.get("dimension") != "energy_and_attention":
                    continue
                text = fact.get("text", "").lower()
                # Look for peak productivity hours
                if "peak" in text or "most productive" in text:
                    self._peak_hours.extend(self._extract_hours(text))
                elif "transition" in text or "wind" in text:
                    self._transition_hours.extend(self._extract_hours(text))
        except (json.JSONDecodeError, OSError):
            log.debug("Failed to load circadian profile")

    def _extract_hours(self, text: str) -> list[int]:
        """Extract hour values from profile text like '9am-12pm' or '09:00-12:00'."""
        import re

        hours: list[int] = []
        # Match patterns like "9am", "10pm", "14:00"
        for m in re.finditer(r"(\d{1,2})\s*(?::00)?\s*(am|pm)?", text):
            h = int(m.group(1))
            ampm = m.group(2)
            if ampm == "pm" and h < 12:
                h += 12
            elif ampm == "am" and h == 12:
                h = 0
            if 0 <= h <= 23:
                hours.append(h)
        return hours

    def _compute_alignment(self) -> float:
        """Compute alignment for current hour.

        Returns:
            0.1 for peak hours, 0.3 for transition, 0.8 for non-productive,
            0.5 when no profile data.
        """
        if not self._peak_hours and not self._transition_hours:
            return 0.5
        hour = datetime.now().hour
        if hour in self._peak_hours:
            return 0.1
        if self._transition_hours and hour in self._transition_hours:
            return 0.3
        # Hours adjacent to peak are transition
        for ph in self._peak_hours:
            if hour == (ph - 1) % 24 or hour == (ph + 1) % 24:
                return 0.3
        return 0.8

"""Stimmung state reader — polls /dev/shm for system mood."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gi.repository import GLib

STIMMUNG_PATH = Path("/dev/shm/hapax-stimmung/state.json")
VISUAL_LAYER_PATH = Path("/dev/shm/hapax-compositor/visual-layer-state.json")
PERCEPTION_PATH = Path.home() / ".cache" / "hapax-voice" / "perception-state.json"

_POLL_MS = 2000


class StimmungState:
    """Parsed stimmung state for the bar."""

    def __init__(self) -> None:
        self.stance: str = "nominal"
        self.dimensions: dict[str, dict[str, Any]] = {}
        self.voice_state: str = "off"
        self.voice_active: bool = False
        self.consent_phase: str = "no_guest"
        self.guest_present: bool = False
        self.recording: bool = False
        self.operator_stress: float = 0.0
        self.operator_energy: float = 0.7
        self.heart_rate: int = 0
        self.activity_label: str = "idle"
        self._callbacks: list = []

    def subscribe(self, callback: Any) -> None:
        self._callbacks.append(callback)

    def _notify(self) -> None:
        for cb in self._callbacks:
            cb(self)

    def start_polling(self) -> None:
        self._poll()
        GLib.timeout_add(_POLL_MS, self._poll)

    def _poll(self) -> bool:
        changed = False
        changed |= self._read_stimmung()
        changed |= self._read_visual_layer()
        if changed:
            self._notify()
        return GLib.SOURCE_CONTINUE

    def _read_stimmung(self) -> bool:
        try:
            data = json.loads(STIMMUNG_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return False

        new_stance = data.get("overall_stance", "nominal")
        new_dims: dict[str, dict[str, Any]] = {}
        for key, val in data.items():
            if isinstance(val, dict) and "value" in val:
                new_dims[key] = val

        changed = new_stance != self.stance or new_dims != self.dimensions
        self.stance = new_stance
        self.dimensions = new_dims

        stress = new_dims.get("operator_stress", {})
        energy = new_dims.get("operator_energy", {})
        self.operator_stress = stress.get("value", 0.0) if stress else 0.0
        self.operator_energy = energy.get("value", 0.7) if energy else 0.7
        return changed

    def _read_visual_layer(self) -> bool:
        try:
            data = json.loads(VISUAL_LAYER_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return False

        vs = data.get("voice_session", {})
        bio = data.get("biometrics", {})

        new_voice_state = vs.get("state", "off")
        new_voice_active = vs.get("active", False)
        new_activity = data.get("activity_label", "idle")
        new_consent = "no_guest"
        new_guest = False

        try:
            perc = json.loads(PERCEPTION_PATH.read_text())
            new_consent = perc.get("consent_phase", "no_guest")
            new_guest = perc.get("guest_present", False)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        self.heart_rate = bio.get("heart_rate_bpm", 0)

        changed = (
            new_voice_state != self.voice_state
            or new_voice_active != self.voice_active
            or new_activity != self.activity_label
            or new_consent != self.consent_phase
            or new_guest != self.guest_present
        )

        self.voice_state = new_voice_state
        self.voice_active = new_voice_active
        self.activity_label = new_activity
        self.consent_phase = new_consent
        self.guest_present = new_guest
        self.recording = new_consent == "recording"
        return changed

    def dimension_value(self, name: str) -> float:
        return self.dimensions.get(name, {}).get("value", 0.0)

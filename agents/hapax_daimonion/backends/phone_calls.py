"""Phone call handling via PipeWire Telephony API (HFP).

Monitors for incoming calls, provides call state to the voice pipeline.
Enables voice commands: "answer that", "hang up", "reject".

Uses org.pipewire.Telephony DBus interface (oFono-compatible).

Provides:
  - phone_call_active: bool (call in progress)
  - phone_call_incoming: bool (ringing, not yet answered)
  - phone_call_number: str (caller number if available)
"""

from __future__ import annotations

import logging
import subprocess
import time

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior

log = logging.getLogger(__name__)

_TELEPHONY_BUS = "org.pipewire.Telephony"
_TELEPHONY_PATH = "/org/pipewire/Telephony"


def _get_call_state() -> dict:
    """Read current call state from PipeWire Telephony API."""
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION)

        # Get managed objects (includes active calls)
        result = bus.call_sync(
            _TELEPHONY_BUS,
            _TELEPHONY_PATH,
            "org.freedesktop.DBus.ObjectManager",
            "GetManagedObjects",
            None,
            GLib.VariantType("(a{oa{sa{sv}}})"),
            Gio.DBusCallFlags.NONE,
            3000,
            None,
        )

        objects = result.unpack()[0]
        for path, ifaces in objects.items():
            # Look for VoiceCall interface (active call)
            if "org.ofono.VoiceCall" in ifaces:
                call = ifaces["org.ofono.VoiceCall"]
                return {
                    "active": True,
                    "state": str(call.get("State", "unknown")),
                    "number": str(call.get("LineIdentification", "")),
                    "name": str(call.get("Name", "")),
                    "path": str(path),
                }

        return {"active": False, "state": "idle", "number": "", "name": "", "path": ""}

    except Exception:
        return {"active": False, "state": "idle", "number": "", "name": "", "path": ""}


def answer_call() -> bool:
    """Answer an incoming call."""
    state = _get_call_state()
    if not state["active"] or state["state"] != "incoming":
        return False
    try:
        from gi.repository import Gio

        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        bus.call_sync(
            _TELEPHONY_BUS,
            state["path"],
            "org.ofono.VoiceCall",
            "Answer",
            None,
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        )
        log.info("Phone call answered: %s", state["number"])
        return True
    except Exception as e:
        log.warning("Failed to answer call: %s", e)
        return False


def hangup_call() -> bool:
    """Hang up the current call."""
    state = _get_call_state()
    if not state["active"]:
        return False
    try:
        from gi.repository import Gio

        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        bus.call_sync(
            _TELEPHONY_BUS,
            state["path"],
            "org.ofono.VoiceCall",
            "Hangup",
            None,
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        )
        log.info("Phone call hung up: %s", state["number"])
        return True
    except Exception as e:
        log.warning("Failed to hang up: %s", e)
        return False


class PhoneCallsBackend:
    """PerceptionBackend monitoring phone call state via PipeWire Telephony."""

    def __init__(self) -> None:
        self._b_active: Behavior[bool] = Behavior(False)
        self._b_incoming: Behavior[bool] = Behavior(False)
        self._b_number: Behavior[str] = Behavior("")

    @property
    def name(self) -> str:
        return "phone_calls"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"phone_call_active", "phone_call_incoming", "phone_call_number"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST  # call state needs fast polling

    def available(self) -> bool:
        try:
            result = subprocess.run(
                ["busctl", "--user", "list"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return "org.pipewire.Telephony" in result.stdout
        except Exception:
            return False

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()
        state = _get_call_state()

        self._b_active.update(state["active"], now)
        self._b_incoming.update(state["state"] == "incoming", now)
        self._b_number.update(state["number"] or state["name"], now)

        behaviors["phone_call_active"] = self._b_active
        behaviors["phone_call_incoming"] = self._b_incoming
        behaviors["phone_call_number"] = self._b_number

    def start(self) -> None:
        state = _get_call_state()
        log.info("Phone calls backend started (state: %s)", state["state"])

    def stop(self) -> None:
        log.info("Phone calls backend stopped")

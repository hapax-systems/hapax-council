"""Phone messages perception backend — SMS count via busctl/OBEX MAP.

Provides unread SMS count. MAP access is expensive so polls infrequently.
Falls back gracefully if MAP session fails.

Provides:
  - phone_sms_unread: int
  - phone_sms_latest_sender: str
  - phone_sms_latest_text: str
"""

from __future__ import annotations

import json
import logging
import subprocess
import time

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)

_PHONE_MAC = "B0:D5:FB:A5:86:E8"


def _read_sms_via_script() -> list[dict]:
    """Read SMS inbox via a helper script that uses gi (system Python)."""
    try:
        result = subprocess.run(
            [
                "/usr/bin/python3",
                "-c",
                """
import json
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION)
try:
    r = bus.call_sync('org.bluez.obex', '/org/bluez/obex',
        'org.bluez.obex.Client1', 'CreateSession',
        GLib.Variant('(sa{sv})', ('"""
                + _PHONE_MAC
                + """', {'Target': GLib.Variant('s', 'map')})),
        GLib.VariantType('(o)'), Gio.DBusCallFlags.NONE, 10000, None)
    mp = r.unpack()[0]
    bus.call_sync('org.bluez.obex', mp, 'org.bluez.obex.MessageAccess1',
        'SetFolder', GLib.Variant('(s)', ('telecom/msg/inbox',)),
        None, Gio.DBusCallFlags.NONE, 10000, None)
    r2 = bus.call_sync('org.bluez.obex', mp, 'org.bluez.obex.MessageAccess1',
        'ListMessages', GLib.Variant('(sa{sv})', ('', {'MaxCount': GLib.Variant('q', 5)})),
        GLib.VariantType('(a{oa{sv}})'), Gio.DBusCallFlags.NONE, 10000, None)
    msgs = []
    for p, props in r2.unpack()[0].items():
        msgs.append({'sender': str(props.get('Sender','')), 'subject': str(props.get('Subject','')),'read': bool(props.get('Read', True))})
    print(json.dumps(msgs))
except Exception as e:
    print(json.dumps([]))
""",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
    except Exception:
        pass
    return []


class PhoneMessagesBackend:
    """PerceptionBackend that reads SMS via MAP (system Python subprocess)."""

    def __init__(self) -> None:
        self._b_unread: Behavior[int] = Behavior(0)
        self._b_latest_sender: Behavior[str] = Behavior("")
        self._b_latest_text: Behavior[str] = Behavior("")
        self._last_poll: float = 0.0
        self._poll_interval: float = 60.0  # MAP is expensive

    @property
    def name(self) -> str:
        return "phone_messages"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"phone_sms_unread", "phone_sms_latest_sender", "phone_sms_latest_text"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        # Check if obex service is running
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", "obex.service"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return result.stdout.strip() == "active"
        except Exception:
            return False

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()
        if now - self._last_poll < self._poll_interval:
            behaviors["phone_sms_unread"] = self._b_unread
            behaviors["phone_sms_latest_sender"] = self._b_latest_sender
            behaviors["phone_sms_latest_text"] = self._b_latest_text
            return

        self._last_poll = now
        messages = _read_sms_via_script()
        if messages:
            unread = sum(1 for m in messages if not m.get("read", True))
            latest = messages[0]
            self._b_unread.update(unread, now)
            self._b_latest_sender.update(latest.get("sender", ""), now)
            self._b_latest_text.update(latest.get("subject", "")[:80], now)

        behaviors["phone_sms_unread"] = self._b_unread
        behaviors["phone_sms_latest_sender"] = self._b_latest_sender
        behaviors["phone_sms_latest_text"] = self._b_latest_text

    def start(self) -> None:
        log.info("Phone messages backend started (poll every %.0fs)", self._poll_interval)

    def stop(self) -> None:
        log.info("Phone messages backend stopped")

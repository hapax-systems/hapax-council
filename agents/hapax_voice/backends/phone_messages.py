"""Phone messages perception backend — SMS via Bluetooth MAP.

Reads SMS inbox from paired phone via BlueZ OBEX Message Access Profile.
Provides unread count and latest message info for voice notification.

Requires: obex.service running, phone BT paired with MAP authorized.

Provides:
  - phone_sms_unread: int (unread message count)
  - phone_sms_latest_sender: str (most recent message sender)
  - phone_sms_latest_text: str (most recent message preview)
"""

from __future__ import annotations

import logging
import time

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)

_PHONE_MAC = "B0:D5:FB:A5:86:E8"


def _read_sms_inbox(max_count: int = 10) -> list[dict]:
    """Read SMS inbox via BlueZ OBEX MAP."""
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION)

        # Create MAP session
        result = bus.call_sync(
            "org.bluez.obex",
            "/org/bluez/obex",
            "org.bluez.obex.Client1",
            "CreateSession",
            GLib.Variant("(sa{sv})", (_PHONE_MAC, {"Target": GLib.Variant("s", "map")})),
            GLib.VariantType("(o)"),
            Gio.DBusCallFlags.NONE,
            10000,
            None,
        )
        map_path = result.unpack()[0]

        # Navigate to inbox
        bus.call_sync(
            "org.bluez.obex",
            map_path,
            "org.bluez.obex.MessageAccess1",
            "SetFolder",
            GLib.Variant("(s)", ("telecom/msg/inbox",)),
            None,
            Gio.DBusCallFlags.NONE,
            10000,
            None,
        )

        # List messages
        result2 = bus.call_sync(
            "org.bluez.obex",
            map_path,
            "org.bluez.obex.MessageAccess1",
            "ListMessages",
            GLib.Variant("(sa{sv})", ("", {"MaxCount": GLib.Variant("q", max_count)})),
            GLib.VariantType("(a{oa{sv}})"),
            Gio.DBusCallFlags.NONE,
            10000,
            None,
        )

        messages = []
        for _path, props in result2.unpack()[0].items():
            messages.append(
                {
                    "sender": str(props.get("Sender", "")),
                    "subject": str(props.get("Subject", "")),
                    "timestamp": str(props.get("Timestamp", "")),
                    "read": bool(props.get("Read", True)),
                }
            )

        # Clean up session
        try:
            bus.call_sync(
                "org.bluez.obex",
                map_path,
                "org.bluez.obex.Session1",
                "Close",
                None,
                None,
                Gio.DBusCallFlags.NONE,
                3000,
                None,
            )
        except Exception:
            pass

        return messages

    except Exception as e:
        log.debug("SMS read failed: %s", e)
        return []


class PhoneMessagesBackend:
    """PerceptionBackend that reads SMS via Bluetooth MAP."""

    def __init__(self) -> None:
        self._b_unread: Behavior[int] = Behavior(0)
        self._b_latest_sender: Behavior[str] = Behavior("")
        self._b_latest_text: Behavior[str] = Behavior("")
        self._last_poll: float = 0.0
        self._poll_interval: float = 30.0  # check every 30s (MAP is expensive)

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
        try:
            from gi.repository import Gio  # noqa: F401

            return True
        except ImportError:
            return False

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()

        # Rate limit MAP polling (expensive BT operation)
        if now - self._last_poll < self._poll_interval:
            behaviors["phone_sms_unread"] = self._b_unread
            behaviors["phone_sms_latest_sender"] = self._b_latest_sender
            behaviors["phone_sms_latest_text"] = self._b_latest_text
            return

        self._last_poll = now
        messages = _read_sms_inbox(max_count=10)

        if messages:
            unread = sum(1 for m in messages if not m["read"])
            latest = messages[0]  # most recent
            self._b_unread.update(unread, now)
            self._b_latest_sender.update(latest["sender"], now)
            self._b_latest_text.update(latest["subject"][:80], now)
        else:
            self._b_unread.update(0, now)

        behaviors["phone_sms_unread"] = self._b_unread
        behaviors["phone_sms_latest_sender"] = self._b_latest_sender
        behaviors["phone_sms_latest_text"] = self._b_latest_text

    def start(self) -> None:
        messages = _read_sms_inbox(max_count=3)
        if messages:
            unread = sum(1 for m in messages if not m["read"])
            log.info(
                "Phone messages backend started (%d messages, %d unread)",
                len(messages),
                unread,
            )
        else:
            log.info("Phone messages backend started (no access or no messages)")

    def stop(self) -> None:
        log.info("Phone messages backend stopped")

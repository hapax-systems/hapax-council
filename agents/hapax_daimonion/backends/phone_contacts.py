"""Phone contacts cache via Bluetooth PBAP.

Pulls phonebook from paired phone, caches as JSON for name lookup.
Used by phone_messages backend to resolve sender numbers to names.

Cache: ~/.cache/hapax-daimonion/contacts.json
Refresh: on daemon startup + every 24h
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

_PHONE_MAC = "B0:D5:FB:A5:86:E8"
_CACHE_PATH = Path.home() / ".cache" / "hapax-daimonion" / "contacts.json"
_CACHE_MAX_AGE_S = 86400  # 24 hours


def pull_contacts() -> dict[str, str]:
    """Pull phonebook from phone via PBAP. Returns {handle: name}."""
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION)

        result = bus.call_sync(
            "org.bluez.obex",
            "/org/bluez/obex",
            "org.bluez.obex.Client1",
            "CreateSession",
            GLib.Variant("(sa{sv})", (_PHONE_MAC, {"Target": GLib.Variant("s", "pbap")})),
            GLib.VariantType("(o)"),
            Gio.DBusCallFlags.NONE,
            15000,
            None,
        )
        pbap = result.unpack()[0]

        # Select phone's internal phonebook
        bus.call_sync(
            "org.bluez.obex",
            pbap,
            "org.bluez.obex.PhonebookAccess1",
            "Select",
            GLib.Variant("(ss)", ("int", "pb")),
            None,
            Gio.DBusCallFlags.NONE,
            10000,
            None,
        )

        # Get size
        size_result = bus.call_sync(
            "org.bluez.obex",
            pbap,
            "org.bluez.obex.PhonebookAccess1",
            "GetSize",
            None,
            GLib.VariantType("(q)"),
            Gio.DBusCallFlags.NONE,
            10000,
            None,
        )
        total = size_result.unpack()[0]
        log.info("PBAP: %d contacts on phone", total)

        # Pull all — returns vCard data as a file transfer
        # For simplicity, use List which returns (handle, name) tuples
        contacts = {}
        offset = 0
        batch = 100
        while offset < total:
            result3 = bus.call_sync(
                "org.bluez.obex",
                pbap,
                "org.bluez.obex.PhonebookAccess1",
                "List",
                GLib.Variant(
                    "(a{sv})",
                    (
                        {
                            "Offset": GLib.Variant("q", offset),
                            "MaxCount": GLib.Variant("q", batch),
                        },
                    ),
                ),
                GLib.VariantType("(a(ss))"),
                Gio.DBusCallFlags.NONE,
                15000,
                None,
            )
            entries = result3.unpack()[0]
            if not entries:
                break
            for handle, name in entries:
                if name:
                    contacts[handle] = name
            offset += len(entries)

        # Clean up
        try:
            bus.call_sync(
                "org.bluez.obex",
                pbap,
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

        return contacts

    except Exception as e:
        log.warning("PBAP pull failed: %s", e)
        return {}


def save_cache(contacts: dict[str, str]) -> None:
    """Save contacts cache to disk."""
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(contacts, indent=2), encoding="utf-8")
    log.info("Contacts cache saved: %d entries", len(contacts))


def load_cache() -> dict[str, str]:
    """Load contacts from cache if fresh enough."""
    if not _CACHE_PATH.exists():
        return {}
    age = time.time() - _CACHE_PATH.stat().st_mtime
    if age > _CACHE_MAX_AGE_S:
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def refresh_if_stale() -> dict[str, str]:
    """Refresh cache if stale, otherwise return cached contacts."""
    cached = load_cache()
    if cached:
        return cached
    contacts = pull_contacts()
    if contacts:
        save_cache(contacts)
    return contacts

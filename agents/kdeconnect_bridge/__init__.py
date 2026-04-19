"""Task #141 — KDEConnect phone-push bridge.

Interim control surface bridging KDEConnect "send text" messages from
the operator's paired phone to the council command registry. Fills the
gap until the physical Stream Deck is ready.

The bridge is structured around three seams to keep it test-friendly
and to degrade gracefully when hardware/IPC is absent:

* ``MessageSource`` — yields inbound text payloads (defaults to a
  subprocess wrapper over ``kdeconnect-cli``; tests inject a fake).
* ``CommandDispatcher`` — async ``(command, args) -> None`` that posts
  to the Tauri command-relay WebSocket at ``ws://localhost:8052``.
* ``AckSender`` — optional ``(message) -> None`` echo back to the
  phone via ``kdeconnect-cli``.

If ``kdeconnect-cli`` is not on ``PATH`` the bridge logs a single
warning and exits cleanly (systemd ``Restart=on-failure`` will not
flap because exit code is 0).
"""

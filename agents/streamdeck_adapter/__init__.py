"""LRR Phase 8 item 6 — Stream Deck adapter.

Thin bridge from a physical Stream Deck key press to a command-registry
dispatch over the Tauri WebSocket relay (``ws://localhost:8052``). The
adapter owns no compositor / studio state of its own — every button
press resolves to a single ``(command, args)`` pair loaded from
``config/streamdeck.yaml`` and forwarded verbatim.

Hardware is operator-dependent; the module is structured with injection
seams (``device_opener`` + ``command_dispatcher``) so tests do not
require the ``streamdeck`` Python library or a plugged-in device, and
so the systemd unit can sit idle-without-hardware without crash-looping.
"""

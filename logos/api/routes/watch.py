"""Watch and phone companion receiver routes mounted on Logos API.

The watch receiver also runs as a standalone service on port 8042 for legacy
clients. Mounting the same router here lets current companion apps POST
biometric data to the canonical Logos API on port 8051.
"""

from __future__ import annotations

from agents.watch_receiver import create_router

router = create_router()

"""``python -m agents.audio_signal_assertion`` entrypoint.

Forwards to :func:`agents.audio_signal_assertion.daemon.main` so the
systemd unit can launch the daemon with ``uv run python -m
agents.audio_signal_assertion`` per the workspace convention.
"""

from __future__ import annotations

from agents.audio_signal_assertion.daemon import main

if __name__ == "__main__":
    raise SystemExit(main())

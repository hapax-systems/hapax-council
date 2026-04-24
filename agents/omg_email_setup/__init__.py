"""omg.lol email-forwarding setup — ytb-OMG5 Phase A.

Thin CLI around :meth:`OmgLolClient.set_email` / :meth:`get_email` for
one-shot operator configuration of ``hapax@omg.lol`` → operator inbox
forwarding. External-account creation (Bluesky, Mastodon, Are.na,
Neocities) is Phase B and is genuinely operator work — no agent
automation possible without platform-side OAuth, which is a separate
workstream.

Usage:
    uv run python -m agents.omg_email_setup set <forward-to-address>
    uv run python -m agents.omg_email_setup show
"""

from agents.omg_email_setup.setup import configure_email_forwarding, main

__all__ = ["configure_email_forwarding", "main"]

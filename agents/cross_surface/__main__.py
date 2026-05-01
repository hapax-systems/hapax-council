"""Daemon entry — `python -m agents.cross_surface` — RETIRED.

The cross-surface daemon's only inhabitant was the Discord webhook poster,
which was retired 2026-05-01 per cc-task
``discord-public-event-activation-or-retire``. Constitutional refusal:
``docs/refusal-briefs/leverage-discord-community.md`` (single-operator
axiom + full-automation envelope).

Running this module now exits non-zero with a refusal message. The systemd
unit ``hapax-discord-webhook.service`` was decommissioned at the same
time and added to the install-units ``DECOMMISSIONED_UNITS`` list, so
no production caller should reach this entrypoint. Manual invocation
(e.g. operator running ``python -m agents.cross_surface``) lands here
as a guard against accidentally restarting the retired daemon.
"""

from __future__ import annotations

import sys

REFUSAL_MESSAGE = (
    "agents.cross_surface entry refused: discord-webhook surface retired "
    "2026-05-01 per cc-task discord-public-event-activation-or-retire. "
    "See docs/refusal-briefs/leverage-discord-community.md for the "
    "constitutional grounds. To lift the refusal, follow the lift sequence "
    "in agents/cross_surface/discord_webhook.py module docstring."
)


if __name__ == "__main__":
    print(REFUSAL_MESSAGE, file=sys.stderr)
    sys.exit(2)

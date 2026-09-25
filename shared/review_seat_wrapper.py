"""Common parts of the read-only substitute reviewer wrappers (muse, vibe, local).

Each wrapper reads the dispatcher's reviewer prompt on stdin and prints the reviewer's reply
on stdout. The dispatcher parses that reply's yaml fence and owns the verdict.

When a wrapper refuses to run a seat, it prints a line containing ``UNSUPPORTED_CLIENT`` and
exits nonzero. That is the process-level signal ``review_team.is_reviewer_route_unavailable``
reads, so a refusal is classified as the route's outage. It is never read as the model's
output, and never as a vote.
"""

from __future__ import annotations

import sys

ROUTE_UNAVAILABLE_EXIT = 69

SEAT_PREAMBLE = """You are a blind reviewer seat invoked non-interactively. Review ONLY the text below.
Do not use tools, read files, browse, or narrate your process; reason silently.
Your entire reply must be exactly one fenced yaml code block that follows the output contract
at the end of the text, and nothing else. A verdict that contradicts your own findings (for
example accept alongside a critical finding) is wrong: a critical finding requires block."""


def refuse(wrapper: str, reason: str) -> int:
    """Refuse the seat as an outage of this route, with the reason and the next action."""

    print(f"{wrapper}: UNSUPPORTED_CLIENT {reason}", file=sys.stderr)
    return ROUTE_UNAVAILABLE_EXIT

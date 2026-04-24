"""omg.lol /statuslog autonomous poster — ytb-OMG4.

Subscribes to high-salience chronicle events, debounces + rate-limits,
walks the publication allowlist, composes a short literary status
via the LLM, and posts to hapax.omg.lol/statuses. Operator-name
leaks are blocked by the allowlist's redaction list AND the referent
picker (which never emits legal name).

Max 3 posts/day; min 4h between posts; salience floor 0.75.
"""

from agents.omg_statuslog_poster.poster import (
    StatuslogPoster,
)

__all__ = ["StatuslogPoster"]

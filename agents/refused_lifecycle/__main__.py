"""One-shot refused-lifecycle tick: ``uv run python -m agents.refused_lifecycle``.

Reads REFUSED tasks from the active vault directory, runs one evaluation
pass with no probes (conservative re-affirm default), and prints a JSON
summary. Probe dispatch is wired in by Phase 3 watcher cc-tasks.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from agents.refused_lifecycle.runner import tick


def main() -> int:
    now = datetime.now(UTC)
    events = tick(now)
    summary = {
        "tick_at": now.isoformat(),
        "transitions": [
            {
                "slug": e.cc_task_slug,
                "from": e.from_state,
                "to": e.to_state,
                "transition": e.transition,
                "reason": e.reason,
            }
            for e in events
        ],
        "count": len(events),
    }
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

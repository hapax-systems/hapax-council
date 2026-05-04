"""Completion predicates for the programme manager.

Each predicate is a ``Callable[[Programme, dict], bool]`` that returns
True when its condition is met. The ``dict`` argument carries runtime
context from the daemon (currently empty; placeholder for perception
state, chat signals, etc.).

The ``DEFAULT_COMPLETION_PREDICATES`` registry is loaded by
``programme_loop._build_manager()`` alongside the abort predicates.
Unknown predicates now default to True (see manager construction)
so the planner's emitted predicate names don't block transitions
when the runtime doesn't implement them yet.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.programme import Programme

log = logging.getLogger(__name__)


def duration_elapsed(programme: Programme, _context: dict) -> bool:
    """True when the programme has run at least ``planned_duration_s``."""
    if programme.actual_started_at is None:
        return False
    elapsed = time.time() - programme.actual_started_at
    return elapsed >= programme.planned_duration_s


def always_true(_programme: Programme, _context: dict) -> bool:
    """Trivial predicate — always satisfied. Use as a no-op gate."""
    return True


# Default registry wired by _build_manager().
DEFAULT_COMPLETION_PREDICATES: dict[str, object] = {
    "duration_elapsed": duration_elapsed,
    "always_true": always_true,
    # operator_speaks_3_times — not yet implemented; will default to
    # True via unknown_predicate_satisfies=True in the manager constructor
    # so programmes don't get stuck.
}

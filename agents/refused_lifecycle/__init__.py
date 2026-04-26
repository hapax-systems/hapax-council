"""Refused-lifecycle state machine (REFUSED ↔ ACCEPTED ↔ REMOVED).

Phase 1 substrate: pure decision logic + atomic frontmatter rewrite.
Phase 2 (separate cc-tasks) wires probe watchers and refusal-brief log
emission. See `docs/research/2026-04-25-refused-lifecycle-pipeline.md`.
"""

from agents.refused_lifecycle.evaluator import decide_transition
from agents.refused_lifecycle.runner import (
    DEFAULT_ACTIVE_DIR,
    apply_transition,
    iter_refused_tasks,
    parse_frontmatter,
    tick,
    transitions_total,
)
from agents.refused_lifecycle.state import (
    ProbeResult,
    RefusalHistoryEntry,
    RefusalTask,
    RemovalSignal,
    TransitionEvent,
    TransitionKind,
    TriggerCategory,
)

__all__ = [
    "DEFAULT_ACTIVE_DIR",
    "ProbeResult",
    "RefusalHistoryEntry",
    "RefusalTask",
    "RemovalSignal",
    "TransitionEvent",
    "TransitionKind",
    "TriggerCategory",
    "apply_transition",
    "decide_transition",
    "iter_refused_tasks",
    "parse_frontmatter",
    "tick",
    "transitions_total",
]

"""logos/engine/rules.py — Rule registry and evaluation.

Ships empty in Phase A — rules are registered in Phase B.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from logos.engine.models import Action, ActionPlan, ChangeEvent

_log = logging.getLogger(__name__)


@dataclass
class Rule:
    """A reactive rule that maps filesystem events to actions."""

    name: str
    description: str
    trigger_filter: Callable[[ChangeEvent], bool]
    produce: Callable[[ChangeEvent], list[Action]]
    phase: int = 0
    cooldown_s: float = 0
    _last_fired: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class RuleRegistry:
    """Registry of named rules. Last registration wins on name collision."""

    def __init__(self) -> None:
        self._rules: dict[str, Rule] = {}

    def register(self, rule: Rule) -> None:
        """Register a rule. Overwrites any existing rule with the same name."""
        self._rules[rule.name] = rule

    def unregister(self, name: str) -> None:
        """Remove a rule by name. No-op if not found."""
        self._rules.pop(name, None)

    def __iter__(self):
        return iter(self._rules.values())

    def __len__(self) -> int:
        return len(self._rules)

    def get(self, name: str) -> Rule | None:
        return self._rules.get(name)


def evaluate_rules(event: ChangeEvent, registry: RuleRegistry) -> ActionPlan:
    """Evaluate all rules against an event and return a deduplicated ActionPlan."""
    plan = ActionPlan()
    seen_names: set[str] = set()

    for rule in registry:
        # Check cooldown under lock (pure in-memory check)
        with rule._lock:
            if rule.cooldown_s > 0:
                elapsed = time.monotonic() - rule._last_fired
                if elapsed < rule.cooldown_s:
                    _log.debug(
                        "Rule %s skipped (cooldown: %.1fs remaining)",
                        rule.name,
                        rule.cooldown_s - elapsed,
                    )
                    continue

        # I/O outside lock — trigger_filter and produce may read filesystem
        try:
            if not rule.trigger_filter(event):
                continue
        except (ValueError, KeyError, TypeError, OSError):
            _log.exception("Exception in trigger_filter for rule %s", rule.name)
            continue

        try:
            actions = rule.produce(event)
        except (ValueError, KeyError, TypeError, OSError):
            _log.exception("Exception in produce for rule %s", rule.name)
            # Update cooldown even on failure to prevent unbounded retry
            with rule._lock:
                rule._last_fired = time.monotonic()
            continue

        # Update cooldown after successful production
        with rule._lock:
            rule._last_fired = time.monotonic()

        for action in actions:
            if action.name not in seen_names:
                seen_names.add(action.name)
                plan.actions.append(action)

    return plan

"""Operator profile integration — loading, caching, accessors."""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field, ValidationError

from .config import PROFILES_DIR

log = logging.getLogger("drift_detector.operator")

_operator_cache: dict | None = None


class OperatorSchema(BaseModel, extra="allow"):
    """Minimal validation for operator.json top-level structure."""

    version: int | str = 0
    operator: dict = Field(default_factory=dict)


SYSTEM_CONTEXT = """\
System: Externalized executive function infrastructure for a single operator.

The operator has ADHD and autism -- task initiation, sustained attention, and \
routine maintenance are genuine cognitive challenges. This system offloads \
cognitive overhead, maintains continuity, monitors health autonomously, and \
surfaces what needs attention. Behavioral variance is expected baseline.

You are a component of this system. Use your context tools to look up operator \
constraints, patterns, and profile facts when needed.\
"""


def _load_operator() -> dict:
    """Load and cache operator.json."""
    global _operator_cache
    if _operator_cache is not None:
        return _operator_cache

    path = PROFILES_DIR / "operator.json"
    if not path.exists():
        _operator_cache = {}
        return _operator_cache

    try:
        raw = json.loads(path.read_text())
        OperatorSchema.model_validate(raw)
        _operator_cache = raw
    except (json.JSONDecodeError, ValidationError, OSError) as e:
        # OSError catches PermissionError + the read_text race where
        # path.exists() passed but the read failed (file removed between
        # the exists check and the read, or backing FS hiccup). Without
        # OSError every caller crashes on a transient read failure even
        # though defaults would suffice. Sister to agents/_operator.py.
        log.warning("operator.json validation failed: %s -- using defaults", e)
        _operator_cache = {}
    return _operator_cache


def get_operator() -> dict:
    """Return the full operator manifest."""
    return _load_operator()


def reload_operator() -> None:
    """Clear operator cache, forcing re-read from disk on next access."""
    global _operator_cache
    _operator_cache = None


def get_constraints(*categories: str) -> list[str]:
    """Get constraint rules for given categories."""
    data = _load_operator()
    all_constraints = data.get("constraints", {})
    if not categories:
        categories = tuple(all_constraints.keys())
    rules: list[str] = []
    for cat in categories:
        rules.extend(all_constraints.get(cat, []))
    return rules


def get_patterns(*categories: str) -> list[str]:
    """Get behavioral patterns for given categories."""
    data = _load_operator()
    all_patterns = data.get("patterns", {})
    if not categories:
        categories = tuple(all_patterns.keys())
    items: list[str] = []
    for cat in categories:
        items.extend(all_patterns.get(cat, []))
    return items


def get_goals() -> list[dict]:
    """Get active goals (primary + secondary)."""
    data = _load_operator()
    goals = data.get("goals", {})
    return goals.get("primary", []) + goals.get("secondary", [])

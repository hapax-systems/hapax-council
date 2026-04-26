"""cc-hygiene-sweeper package.

Read-only diagnostic sweeper for the vault-SSOT cc-task pipeline. Implements
the 8 hygiene checks described in
``docs/research/2026-04-26-task-list-hygiene-operator-visibility.md`` §2 and
emits an append-only event log + machine-readable JSON state snapshot.

Auto-actions are PR2 territory; this package is strictly observational.
"""

from __future__ import annotations

__all__ = ["actions", "checks", "dashboard", "events", "models", "ntfy", "state"]

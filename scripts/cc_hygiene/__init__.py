"""cc-hygiene-sweeper package.

Diagnostic sweeper for the vault-SSOT cc-task pipeline. Implements
the hygiene checks described in
``docs/research/2026-04-26-task-list-hygiene-operator-visibility.md`` §2 and
emits an append-only event log + machine-readable JSON state snapshot.

The CLI wires a scoped ``ghost_claimed`` auto-revert; additional auto-actions
remain library-only until explicitly enabled.
"""

from __future__ import annotations

__all__ = ["actions", "checks", "dashboard", "events", "models", "ntfy", "state"]

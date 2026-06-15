"""cc-hygiene-sweeper package.

Diagnostic sweeper for the vault-SSOT cc-task pipeline. Implements the 8
hygiene checks described in
``docs/research/2026-04-26-task-list-hygiene-operator-visibility.md`` §2 and
emits an append-only event log + machine-readable JSON state snapshot.

The 8 checks (``cc_hygiene.checks``) are read-only pure functions. The one
mutation is the ``ghost_claimed`` self-heal in ``cc_hygiene.actions``, run by
default after the sweep: a ``status: claimed`` note with no claimer is reverted
to ``offered`` so the violation stops re-firing. Disable it with the sweeper's
``--no-actions`` flag (the broader H2/H7 auto-actions remain unwired).
"""

from __future__ import annotations

__all__ = ["actions", "checks", "dashboard", "events", "models", "ntfy", "state"]

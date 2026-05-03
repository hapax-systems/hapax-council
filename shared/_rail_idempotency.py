"""Shared sqlite-backed idempotency store for receive-only payment rails.

Extracted from ``shared.stripe_payment_link_receive_only_rail`` (#2322)
so the same pattern can apply across all monetization rails.

Webhook at-least-once delivery semantics permit the *same* event id
to arrive twice within the platform's retry window — typically a
network retry between the platform's edge and our receiver. Without
an idempotency check, the downstream publisher would write two
manifest rows for one logical event. The store keys on the platform-
provided event identifier with a UNIQUE constraint and reports
duplicate deliveries via :meth:`record_or_skip` returning ``False``
on collision.

Receive-only invariant preserved: this module imports only stdlib
(``sqlite3``, ``pathlib``, ``os``, ``datetime``); zero outbound network
surface. The DB lives on local disk under ``$HAPAX_HOME`` (or
``~/hapax-state``) — no network call.

Per-rail subdirectories isolate ledgers, so a duplicate ``evt_...`` id
in Stripe cannot conflict with a coincidentally-equal ``X-Patreon-
Webhook-Id`` value. Callers pass a unique-per-rail directory name to
:func:`default_idempotency_db_path`; the store creates parent dirs on
demand.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class IdempotencyError(Exception):
    """Fail-closed error from the idempotency store.

    Distinct from per-rail ``ReceiveOnlyRailError`` so callers can
    distinguish ``store-misuse`` (e.g. empty event id) from ``rail
    payload rejection``. Per-rail receivers wrap this in their own
    error type when surfacing to upstream callers.
    """


class IdempotencyStore:
    """sqlite-backed event-id seen-set with UNIQUE constraint.

    Construction is idempotent — creates the parent directory + table
    on first use. Subsequent constructions on the same db path see
    prior inserts (the persistence guarantee).

    Concurrent receivers are safe via sqlite's serialized writes
    (per-connection autocommit + single-row INSERT per delivery —
    contention is negligible for webhook traffic).

    Each rail should construct one store keyed on its own subdirectory
    so event-id namespaces don't collide across rails.
    """

    _SCHEMA_SQL = (
        "CREATE TABLE IF NOT EXISTS rail_webhook_events ("
        "  event_id TEXT PRIMARY KEY,"
        "  first_seen_at_iso TEXT NOT NULL"
        ")"
    )

    def __init__(self, *, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(self._SCHEMA_SQL)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path), isolation_level=None, timeout=5.0)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def record_or_skip(self, event_id: str, *, first_seen_at: datetime | None = None) -> bool:
        """Insert ``event_id`` into the seen-set or report a duplicate.

        Returns ``True`` if this is the first time we have seen the
        event id (caller should proceed with downstream processing) or
        ``False`` if the id was already in the table (caller should
        short-circuit to a no-op). Does not raise on collision;
        collision is the explicit signal.
        """
        if not event_id or not isinstance(event_id, str):
            raise IdempotencyError(
                f"event_id must be a non-empty string, got {type(event_id).__name__}"
            )
        first_seen_iso = (first_seen_at or datetime.now(tz=UTC)).isoformat()
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO rail_webhook_events(event_id, first_seen_at_iso) VALUES (?, ?)",
                    (event_id, first_seen_iso),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def has_seen(self, event_id: str) -> bool:
        """Read-only existence probe — ``True`` if the id is recorded."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM rail_webhook_events WHERE event_id = ? LIMIT 1",
                (event_id,),
            )
            return cursor.fetchone() is not None


def default_idempotency_db_path(rail_subdir: str) -> Path:
    """Default disk location for a rail's idempotency sqlite db.

    Honors ``HAPAX_HOME`` (used by tests for tmp_path isolation) and
    falls back to ``~/hapax-state``. ``rail_subdir`` is a per-rail
    namespace name (e.g. ``stripe-payment-link``, ``patreon``) so
    different rails maintain independent ledgers.
    """
    base = os.environ.get("HAPAX_HOME")
    if base:
        return Path(base) / rail_subdir / "idempotency.db"
    return Path.home() / "hapax-state" / rail_subdir / "idempotency.db"


_RAIL_STORE_REGISTRY: dict[str, IdempotencyStore] = {}


def get_idempotency_store(rail_subdir: str) -> IdempotencyStore:
    """Return the process-singleton idempotency store for ``rail_subdir``.

    Lazy-creates one :class:`IdempotencyStore` per rail name + caches.
    All rail routes call this with their per-rail subdirectory name
    (e.g. ``"patreon"``, ``"ko-fi"``, ``"github-sponsors"``); the
    registry returns the same instance on subsequent calls within the
    same process.

    Replaces the per-rail ``_<rail>_idempotency_store`` module-level
    singletons + ``_get_<rail>_idempotency_store()`` getters that each
    rail introduced before this consolidation.

    Tests reset state via :func:`reset_idempotency_store` (per-rail or
    global). Combined with ``monkeypatch.setenv("HAPAX_HOME", str(tmp_path))``
    the registry materializes a fresh sqlite db rooted in the test
    scratch directory on the next call.
    """
    if rail_subdir not in _RAIL_STORE_REGISTRY:
        _RAIL_STORE_REGISTRY[rail_subdir] = IdempotencyStore(
            db_path=default_idempotency_db_path(rail_subdir),
        )
    return _RAIL_STORE_REGISTRY[rail_subdir]


def reset_idempotency_store(rail_subdir: str | None = None) -> None:
    """Test helper: drop the cached store for the named rail or all rails.

    Pass ``rail_subdir=None`` to clear every rail (test-suite teardown).
    Pass a specific rail name to drop just that one (per-test isolation).
    The registry repopulates lazily on the next :func:`get_idempotency_store`
    call.
    """
    if rail_subdir is None:
        _RAIL_STORE_REGISTRY.clear()
    else:
        _RAIL_STORE_REGISTRY.pop(rail_subdir, None)


__all__ = [
    "IdempotencyError",
    "IdempotencyStore",
    "default_idempotency_db_path",
    "get_idempotency_store",
    "reset_idempotency_store",
]

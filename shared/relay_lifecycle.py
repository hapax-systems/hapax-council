"""Single-source relay-retirement predicate for dispatch eligibility.

This module is the ONE authoritative implementation of "is this lane's relay
retired?" lifted out of the bash launcher (``scripts/hapax-codex``) and the
coordinator (``agents/coordinator/core.py``) so the dispatch gate and the
launcher share a single predicate. It reconciles the three divergences that
produced rc=6 dispatch refusals (verified design-of-record,
``non-boutique-codex-auth-and-lane-liveness-design-2026-07-03.md``):

1. VOCABULARY — the launcher matched nine prefixes (RETIRED, SUPERSEDED, CLOSED,
   IDLE_WOUND_DOWN, WIND_DOWN_IDLE, WOUND_DOWN, WIND_DOWN, WINDING_DOWN,
   ANTIGRAVITY_TAKEOVER); the coordinator's ``_RETIRED_RELAY_STATUS_PREFIXES``
   matched only six (missing SUPERSEDED, CLOSED, ANTIGRAVITY_TAKEOVER). A
   SUPERSEDED/CLOSED relay was therefore routed by the coordinator and refused
   by the launcher -> rc=6. The launcher's full set is the authority here: the
   launcher IS the refusal surface (its exit 6 is rc=6), so to eliminate rc=6
   the gate and the coordinator must agree with it. (Confirmed by
   test_current_session_relay_retirement_blocks_without_force: SUPERSEDED -> rc=6.
   Production lane relays only carry `status: retired` via hapax-relay-retire, so
   superseded/closed are defensive — but the unified predicate matches the
   launcher to end rc=6.)

2. FILE RESOLUTION — the launcher read one file (``{role}.yaml``); the
   coordinator read the freshest of five candidate files. A lane whose
   ``{role}.yaml`` was retired but whose ``{role}-status.yaml`` was fresh was
   seen oppositely by the two (the cx-oofta incident). The coordinator's
   freshest-of-candidates resolution is the authority here.

3. PARSER — the launcher's awk scraped every ``status:`` line (matching stale
   historical markers); PyYAML last-wins on duplicate keys, so the latest status
   is the current truth. PyYAML is the authority: a relay that was retired then
   resumed should not be stuck retired.

Canonicalization upper-cases and maps both hyphens and spaces to underscores, so
``wind_down_idle``, ``wind-down-idle`` and ``wind down idle`` all match
``WIND_DOWN_IDLE`` (the launcher and the coordinator normalized differently;
this is the strict union).
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

import yaml

DEFAULT_RELAY_DIR = Path.home() / ".cache" / "hapax" / "relay"

__all__ = [
    "DEFAULT_RELAY_DIR",
    "RETIRED_PREFIXES",
    "lane_is_retired",
    "parse_relay_document",
    "relay_status_values",
    "relay_value_is_retired",
    "relay_values_are_retired",
]

# The full retirement vocabulary — the launcher's set. The launcher is the
# REFUSAL surface (its exit 6 IS rc=6): to eliminate rc=6 the dispatch gate and
# the coordinator must AGREE with the launcher, so its vocabulary is the
# authority (not the coordinator's narrower six, which under-refused SUPERSEDED/
# CLOSED/ANTIGRAVITY_TAKEOVER and routed such lanes into rc=6). ANTIGRAVITY_TAKEOVER
# is the terminal takeover marker; the broad ANTIGRAVITY* glob stays out (antigrav
# is a live interface — coordination reform Phase 1, per scripts/hapax-codex).
# NOTE: this was briefly narrowed to 7 on the coordinator-test/triage_officer
# reading, then re-broadened to 9 — the launcher tests
# (test_launcher_blocks_suffixed_terminal_relay_state_without_force,
# test_current_session_relay_retirement_blocks_without_force) confirm SUPERSEDED
# IS retirement for the refusal surface. (Production lane relays only ever carry
# `status: retired` via hapax-relay-retire, so the superseded/closed cases are
# defensive — but the unified predicate must match the launcher to end rc=6.)
RETIRED_PREFIXES: tuple[str, ...] = (
    "RETIRED",
    "SUPERSEDED",
    "CLOSED",
    "IDLE_WOUND_DOWN",
    "WIND_DOWN_IDLE",
    "WOUND_DOWN",
    "WIND_DOWN",
    "WINDING_DOWN",
    "ANTIGRAVITY_TAKEOVER",
)

# The status-bearing keys a relay YAML may carry. This is the multi-key union
# the bash awk scraped (status, state, relay_status, session_state, role) plus
# session_status; PyYAML parses each key to its latest value (last-wins on
# duplicates), which is the current-truth semantics the coordinator already used.
_STATUS_KEYS: tuple[str, ...] = (
    "status",
    "state",
    "relay_status",
    "session_state",
    "session_status",
    "role",
)


def _candidate_paths(role: str, session: str, relay_dir: Path) -> list[Path]:
    """Candidate relay files for one lane, in resolution order.

    Mirrors ``agents/coordinator/core.py::_relay_candidates`` so the gate and
    the coordinator resolve a lane's relay document identically.
    """

    names = [
        f"{role}-status.yaml",
        f"{role}.yaml",
        f"status-{role}.yaml",
        f"peer-status-{role}.yaml",
    ]
    if session:
        names.append(f"peer-status-{session}.yaml")
    return [relay_dir / name for name in names]


def _canonical(value: str) -> str:
    """Normalize a status value for prefix matching: trim, uppercase, underscores."""

    return value.strip().strip("'\"").upper().replace("-", "_").replace(" ", "_")


def relay_value_is_retired(value: object) -> bool:
    """True if a single status value expresses a retired/wound-down state."""

    if not isinstance(value, str) or not value.strip():
        return False
    canonical = _canonical(value)
    return any(canonical.startswith(prefix) for prefix in RETIRED_PREFIXES)


def relay_values_are_retired(values: Iterable[object]) -> bool:
    """True if any status value expresses a retired/wound-down state.

    The pure predicate: given the multi-key status values from one relay
    document, is the lane retired? Performs no IO; this is the unit-testable
    contract the dispatch gate and the launcher both consume.
    """

    return any(relay_value_is_retired(value) for value in values)


def parse_relay_document(text: str) -> dict:
    """Parse one relay YAML stream with latest-document merge semantics."""

    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError:
        return {}
    # Relay files are append-history: a status change is often a new YAML document
    # (``---``) appended after the prior state. ``safe_load`` would ComposerError
    # on the multi-doc stream (or load only the first) and silently drop the
    # latest state — the real cx-crit divergence (coordinator saw the stale first
    # doc / empty, launcher's flat awk scraped every doc). Merge every document in
    # order so the LATEST value per key wins: a resumed lane is not stuck retired,
    # and a newly-retired lane is retired even when appended as a new document.
    merged: dict = {}
    for document in documents:
        if isinstance(document, dict):
            merged.update(document)
    return merged


def _load_freshest_relay(role: str, session: str, relay_dir: Path) -> dict:
    """Return the parsed freshest candidate relay document for a lane (or ``{}``)."""

    freshest: Path | None = None
    freshest_mtime = -1.0
    for path in _candidate_paths(role, session, relay_dir):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > freshest_mtime:
            freshest = path
            freshest_mtime = mtime
    if freshest is None:
        return {}
    try:
        return parse_relay_document(freshest.read_text(encoding="utf-8"))
    except OSError:
        return {}


def relay_status_values(relay: dict) -> list[str]:
    """Extract the multi-key status values from a parsed relay document."""

    values: list[str] = []
    for key in _STATUS_KEYS:
        value = relay.get(key)
        if isinstance(value, str):
            values.append(value)
    return values


def _effective_relay_dir(relay_dir: Path | None) -> Path:
    """Resolve the relay directory: explicit arg > ``$HAPAX_RELAY_DIR`` > default.

    The launcher (hapax-codex), the RTE scripts (hapax-rte-state, assign-rte),
    and the launcher tests set ``HAPAX_RELAY_DIR``; ``lane_is_retired`` honors it
    so the dispatch gate, the coordinator, and the launcher all read the SAME
    relay store (the prior launcher read ``$HAPAX_RELAY_DIR`` directly).
    """

    if relay_dir is not None:
        return relay_dir
    env_dir = os.environ.get("HAPAX_RELAY_DIR")
    return Path(env_dir) if env_dir else DEFAULT_RELAY_DIR


def lane_is_retired(
    role: str,
    session: str = "",
    *,
    relay_dir: Path | None = None,
) -> bool:
    """True if the freshest relay document for ``role`` expresses a retired state.

    The resolver: freshest-of-candidates + PyYAML (latest-status-wins) + the
    multi-key status union + :func:`relay_values_are_retired`. This is the single
    predicate the dispatch gate (``coord_dispatch.run_atomic_dispatch_launch``)
    and the launcher (``hapax-codex``) must consult so a retired lane is never
    routed to and a resumed lane is never stuck retired.
    """

    relay = _load_freshest_relay(role, session, _effective_relay_dir(relay_dir))
    if not relay:
        return False
    return relay_values_are_retired(relay_status_values(relay))

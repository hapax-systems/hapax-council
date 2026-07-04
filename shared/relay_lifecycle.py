"""Single-source relay-retirement predicate for dispatch eligibility.

This module is the ONE authoritative implementation of "is this lane's relay
retired?" lifted out of the bash launcher (``scripts/hapax-codex``) and the
coordinator (``agents/coordinator/core.py``) so the dispatch gate and the
launcher share a single predicate. It reconciles the three divergences that
produced rc=6 dispatch refusals (verified design-of-record,
``non-boutique-codex-auth-and-lane-liveness-design-2026-07-03.md``):

1. VOCABULARY — the coordinator's six wind-down/retired prefixes are the
   intentional, correct lane-retirement vocabulary; the launcher's awk
   additionally matched SUPERSEDED/CLOSED/ANTIGRAVITY_TAKEOVER. Of those three,
   only ANTIGRAVITY_TAKEOVER is a genuine lane-terminal marker (antigrav
   takeover — the hapax-codex comment + cc_hygiene confirm it); SUPERSEDED and
   CLOSED are TASK/CLAIM terminal states (triage_officer/core.py:267
   {"done","closed","withdrawn","superseded"}) that leaked into the launcher's
   relay-vocabulary and are NOT lane retirement. So a SUPERSEDED/CLOSED relay
   was OVER-REFUSED by the launcher (not under-recognized by the coordinator)
   -> rc=6; the prior map's "broaden the coordinator" direction was inverted.
   The reconciled set is the coordinator's six + ANTIGRAVITY_TAKEOVER (seven).
   The launcher thinning (slice 2b) narrows its awk to match; until then the
   gate (this predicate) is authoritative and agrees with the coordinator.

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

from collections.abc import Iterable
from pathlib import Path

import yaml

DEFAULT_RELAY_DIR = Path.home() / ".cache" / "hapax" / "relay"

__all__ = [
    "DEFAULT_RELAY_DIR",
    "RETIRED_PREFIXES",
    "lane_is_retired",
    "relay_status_values",
    "relay_value_is_retired",
    "relay_values_are_retired",
]

# The reconciled retirement vocabulary: the coordinator's six wind-down/retired
# prefixes + ANTIGRAVITY_TAKEOVER (the genuine lane-terminal marker; the broad
# ANTIGRAVITY* glob stays out — antigrav is a live interface, coordination
# reform Phase 1). SUPERSEDED/CLOSED are EXCLUDED — they are task/claim terminal
# states (triage_officer/core.py:267), not lane retirement; the launcher's awk
# over-refused them (the bug slice 2b thins). Confirmed by the
# test_reconciled_vocabulary_drops_task_claim_states test + the coordinator's own
# test_retired_relay_status_variants_normalize_and_suppress_claim.
RETIRED_PREFIXES: tuple[str, ...] = (
    "RETIRED",
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
        documents = list(yaml.safe_load_all(freshest.read_text(encoding="utf-8")))
    except (yaml.YAMLError, OSError):
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


def relay_status_values(relay: dict) -> list[str]:
    """Extract the multi-key status values from a parsed relay document."""

    values: list[str] = []
    for key in _STATUS_KEYS:
        value = relay.get(key)
        if isinstance(value, str):
            values.append(value)
    return values


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

    relay = _load_freshest_relay(role, session, relay_dir or DEFAULT_RELAY_DIR)
    if not relay:
        return False
    return relay_values_are_retired(relay_status_values(relay))

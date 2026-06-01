"""Per-field vault write-ownership policy (OQ-9).

CASE-SDLC-REFORM-001, Phase 8 ("vault per-field ownership model"). The
coordination-reform master design (2026-05-30, OQ-9 — operator-approved)
specifies:

    Coordination fields are daemon-owned; life-planning fields (goals, daily
    notes, people) are operator-owned. The daemon NEVER overwrites operator-owned
    fields. Conflicts on coordination fields resolve by ledger order; conflicts on
    operator fields always favour the human.

Before this module the invariant held only *incidentally* — daemon writers spliced
markdown body sections or rewrote whole frontmatter dicts they had just parsed from
disk, so operator fields survived by accident rather than by contract. This module
turns "the daemon never clobbers operator life-planning fields" into a governed,
enforced rule that the vault writers consult on every frontmatter write.

Ownership model
---------------
Each vault note has a *type* (its ``type:`` frontmatter, or a type the caller
asserts from context — e.g. the sprint tracker knows ``measures/`` notes are
``measure`` notes). Per ``(note_type, key)`` a field is owned by either the DAEMON
or the OPERATOR:

* **Daemon-generated note types** (briefing, digest, nudges, …): the daemon owns
  the whole file — every key is daemon-writable.
* **Coordination note types with operator-authored fields** (measure, gate, goal):
  a small explicit allowlist of coordination keys is daemon-writable; everything
  else is operator-owned.
* **Pure operator note types** (daily, person): the daemon owns *no* frontmatter
  key (it writes body sections or reads only).
* **Unknown note types / unlisted keys**: operator-owned by default — fail-safe for
  the human.

The daemon refuses to write any OPERATOR-owned key. Conflicts between successive
daemon writes to the same coordination key resolve by ledger order (the event log
is the SSOT; the latest ledger value wins).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from shared.frontmatter import parse_frontmatter

log = logging.getLogger(__name__)

_MISSING = object()

__all__ = [
    "Ownership",
    "DAEMON_NOTE_TYPES",
    "COORDINATION_FIELDS",
    "DAEMON_ALL",
    "daemon_owned_keys",
    "is_daemon_writable",
    "ownership",
    "Partition",
    "partition_frontmatter",
    "filter_daemon_frontmatter",
    "filter_system_egress",
    "resolve_by_ledger_order",
    "MergeResult",
    "merge_daemon_frontmatter",
    "WriteResult",
    "governed_note_write",
    "frontmatter_block",
    "frontmatter_preserved",
]


class Ownership(StrEnum):
    """Which principal owns a vault frontmatter field."""

    DAEMON = "daemon"
    OPERATOR = "operator"


# Note types the daemon fully generates — every frontmatter key is daemon-owned.
# These files are projections of system state; the operator does not hand-edit them.
DAEMON_NOTE_TYPES: frozenset[str] = frozenset(
    {
        "briefing",
        "digest",
        "nudges",
        "goals",  # the 30-system/goals.md snapshot, not an operator `goal` note
        "decision",
        "bridge-prompt",
        "profile-summary",
        "rag_note",
        "sprint-summary",
        "posterior-tracker",
        "observatory",  # daily velocity:quality observation (velocity_quality_observatory feeder)
    }
)

# Per-type daemon-owned coordination-field allowlists for notes that otherwise
# carry operator-authored frontmatter. A key NOT listed here (for these types) is
# operator-owned and the daemon must never write it.
COORDINATION_FIELDS: dict[str, frozenset[str]] = {
    # R&D sprint measure notes: the sprint tracker owns completion/result state.
    "measure": frozenset(
        {"status", "completed_at", "result_summary", "acknowledged", "evaluated_at", "result_value"}
    ),
    # Decision-gate notes: the sprint tracker owns evaluation state.
    "gate": frozenset({"status", "acknowledged", "evaluated_at", "result_value"}),
    # Operator goal notes: the daemon may project computed progress only.
    "goal": frozenset({"progress", "sprint_progress", "last_synced"}),
    # Daily notes: daemon writes BODY sections only — no frontmatter key is daemon-owned.
    "daily": frozenset(),
    # People notes: daemon reads cadence only — no frontmatter key is daemon-owned.
    "person": frozenset(),
}

# Sentinel returned by ``daemon_owned_keys`` meaning "every key is daemon-owned".
DAEMON_ALL: None = None


def daemon_owned_keys(note_type: str | None) -> frozenset[str] | None:
    """Return the set of daemon-writable frontmatter keys for ``note_type``.

    Returns:
        ``None`` (``DAEMON_ALL``) when every key is daemon-owned (a daemon-generated
        note type); a ``frozenset`` of the daemon-writable keys otherwise (possibly
        empty, meaning the daemon owns no frontmatter on this note type).
    """
    if note_type in DAEMON_NOTE_TYPES:
        return DAEMON_ALL
    return COORDINATION_FIELDS.get(note_type or "", frozenset())


def is_daemon_writable(note_type: str | None, key: str) -> bool:
    """True iff the daemon is allowed to write frontmatter ``key`` on ``note_type``."""
    allowed = daemon_owned_keys(note_type)
    # ``None`` (DAEMON_ALL) means every key on this note type is daemon-owned.
    return allowed is None or key in allowed


def ownership(note_type: str | None, key: str) -> Ownership:
    """Classify a ``(note_type, key)`` as DAEMON- or OPERATOR-owned."""
    return Ownership.DAEMON if is_daemon_writable(note_type, key) else Ownership.OPERATOR


@dataclass(frozen=True)
class Partition:
    """A proposed frontmatter write split by ownership."""

    allowed: dict[str, Any]  # daemon-owned keys the daemon may write
    refused: dict[str, Any]  # operator-owned keys the daemon must NOT write


def partition_frontmatter(note_type: str | None, proposed: Mapping[str, Any]) -> Partition:
    """Split ``proposed`` frontmatter into daemon-writable vs operator-owned keys."""
    allowed: dict[str, Any] = {}
    refused: dict[str, Any] = {}
    for key, value in proposed.items():
        if is_daemon_writable(note_type, key):
            allowed[key] = value
        else:
            refused[key] = value
    return Partition(allowed=allowed, refused=refused)


def filter_daemon_frontmatter(
    note_type: str | None, proposed: Mapping[str, Any], *, warn: bool = True
) -> dict[str, Any]:
    """Drop operator-owned keys from a proposed daemon frontmatter write.

    This is the guard a daemon writer applies before emitting frontmatter: any key
    it is not allowed to own is refused (dropped) rather than written. For a
    daemon-generated note type every key passes through unchanged.
    """
    part = partition_frontmatter(note_type, proposed)
    if part.refused and warn:
        log.warning(
            "vault_ownership: refusing %d operator-owned frontmatter key(s) on %r note: %s",
            len(part.refused),
            note_type,
            sorted(part.refused),
        )
    return part.allowed


def filter_system_egress(
    note_type: str | None, proposed: Mapping[str, Any], *, warn: bool = True
) -> dict[str, Any]:
    """Filter frontmatter for the daemon's system-directory egress (``write_to_vault``).

    The ``30-system/`` tree is wholly daemon-owned — the operator does not hand-edit
    it — so daemon-generated and *unrecognised* note types pass through unchanged.
    Only when a KNOWN operator/coordination note type (measure, gate, goal, daily,
    person) is routed through the system writer are its operator-owned keys refused,
    as defence in depth against an operator note leaking through the wrong egress.

    The authoritative per-field enforcement for operator notes lives in
    :func:`governed_note_write` (used by the sprint tracker), not here; this guard
    only stops the generic system writer from being a back door.
    """
    if note_type not in COORDINATION_FIELDS:
        return dict(proposed)
    return filter_daemon_frontmatter(note_type, proposed, warn=warn)


def resolve_by_ledger_order(writes: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    """Fold ordered ``(key, value)`` coordination writes last-wins.

    The event log is the SSOT for coordination fields, and ledger entries are
    appended in order, so "the latest write wins" is simply the last value seen for
    each key when iterating in append order.
    """
    resolved: dict[str, Any] = {}
    for key, value in writes:
        resolved[key] = value
    return resolved


@dataclass(frozen=True)
class MergeResult:
    """Outcome of merging a daemon frontmatter write into an existing note."""

    merged: dict[str, Any]  # frontmatter to persist
    refused: dict[str, Any]  # operator-owned keys whose proposed change was rejected
    applied: frozenset[str]  # daemon-owned keys actually changed


def merge_daemon_frontmatter(
    existing: Mapping[str, Any],
    proposed: Mapping[str, Any],
    note_type: str | None,
    *,
    ledger_resolved: Mapping[str, Any] | None = None,
) -> MergeResult:
    """Merge a daemon write over an existing note, preserving operator fields.

    Rules (OQ-9):

    * Every operator-owned key in ``existing`` is preserved verbatim. If ``proposed``
      tries to change or add an operator-owned key, that change is *refused* (recorded
      in ``MergeResult.refused``) and the operator value stands.
    * Daemon-owned keys in ``proposed`` are applied. When ``ledger_resolved`` carries
      the same key, the ledger value wins (conflict resolution by ledger order — the
      ledger is the SSOT and the note is a projection of it).
    * Daemon-owned keys present only in ``ledger_resolved`` are projected in too.
    """
    merged: dict[str, Any] = dict(existing)
    refused: dict[str, Any] = {}
    applied: set[str] = set()

    for key, value in proposed.items():
        if is_daemon_writable(note_type, key):
            new_value = (
                ledger_resolved[key]
                if ledger_resolved is not None and key in ledger_resolved
                else value
            )
            if merged.get(key, _MISSING) != new_value:
                applied.add(key)
            merged[key] = new_value
        elif merged.get(key, _MISSING) != value:
            # Operator-owned key the daemon tried to change or add — refuse it.
            refused[key] = value

    # Project any ledger-resolved daemon keys that weren't in ``proposed``.
    if ledger_resolved is not None:
        for key, value in ledger_resolved.items():
            if is_daemon_writable(note_type, key) and merged.get(key, _MISSING) != value:
                merged[key] = value
                applied.add(key)

    return MergeResult(merged=merged, refused=refused, applied=frozenset(applied))


@dataclass(frozen=True)
class WriteResult:
    """Outcome of a governed on-disk note write."""

    path: Path
    written: bool
    refused: dict[str, Any]
    applied: frozenset[str]


def governed_note_write(
    path: Path,
    *,
    frontmatter: Mapping[str, Any],
    note_type: str | None,
    body: str | None = None,
    ledger_resolved: Mapping[str, Any] | None = None,
    sort_keys: bool = False,
) -> WriteResult:
    """Atomically write a vault note, merging daemon-only frontmatter.

    Reads the note currently on disk (if any), merges ``frontmatter`` per the
    ownership rules — preserving every operator-owned field — and writes the result
    back atomically. ``body=None`` preserves the existing body; pass a string to
    replace it. Operator-owned keys in ``frontmatter`` are refused, never written.
    """
    existing_fm: Mapping[str, Any] = {}
    existing_body = ""
    if path.exists():
        existing_fm, existing_body = parse_frontmatter(path)

    result = merge_daemon_frontmatter(
        existing_fm, frontmatter, note_type, ledger_resolved=ledger_resolved
    )
    out_body = existing_body if body is None else body

    yaml_str = yaml.dump(
        result.merged, default_flow_style=False, sort_keys=sort_keys, allow_unicode=True
    )
    content = f"---\n{yaml_str}---\n{out_body}"

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.rename(path)

    return WriteResult(path=path, written=True, refused=result.refused, applied=result.applied)


def frontmatter_block(text: str) -> str:
    """Return the raw ``---``-delimited frontmatter block of ``text`` (incl. markers).

    Returns ``""`` when ``text`` has no frontmatter. Used by body-only writers (e.g.
    the daily-note context writer) to prove a write left operator frontmatter
    untouched.
    """
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end == -1:
        return ""
    return text[: end + 4]


def frontmatter_preserved(before: str, after: str) -> bool:
    """True iff ``before`` and ``after`` carry byte-identical frontmatter blocks.

    A daemon body-section write to an operator-owned note (a daily note) must leave
    the frontmatter exactly as the operator left it; this is the enforcement check.
    """
    return frontmatter_block(before) == frontmatter_block(after)

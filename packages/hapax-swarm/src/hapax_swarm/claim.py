"""``claim_before_parallel_work`` — atomic claim primitive.

The single discipline that closed the largest velocity leak across a
3-month single-operator multi-agent program: before opening a PR on an
out-of-lane or cross-cutting surface, every session must

1. Read every sibling ``{role}.yaml`` and reject if any
   ``currently_working_on.surface`` overlaps the claim,
2. Write its own ``currently_working_on`` record (atomic),
3. Optionally drop a 1-line announcement note for human review.

This module wraps that protocol in a single function so callers cannot
forget step 1 or step 2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hapax_swarm.relay import RelayDir


class ClaimConflict(RuntimeError):
    """Raised when a sibling already claims an overlapping surface.

    Attributes:
        surface: the surface the caller tried to claim.
        conflicts: list of ``(role, currently_working_on)`` records.
    """

    def __init__(
        self,
        surface: str,
        conflicts: list[tuple[str, dict[str, Any]]],
    ) -> None:
        self.surface = surface
        self.conflicts = conflicts
        peers = ", ".join(role for role, _ in conflicts)
        super().__init__(f"sibling claim collision on {surface!r}: held by {peers}")


def claim_before_parallel_work(
    relay: RelayDir,
    *,
    role: str,
    surface: str,
    branch_target: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically claim ``surface`` for ``role``.

    Steps:

    1. Re-read all sibling ``{role}.yaml`` files via
       :meth:`RelayDir.find_conflicting_claims`. If any sibling already
       claims an overlapping surface, raise :class:`ClaimConflict`.
    2. Atomically write ``currently_working_on`` into the caller's own
       ``{role}.yaml`` (preserving any existing fields).

    Returns the post-write ``currently_working_on`` payload.

    The check + write is *not* a true mutual-exclusion lock — two
    sessions running simultaneously could both pass step 1 and both
    write in step 2. Filesystem-as-bus does not promise that. What it
    promises (and empirically delivers) is that any *human-paced*
    workflow built on top of this primitive avoids duplicate PRs in
    practice. If two sessions race, the relay yamls show both claims
    and the operator (or a downstream reactive engine) can adjudicate.

    For tighter mutual exclusion, layer a ``locks/`` file on top via
    :meth:`RelayDir.lock_path`.
    """
    conflicts = relay.find_conflicting_claims(surface, exclude_role=role)
    if conflicts:
        raise ClaimConflict(surface, conflicts)

    record: dict[str, Any] = {
        "surface": surface,
        "branch_target": branch_target,
        "claimed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if extra:
        record.update(extra)

    peer = relay.peer(role)
    peer.update(currently_working_on=record)
    return record

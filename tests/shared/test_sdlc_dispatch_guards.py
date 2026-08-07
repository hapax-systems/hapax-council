"""Regression pin for the dispatch worktree-staleness guard markers.

``check_worktree_claim_guard`` decides whether a lane worktree carries a current
``cc-claim`` by looking for marker strings in it. A marker naming something no
``cc-claim`` contains cannot ever be found, so the guard rejects EVERY worktree
as stale and dispatch-into-worktree refuses unconditionally. That is what
happened on trunk: two aspirational markers were added ahead of the ``cc-claim``
that would carry them, and one of them
(``publish_admitted_claim``) exists in no ``cc-claim`` in any branch.

A guard that can never pass is a wedge, not a guard. These tests pin each marker
to a string actually present in the current ``scripts/cc-claim``, so the next
attempt to add a marker ahead of its script breaks a test instead of silently
breaking dispatch.

Recheck by hand:
    for m in "missing required AuthorityCase/ISAP fields" authority_case parent_spec; do
      grep -c -- "$m" scripts/cc-claim
    done
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.sdlc_dispatch_guards import (
    DISPATCH_CLAIM_GUARD_MARKERS,
    DISPATCH_CLOSE_GUARD_MARKERS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("marker", DISPATCH_CLAIM_GUARD_MARKERS)
def test_every_claim_guard_marker_appears_in_the_current_cc_claim(marker: str) -> None:
    source = (REPO_ROOT / "scripts" / "cc-claim").read_text(encoding="utf-8")
    assert marker in source, (
        f"claim guard marker {marker!r} appears in no current scripts/cc-claim. "
        "check_worktree_claim_guard would reject every worktree as stale and "
        "dispatch-into-worktree would refuse unconditionally. Add a marker only "
        "together with the cc-claim that carries it."
    )


@pytest.mark.parametrize("marker", DISPATCH_CLOSE_GUARD_MARKERS)
def test_every_close_guard_marker_appears_in_the_current_cc_close(marker: str) -> None:
    source = (REPO_ROOT / "scripts" / "cc-close").read_text(encoding="utf-8")
    assert marker in source, (
        f"close guard marker {marker!r} appears in no current scripts/cc-close, so "
        "the close-side staleness guard can never pass. Add a marker only together "
        "with the cc-close that carries it."
    )


def test_the_marker_sets_are_not_empty() -> None:
    """An empty marker tuple would make ``all(...)`` vacuously true.

    Without this, the guard would accept every worktree as current -- the exact
    inverse failure of the one above, and equally invisible: both parametrized
    tests above would collect zero cases and report success.
    """
    assert DISPATCH_CLAIM_GUARD_MARKERS, "claim guard markers must not be empty"
    assert DISPATCH_CLOSE_GUARD_MARKERS, "close guard markers must not be empty"

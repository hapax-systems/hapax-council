"""Which code produced this decision.

A decision with no adjudicator identity is not replayable, and on this estate that is not a
theoretical concern. Measured 2026-08-20:

- ``~/.cache/hapax/source-activation/worktree`` is a symlink into
  ``releases/<sha>/`` that repointed ~7x/day across Aug 17-20 (3, 8, 6, 4 release trees on
  those days) — roughly a three-hour half-life. It repointed twice during the session that
  wrote this module.
- ``~/.claude/settings.json`` pins its hooks to an ABSOLUTE release path, frozen at
  ``158e746b`` (2026-08-08) — eleven days and 124 differing files in ``shared/`` behind the
  floating tree.
- ``route-decisions.jsonl`` carries ``routing_model_version`` on 559 of 559 records, and its
  value is the constant ``"capacity-dimensional-v1"`` — a basis name, not a code identity.
  None of the 48 keys on a record holds a 40-hex sha.

So two decisions about the same subject three hours apart were made by different code, with
nothing recording that anything changed, and every mechanical check over that history is void
across a redeploy boundary. SLSA makes ``builder.id`` "the sole determiner of the build level";
these receipts are under-specified in the way the state of the art calls fatal.

## Resolve from ``__file__``, not from the symlink

The obvious implementation reads the symlink. That is wrong, and wrong in the direction that
matters: if the tree repoints mid-run, the symlink names the code that will run NEXT while the
process is still executing the old one, so the receipt would attribute a decision to code that
did not make it. ``Path(__file__).resolve()`` names the tree this module was actually loaded
from. It is the only source that cannot drift out from under the running process.

## A release path is a claim, not a proof

Raised by codex-1 in review and confirmed by measurement: **release trees on this estate are
git checkouts and they are writable.** At the time of writing, the live release tree
``45086a03…`` carried a modified ``scripts/hapax-determine`` while its directory name asserted
that commit. Reading the sha out of the path and reporting ``dirty=false`` would have
attributed a decision to a commit the running code did not match — defeating the exact
guarantee this module exists to provide.

So the path sha is recorded as ``declared_sha`` and the *verified* HEAD as ``sha``, with
``dirty`` reporting uncommitted modifications. The two can disagree, and when they do a reader
can see it. A release path with no verifiable checkout behind it yields ``sha=None``: the claim
survives in ``declared_sha`` rather than being promoted into the verified slot.

## Indeterminate is a state, not a default

Following the same rule established for supply freshness in this package: when the identity
cannot be determined — an editable install, a zipapp, an unpacked archive — the result says so
in a typed field rather than defaulting to a plausible value. A receipt that quietly attributes
a decision to the wrong tree is worse than one that says it does not know.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

#: ``.../source-activation/releases/<40-hex>/...`` — the deployed-release layout.
_RELEASE_PATH_RE = re.compile(r"/source-activation/releases/([0-9a-f]{40})(?:/|$)")
_SHA_RE = re.compile(r"[0-9a-f]{40}")

AdjudicatorSource = Literal["release_tree", "git_worktree", "indeterminate"]


@dataclass(frozen=True, slots=True)
class AdjudicatorIdentity:
    """The code that produced a decision, and how confidently that was established."""

    #: The commit that best describes the code that ran — VERIFIED where verification is
    #: possible, not inferred from a directory name. None when nothing could be established.
    sha: str | None
    #: How ``sha`` was established. See the class docstring: no value here means "trust me".
    source: AdjudicatorSource
    #: The resolved filesystem path the determination was made from, always recorded so the
    #: claim is auditable even when ``sha`` is None.
    resolved_from: str
    #: True when the tree had uncommitted modifications at resolution time. A dirty tree means
    #: ``sha`` does NOT fully identify the running code, whatever the source.
    dirty: bool = False
    #: For a release tree, the sha its PATH claims. Recorded separately from ``sha`` because
    #: they can disagree: release trees on this estate are git checkouts and are WRITABLE, so
    #: the directory name is a claim, not a proof. Measured 2026-08-20: the live release tree
    #: `45086a03…` carried a modified `scripts/hapax-determine` while its path asserted a clean
    #: commit. A reader must be able to see the claim and the verification separately.
    declared_sha: str | None = None

    # NOTE: an `is_authoritative` convenience property (`source == "release_tree"`) was written
    # here and REMOVED before merge. The unused-function gate flagged it, correctly: nothing in
    # production consumed it, only tests. The gate offered three remedies — remove it, give it
    # a real call path, or add it to scripts/vulture_whitelist.py. Whitelisting a property
    # invented and never consumed is exactly how that 5,088-line file became the estate's
    # tombstone for built-and-unwired machinery, so it was removed. `source` already carries
    # the distinction; a caller that needs the predicate can compare against it, and the
    # divergence alarm that would genuinely want it is separate, unbuilt work.

    def as_receipt(self) -> dict[str, object]:
        """The shape written onto decisions and run records."""
        return {
            "adjudicator_sha": self.sha,
            "adjudicator_source": self.source,
            "adjudicator_resolved_from": self.resolved_from,
            "adjudicator_dirty": self.dirty,
            "adjudicator_declared_sha": self.declared_sha,
        }


def record_has_usable_adjudicator(record: Mapping[str, object]) -> bool:
    """Does this decision/run record identify the code that produced it?

    The check the estate did not have. `routing_model_version` is present on 559 of 559
    historical route decisions carrying the constant ``"capacity-dimensional-v1"``, so
    "an adjudicator field exists" was never the same question as "the adjudicator is known".

    Usable means: a verified 40-hex ``adjudicator_sha`` from a source that could verify it.
    A record is NOT usable when it carries only a basis name, when the sha is absent, when the
    source is ``indeterminate`` (including a release path nothing could confirm), or when the
    tree was dirty — a dirty tree's HEAD does not determine the code that ran.
    """
    sha = record.get("adjudicator_sha")
    source = record.get("adjudicator_source")
    if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
        return False
    if source not in ("release_tree", "git_worktree"):
        return False
    return record.get("adjudicator_dirty") is not True


def _git_head(tree: Path) -> tuple[str | None, bool]:
    """HEAD sha and dirtiness for a git worktree, or (None, False) if not one."""
    try:
        sha = subprocess.run(
            ["git", "-C", str(tree), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if sha.returncode != 0:
            return (None, False)
        head = sha.stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", head):
            return (None, False)
        status = subprocess.run(
            ["git", "-C", str(tree), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return (head, bool(status.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        return (None, False)


@lru_cache(maxsize=1)
def adjudicator_identity(module_file: str | None = None) -> AdjudicatorIdentity:
    """Identify the code this process is running.

    Cached: the answer cannot change within a process, because the loaded module cannot be
    relocated mid-run. That is the same property that makes ``__file__`` the correct source
    and the symlink the incorrect one.

    ``module_file`` exists for tests; production callers pass nothing.
    """
    resolved = Path(module_file or __file__).resolve()
    text = str(resolved)
    declared = match.group(1) if (match := _RELEASE_PATH_RE.search(text)) else None

    # Find the enclosing checkout, if any. The module lives at <root>/shared/<file>.py, but a
    # symlinked or relocated layout should still resolve rather than silently degrade.
    for candidate in (resolved.parent, *resolved.parents):
        if (candidate / ".git").exists():
            head, dirty = _git_head(candidate)
            if head is not None:
                # A release path is a CLAIM about content, and release trees here are git
                # checkouts that are writable. Verify rather than trust the directory name:
                # report the sha that actually describes the tree, keep the claim alongside,
                # and let `dirty` say whether even that sha fully determines the code.
                return AdjudicatorIdentity(
                    sha=head,
                    source="release_tree" if declared else "git_worktree",
                    resolved_from=text,
                    dirty=dirty,
                    declared_sha=declared,
                )
            break

    if declared is not None:
        # A release path with no verifiable checkout behind it: the name asserts a commit and
        # nothing can confirm it. `sha` stays None — the claim is preserved in `declared_sha`
        # where a reader can see it is unverified, rather than promoted into the verified slot.
        return AdjudicatorIdentity(
            sha=None,
            source="indeterminate",
            resolved_from=text,
            declared_sha=declared,
        )

    return AdjudicatorIdentity(sha=None, source="indeterminate", resolved_from=text)

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

## Indeterminate is a state, not a default

Following the same rule established for supply freshness in this package: when the identity
cannot be determined — running from a git worktree, an editable install, a zipapp — the result
says so in a typed field rather than defaulting to a plausible value. A receipt that quietly
attributes a decision to the wrong tree is worse than one that says it does not know.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

#: ``.../source-activation/releases/<40-hex>/...`` — the deployed-release layout.
_RELEASE_PATH_RE = re.compile(r"/source-activation/releases/([0-9a-f]{40})(?:/|$)")

AdjudicatorSource = Literal["release_tree", "git_worktree", "indeterminate"]


@dataclass(frozen=True, slots=True)
class AdjudicatorIdentity:
    """The code that produced a decision, and how confidently that was established."""

    #: 40-hex commit sha, or None when the source is ``indeterminate``.
    sha: str | None
    #: How the sha was established. ``release_tree`` is authoritative: the path this module
    #: was loaded from encodes the deployed release. ``git_worktree`` is a development
    #: checkout, where HEAD is a reasonable but weaker claim — the tree may be dirty.
    source: AdjudicatorSource
    #: The resolved filesystem path the determination was made from, always recorded so the
    #: claim is auditable even when ``sha`` is None.
    resolved_from: str
    #: True when the working tree had uncommitted changes. Only meaningful for
    #: ``git_worktree``; a dirty tree means the sha does NOT fully identify the code.
    dirty: bool = False

    @property
    def is_authoritative(self) -> bool:
        """A clean release tree is the only identity that fully determines the code."""
        return self.source == "release_tree"

    def as_receipt(self) -> dict[str, object]:
        """The shape written onto decisions and run records."""
        return {
            "adjudicator_sha": self.sha,
            "adjudicator_source": self.source,
            "adjudicator_resolved_from": self.resolved_from,
            "adjudicator_dirty": self.dirty,
        }


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

    if match := _RELEASE_PATH_RE.search(text):
        return AdjudicatorIdentity(
            sha=match.group(1),
            source="release_tree",
            resolved_from=text,
        )

    # Walk up looking for a git checkout. The module lives at <root>/shared/<file>.py, so the
    # repository root is normally two levels up, but a symlinked or relocated layout should
    # still resolve rather than silently degrade.
    for candidate in (resolved.parent, *resolved.parents):
        if (candidate / ".git").exists():
            head, dirty = _git_head(candidate)
            if head is not None:
                return AdjudicatorIdentity(
                    sha=head,
                    source="git_worktree",
                    resolved_from=text,
                    dirty=dirty,
                )
            break

    return AdjudicatorIdentity(sha=None, source="indeterminate", resolved_from=text)

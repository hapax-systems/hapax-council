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

And the claim is only heard from one place. Raised by coderabbitai in review: the first
implementation matched the release layout as a **substring of any path**, so any directory that
named itself ``…/source-activation/releases/<40-hex>/…`` minted a ``release_tree`` verdict —
a scratch copy, an unpacked archive, a test fixture. Deployment is a location, not a spelling,
so containment is checked against the root the activator itself writes
(``HAPAX_SOURCE_ACTIVATE_STATE_DIR``, ``scripts/hapax-source-activate:34``). The same layout
elsewhere carries no claim at all.

## The claim is about load time; every measurement happens later

Raised by codex-1 in review, and the deepest form of this module's own subject. Resolving from
``__file__`` fixes *which tree* is measured, but not *when*. The first measurement happens when
a receipt is written, which can be arbitrarily long after the process loaded its code. In
between, a tree can be modified, executed, and restored to a clean HEAD — at which point
``dirty`` reports False, ``sha`` reports the clean commit, and the receipt confidently
attributes the decision to code that never ran. Checkouts, rebases and lazy imports all open
the same window, and since release trees here are writable it is not theoretical.

So this module hashes its own source at IMPORT — the moment those bytes became the running
code — and ``source_matches_head`` reports whether that hash equals the blob the claimed commit
records at that path. It is the one field that speaks to load time; ``dirty`` still speaks for
the rest of the tree, at measurement time. ``record_has_usable_adjudicator`` requires it.

## Indeterminate is a state, not a default

Following the same rule established for supply freshness in this package: when the identity
cannot be determined — an editable install, a zipapp, an unpacked archive — the result says so
in a typed field rather than defaulting to a plausible value. A receipt that quietly attributes
a decision to the wrong tree is worse than one that says it does not know.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

_SHA_RE = re.compile(r"[0-9a-f]{40}")


def _trusted_releases_root() -> Path:
    """The one directory whose layout is allowed to mean "deployed release".

    ``scripts/hapax-source-activate:34`` defines the state dir as
    ``${HAPAX_SOURCE_ACTIVATE_STATE_DIR:-$HOME/.cache/hapax/source-activation}`` and creates
    release trees beneath ``releases/``. Reading the same variable keeps this function and the
    activator from disagreeing about where releases live; it is the activator's own
    configuration, not an escape hatch added for tests.
    """
    configured = os.environ.get("HAPAX_SOURCE_ACTIVATE_STATE_DIR")
    base = (
        Path(configured) if configured else Path.home() / ".cache" / "hapax" / "source-activation"
    )
    return (base / "releases").resolve()


def _declared_release_sha(resolved: Path) -> str | None:
    """The sha a path CLAIMS, but only from inside the trusted releases root.

    Raised by coderabbitai in review: the earlier implementation regex-searched for
    ``/source-activation/releases/<40-hex>`` **anywhere** in the path, so any copy, scratch
    checkout, or archive that happened to contain those components — ``/tmp/x/source-activation/
    releases/<sha>/shared/…`` — was classified ``release_tree`` and read as authoritative. A
    substring is not a location. The layout only carries meaning inside the directory the
    activator actually writes, so containment is checked against that root and the sha is taken
    from the first component beneath it rather than matched loose.

    Outside the root the answer is None, not the path's claim: ``resolved_from`` already records
    the full path for forensics, and surfacing an untrusted sha in ``declared_sha`` would invite
    a reader to trust exactly what this check exists to distrust.
    """
    try:
        relative = resolved.relative_to(_trusted_releases_root())
    except (ValueError, OSError, RuntimeError):
        return None
    head = relative.parts[0] if relative.parts else ""
    return head if _SHA_RE.fullmatch(head) else None


def _sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


#: Resolved path -> sha256 of its bytes, captured when that module was imported.
#:
#: The decision is not made by one file. `dispatcher_policy` computes routes and
#: `hapax-determine` runs producers; hashing only this helper would verify the provenance
#: machinery while saying nothing about the code that actually decided — raised by codex-1 as
#: "only the helper is hashed, not the code that made the decision". Each participating module
#: registers itself at its own import, because that is the only moment its bytes are known to
#: be the bytes that will run.
_LOADED_MODULES: dict[str, str] = {}


def _capture(module_file: str) -> Path | None:
    """Record a module's loaded bytes. Returns the resolved path it was recorded under.

    Resolution happens HERE, once, at import. `adjudicator_identity` reuses the stored path
    rather than resolving ``__file__`` again — raised by codex-1 as "import-time hashing still
    does not pin the loaded tree": when the import path runs through the activation symlink, a
    repoint between the two resolutions selects a different checkout, and a helper unchanged
    across releases hashes equal to the new HEAD. That is the original symlink defect one layer
    down, and it is defeated by not resolving twice.

    Known limit, stated rather than papered over: the loader has already read the file, and this
    re-reads it. A change landing between those two reads is invisible. Closing that would need
    an import hook; the window is microseconds against the hours these receipts are read across,
    and `source_matches_head` is not claimed to cover it.
    """
    try:
        resolved = Path(module_file).resolve()
        _LOADED_MODULES[str(resolved)] = _sha256_of(resolved.read_bytes())
    except OSError:
        return None
    return resolved


def register_adjudicator_module(module_file: str) -> None:
    """Declare a module as part of the code whose identity a receipt asserts.

    Called at import by every module that participates in a decision. Modules that do not
    register are not covered, and the receipt says which ones were — see
    ``adjudicator_modules_verified``. A silent narrowing would be the same defect this module
    exists to prevent, so the scope of the claim travels with the claim.
    """
    _capture(module_file)


#: Captured at import, once. See ``_capture``.
_OWN_PATH = _capture(__file__)


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
    #: True when the tree had uncommitted modifications, False when it was verified clean, and
    #: **None when cleanliness could not be determined** — a failed or timed-out ``git status``.
    #: Three states, not two: an unmeasurable tree is not a clean one. Test ``is False``, never
    #: falsiness, or None silently reads as clean and the sha claims more than it knows.
    dirty: bool | None = None
    #: Does the source that was LOADED still match what ``sha`` claims?
    #:
    #: True when this module's bytes, hashed at import, equal the blob the reported commit
    #: records at this path. False when they demonstrably differ — the process is executing code
    #: the claimed commit does not contain. **None when it could not be checked**, which
    #: includes every path where there is no commit to check against.
    #:
    #: Raised by codex-1 in review, and the deepest form of this module's own subject. Every
    #: other measurement here happens when a receipt is WRITTEN; the claim being made is about
    #: when the code was LOADED. Between the two, a tree can be modified, executed, and then
    #: restored to a clean HEAD — at which point ``dirty`` reports False, ``sha`` reports the
    #: clean commit, and the receipt confidently attributes the decision to code that never ran.
    #: Verifying the loaded bytes against the commit closes that window for this module's own
    #: source; ``dirty`` still speaks for the rest of the tree, at measurement time.
    source_matches_head: bool | None = None
    #: Exactly which modules ``source_matches_head`` covers, repo-relative and sorted.
    #:
    #: Raised by codex-1: the earlier version hashed only this helper, so a True verdict verified
    #: the provenance machinery while saying nothing about `dispatcher_policy` or
    #: `hapax-determine` — the code that actually decides. Either could be loaded modified and
    #: restored before the receipt was written, and every field would still read clean.
    #:
    #: Participating modules now register at their own import and the verdict spans all of them.
    #: The set travels with the claim because a claim whose scope must be inferred from a field
    #: NAME is how this whole defect class starts: a reader can see what was covered instead of
    #: assuming it was everything.
    verified_modules: tuple[str, ...] = ()
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
            "adjudicator_source_matches_head": self.source_matches_head,
            "adjudicator_verified_modules": list(self.verified_modules),
            "adjudicator_declared_sha": self.declared_sha,
        }


def record_has_usable_adjudicator(record: Mapping[str, object]) -> bool:
    """Does this decision/run record identify the code that produced it?

    The check the estate did not have. `routing_model_version` is present on 559 of 559
    historical route decisions carrying the constant ``"capacity-dimensional-v1"``, so
    "an adjudicator field exists" was never the same question as "the adjudicator is known".

    Usable means: a verified 40-hex ``adjudicator_sha`` from a source that could verify it,
    over a tree verified clean. A record is NOT usable when it carries only a basis name, when
    the sha is absent, when the source is ``indeterminate`` (including a release path nothing
    could confirm), when the tree was dirty, or when **cleanliness could not be determined** —
    a dirty tree's HEAD does not determine the code that ran, and neither does an unmeasured
    one. The test is ``is False``, not falsiness: ``None`` means unknown and must not pass.
    """
    sha = record.get("adjudicator_sha")
    source = record.get("adjudicator_source")
    if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
        return False
    if source not in ("release_tree", "git_worktree"):
        return False
    if record.get("adjudicator_dirty") is not False:
        return False
    # The loaded source must match the commit being claimed, not merely coexist with it. Both
    # tests are `is True`/`is False` rather than falsiness, because the absent field and the
    # unknown value are the same thing here — an older record that predates this check has not
    # passed it, and must not inherit a pass from a missing key.
    if record.get("adjudicator_source_matches_head") is not True:
        return False
    # A match verdict must name what it matched. This is not a second guard on the same hazard:
    # the check above asks whether the loaded bytes agreed with the commit, this one asks
    # whether the claim declares its own scope. A record asserting True over an empty set is
    # self-contradictory, and accepting it would reinstate exactly the unscoped claim that
    # made the previous version of this field an over-claim.
    modules = record.get("adjudicator_verified_modules")
    return isinstance(modules, (list, tuple)) and len(modules) > 0


def _git_head(tree: Path) -> tuple[str | None, bool | None]:
    """HEAD sha and dirtiness, where dirtiness may be UNKNOWN.

    Returns ``(head, dirty)`` with ``dirty=None`` meaning "could not be determined".

    Raised by codex-1 in review: an earlier version ignored ``git status``'s return code, so a
    failed or timed-out status produced empty stdout, ``bool("")`` was False, and the identity
    reported a **verified clean tree**. Failure to measure was rendered as a measurement — the
    exact defect this module exists to prevent, committed inside it. `dirty` therefore has
    three states, and callers must test ``is False`` rather than falsiness.
    """
    try:
        sha = subprocess.run(
            ["git", "-C", str(tree), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if sha.returncode != 0:
            return (None, None)
        head = sha.stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", head):
            return (None, None)
        status = subprocess.run(
            ["git", "-C", str(tree), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if status.returncode != 0:
            # HEAD is known, cleanliness is not. Report the sha and refuse to characterise
            # the tree, rather than inferring "clean" from an empty failure buffer.
            return (head, None)
        return (head, bool(status.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        return (None, None)


def _blob_sha256_at(tree: Path, head: str, relative: Path) -> str | None:
    """sha256 of what ``head`` records at ``relative``, or None if it cannot be looked up."""
    try:
        blob = subprocess.run(
            ["git", "-C", str(tree), "cat-file", "blob", f"{head}:{relative.as_posix()}"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if blob.returncode != 0:
        # The commit does not contain this path at all — a file not yet committed, or a tree
        # that does not correspond. Unknown, not mismatched: "cannot look it up" and "looked it
        # up and it differs" are different claims, and only the second justifies an alarm.
        return None
    return _sha256_of(blob.stdout)


def _loaded_source_matches(
    tree: Path, head: str, is_own_source: bool
) -> tuple[bool | None, tuple[str, ...]]:
    """Do the bytes every registered module LOADED match what ``head`` records for them?

    Returns ``(verdict, verified_paths)``. True only when every registered module inside this
    tree was looked up and matched; False as soon as one demonstrably differs; None when
    anything could not be confirmed. ``verified_paths`` names exactly what the verdict covers,
    repo-relative and sorted, so the scope of the claim is readable from the receipt rather than
    inferred from the field's name.

    When ``adjudicator_identity`` is called with an explicit ``module_file``, the answer is None:
    that path was never loaded by this process, so a fixture cannot mint the strongest claim.
    """
    if not is_own_source:
        return (None, ())

    verified: list[str] = []
    mismatched = False
    unknown = False
    for path_text, loaded_sha in sorted(_LOADED_MODULES.items()):
        try:
            relative = Path(path_text).relative_to(tree)
        except ValueError:
            # Registered from outside this checkout — not this tree's business, and not a
            # mismatch. It is still absent from `verified`, which is where a reader sees it.
            continue
        committed = _blob_sha256_at(tree, head, relative)
        if committed is None:
            unknown = True
        elif committed != loaded_sha:
            mismatched = True
        else:
            verified.append(relative.as_posix())

    if mismatched:
        return (False, tuple(sorted(verified)))
    if unknown or not verified:
        # Not every participating module could be confirmed. A partial pass would be exactly
        # the over-claim this field exists to retire.
        return (None, tuple(sorted(verified)))
    return (True, tuple(sorted(verified)))


@lru_cache(maxsize=1)
def adjudicator_identity(module_file: str | None = None) -> AdjudicatorIdentity:
    """Identify the code this process is running.

    Cached: the answer cannot change within a process, because the loaded module cannot be
    relocated mid-run. That is the same property that makes ``__file__`` the correct source
    and the symlink the incorrect one.

    ``module_file`` exists for tests; production callers pass nothing. When it IS supplied the
    identity describes a path this process never loaded, so ``source_matches_head`` stays None:
    a test fixture must not be able to mint the strongest available claim.
    """
    is_own_source = module_file is None
    # For the production path, reuse the path resolved at IMPORT. Resolving `__file__` again
    # here would re-follow the activation symlink, and a repoint between the two resolutions
    # selects a different checkout — the original symlink defect, one layer down. Falling back
    # to a live resolve only when the import-time capture failed, where there is nothing to
    # drift from.
    if is_own_source:
        resolved = _OWN_PATH if _OWN_PATH is not None else Path(__file__).resolve()
    else:
        resolved = Path(module_file).resolve()
    text = str(resolved)
    declared = _declared_release_sha(resolved)

    # Find the enclosing checkout, if any. The module lives at <root>/shared/<file>.py, but a
    # symlinked or relocated layout should still resolve rather than silently degrade.
    for candidate in (resolved.parent, *resolved.parents):
        if (candidate / ".git").exists():
            head, dirty = _git_head(candidate)
            if head is not None:
                matches, verified_modules = _loaded_source_matches(candidate, head, is_own_source)
                # A release path is a CLAIM about content, and release trees here are git
                # checkouts that are writable. Verify rather than trust the directory name:
                # report the sha that actually describes the tree, keep the claim alongside,
                # and let `dirty` say whether even that sha fully determines the code.
                return AdjudicatorIdentity(
                    sha=head,
                    source="release_tree" if declared else "git_worktree",
                    resolved_from=text,
                    dirty=dirty,
                    source_matches_head=matches,
                    verified_modules=verified_modules,
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

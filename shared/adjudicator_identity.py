"""Which code produced this decision, and how much of that is actually established.

A decision with no adjudicator identity is not replayable, and on this estate that is not a
theoretical concern. Measured 2026-08-20:

- ``~/.cache/hapax/source-activation/worktree`` is a symlink into ``releases/<sha>/`` that
  repointed ~7x/day across Aug 17-20 (3, 8, 6, 4 release trees on those days) — roughly a
  three-hour half-life. It repointed twice during the session that wrote this module.
- ``~/.claude/settings.json`` pins its hooks to an ABSOLUTE release path, frozen at ``158e746b``
  (2026-08-08) — eleven days and 124 differing files in ``shared/`` behind the floating tree.
- ``route-decisions.jsonl`` carries ``routing_model_version`` on 559 of 559 records, and its
  value is the constant ``"capacity-dimensional-v1"`` — a basis name, not a code identity. None
  of the 48 keys on a record holds a 40-hex sha.

So two decisions about the same subject three hours apart were made by different code, with
nothing recording that anything changed. SLSA makes ``builder.id`` "the sole determiner of the
build level"; these receipts are under-specified in the way the state of the art calls fatal.

## What this module establishes, and what it does not

It records, for each decision: the checkout the deciding code was loaded from, that checkout's
HEAD and cleanliness **as measured when the receipt was written**, what the deploy path claimed,
and the set of first-party modules the process had loaded.

It does **not** establish that the code which ran is the code that commit contains. That
distinction is the whole content of this docstring, and it was arrived at the hard way: four
successive attempts to close it were each refuted in review, and each refutation was correct.

- Reading the sha from the release path: refuted — release trees here are writable git
  checkouts, and the live tree ``45086a03`` carried a modified ``scripts/hapax-determine`` while
  its directory name asserted that commit.
- Hashing this module's source at import and comparing it to the blob at HEAD: refuted — it
  verified the provenance helper while saying nothing about ``dispatcher_policy`` or
  ``hapax-determine``, which are what decide.
- Sweeping every already-loaded in-tree module and hashing those: refuted — the sweep runs after
  those modules imported and re-reads them from disk, so a dependency loaded while modified and
  restored beforehand is credited with its restored bytes. A false positive, which is worse than
  the gap it closed.
- Hashing at each module's own registration: refuted for the same reason one level in. Python's
  loader has already read and compiled the file before any line of that module runs, so
  ``read_bytes()`` at import is still a RE-READ. There is no point in a Python process at which
  a module can observe the bytes it was itself compiled from.

The conclusion is not that the fourth attempt needed a fifth guard. It is that **in-process
load-time verification is not achievable**, and every mechanism that appeared to provide it was
a proxy wearing the name of a guarantee. Establishing it requires an immutable build identity
captured BEFORE execution — the activation step recording the tree it deployed and the runtime
refusing to run a tree that has changed since. That is deploy-side work and is deliberately not
attempted here.

``record_identifies_its_checkout`` is named for what it establishes, and only that. It was once
called ``record_has_usable_adjudicator`` and documented as necessary-but-not-sufficient, which
codex-1 refuted: a limit written in a docstring that the only caller does not enforce is not a
qualification, it is the same representation-without-enforcement defect this change set exists
to remove, reappearing inside the fix for it. A name a caller can misuse is a worse guard than a
paragraph nobody reads.

## Resolve from ``__file__``, not from the symlink

The obvious implementation reads the activation symlink. That is wrong in the direction that
matters: if the tree repoints mid-run, the symlink names the code that will run NEXT while the
process is still executing the old one, so the receipt would attribute a decision to code that
did not make it. ``Path(__file__).resolve()`` names the tree this module was actually loaded
from, and it is resolved ONCE, at import, because resolving it again when the receipt is built
would re-follow a link that may since have moved.

## Indeterminate is a state, not a default

When the identity cannot be determined — an editable install, a zipapp, an unpacked archive —
the result says so in a typed field rather than defaulting to a plausible value. A receipt that
quietly attributes a decision to the wrong tree is worse than one that says it does not know.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
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

    Raised by coderabbitai in review: an earlier implementation regex-searched for
    ``/source-activation/releases/<40-hex>`` **anywhere** in the path, so any copy, scratch
    checkout, or archive that happened to contain those components was classified
    ``release_tree`` and read as authoritative. A substring is not a location.

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


def _is_vendored(path: Path) -> bool:
    """Third-party or standard-library code, which this tree's HEAD says nothing about."""
    if {".venv", "site-packages", "dist-packages"} & set(path.parts):
        return True
    for base in (sys.base_prefix, sys.base_exec_prefix):
        try:
            path.relative_to(Path(base).resolve())
            return True
        except (ValueError, OSError, RuntimeError):
            continue
    return False


def _first_party_loaded_modules() -> set[str]:
    """Every non-vendored module currently loaded.

    Deliberately NOT filtered to the checkout. An earlier version resolved each ``__file__`` and
    dropped anything failing ``relative_to(root)``, which codex-1 refuted: a module keeps a
    symlink-spelled ``__file__`` that is resolved only when the receipt is built, so a repointed
    activation symlink makes it resolve into the NEW checkout, fail containment against the
    original tree, and vanish from the enumeration entirely — leaving coverage that looked
    complete over code the receipt never saw.

    A module that cannot be placed is exactly the one that must be reported. Everything
    first-party is returned and classified downstream; nothing is dropped for failing to fit.

    Reports ``__file__`` AS PYTHON RECORDED IT, resolving only to decide vendored-ness. Raised by
    codex-1: resolving for the report re-follows the activation symlink at receipt time, so a
    module imported through the link and then repointed is recorded under the NEW checkout — the
    receipt naming a file that never participated. ``__file__`` is fixed at import and cannot
    drift; the resolved form can, and does, roughly seven times a day on this estate.

    This function MUST NOT RAISE. Raised by codex-1: ``sys.modules`` is a mutable mapping any
    library may write to, and an entry whose ``__file__`` is not a path — ``__file__ = 42``
    demonstrably raises TypeError from ``Path()`` — would propagate out of here. Route
    construction calls it directly and ``run_producer`` calls it from a ``finally``, where an
    exception would REPLACE the return value, so one unusual dependency could stop both route
    and determination records from being written at all.

    A module that cannot be described is recorded by name rather than skipped. Dropping it would
    be the same omission-as-fact this function exists to prevent, and the marker is the honest
    statement: something participated and could not be identified.
    """
    found: set[str] = set()
    for name, module in list(sys.modules.items()):
        try:
            file = getattr(module, "__file__", None)
            if not file:
                continue
            try:
                vendored = _is_vendored(Path(file).resolve())
            except (OSError, RuntimeError):
                vendored = False  # unresolvable is a reason to report, not to skip
            if not vendored:
                found.add(str(file))
        except Exception:  # noqa: BLE001 - see the must-not-raise contract above
            found.add(f"<unidentifiable module: {name}>")
    return found


def _resolve_own_path() -> Path | None:
    """This module's path, resolved ONCE at import. See the docstring on the symlink."""
    try:
        return Path(__file__).resolve()
    except (OSError, RuntimeError):
        return None


_OWN_PATH = _resolve_own_path()

AdjudicatorSource = Literal["release_tree", "git_worktree", "indeterminate"]


@dataclass(frozen=True, slots=True)
class AdjudicatorIdentity:
    """The code that produced a decision, and how confidently that was established."""

    #: The commit describing the checkout the deciding code was loaded from — VERIFIED against
    #: git, not inferred from a directory name. None when nothing could be established.
    sha: str | None
    #: How ``sha`` was established. See the module docstring: no value here means "trust me".
    source: AdjudicatorSource
    #: The resolved filesystem path the determination was made from, always recorded so the
    #: claim is auditable even when ``sha`` is None.
    resolved_from: str
    #: True when the tree had uncommitted modifications AT RECEIPT TIME, False when it was
    #: verified clean then, and **None when cleanliness could not be determined** — a failed or
    #: timed-out ``git status``. Three states, not two: an unmeasurable tree is not a clean one.
    #: Test ``is False``, never falsiness, or None silently reads as clean.
    #:
    #: Note the qualifier. This is a measurement taken when the receipt was written, which can be
    #: long after the code was loaded; it does not establish that the tree was clean at load.
    dirty: bool | None = None
    #: Every first-party module the process had loaded when the receipt was written, sorted and
    #: repo-relative where they fall inside the checkout.
    #:
    #: This is a COVERAGE STATEMENT, not a verification: it names what participated so a reader
    #: can see the scope of the decision rather than infer it. There is deliberately no
    #: per-module verdict — see the module docstring for why four attempts at one were refuted.
    loaded_modules: tuple[str, ...] = ()
    #: For a release tree, the sha its PATH claims. Recorded separately from ``sha`` because they
    #: can disagree: release trees on this estate are git checkouts and are WRITABLE, so the
    #: directory name is a claim, not a proof. Measured 2026-08-20: the live release tree
    #: `45086a03` carried a modified `scripts/hapax-determine` while its path asserted a clean
    #: commit. A reader must be able to see the claim and the verification separately.
    declared_sha: str | None = None

    def as_receipt(self) -> dict[str, object]:
        """The shape written onto decisions and run records."""
        return {
            "adjudicator_sha": self.sha,
            "adjudicator_source": self.source,
            "adjudicator_resolved_from": self.resolved_from,
            "adjudicator_dirty": self.dirty,
            "adjudicator_loaded_modules": list(self.loaded_modules),
            "adjudicator_declared_sha": self.declared_sha,
        }


def record_identifies_its_checkout(record: Mapping[str, object]) -> bool:
    """Does this record name the checkout it was produced from, verifiably and cleanly?

    True means: a verified 40-hex sha, from a source that could verify it, over a tree measured
    clean at receipt time. That is exactly what answers the demand this module was written for —
    two decisions three hours apart, made by different release trees, with nothing recording
    that anything changed. Different checkout, different sha: a redeploy is now distinguishable
    from a repair.

    It does NOT mean the decision is attributable to that commit's contents, and the name says
    ``identifies_its_checkout`` rather than ``has_usable_adjudicator`` for that reason. codex-1
    raised the earlier name in review: a function documented as necessary-but-not-sufficient
    whose only consumer treats it as sufficient is not qualified, it is misnamed. Documenting a
    limit that the caller does not enforce is the exact defect this change set exists to remove,
    and it had reappeared here.

    Nothing in a Python process can establish that the bytes it executed are the bytes a commit
    records — the loader reads and compiles a module before any of its code runs, so every
    in-process check is a re-read, defeatable by modifying a file, loading it, and restoring it.
    Four mechanisms claiming otherwise were refuted in review; see the module docstring.

    A record does NOT identify its checkout when it carries only a basis name, when the sha is
    absent, when the source is ``indeterminate`` (including a release path nothing could
    confirm), when the tree was dirty, or when **cleanliness could not be determined**. The test
    is ``is False``, not falsiness: ``None`` means unknown and must not pass.
    """
    sha = record.get("adjudicator_sha")
    source = record.get("adjudicator_source")
    if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
        return False
    if source not in ("release_tree", "git_worktree"):
        return False
    return record.get("adjudicator_dirty") is False


def _git_env() -> dict[str, str]:
    """The environment with every ``GIT_*`` variable removed.

    Raised independently by codex-1 and gemini-1: ``git -C <tree>`` does NOT override
    ``GIT_DIR``, ``GIT_WORK_TREE``, ``GIT_INDEX_FILE`` and friends. A process carrying them —
    most obviously anything running inside a git hook, which this estate does — measures the
    AMBIENT repository while ``adjudicator_resolved_from`` still names this checkout. The
    receipt then pairs one tree's path with another tree's clean HEAD, and
    ``record_identifies_its_checkout`` returns True for the mismatched tuple: a false positive
    in the one predicate this module exists to make trustworthy.

    Everything ``GIT_*`` goes, rather than an allowlist of the known-dangerous ones. This code
    needs none of them, and an allowlist would need extending every time git adds a variable —
    a guard that silently narrows as the world changes is the failure mode this whole change
    set is about.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git_head(tree: Path) -> tuple[str | None, bool | None]:
    """HEAD sha and dirtiness, from ONE git snapshot, where dirtiness may be UNKNOWN.

    Returns ``(head, dirty)`` with ``dirty=None`` meaning "could not be determined".

    One invocation, deliberately. Raised by codex-1: reading HEAD and status as two separate
    subprocesses does not check that HEAD stayed put between them, so a checkout moving from
    commit A to a clean commit B mid-measurement returns ``(A, False)`` — a verified sha over a
    tree that was never measured clean, accepted by ``record_identifies_its_checkout``. Mutable
    checkouts are the threat this module exists for (the activation symlink repoints ~7x/day and
    release trees are writable), so a race between the two reads defeats its central claim.

    ``git status --porcelain=v2 --branch`` reports ``# branch.oid`` and the working-tree entries
    from the same snapshot, so the pair cannot disagree. Bracketing two reads and degrading on
    mismatch would also work and was the other option offered in review; one snapshot is chosen
    because it removes the race rather than detecting it.

    Earlier and still true: an even earlier version ignored the return code entirely, so a failed
    status produced empty stdout, ``bool("")`` was False, and the identity reported a **verified
    clean tree**. Failure to measure rendered as a measurement — the exact defect this module
    exists to prevent, committed inside it. ``dirty`` therefore has three states and callers must
    test ``is False`` rather than falsiness.
    """
    try:
        status = subprocess.run(
            [
                "git",
                "-C",
                str(tree),
                "status",
                "--porcelain=v2",
                "--branch",
                # Explicit, so an ambient `status.showUntrackedFiles=no` cannot hide an untracked
                # file that this process may well have imported. Same class of hazard as the
                # environment below: configuration deciding what the snapshot means.
                "--untracked-files=normal",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=_git_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return (None, None)
    if status.returncode != 0:
        return (None, None)

    head: str | None = None
    dirt = False
    for line in status.stdout.splitlines():
        if line.startswith("# branch.oid "):
            candidate = line.removeprefix("# branch.oid ").strip()
            head = candidate if _SHA_RE.fullmatch(candidate) else None
        elif line and not line.startswith("#"):
            dirt = True

    if head is None:
        # `# branch.oid (initial)` on an unborn branch, or output this parser does not
        # recognise. Nothing to report rather than a malformed identity.
        return (None, None)
    return (head, dirt)


def _relative_to_tree(path_text: str, tree: Path) -> str:
    """Repo-relative where it fits, full path where it does not. Never dropped."""
    try:
        return Path(path_text).relative_to(tree).as_posix()
    except ValueError:
        return path_text


def adjudicator_identity(module_file: str | None = None) -> AdjudicatorIdentity:
    """Identify the code this process is running.

    Deliberately NOT cached. An earlier version was, justified by "the answer cannot change
    within a process" — which the module enumeration makes false, since a lazy import after the
    first receipt changes the answer. codex-1 raised it twice, the second time noting that
    invalidating only on registration still leaves unregistered late imports invisible. A cache
    whose justification has been withdrawn is a stale answer with a comment attached, so it is
    gone; the cost is two git subprocesses per receipt.

    ``module_file`` exists for tests; production callers pass nothing and get the path resolved
    at import.

    This function must not raise. It sits on every route-decision and determination write, so an
    exception escaping here would stop the decision from being recorded at all — provenance
    failing closed over the thing it is describing. Raised by codex-1: an earlier version, when
    import-time resolution had already failed, retried ``Path(__file__).resolve()`` outside any
    handler, so a persistent OSError escaped through every writer. That fallback also RETRIED the
    operation that had just failed, which is the wrong direction on its face — failure paths
    narrow, they do not widen. It is gone rather than wrapped.
    """
    # Enumerated up front so it lands on EVERY branch. Raised by codex-1: the enumeration used
    # to run only after successful git verification, so both indeterminate returns reported an
    # empty list — the most uncertain receipts stating that nothing participated, which is not
    # merely unverified but false. Omission read as fact, one more time.
    loaded = _first_party_loaded_modules()

    if module_file is None:
        if _OWN_PATH is None:
            return AdjudicatorIdentity(
                sha=None,
                source="indeterminate",
                resolved_from=str(__file__),
                loaded_modules=tuple(sorted(loaded)),
            )
        resolved = _OWN_PATH
    else:
        try:
            resolved = Path(module_file).resolve()
        except (OSError, RuntimeError):
            return AdjudicatorIdentity(
                sha=None,
                source="indeterminate",
                resolved_from=str(module_file),
                loaded_modules=tuple(sorted(loaded)),
            )

    text = str(resolved)
    declared = _declared_release_sha(resolved)

    # Find the enclosing checkout, if any. The module lives at <root>/shared/<file>.py, but a
    # symlinked or relocated layout should still resolve rather than silently degrade.
    for candidate in (resolved.parent, *resolved.parents):
        try:
            is_checkout = (candidate / ".git").exists()
        except OSError:
            continue
        if is_checkout:
            head, dirty = _git_head(candidate)
            if head is not None:
                # A release path is a CLAIM about content, and release trees here are git
                # checkouts that are writable. Verify rather than trust the directory name:
                # report the sha that actually describes the tree and keep the claim alongside.
                return AdjudicatorIdentity(
                    sha=head,
                    source="release_tree" if declared else "git_worktree",
                    resolved_from=text,
                    dirty=dirty,
                    loaded_modules=tuple(sorted(_relative_to_tree(p, candidate) for p in loaded)),
                    declared_sha=declared,
                )
            break

    # No verifiable checkout. `sha` stays None — where a release path made a claim it is
    # preserved in `declared_sha`, visibly unverified, rather than promoted into the verified
    # slot. The loaded-module list is reported either way: what ran is knowable even when the
    # tree it ran from is not.
    return AdjudicatorIdentity(
        sha=None,
        source="indeterminate",
        resolved_from=text,
        loaded_modules=tuple(sorted(loaded)),
        declared_sha=declared,
    )

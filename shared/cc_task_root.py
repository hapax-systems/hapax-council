"""Where the cc-task SSOT lives — resolved once, in one place.

``R4.1-portable-work-intake-plane`` names this as the first clause of its gap: *"task root
instance-relative (cc-claim hardcodes ``$HOME/Documents/Personal/20-projects/hapax-cc-tasks``)"*.
R4.1 gates the whole of P4, and nothing downstream of it can be instance-relative while roughly
twenty consumers each rebuild one operator's absolute path independently. Measured 2026-08-12::

    rg -l 'Documents/Personal/20-projects/hapax-cc-tasks' --glob '!*.md' --glob '!tests/**'

Two sources, in order:

1. ``HAPAX_CC_TASKS_ROOT`` — an explicit instance override. Wins outright.
2. ``PERSONAL_VAULT_PATH / 20-projects / hapax-cc-tasks`` — the estate knob that already exists in
   :mod:`shared.config`. Under today's defaults this reduces to today's path exactly, so adopting
   the resolver moves nothing.

**Precedence, not fallback.** An override naming a root that does not exist REFUSES; it never
quietly resolves to the default. Silently writing tasks into a different vault than the operator
configured is precisely the failure this module exists to prevent, and it is invisible from the
inside — the writes succeed, into the wrong SSOT. A failure path may do less than the primary; it
may not do something else instead.

**Absence is two states, not one.** An override pointing at nothing is a misconfiguration. The
default pointing at nothing is *genesis* — R4.1's third clause is "first-init creates the empty
task vault", so the pre-creation state is legitimate and has to be reportable rather than fatal.
Collapsing both into one boolean is what would force a caller to guess which it was looking at, so
:func:`resolve_cc_task_root` returns the path, the source that chose it, and whether it exists;
a caller that needs a vault already present reads ``.exists`` and refuses on its own terms.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

#: Explicit instance override. Named for the estate, not for any one consumer, because every
#: consumer must agree about where the SSOT is — that agreement is the whole point.
OVERRIDE_ENV = "HAPAX_CC_TASKS_ROOT"

#: The estate-relative location under the personal vault. Kept as parts rather than a joined
#: string so the same value builds the shell resolver's path without a second literal.
VAULT_RELATIVE_PARTS = ("20-projects", "hapax-cc-tasks")


class CcTaskRootSource(StrEnum):
    """Which of the two sources chose the path. Recorded so a disagreement is legible."""

    OVERRIDE = "override"
    PERSONAL_VAULT = "personal_vault"


class CcTaskRootUnavailable(RuntimeError):
    """The root cannot be used. The message names the next action."""


@dataclass(frozen=True)
class CcTaskRoot:
    """A resolved root, with the two facts a caller needs in order to act on it."""

    path: Path
    source: CcTaskRootSource
    exists: bool

    @property
    def active(self) -> Path:
        return self.path / "active"

    @property
    def closed(self) -> Path:
        return self.path / "closed"


def _personal_vault() -> Path:
    # Read at call time rather than import time. `shared.config` snapshots PERSONAL_VAULT_PATH
    # into a module constant when it is first imported, which makes it unchangeable for the life
    # of the process — fine for an agent, wrong for a test that has to prove the knob is honoured
    # and wrong for a first-init flow that sets it before creating anything.
    return Path(os.environ.get("PERSONAL_VAULT_PATH", str(Path.home() / "Documents" / "Personal")))


def resolve_cc_task_root() -> CcTaskRoot:
    """Resolve the root without requiring it to exist.

    Raises :class:`CcTaskRootUnavailable` only for an override that names a path which is not a
    usable directory — that is a misconfiguration, and continuing under it would write to the
    wrong place. A missing default is *returned* with ``exists=False``, because that is genesis.
    """

    override = os.environ.get(OVERRIDE_ENV, "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_dir():
            raise CcTaskRootUnavailable(
                f"{OVERRIDE_ENV} names {path}, which is not a directory. Refusing rather than "
                f"falling back to the vault default: a silent fallback would write cc-tasks into "
                f"a different SSOT than the one you configured. Next: create {path}, or unset "
                f"{OVERRIDE_ENV} to use the personal vault"
            )
        return CcTaskRoot(path=path, source=CcTaskRootSource.OVERRIDE, exists=True)

    path = _personal_vault().joinpath(*VAULT_RELATIVE_PARTS)
    return CcTaskRoot(path=path, source=CcTaskRootSource.PERSONAL_VAULT, exists=path.is_dir())


def cc_task_root() -> Path:
    """The resolved path, whether or not it exists yet. For callers that create or report."""

    return resolve_cc_task_root().path


# A `require_cc_task_root()` belongs here — the resolved path, refusing the genesis state with a
# message that distinguishes "not created yet" from "broken install". It is deliberately NOT in
# this commit: it would have no caller, and the estate's unused-callable gate is right to refuse
# one. It lands with the first consumer that reads or mutates tasks, in the same change, so the
# function and its call site are reviewed together. Nothing is lost meanwhile —
# `resolve_cc_task_root().exists` already carries the distinction any such caller would need.

"""``RelayDir`` — typed view over the relay directory tree.

The relay directory is the bus. By convention it lives at::

    ~/.cache/hapax/relay/

with the layout documented in ``PROTOCOL.md``:

.. code-block:: text

    relay/
    ├── PROTOCOL.md
    ├── alpha.yaml
    ├── beta.yaml
    ├── delta.yaml
    ├── epsilon.yaml
    ├── queue/
    ├── glossary.yaml
    ├── convergence.log
    ├── inflections/
    ├── locks/
    └── context/

``RelayDir`` is intentionally narrow — it provides path resolution,
peer discovery, and the cross-cutting *claim conflict* check. It does
not own a process, hold locks, or talk to any daemon.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from hapax_swarm.peer import PeerYaml

if TYPE_CHECKING:
    from pathlib import Path


@dataclasses.dataclass
class RelayDir:
    """A directory acting as a coordination bus for N peer sessions.

    Construct with the directory root::

        RelayDir(Path.home() / ".cache" / "hapax" / "relay")

    All paths returned by this class are absolute and rooted in
    ``self.root``.
    """

    root: Path

    def ensure(self) -> None:
        """Create the relay directory and its conventional subdirs."""
        for sub in ("queue", "inflections", "locks", "context"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    # --- peer.yaml ---------------------------------------------------

    def peer(self, role: str) -> PeerYaml:
        """Return a :class:`PeerYaml` view for ``role``."""
        if not role or "/" in role or role.startswith("."):
            raise ValueError(f"invalid peer role: {role!r}")
        return PeerYaml(role=role, path=self.root / f"{role}.yaml")

    def known_peers(self) -> list[str]:
        """Return roles for which a ``{role}.yaml`` exists.

        Discovery is by-convention: any ``*.yaml`` at the top level of
        the relay directory whose stem is not a reserved name (currently
        ``glossary``) is treated as a peer file.
        """
        if not self.root.exists():
            return []
        roles: list[str] = []
        for path in sorted(self.root.glob("*.yaml")):
            stem = path.stem
            if stem in {"glossary"}:
                continue
            roles.append(stem)
        return roles

    # --- queue + locks + context (path resolution only) -------------

    def queue_dir(self) -> Path:
        return self.root / "queue"

    def lock_path(self, role: str, path_slug: str) -> Path:
        return self.root / "locks" / f"{role}-{path_slug}.lock"

    def context_path(self, topic: str) -> Path:
        return self.root / "context" / f"{topic}.md"

    def inflection_path(self, timestamp: str) -> Path:
        return self.root / "inflections" / f"{timestamp}.md"

    # --- claim conflict check ---------------------------------------

    def find_conflicting_claims(
        self,
        surface: str,
        *,
        exclude_role: str | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Return ``(role, currently_working_on)`` for sibling claims that
        overlap ``surface``.

        ``surface`` is matched as a plain prefix against the sibling's
        ``currently_working_on.surface`` field; either side being a
        prefix of the other counts as overlap. This intentionally
        catches both "I claim ``packages/hapax-swarm/`` while a peer
        claims ``packages/``" and the reverse.

        Exclude self via ``exclude_role`` when checking before claiming.
        """
        conflicts: list[tuple[str, dict[str, Any]]] = []
        for role in self.known_peers():
            if exclude_role is not None and role == exclude_role:
                continue
            peer = self.peer(role)
            record = peer.currently_working_on
            if record is None:
                continue
            other_surface = record.get("surface")
            if not isinstance(other_surface, str) or not other_surface:
                continue
            if _surfaces_overlap(surface, other_surface):
                conflicts.append((role, record))
        return conflicts


def _surfaces_overlap(a: str, b: str) -> bool:
    """True iff one surface path is a prefix of the other.

    Both ``packages/hapax-swarm/`` claiming ``packages/`` and the
    reverse count as a conflict.
    """
    if a == b:
        return True
    if not a.endswith("/"):
        a = a + "/"
    if not b.endswith("/"):
        b = b + "/"
    return a.startswith(b) or b.startswith(a)

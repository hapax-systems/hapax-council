"""Allowlist gate for V5 publication-bus publishers.

Surface targets must be explicitly registered before a publisher will
emit. The allowlist is loaded at module-import time from a YAML
config (operator-curated, in-repo); runtime mutation is forbidden
per the single_user axiom.

Per V5 weave §2.1 PUB-P0-B: the allowlist is one of three
load-bearing invariants every publisher enforces; the
``Publisher.publish()`` superclass method calls
``allowlist.permits(target)`` before any send attempt.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class AllowlistViolation(Exception):
    """Raised when a publisher attempts to emit to a non-allowlisted target.

    Caught by ``Publisher.publish()`` to convert the exception into a
    refused result (counter++ + refusal-brief append). Subclass code
    should not need to catch this directly.
    """


@dataclass(frozen=True)
class AllowlistGate:
    """Per-surface allowlist of permitted target identifiers.

    A target is anything that uniquely identifies the destination of
    a publish-event: a domain (``zenodo.org``), a handle (``@hapax``),
    a paper-id (``arxiv:2026.04.25``). The shape is opaque to the
    gate; matching is exact-string equality against the registered
    set.

    Wildcard or pattern-based allowlists are deliberately out of
    scope — operator-curated explicit registration is the single-
    user axiom's preferred pattern. Future expansion (regex, prefix
    match) would be additive.
    """

    surface_name: str
    permitted: frozenset[str] = field(default_factory=frozenset)

    def permits(self, target: str) -> bool:
        """Return ``True`` iff ``target`` is in the registered set."""
        return target in self.permitted

    def assert_permits(self, target: str) -> None:
        """Raise :class:`AllowlistViolation` when ``target`` is not permitted."""
        if not self.permits(target):
            raise AllowlistViolation(
                f"surface {self.surface_name!r} does not permit target {target!r}; "
                f"add it to the surface's allowlist YAML to enable"
            )


def load_allowlist(surface_name: str, permitted: list[str]) -> AllowlistGate:
    """Construct an :class:`AllowlistGate` from a list of permitted targets.

    Convenience constructor for module-load-time wiring. Subclass
    publishers typically call this once at module import to construct
    a class attribute, e.g.::

        ALLOWLIST_ZENODO = load_allowlist(
            "zenodo-deposit",
            permitted=["zenodo.org", "sandbox.zenodo.org"],
        )

        class ZenodoPublisher(Publisher):
            surface_name = "zenodo-deposit"
            allowlist = ALLOWLIST_ZENODO
            ...

    The list-to-frozenset conversion happens here so subclass code can
    use natural Python lists in the YAML-derived config without having
    to wrap them.
    """
    return AllowlistGate(surface_name=surface_name, permitted=frozenset(permitted))


__all__ = [
    "AllowlistGate",
    "AllowlistViolation",
    "load_allowlist",
]

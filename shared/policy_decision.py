"""The typed decision result returned by the coordination policy layer.

This is the universal output of the future ``policy-decide`` (master design
section 4.1) and of the daemon-independent embedded floor (``policy_floor``).
Every decision carries a ``policy_version`` stamp so a fleet-wide regression can
be bisected to the change that introduced it. Pure data — no IO, no imports
beyond the stdlib — so the irreversible-harm floor can never be weakened by a
bug in a heavier dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

#: Bumped whenever the decision logic changes; stamped on every Decision.
POLICY_DECIDE_VERSION = "0.1.0"


class Verdict(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"


class FailMode(StrEnum):
    #: Reversible op while the kernel is down: allow, but emit a ledger line.
    FAIL_OPEN_WITH_LEDGER = "fail_open_with_ledger"
    #: Irreversible-harm class: block when authority cannot be confirmed.
    FAIL_CLOSED = "fail_closed"


@dataclass(frozen=True)
class Decision:
    """A single allow/block decision with the legibility fields the UI/why-blocked surface needs."""

    verdict: Verdict
    gate: str
    reason: str
    fail_mode: FailMode
    required_field: str | None = None
    current_value: str | None = None
    remediation_verb: str | None = None
    policy_version: str = POLICY_DECIDE_VERSION

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    @property
    def blocked(self) -> bool:
        return self.verdict is Verdict.BLOCK

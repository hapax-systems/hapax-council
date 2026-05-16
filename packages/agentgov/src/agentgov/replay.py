"""Governance replay harness — re-evaluate historical decisions against current policy.

Replays recorded governance decisions (VetoChain evaluations, consent checks,
principal delegations) through the current policy surface. Emits pass/fail
certificates per decision. Regressions are surfaced for escalation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from agentgov.primitives import VetoChain, VetoResult

log = logging.getLogger(__name__)


class ReplayVerdict(Enum):
    PASS = "pass"
    FAIL = "fail"
    REGRESSION = "regression"


@dataclass(frozen=True)
class DecisionRecord:
    """A recorded governance decision to replay."""

    id: str
    timestamp: str
    context: dict[str, Any]
    original_allowed: bool
    original_denied_by: tuple[str, ...] = ()
    source: str = ""


@dataclass(frozen=True)
class ReplayCertificate:
    """Result of replaying a single decision against current policy."""

    record_id: str
    verdict: ReplayVerdict
    original_allowed: bool
    current_allowed: bool
    current_denied_by: tuple[str, ...] = ()
    replayed_at: str = ""

    @property
    def is_regression(self) -> bool:
        return self.verdict == ReplayVerdict.REGRESSION


@dataclass
class ReplayReport:
    """Aggregate result of replaying a batch of decisions."""

    certificates: list[ReplayCertificate] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.certificates)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.certificates if c.verdict == ReplayVerdict.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.certificates if c.verdict == ReplayVerdict.FAIL)

    @property
    def regressions(self) -> list[ReplayCertificate]:
        return [c for c in self.certificates if c.is_regression]


def replay_decision(
    record: DecisionRecord,
    chain: VetoChain[dict[str, Any]],
) -> ReplayCertificate:
    """Replay a single decision record against a VetoChain."""
    result: VetoResult = chain.evaluate(record.context)
    now = datetime.now(UTC).isoformat()

    if result.allowed == record.original_allowed:
        verdict = ReplayVerdict.PASS
    elif record.original_allowed and not result.allowed:
        verdict = ReplayVerdict.REGRESSION
    else:
        verdict = ReplayVerdict.FAIL

    return ReplayCertificate(
        record_id=record.id,
        verdict=verdict,
        original_allowed=record.original_allowed,
        current_allowed=result.allowed,
        current_denied_by=result.denied_by,
        replayed_at=now,
    )


def replay_batch(
    records: list[DecisionRecord],
    chain: VetoChain[dict[str, Any]],
) -> ReplayReport:
    """Replay a batch of decision records. Returns aggregate report."""
    report = ReplayReport()
    for record in records:
        cert = replay_decision(record, chain)
        report.certificates.append(cert)
        if cert.is_regression:
            log.warning(
                "Governance regression: %s was allowed, now denied by %s",
                record.id,
                cert.current_denied_by,
            )
    return report

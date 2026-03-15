"""Consent-gated writer — the single chokepoint for person-adjacent persistence.

Every persistent write of data that could contain information about a
non-operator person MUST pass through this gate. The gate:

1. Checks whether the data's consent label permits the write
2. Verifies all provenance contracts are active
3. Logs the decision (allow/curtail) with audit context
4. Either persists the data or curtails (returns structured denial)

The provable property:
    ∀ data: gate.write(data) succeeds → data.provenance ⊆ active_contracts

This is the interpersonal_transparency axiom (it-consent-001, T0)
made structural: there is no code path to persist person-adjacent data
that bypasses this gate.

See DD-12 (runtime label checks at file boundaries).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.governance.consent import ConsentRegistry, load_contracts
from shared.governance.consent_label import ConsentLabel
from shared.governance.governor import GovernorWrapper, consent_output_policy
from shared.governance.labeled import Labeled
from shared.governance.revocation import check_provenance

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateDecision:
    """Result of a consent gate check."""

    allowed: bool
    reason: str
    data_category: str = ""
    person_ids: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    timestamp: str = ""


@dataclass
class ConsentGatedWriter:
    """Single chokepoint for person-adjacent persistent writes.

    All writes go through check_and_write(). The gate validates consent
    labels and provenance before allowing persistence. Denied writes
    produce structured GateDecision objects for audit.

    The audit log is append-only and survives process restarts (JSONL on disk).
    """

    _registry: ConsentRegistry
    _governor: GovernorWrapper
    _audit_path: Path | None = None
    _decisions: list[GateDecision] = field(default_factory=list)

    @staticmethod
    def create(
        agent_id: str = "consent-gate",
        audit_path: Path | None = None,
    ) -> ConsentGatedWriter:
        """Create a ConsentGatedWriter with loaded registry and governor."""
        registry = load_contracts()
        governor = GovernorWrapper(agent_id)
        governor.add_output_policy(consent_output_policy(ConsentLabel.bottom()))
        return ConsentGatedWriter(
            _registry=registry,
            _governor=governor,
            _audit_path=audit_path,
        )

    def check(
        self,
        data: Labeled[Any],
        *,
        data_category: str = "",
        person_ids: tuple[str, ...] = (),
    ) -> GateDecision:
        """Check whether data can be persisted. Does NOT write.

        Returns GateDecision with allowed=True/False and reason.
        """
        now = datetime.now(UTC).isoformat()

        # 1. Check provenance — all contracts must be active
        active_ids = frozenset(cid for cid, c in self._registry._contracts.items() if c.active)
        if data.provenance and not check_provenance(data, active_ids):
            revoked = data.provenance - active_ids
            decision = GateDecision(
                allowed=False,
                reason=f"Provenance contains revoked contracts: {sorted(revoked)}",
                data_category=data_category,
                person_ids=person_ids,
                provenance=tuple(sorted(data.provenance)),
                timestamp=now,
            )
            self._record(decision)
            return decision

        # 2. Check consent label via governor
        result = self._governor.check_output(data)
        if not result.allowed:
            denial = result.denial
            decision = GateDecision(
                allowed=False,
                reason=denial.reason if denial else "Governor denied output",
                data_category=data_category,
                person_ids=person_ids,
                provenance=tuple(sorted(data.provenance)),
                timestamp=now,
            )
            self._record(decision)
            return decision

        # 3. Check person-specific consent contracts
        for person_id in person_ids:
            if person_id == "operator":
                continue
            if not self._registry.contract_check(person_id, data_category):
                decision = GateDecision(
                    allowed=False,
                    reason=(
                        f"No active consent contract for person '{person_id}' "
                        f"in category '{data_category}'"
                    ),
                    data_category=data_category,
                    person_ids=person_ids,
                    provenance=tuple(sorted(data.provenance)),
                    timestamp=now,
                )
                self._record(decision)
                return decision

        # All checks passed
        decision = GateDecision(
            allowed=True,
            reason="All consent checks passed",
            data_category=data_category,
            person_ids=person_ids,
            provenance=tuple(sorted(data.provenance)),
            timestamp=now,
        )
        self._record(decision)
        return decision

    def check_and_write(
        self,
        data: Labeled[Any],
        target_path: Path,
        *,
        data_category: str = "",
        person_ids: tuple[str, ...] = (),
        write_fn: Any = None,
    ) -> GateDecision:
        """Check consent and write if allowed.

        If write_fn is provided, calls write_fn(data.value, target_path).
        Otherwise writes str(data.value) to target_path.

        Returns GateDecision regardless of outcome.
        """
        decision = self.check(data, data_category=data_category, person_ids=person_ids)

        if decision.allowed:
            if write_fn:
                write_fn(data.value, target_path)
            else:
                target_path.write_text(str(data.value))
            log.info("Consent gate: ALLOWED write to %s", target_path)
        else:
            log.info(
                "Consent gate: CURTAILED write to %s — %s",
                target_path,
                decision.reason,
            )

        return decision

    @property
    def decisions(self) -> list[GateDecision]:
        """All decisions made by this gate instance."""
        return list(self._decisions)

    def reload_contracts(self) -> None:
        """Reload consent contracts from disk (after new contract created)."""
        self._registry = load_contracts()

    def _record(self, decision: GateDecision) -> None:
        """Record decision to in-memory log and optional disk audit."""
        self._decisions.append(decision)

        if self._audit_path:
            try:
                self._audit_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._audit_path, "a") as f:
                    entry = {
                        "timestamp": decision.timestamp,
                        "allowed": decision.allowed,
                        "reason": decision.reason,
                        "data_category": decision.data_category,
                        "person_ids": list(decision.person_ids),
                        "provenance": list(decision.provenance),
                    }
                    f.write(json.dumps(entry) + "\n")
            except Exception:
                log.debug("Failed to write audit log", exc_info=True)

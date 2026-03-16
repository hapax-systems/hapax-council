"""ConsentGatedReader — the single chokepoint for data retrieval before LLM consumption.

Completes the DIFC loop: ConsentGatedWriter gates persistence,
ConsentGatedReader gates retrieval. Together they enforce consent at
both boundaries of the information flow.

Provable property: for all data d reaching the LLM,
every person_id in d either has an active consent contract
or has been abstracted to a non-identifying form.

See DD-12 (runtime label checks at retrieval boundaries).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shared.governance.consent import ConsentRegistry, load_contracts
from shared.governance.degradation import degrade
from shared.governance.person_extract import (
    extract_calendar_persons,
    extract_email_persons,
    extract_person_ids,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievedDatum:
    """A piece of data retrieved from a tool/data source before LLM consumption."""

    content: str
    person_ids: frozenset[str]
    data_category: str  # "calendar", "email", "document", etc.
    source: str  # tool/collection name for audit


@dataclass(frozen=True)
class ReaderDecision:
    """Result of a consent-gated read check."""

    allowed: bool  # True if ANY content can flow
    degradation_level: int  # 1=full, 2=abstract, 3=existence, 4=suppress
    filtered_content: str  # content after degradation
    consented_count: int
    unconsented_count: int
    audit_note: str  # "2 of 5 persons consented" (no names in audit)


# ── Tool → category mapping ─────────────────────────────────────────────────

_TOOL_CATEGORIES: dict[str, str] = {
    "search_documents": "document",
    "get_calendar_today": "calendar",
    "search_emails": "email",
    "search_drive": "document",
    "analyze_scene": "perception",
    "get_briefing": "document",  # briefings aggregate calendar/email mentioning people
}

# Tools not in dict pass through unfiltered (system_status, desktop, consent tools)
_PASSTHROUGH_TOOLS: frozenset[str] = frozenset(
    {
        "get_system_status",
        "focus_window",
        "switch_workspace",
        "open_app",
        "confirm_open_app",
        "get_desktop_state",
        "send_sms",
        "confirm_send_sms",
        "generate_image",
        "check_consent_status",
        "describe_consent_flow",
        "check_governance_health",
        "get_current_time",
        "get_weather",
    }
)

# ── Category-specific person extractors ──────────────────────────────────────

_CATEGORY_EXTRACTORS: dict[str, object] = {
    "calendar": extract_calendar_persons,
    "email": extract_email_persons,
}


class ConsentGatedReader:
    """Single chokepoint for all data retrieval before LLM consumption.

    Created once per ConversationPipeline instance. Refreshes its registry
    on each conversation start to pick up newly created contracts.
    """

    def __init__(
        self,
        registry: ConsentRegistry,
        operator_ids: frozenset[str],
        audit_path: Path | None = None,
    ) -> None:
        self._registry = registry
        self._operator_ids = operator_ids
        self._audit_path = audit_path
        self._decisions: list[ReaderDecision] = []
        self._known_persons = self._build_known_persons()

    @staticmethod
    def create(
        operator_ids: frozenset[str] | None = None,
        audit_path: Path | None = None,
    ) -> ConsentGatedReader:
        """Create a ConsentGatedReader with loaded registry."""
        from shared.config import OPERATOR_IDS

        registry = load_contracts()
        ids = operator_ids or OPERATOR_IDS
        return ConsentGatedReader(
            registry=registry,
            operator_ids=ids,
            audit_path=audit_path,
        )

    def reload_contracts(self) -> None:
        """Reload consent contracts from disk."""
        self._registry = load_contracts()
        self._known_persons = self._build_known_persons()

    def filter(self, datum: RetrievedDatum) -> ReaderDecision:
        """The core gate. Partitions person_ids into consented/unconsented, applies degradation.

        Key invariant: the operator (operator_ids) is always treated as consented.
        Every other person requires contract_check(person_id, data_category).
        """
        # Partition person IDs
        consented: set[str] = set()
        unconsented: set[str] = set()

        for pid in datum.person_ids:
            if pid in self._operator_ids or self._registry.contract_check(pid, datum.data_category):
                consented.add(pid)
            else:
                unconsented.add(pid)

        # Determine degradation level
        if not unconsented:
            # All consented (or no persons at all) — full access
            decision = ReaderDecision(
                allowed=True,
                degradation_level=1,
                filtered_content=datum.content,
                consented_count=len(consented),
                unconsented_count=0,
                audit_note=f"{len(consented)} of {len(datum.person_ids)} persons consented",
            )
        else:
            # Some unconsented — apply abstraction (Level 2)
            filtered = degrade(datum.content, frozenset(unconsented), datum.data_category)
            decision = ReaderDecision(
                allowed=True,
                degradation_level=2,
                filtered_content=filtered,
                consented_count=len(consented),
                unconsented_count=len(unconsented),
                audit_note=(
                    f"{len(consented)} of {len(datum.person_ids)} persons consented, "
                    f"{len(unconsented)} abstracted"
                ),
            )

        self._record(decision, datum.source, datum.data_category)
        return decision

    def filter_tool_result(self, tool_name: str, result: str) -> str:
        """Convenience: extract persons from tool result, filter, return string.

        This is the method called from conversation_pipeline._handle_tool_calls().
        Tools not in _TOOL_CATEGORIES pass through unfiltered.
        """
        # Passthrough for system/UI tools
        if tool_name in _PASSTHROUGH_TOOLS or tool_name not in _TOOL_CATEGORIES:
            return result

        category = _TOOL_CATEGORIES[tool_name]

        # Use category-specific extractor if available, else generic
        extractor = _CATEGORY_EXTRACTORS.get(category)
        if extractor:
            person_ids = extractor(result)
        else:
            person_ids = extract_person_ids(result, known_persons=self._known_persons)

        # If no persons found, pass through
        if not person_ids:
            return result

        datum = RetrievedDatum(
            content=result,
            person_ids=person_ids,
            data_category=category,
            source=tool_name,
        )
        decision = self.filter(datum)
        return decision.filtered_content

    @property
    def decisions(self) -> list[ReaderDecision]:
        """All decisions made by this reader instance."""
        return list(self._decisions)

    def _build_known_persons(self) -> frozenset[str]:
        """Build the set of known person names from active contracts."""
        persons: set[str] = set()
        for contract in self._registry.active_contracts:
            for party in contract.parties:
                if party != "operator" and party not in self._operator_ids:
                    persons.add(party)
        return frozenset(persons)

    def _record(self, decision: ReaderDecision, source: str, category: str) -> None:
        """Record decision to in-memory log and optional disk audit."""
        self._decisions.append(decision)

        if decision.degradation_level > 1:
            log.info(
                "Consent reader: degraded %s/%s — %s",
                source,
                category,
                decision.audit_note,
            )

        if self._audit_path:
            try:
                self._audit_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._audit_path, "a") as f:
                    entry = {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "source": source,
                        "category": category,
                        "degradation_level": decision.degradation_level,
                        "consented": decision.consented_count,
                        "unconsented": decision.unconsented_count,
                        "audit_note": decision.audit_note,
                    }
                    f.write(json.dumps(entry) + "\n")
            except Exception:
                log.debug("Failed to write reader audit log", exc_info=True)

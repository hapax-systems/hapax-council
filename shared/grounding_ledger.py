"""Grounding ledger — persistent claim-ownership tracking.

Tracks the operator's personal relationship to each research claim:
unexamined, CCTV-verified, personally grounded, or already owned.
Persists to JSONL for durability and CHI methodology evidence.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from shared.jsonl_retention import rewrite_bounded_jsonl_lines

log = logging.getLogger(__name__)

DEFAULT_LEDGER_PATH = Path.home() / ".cache" / "hapax" / "grounding-ledger.jsonl"
MAX_GROUNDING_LEDGER_ENTRIES = 10_000


class GroundingState(StrEnum):
    UNEXAMINED = "unexamined"
    CCTV_QUEUED = "cctv_queued"
    CCTV_COMPLETE = "cctv_complete"
    PERSONALLY_GROUNDED = "personally_grounded"
    OWNED_DOMAIN = "owned_domain"
    CONTESTED = "contested"


class GroundingEntry(BaseModel):
    model_config = ConfigDict(frozen=False)

    claim_id: str
    claim_text: str
    craft_composite: float = 0.0
    craft_category: str = ""
    state: GroundingState = GroundingState.UNEXAMINED
    grounded_at: str | None = None
    session_id: str | None = None
    open_questions: list[str] = Field(default_factory=list)
    falsification_condition: str | None = None
    divergences_identified: list[str] = Field(default_factory=list)


class GroundingLedger:
    """Compacted ledger tracking latest claim grounding state."""

    def __init__(
        self,
        path: Path = DEFAULT_LEDGER_PATH,
        *,
        max_entries: int = MAX_GROUNDING_LEDGER_ENTRIES,
    ) -> None:
        self.path = path
        self.max_entries = max_entries
        self._entries: dict[str, GroundingEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                entry = GroundingEntry(**data)
                self._entries[entry.claim_id] = entry
            except Exception:
                log.warning("Skipping malformed ledger line")

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # jsonl-rotation: exempt(inline compacted state ledger; one live row per claim)
        rewrite_bounded_jsonl_lines(
            self.path,
            (item.model_dump_json() for item in self._entries.values()),
            max_lines=self.max_entries,
        )

    def get(self, claim_id: str) -> GroundingEntry | None:
        return self._entries.get(claim_id)

    def record_verdict(
        self,
        claim_id: str,
        claim_text: str,
        state: GroundingState,
        *,
        craft_composite: float = 0.0,
        craft_category: str = "",
        session_id: str | None = None,
        open_questions: list[str] | None = None,
        falsification_condition: str | None = None,
        divergences: list[str] | None = None,
    ) -> GroundingEntry:
        entry = GroundingEntry(
            claim_id=claim_id,
            claim_text=claim_text,
            craft_composite=craft_composite,
            craft_category=craft_category,
            state=state,
            grounded_at=datetime.now(UTC).isoformat(),
            session_id=session_id,
            open_questions=open_questions or [],
            falsification_condition=falsification_condition,
            divergences_identified=divergences or [],
        )
        self._entries[claim_id] = entry
        self._persist()
        return entry

    def progress(self) -> dict[str, int | float]:
        total = len(self._entries)
        by_state: dict[str, int] = {}
        cat_a_total = 0
        cat_a_grounded = 0
        for entry in self._entries.values():
            by_state[entry.state] = by_state.get(entry.state, 0) + 1
            if entry.craft_category == "ground_personally":
                cat_a_total += 1
                if entry.state in (
                    GroundingState.PERSONALLY_GROUNDED,
                    GroundingState.OWNED_DOMAIN,
                ):
                    cat_a_grounded += 1

        deficit = 1.0 - (cat_a_grounded / cat_a_total) if cat_a_total > 0 else 1.0
        return {
            "total": total,
            "grounding_deficit": round(deficit, 4),
            "category_a_total": cat_a_total,
            "category_a_grounded": cat_a_grounded,
            **by_state,
        }

    def all_entries(self) -> list[GroundingEntry]:
        return list(self._entries.values())

    def entries_by_state(self, state: GroundingState) -> list[GroundingEntry]:
        return [e for e in self._entries.values() if e.state == state]

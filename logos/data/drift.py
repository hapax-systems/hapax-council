"""Drift report data collector."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from shared.config import PROFILES_DIR


@dataclass
class DriftItem:
    severity: str = ""
    category: str = ""
    doc_file: str = ""
    description: str = ""
    suggestion: str = ""


@dataclass
class DriftSummary:
    drift_count: int = 0
    hygiene_count: int = 0
    docs_analyzed: int = 0
    summary: str = ""
    latest_timestamp: str = ""
    items: list[DriftItem] = field(default_factory=list)
    report_age_h: float = 0.0


# Categories that represent doc hygiene tasks, not actual system-state drift.
HYGIENE_CATEGORIES = {
    "coverage-gap",
    "missing-section",
    "missing_project_memory",
    "spec-reference-gap",
}


def collect_drift() -> DriftSummary | None:
    """Read profiles/drift-report.json."""
    report_path = PROFILES_DIR / "drift-report.json"
    history_path = PROFILES_DIR / "drift-history.jsonl"

    if not report_path.exists():
        return None

    try:
        data = json.loads(report_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    # Get timestamp from history if available
    timestamp = ""
    if history_path.exists():
        for line in reversed(history_path.read_text().splitlines()):
            line = line.strip()
            if line:
                try:
                    timestamp = json.loads(line).get("timestamp", "")
                except (json.JSONDecodeError, KeyError):
                    pass
                break

    # Parse drift items
    items = []
    for raw in data.get("drift_items", []):
        # Agent model uses doc_claim/reality; build description from them
        doc_claim = raw.get("doc_claim", "")
        reality = raw.get("reality", "")
        description = raw.get("description", "") or (
            f"{doc_claim} → {reality}" if doc_claim and reality else doc_claim or reality
        )
        items.append(
            DriftItem(
                severity=raw.get("severity", ""),
                category=raw.get("category", ""),
                doc_file=raw.get("doc_file", ""),
                description=description,
                suggestion=raw.get("suggestion", ""),
            )
        )

    # Compute report age
    report_age_h = 0.0
    if timestamp:
        try:
            ts = datetime.fromisoformat(timestamp)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            report_age_h = (datetime.now(UTC) - ts).total_seconds() / 3600
        except (ValueError, TypeError):
            pass

    drift_items = [i for i in items if i.category not in HYGIENE_CATEGORIES]
    hygiene_items = [i for i in items if i.category in HYGIENE_CATEGORIES]

    return DriftSummary(
        drift_count=len(drift_items),
        hygiene_count=len(hygiene_items),
        docs_analyzed=len(data.get("docs_analyzed", [])),
        summary=data.get("summary", ""),
        latest_timestamp=timestamp,
        items=items,
        report_age_h=round(report_age_h, 1),
    )

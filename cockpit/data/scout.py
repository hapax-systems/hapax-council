"""Scout report data collector."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


from shared.config import PROFILES_DIR


@dataclass
class ScoutRecommendation:
    component: str
    current: str
    tier: str  # "adopt" | "evaluate" | "monitor" | "current-best"
    summary: str
    confidence: str = "medium"
    migration_effort: str = ""


@dataclass
class ScoutData:
    generated_at: str = ""
    components_scanned: int = 0
    recommendations: list[ScoutRecommendation] = field(default_factory=list)
    adopt_count: int = 0
    evaluate_count: int = 0


def collect_scout() -> ScoutData | None:
    """Read profiles/scout-report.json."""
    path = PROFILES_DIR / "scout-report.json"
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    recs = [
        ScoutRecommendation(
            component=r.get("component", ""),
            current=r.get("current", ""),
            tier=r.get("tier", "current-best"),
            summary=r.get("summary", ""),
            confidence=r.get("confidence", "medium"),
            migration_effort=r.get("migration_effort", ""),
        )
        for r in data.get("recommendations", [])
    ]

    return ScoutData(
        generated_at=data.get("generated_at", ""),
        components_scanned=data.get("components_scanned", 0),
        recommendations=recs,
        adopt_count=sum(1 for r in recs if r.tier == "adopt"),
        evaluate_count=sum(1 for r in recs if r.tier == "evaluate"),
    )
